"""
socrates/llm/groq_client.py — Groq LLM tiebreaker for LOW_CONFIDENCE events.

Role:
  When deterministic rules return LOW_CONFIDENCE (ambiguous error keywords,
  warning noise in stderr, slight runtime anomalies), Groq provides a quick,
  free-tier second opinion: should Socrates intervene?

Hard constraints:
  - Key from GROQ_API_KEY env var only. Missing key → treat as NONE immediately.
  - Leaked secrets NEVER pass through here (enforced in routing and defense-in-depth).
  - All prompt payloads are scrubbed through leaked_secrets scanner locally before sending.
  - Minimal facts only: command, exit_code, scrubbed stderr excerpt, baseline delta.
  - Failures (network, timeouts, 429, JSON parse) degrade to NONE silently.
  - Client-side rate-limit throttling and backoff on 429.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Optional

from socrates.config import SocratesConfig
from socrates.rules.base import Confidence, RuleResult, RuleType
from socrates.rules.leaked_secrets import scan_for_secrets, redact_matches

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are Socrates, an intelligent terminal observer assistant for software developers.
A command was executed, and the rule engine flagged an ambiguous condition (exit code 0 with warning/error keywords in stderr, or runtime anomaly).
Your task is to evaluate whether this represents a real issue that genuinely warrants speaking up to the developer right now.

Respond ONLY with a valid JSON object matching this schema:
{
  "intervene": true | false,
  "reason": "one concise sentence explaining why intervention is or is not warranted"
}
Do not include markdown fences or any other text.
"""


def scrub_text(text: str) -> str:
    """Replace any secret-shaped tokens with [REDACTED:<type>] before sending externally."""
    if not text:
        return text
    matches = scan_for_secrets(text)
    return redact_matches(text, matches)


class GroqClient:
    def __init__(self, config: SocratesConfig, api_key: Optional[str] = None):
        self.config = config
        self._api_key = api_key or os.environ.get("GROQ_API_KEY", "")
        self._last_call_ts: float = 0.0
        self._backoff_until: float = 0.0

    @property
    def is_available(self) -> bool:
        """Check if Groq is enabled and an API key is present."""
        if not getattr(self.config, "groq_enabled", True):
            return False
        return bool(self._api_key and self._api_key.strip())

    def tiebreak(self, result: RuleResult) -> RuleResult:
        """
        Evaluate a LOW_CONFIDENCE rule result using Groq.
        Returns an updated RuleResult:
          - HIGH_CONFIDENCE if Groq says intervene is true
          - NONE if Groq says false or on any error/degradation
        """
        # Hard defense-in-depth: leaked secrets must NEVER leave the machine
        if result.rule_type == RuleType.LEAKED_SECRETS:
            logger.warning("Attempted to route LEAKED_SECRETS through Groq. Blocked.")
            return result

        if not self.is_available:
            logger.debug("Groq tiebreaker unavailable (disabled or missing GROQ_API_KEY). Treating as NONE.")
            return RuleResult(
                rule_type=result.rule_type,
                confidence=Confidence.NONE,
                facts=result.facts,
                fingerprint_key=result.fingerprint_key,
            )

        now = time.time()
        # Check 429 backoff
        if now < self._backoff_until:
            logger.debug("Groq in rate-limit backoff until %.1f (current: %.1f). Treating as NONE.", self._backoff_until, now)
            return RuleResult(
                rule_type=result.rule_type,
                confidence=Confidence.NONE,
                facts=result.facts,
                fingerprint_key=result.fingerprint_key,
            )

        # Enforce minimum interval between calls (client-side throttle)
        min_interval = getattr(self.config, "groq_min_call_interval_seconds", 2.0)
        elapsed_since_last = now - self._last_call_ts
        if elapsed_since_last < min_interval:
            time.sleep(min_interval - elapsed_since_last)

        prompt_payload = self._build_payload(result)
        decision = self._call_groq_with_retry(prompt_payload)
        self._last_call_ts = time.time()

        if decision and decision.get("intervene") is True:
            updated_facts = dict(result.facts)
            updated_facts["groq_reason"] = decision.get("reason", "")
            return RuleResult(
                rule_type=result.rule_type,
                confidence=Confidence.HIGH_CONFIDENCE,
                facts=updated_facts,
                fingerprint_key=result.fingerprint_key,
            )

        return RuleResult(
            rule_type=result.rule_type,
            confidence=Confidence.NONE,
            facts=result.facts,
            fingerprint_key=result.fingerprint_key,
        )

    def _build_payload(self, result: RuleResult) -> str:
        """Construct the scrubbed JSON prompt payload."""
        facts = result.facts
        scrubbed = {
            "rule_type": result.rule_type.value,
            "command": scrub_text(facts.get("command", "")),
            "exit_code": facts.get("exit_code", 0),
            "stderr_excerpt": scrub_text(facts.get("stderr_excerpt", facts.get("stderr_tail", "")))[:1000],
            "details": {
                k: scrub_text(str(v))
                for k, v in facts.items()
                if k not in {"command", "exit_code", "stderr_excerpt", "stderr_tail"}
            },
        }
        return json.dumps(scrubbed, indent=2)

    def _call_groq_with_retry(self, user_content: str) -> Optional[dict[str, Any]]:
        """Call Groq API with single retry on 429."""
        retried = False
        while True:
            try:
                import groq
                client = groq.Groq(
                    api_key=self._api_key,
                    timeout=getattr(self.config, "groq_timeout_seconds", 8.0),
                )
                model = getattr(self.config, "groq_model", "openai/gpt-oss-20b")

                completion = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_content},
                    ],
                    temperature=0.1,
                    max_tokens=600,
                )

                content = completion.choices[0].message.content or ""
                return self._parse_response(content)

            except Exception as e:
                # Check for 429 rate limit
                status_code = getattr(e, "status_code", None)
                err_msg = str(e)
                if status_code == 429 or "429" in err_msg or "rate_limit" in err_msg.lower():
                    backoff = getattr(self.config, "groq_rate_limit_backoff_seconds", 30.0)
                    self._backoff_until = time.time() + backoff
                    logger.debug("Groq 429 rate limit received. Backing off for %.1fs", backoff)
                    if not retried:
                        retried = True
                        # Lightweight short retry after 1s once
                        time.sleep(1.0)
                        continue
                    return None

                logger.debug("Groq call failed with exception: %s. Degrading to NONE.", e)
                return None

    def _parse_response(self, text: str) -> Optional[dict[str, Any]]:
        """Parse strict JSON response from Groq."""
        text = text.strip()
        # Remove potential markdown fences
        if text.startswith("```"):
            lines = text.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines).strip()

        try:
            data = json.loads(text)
            if isinstance(data, dict) and "intervene" in data:
                return data
            return None
        except Exception:
            logger.debug("Failed to parse Groq response as JSON: %r", text[:100])
            return None
