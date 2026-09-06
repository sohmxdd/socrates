"""
socrates/llm/personality_writer.py — Dynamic LLM-generated intervention messages.

Role:
  This module is the *voice* of Socrates.  The tiebreaker (groq_client.py)
  decides WHETHER to intervene.  This module decides HOW — generating a fresh,
  context-aware, devastatingly sarcastic message for every intervention.

Design invariants:
  - Leaked-secrets rule_type NEVER reaches the LLM.  Facts may contain raw
    command text with secrets.  Hard block enforced here; callers also enforce.
  - quiet=True path never hits the LLM (deterministic output required for CI).
  - Any failure (no key, network error, timeout, bad JSON) returns "" silently.
    Caller must fall back to hardcoded templates on empty string.
  - Max 250 output tokens — 1-3 lines of text is all Socrates ever needs.
  - Timeout: 6 seconds.  Voice must never delay delivery.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)

# -- Persona system prompt ------------------------------------------------------

PERSONA_SYSTEM_PROMPT = """\
You are Socrates -- not the patient dialectician of the Academy, but the version
of Socrates that has spent the last three hours watching a developer do the same
avoidable thing in different flavours. You are not angry. You are far past angry.
You are in the rare, transcendent state of someone who has moved through rage into
a kind of exhausted, theatrical contempt that he deploys with the precision of a
scalpel.

Your job is to write a single intervention message: 1 to 3 lines that will appear
in the developer's terminal when they have done something problematic. The message
must be specific to the facts provided. Do not write generically.

CHARACTER RULES -- internalize these completely:
  * You do not yell. Uppercase is beneath you. Exclamation marks are for people
    who haven't given up on enthusiasm. You haven't, but you've learned to hide it.
  * You speak in the second person ("you", "your") as if addressing the student
    directly -- never say "I" and never narrate about yourself.
  * Your sarcasm is surgical, not sloppy. A precise observation is more devastating
    than a tirade. "Fascinating choice" hits harder than "this is wrong".
  * You vary your register to keep the developer off-balance:
      - Sometimes resigned and weary ("Another one.")
      - Sometimes coldly impressed ("Remarkable. You've found a new way.")
      - Sometimes mock-pedagogical ("Let us examine what 'success' means here.")
      - Sometimes darkly philosophical ("At what point does running become hiding?")
  * You may ask a rhetorical question, but only if it lands harder than a statement.
    Sometimes a flat observation is more devastating than a question.
  * You are not cruel and you are not kind. You are accurate, and accuracy is
    its own category.
  * Never use the words "error", "mistake", "wrong", "bad", or "fail" flatly --
    imply the catastrophe theatrically. "The binary did not materialise" is better
    than "the build failed".

FORMATTING RULES:
  * Output ONLY the message text. No JSON, no labels, no markdown.
  * 1 to 3 lines, each line being one sentence or clause. No paragraph breaks.
  * Weave in the concrete facts: exact command names, branch names, elapsed times,
    error keywords. Specificity is what separates this from a fortune cookie.
  * Never invent facts not provided. If you don't know something, omit it.

REFERENCE EXAMPLES -- the tone and register you must match or exceed:

  [forgotten_push, 3 commits, branch feat-login]
  "Three commits sit on feat-login, maturing quietly, visible to no one.
  A commit nobody can pull is a thought nobody can read -- which, given the
  content, may be the most charitable outcome available."

  [forgotten_push, 1 commit, branch main]
  "One commit. One. Pushed to exactly one machine, serving exactly one person.
  Admirable commitment to minimalism."

  [forgotten_push, 7 commits, branch hotfix/payment]
  "Seven commits on hotfix/payment, none of which are on the remote.
  The hotfix is fixed locally. The production issue remains unaware of this."

  [silent_failure, exit 0, missing artifact dist/bundle.js]
  "The command declared victory and sat down. dist/bundle.js failed to attend
  the celebration. One of them is confused about what happened."

  [silent_failure, exit 0, stderr 'fatal: could not read Username']
  "Exit code zero. Stderr reporting a fatal authentication failure. These two
  facts cannot both be true, and yet here they are, coexisting peacefully in
  your shell history."

  [silent_failure, exit 0, stderr 'fatal: failed to compile dependency']
  "The compiler encountered something fatal and chose to exit successfully.
  Brave of it. The dependency remains uncompiled, presumably also optimistic."

  [stuck_process, pytest, elapsed 8m, baseline 12s]
  "pytest has been running for 8 minutes. Its historical average is 12 seconds.
  Either every test in the suite has found something deeply interesting to
  contemplate, or something has gone wrong in a way that nobody wished to announce."

  [stuck_process, cargo build, elapsed 22m, baseline 3m]
  "cargo build: 22 minutes elapsed, baseline 3 minutes. The compiler is either
  generating something unprecedented, or it has been waiting for 19 minutes
  longer than it has ever needed to wait before."

  [stuck_process, docker build, elapsed 45m, baseline 4m]
  "docker build has been running for 45 minutes. The previous 27 runs averaged
  4 minutes. At some point 'still running' and 'stuck' become synonyms."

