"""
socrates/rules/leaked_secrets.py — Rule 2: Leaked secrets in commands.

Detects secrets, API keys, and high-entropy tokens that appear in command text.
This is the most privacy-sensitive rule in Socrates.

HARD CONSTRAINTS (enforced architecturally, not just by convention):
  1. This rule NEVER sends flagged content to any network endpoint.
  2. This rule NEVER escalates to the Groq LLM tiebreaker.
  3. The scan_for_secrets() and redact_matches() functions are exported for
     use by groq_client.py to scrub Groq payloads BEFORE any data leaves
     the machine — see Section 0 and Section 4 of the spec.

Detection strategy (two-stage):
  Stage 1 — Regex patterns for known secret formats:
    - AWS access keys (AKIA...) and secret keys
    - GitHub Personal Access Tokens (ghp_, gho_, github_pat_...)
    - Private key PEM headers
    - Generic API key / bearer token patterns
    - .env-style KEY=<high-entropy-value> assignments
    - Stripe, Slack, Twilio, SendGrid, Anthropic token formats
    - SSH private key content
  Stage 2 — Shannon entropy scoring on candidate tokens:
    - Tokens that pass length + charset filters are entropy-scored
    - High entropy (≥ threshold) flags unknown/novel secret formats
    - Avoids flagging common words, file paths, or UUIDs (tuned thresholds)

Returns HIGH_CONFIDENCE on any match.
"""
from __future__ import annotations

import math
import re
import string
from dataclasses import dataclass
from typing import Optional

from socrates.rules.base import Confidence, RuleResult, RuleType


# ── Secret pattern definitions ─────────────────────────────────────────────────

@dataclass(frozen=True)
class SecretMatch:
    """A detected secret in command text."""
    pattern_name: str      # Human-readable type (e.g. "AWS Access Key")
    matched_text: str      # The actual matched string (kept local ONLY)
    start: int             # Character offset in the original text
    end: int               # Character offset in the original text


# Patterns: (name, compiled_regex)
# Each pattern is tested against the full command string.
_SECRET_PATTERNS: list[tuple[str, re.Pattern]] = [
    # AWS
    ("AWS Access Key ID",
     re.compile(r'\bAKIA[0-9A-Z]{16}\b')),
    ("AWS Secret Access Key",
     re.compile(r'\b[0-9a-zA-Z+/]{40}\b(?=.*(?:aws|secret|key))', re.IGNORECASE)),
    # GitHub
    ("GitHub Personal Access Token (classic)",
     re.compile(r'\bghp_[0-9a-zA-Z]{36,}\b')),
    ("GitHub OAuth Token",
     re.compile(r'\bgho_[0-9a-zA-Z]{36,}\b')),
    ("GitHub App Token",
     re.compile(r'\bghs_[0-9a-zA-Z]{36,}\b')),
    ("GitHub Fine-Grained PAT",
     re.compile(r'\bgithub_pat_[0-9a-zA-Z_]{82,}\b')),
    # Slack
    ("Slack Bot Token",
     re.compile(r'\bxoxb-[0-9]{10,13}-[0-9]{10,13}-[0-9a-zA-Z]{24}\b')),
    ("Slack User Token",
     re.compile(r'\bxoxp-[0-9]{10,13}-[0-9]{10,13}-[0-9]{10,13}-[0-9a-f]{32}\b')),
    # Stripe
    ("Stripe Secret Key",
     re.compile(r'\bsk_live_[0-9a-zA-Z]{24,}\b')),
    ("Stripe Restricted Key",
     re.compile(r'\brk_live_[0-9a-zA-Z]{24,}\b')),
    # OpenAI / Anthropic style
    ("OpenAI API Key",
     re.compile(r'\bsk-[0-9a-zA-Z]{32,}\b')),
    ("Anthropic API Key",
     re.compile(r'\bsk-ant-[0-9a-zA-Z_-]{90,}\b')),
    # Google
    ("Google API Key",
     re.compile(r'\bAIza[0-9A-Za-z_-]{35}\b')),
    # Twilio
    ("Twilio Account SID",
     re.compile(r'\bAC[0-9a-f]{32}\b')),
    ("Twilio Auth Token",
     re.compile(r'\b[0-9a-f]{32}\b(?=.*twilio)', re.IGNORECASE)),
    # SendGrid
    ("SendGrid API Key",
     re.compile(r'\bSG\.[0-9a-zA-Z_-]{22}\.[0-9a-zA-Z_-]{43}\b')),
    # Heroku
    ("Heroku API Key",
     re.compile(r'\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b(?=.*heroku)',
                re.IGNORECASE)),
    # PEM private keys
    ("Private Key (PEM)",
     re.compile(r'-----BEGIN\s+(?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----')),
    # .env-style assignments with high-entropy values
    # Matches: TOKEN=sk-abc123... or API_KEY="ghp_xyz..."
    ("Env-style secret assignment",
     re.compile(
         r'(?:^|[\s;|&])(?:export\s+)?[A-Z][A-Z0-9_]{2,}(?:_KEY|_TOKEN|_SECRET|_PASSWORD|_PASS|_PWD|_CREDENTIAL|_API)\s*=\s*["\']?([^\s"\']{16,})',
         re.MULTILINE,
     )),
    # Bearer tokens in curl/wget/http calls
    ("Bearer Token",
     re.compile(r'\bBearer\s+([A-Za-z0-9\-_=]+\.[A-Za-z0-9\-_=]+\.?[A-Za-z0-9\-_.+/=]*)\b')),
    # Basic auth credentials embedded in URLs
    ("URL with embedded credentials",
     re.compile(r'https?://[^@\s]+:[^@\s]+@[^\s]+')),
]

