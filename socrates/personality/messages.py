"""
socrates/personality/messages.py — In-character message generation for Socrates.

Requirements (from Section 7):
  - Pure function: (rule_type, facts, quiet=False) -> str
  - Zero imports from rules, gate, daemon, or presentation.
  - Tone rules:
      * Short rhetorical / mock-Socratic question or observation.
      * Concrete facts first (counts, durations, branch names, file names).
      * Dry, slightly theatrical, never blocking.
      * Max 1–3 lines.
  - quiet=True: Plain, factual, direct message with no Socratic personality.
"""
from __future__ import annotations

from typing import Any


def generate_message(rule_type: Any, facts: dict, quiet: bool = False) -> str:
    """
    Generate an intervention message for a given rule type and facts dict.
    If quiet=True, returns a concise factual message with zero persona.
    """
    rt = getattr(rule_type, "value", str(rule_type)).lower()

    if "forgotten_push" in rt:
        return _format_forgotten_push(facts, quiet=quiet)
    elif "leaked_secrets" in rt:
        return _format_leaked_secrets(facts, quiet=quiet)
    elif "silent_failure" in rt:
        return _format_silent_failure(facts, quiet=quiet)
    elif "stuck_process" in rt:
        return _format_stuck_process(facts, quiet=quiet)
    else:
        return _format_generic(rt, facts, quiet=quiet)


def _format_forgotten_push(facts: dict, quiet: bool = False) -> str:
    count = facts.get("unpushed_count", facts.get("count", "some"))
    branch = facts.get("branch", "current branch")
    plural = "commit" if count == 1 else "commits"

    if quiet:
        return f"{count} unpushed {plural} on '{branch}'."

    snooze_hint = "(run 'socrates snooze' to mute this branch for today)"
    return (
        f"You have created {count} {plural} on '{branch}', yet they remain trapped upon this machine.\n"
        f"Tell me — what is the purpose of a commit that nobody can pull? {snooze_hint}"
    )


def _format_leaked_secrets(facts: dict, quiet: bool = False) -> str:
    pattern_names = facts.get("pattern_types", facts.get("pattern_names", []))
    if pattern_names:
        secret_type = ", ".join(pattern_names)
    else:
        secret_type = facts.get("secret_type", "sensitive credential")

    if quiet:
        return f"Detected potential secret in command: {secret_type}."

    article = "An" if secret_type[0].lower() in "aeiou" else "A"
    return (
        f"{article} {secret_type} sits plainly in that command, for any shell history or log to find.\n"
        f"Tell me — is a secret truly a secret, if you have just shouted it into your terminal?"
    )


def _format_silent_failure(facts: dict, quiet: bool = False) -> str:
    missing_artifact = facts.get("artifact_path", facts.get("missing_artifact"))
    error_keyword = facts.get("error_keyword", facts.get("symptom"))
    cmd = facts.get("command", "command")

    if missing_artifact:
        if quiet:
            return f"Command exited 0 but expected artifact was not created: '{missing_artifact}'."
        return (
            f"The command claimed success with exit code 0, yet '{missing_artifact}' does not exist.\n"
            f"Tell me — which one of you is lying?"
        )

    if error_keyword:
        if quiet:
            return f"Command exited 0 but produced error in stderr: '{error_keyword}'."
        return (
            f"The command exited with code 0, yet stderr reports '{error_keyword}'.\n"
            f"Tell me — what does success truly mean to you?"
        )

    if quiet:
        return f"Command exited 0 but appears to have failed silently: {cmd}"

    return (
        f"The command returned exit code 0, and yet all evidence suggests it did not succeed.\n"
        f"Tell me — if an error occurs in a shell and nobody checks its stderr, was it truly successful?"
    )


def _format_stuck_process(facts: dict, quiet: bool = False) -> str:
    elapsed = facts.get("elapsed_secs", facts.get("elapsed", 0))
    mean = facts.get("baseline_mean_secs", facts.get("mean", 0))
    cmd = facts.get("command_sig", facts.get("command", "process"))

    elapsed_str = _format_duration(elapsed)
    mean_str = _format_duration(mean)

    if quiet:
        return f"Process '{cmd}' has been running for {elapsed_str} (historical baseline: {mean_str})."

    return (
        f"Process '{cmd}' normally finishes in {mean_str}. It has now been running for {elapsed_str}.\n"
        f"Tell me — at what point does 'running' become 'waiting'?"
    )


def _format_generic(rt: str, facts: dict, quiet: bool = False) -> str:
    name = rt.replace("_", " ").title()
    if quiet:
        return f"Socrates: {name} event detected."
    return f"Socrates: A curious condition has arisen ({name}). Pray, observe your console."


def _format_duration(secs: float | int) -> str:
    """Format seconds into readable units (e.g. '12s', '3m 15s', '1h 5m')."""
    try:
        s = int(round(float(secs)))
    except (ValueError, TypeError):
        return str(secs)

    if s < 60:
        return f"{s} seconds" if s != 1 else "1 second"
    minutes = s // 60
    rem_s = s % 60
    if minutes < 60:
        if rem_s == 0:
            return f"{minutes} minutes" if minutes != 1 else "1 minute"
        return f"{minutes}m {rem_s}s"
    hours = minutes // 60
    rem_m = minutes % 60
    return f"{hours}h {rem_m}m"