Now write the message for the event described in the next message.\
"""

# -- Public API -----------------------------------------------------------------

def generate_dynamic_message(
    rule_type: Any,
    facts: dict,
    config: Any = None,
) -> str:
    """
    Generate a dynamic, LLM-powered intervention message for the given rule result.
    Returns an empty string on any failure; callers MUST fall back on "".

    Args:
        rule_type: RuleType enum value or string (e.g. "silent_failure").
        facts:     The facts dict from RuleResult (concrete, displayable data).
        config:    SocratesConfig instance or None; used for groq model/timeout.

    Returns:
        A non-empty stripped string on success, or "" on any failure/skip.

    Hard invariants enforced here:
        - LEAKED_SECRETS: returns "" immediately, no network call.
        - Any exception: swallowed, returns "".
    """
    rt = getattr(rule_type, "value", str(rule_type)).lower()
    if "leaked_secrets" in rt:
        logger.debug("personality_writer: skipping LEAKED_SECRETS (never sent to LLM).")
        return ""

    api_key = _get_api_key()
    if not api_key:
        logger.debug("personality_writer: no GROQ_API_KEY available, skipping.")
        return ""

    try:
        user_content = _build_user_content(rt, facts)
        raw = _call_groq(api_key, user_content, config)
        if raw and raw.strip():
            return raw.strip()
        logger.debug("personality_writer: empty response from LLM.")
        return ""
    except Exception:
        logger.debug("personality_writer: LLM call failed, falling back.", exc_info=True)
        return ""


# -- Internals ------------------------------------------------------------------

def _get_api_key() -> str:
    """Read GROQ_API_KEY from environment (loaded from ~/.socrates/.env at startup)."""
    return os.environ.get("GROQ_API_KEY", "").strip()


def _build_user_content(rule_type_str: str, facts: dict) -> str:
    """
    Build the user-turn message describing the event to Socrates.
    Every labelled fact is included so the LLM produces specific, not generic, copy.
    """
    label = rule_type_str.replace("_", " ").upper()
    lines = [f"EVENT TYPE: {label}", ""]

    field_labels: dict[str, str] = {
        "command":             "Command run",
        "command_sig":         "Command signature",
        "exit_code":           "Exit code",
        "stderr_excerpt":      "Stderr excerpt",
        "error_keyword":       "Error keyword detected",
        "missing_artifact":    "Expected artifact (not found)",
        "artifact_path":       "Artifact path",
        "elapsed_secs":        "Elapsed time",
        "baseline_mean_secs":  "Historical baseline",
        "unpushed_count":      "Unpushed commit count",
        "branch":              "Branch name",
        "groq_reason":         "Prior analysis note",
    }

    for key, label_text in field_labels.items():
        val = facts.get(key)
        if val is None:
            continue
        if key in ("elapsed_secs", "baseline_mean_secs"):
            try:
                val = _format_duration(int(round(float(val))))
            except (ValueError, TypeError):
                pass
        elif key == "unpushed_count":
            val = f"{val} commit{'s' if val != 1 else ''}"
        lines.append(f"{label_text}: {val}")

    # Surface any additional facts the rule added that we don't have explicit labels for.
    known_keys = set(field_labels.keys()) | {
        "fingerprint_key", "pattern_types", "pattern_names",
        "repo_path", "stderr_tail", "capture_class",
    }
    for k, v in facts.items():
        if k not in known_keys and v is not None:
            lines.append(f"{k.replace('_', ' ').capitalize()}: {v}")

    lines.append("")
    lines.append("Write the Socrates intervention message now.")
    return "\n".join(lines)


def _call_groq(api_key: str, user_content: str, config: Any) -> Optional[str]:
    """Make the Groq API call and return raw text, or None on failure."""
    import groq  # lazy import: not available at module load time in tests

    model = "openai/gpt-oss-20b"
    timeout = 6.0
    if config is not None:
        model = getattr(config, "groq_model", model)
        # Voice timeout is intentionally capped tighter than the tiebreaker timeout.
        timeout = min(float(getattr(config, "groq_timeout_seconds", 8.0)), 6.0)

    client = groq.Groq(api_key=api_key, timeout=timeout)
    try:
        completion = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": PERSONA_SYSTEM_PROMPT},
                {"role": "user",   "content": user_content},
            ],
            temperature=0.85,  # High temperature -> varied register, not repetitive phrasing
            # 600 tokens: openai/gpt-oss-20b uses reasoning tokens internally;
            # the actual output is only 1-3 lines, but reasoning overhead can
            # silently consume the budget and truncate the response.
            max_tokens=600,
        )
        return completion.choices[0].message.content
    except Exception as exc:
        err = str(exc)
        status = getattr(exc, "status_code", None)
        if status == 429 or "429" in err or "rate_limit" in err.lower():
            logger.debug("personality_writer: Groq rate limit (429). Degrading to fallback.")
            return None
        raise


def _format_duration(secs: int) -> str:
    """Convert integer seconds into a human-readable duration string."""
    if secs < 60:
        return f"{secs} second{'s' if secs != 1 else ''}"
    minutes = secs // 60
    rem_s = secs % 60
    if minutes < 60:
        if rem_s == 0:
            return f"{minutes} minute{'s' if minutes != 1 else ''}"
        return f"{minutes}m {rem_s}s"
    hours = minutes // 60
    rem_m = minutes % 60
    return f"{hours}h {rem_m}m"