# ── Entropy-based detection ────────────────────────────────────────────────────

# Characters that constitute a "high-density" charset for entropy scoring.
_BASE64_CHARS = set(string.ascii_letters + string.digits + "+/=")
_HEX_CHARS = set(string.hexdigits)

# Minimum token length and entropy threshold for the entropy scan.
_MIN_TOKEN_LENGTH = 20
_ENTROPY_THRESHOLD_BASE64 = 4.5   # bits per character (tuned to reduce false positives)
_ENTROPY_THRESHOLD_HEX = 3.5      # hex strings are less entropic by nature


def _shannon_entropy(s: str) -> float:
    """Compute Shannon entropy (bits per character) of a string."""
    if not s:
        return 0.0
    freq = {}
    for c in s:
        freq[c] = freq.get(c, 0) + 1
    length = len(s)
    return -sum((count / length) * math.log2(count / length) for count in freq.values())


def _looks_like_secret_token(token: str) -> Optional[str]:
    """
    Return a description if a token looks like a high-entropy secret.
    Returns None if the token is benign (file path, UUID, common word, etc.).
    """
    n = len(token)
    if n < _MIN_TOKEN_LENGTH:
        return None

    # Skip tokens that look like file paths.
    if token.startswith("/") or token.startswith("./") or token.startswith(".."):
        return None

    # Skip UUIDs (they're legitimately low-entropy by design and not secrets).
    if re.match(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', token, re.IGNORECASE):
        return None

    # Check base64-ish charset (letters + digits + +/=).
    if set(token) <= _BASE64_CHARS:
        entropy = _shannon_entropy(token)
        if entropy >= _ENTROPY_THRESHOLD_BASE64:
            return f"High-entropy base64-like token ({n} chars, entropy={entropy:.2f})"

    # Check hex charset.
    if set(token.lower()) <= _HEX_CHARS and n >= 32:
        entropy = _shannon_entropy(token.lower())
        if entropy >= _ENTROPY_THRESHOLD_HEX:
            return f"High-entropy hex string ({n} chars, entropy={entropy:.2f})"

    return None


# ── Public API ─────────────────────────────────────────────────────────────────

def scan_for_secrets(text: str) -> list[SecretMatch]:
    """
    Scan a text string for secrets using both regex patterns and entropy scoring.

    This function is exported for use by groq_client.py to scrub payloads
    before they leave the machine. It is a pure local function — no network,
    no side effects.

    Args:
        text: Any string to scan (command text, stderr excerpt, etc.)

    Returns:
        List of SecretMatch objects. Empty list = clean.
    """
    matches: list[SecretMatch] = []

    # Stage 1: regex patterns.
    for name, pattern in _SECRET_PATTERNS:
        for m in pattern.finditer(text):
            matches.append(SecretMatch(
                pattern_name=name,
                matched_text=m.group(0),
                start=m.start(),
                end=m.end(),
            ))

    # Stage 2: entropy scan on whitespace-delimited tokens.
    for token in _tokenize(text):
        desc = _looks_like_secret_token(token)
        if desc:
            # Find the offset in the original text.
            idx = text.find(token)
            matches.append(SecretMatch(
                pattern_name=desc,
                matched_text=token,
                start=idx,
                end=idx + len(token),
            ))

    # Deduplicate overlapping matches (keep the first-seen for each char range).
    return _deduplicate_matches(matches)


def redact_matches(text: str, matches: list[SecretMatch]) -> str:
    """
    Replace detected secrets in text with [REDACTED:<type>] markers.
    Used by groq_client.py to scrub payloads before sending to Groq.

    The actual secret value is NEVER included in the replacement.
    """
    if not matches:
        return text

    # Sort by start offset, process in reverse to preserve offsets.
    sorted_matches = sorted(matches, key=lambda m: m.start, reverse=True)
    result = text
    for m in sorted_matches:
        redaction = f"[REDACTED:{m.pattern_name}]"
        result = result[:m.start] + redaction + result[m.end:]
    return result


def check_leaked_secrets(command: str) -> RuleResult:
    """
    Main entry point for the leaked-secrets rule.

    Called on preexec events (before the command runs, if possible).
    NEVER escalates to Groq. NEVER sends command content to any network path.

    Args:
        command: The raw command string from preexec.

    Returns:
        HIGH_CONFIDENCE if any secret pattern matches.
        NONE otherwise.
    """
    matches = scan_for_secrets(command)
    if not matches:
        return RuleResult.none(RuleType.LEAKED_SECRETS)

    # Gather the pattern types found (but NOT the actual secret values).
    pattern_types = list(dict.fromkeys(m.pattern_name for m in matches))

    # For the fingerprint: use a hash of the pattern types + a prefix of the command
    # (not the secret values themselves — we hash only the structural signature).
    import hashlib
    fingerprint_data = f"leaked_secrets:{command[:50]}:{','.join(pattern_types)}"
    fingerprint_key = hashlib.sha256(fingerprint_data.encode()).hexdigest()[:24]

    return RuleResult(
        confidence=Confidence.HIGH_CONFIDENCE,
        rule_type=RuleType.LEAKED_SECRETS,
        facts={
            "pattern_types": pattern_types,
            "match_count": len(matches),
            # NEVER include matched_text in facts — it stays in the scanner only.
        },
        fingerprint_key=fingerprint_key,
    )


# ── Internal helpers ───────────────────────────────────────────────────────────

def _tokenize(text: str) -> list[str]:
    """
    Split text into candidate tokens for entropy scanning.
    Splits on whitespace and common shell metacharacters.
    """
    # Split on whitespace, quotes, equals, and shell operators.
    tokens = re.split(r'[\s=\'"`,;|&<>()\[\]{}\\]+', text)
    return [t for t in tokens if len(t) >= _MIN_TOKEN_LENGTH]


def _deduplicate_matches(matches: list[SecretMatch]) -> list[SecretMatch]:
    """Remove overlapping matches, keeping the earliest start position."""
    if not matches:
        return []
    sorted_m = sorted(matches, key=lambda m: (m.start, m.end))
    deduped: list[SecretMatch] = [sorted_m[0]]
    for m in sorted_m[1:]:
        last = deduped[-1]
        if m.start >= last.end:
            deduped.append(m)
        # If overlapping: skip (the earlier/longer match already covers it)
    return deduped


def validate_secret_pattern(pattern_name: str, regex_str: str) -> bool:
    """
    Validate that a custom regex pattern compiles cleanly and has a valid non-empty name.
    """
    if not pattern_name or not pattern_name.strip():
        return False
    if not regex_str or not regex_str.strip():
        return False
    try:
        re.compile(regex_str)
        return True
    except re.error:
        return False
