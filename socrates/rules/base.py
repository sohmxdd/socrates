"""
socrates/rules/base.py — Shared types for the rule engine.

This module defines the core data types that flow between:
  shell hook → daemon → rule engine → gate → delivery

It has ZERO imports from other socrates modules — it is the foundation
that everything else imports from, never the other way around.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Optional


# ── Enums ──────────────────────────────────────────────────────────────────────

class Confidence(Enum):
    """
    Rule output: how confident is the rule engine that an intervention is warranted?

    NONE            → No issue detected. The event is clean. Do nothing.
    HIGH_CONFIDENCE → Issue is clear and unambiguous. Intervene directly.
    LOW_CONFIDENCE  → Ambiguous signal. Route to Groq tiebreaker (unless
                      the rule is leaked_secrets, which never touches the network).
    """
    NONE = auto()
    HIGH_CONFIDENCE = auto()
    LOW_CONFIDENCE = auto()


class RuleType(str, Enum):
    """The four detection rules in v1."""
    FORGOTTEN_PUSH  = "forgotten_push"
    LEAKED_SECRETS  = "leaked_secrets"
    SILENT_FAILURE  = "silent_failure"
    STUCK_PROCESS   = "stuck_process"


class CaptureClass(str, Enum):
    """Command classification from the shell hook."""
    SAFE   = "SAFE"    # stderr was captured; artifact checks possible
    UNSAFE = "UNSAFE"  # exit-code-only; no output available


# ── Data types ─────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class EventData:
    """
    A completed command event, as passed to the rule engine.
    Created by the daemon from the postcmd event payload.
    """
    session_id:    str
    command:       str
    command_sig:   str
    cwd:           str
    capture_class: str                   # CaptureClass value
    start_ts:      str                   # ISO-8601 UTC
    end_ts:        str                   # ISO-8601 UTC
    exit_code:     int
    repo_path:     Optional[str] = None
    stderr_tail:   Optional[str] = None  # Only set for SAFE commands

    @property
    def duration_seconds(self) -> float:
        """Elapsed time in seconds. Returns 0.0 if timestamps are missing/invalid."""
        try:
            from datetime import datetime
            s = datetime.fromisoformat(self.start_ts)
            e = datetime.fromisoformat(self.end_ts)
            return max(0.0, (e - s).total_seconds())
        except Exception:
            return 0.0


@dataclass
class RuleResult:
    """
    The output of a single rule evaluation.

    confidence  : how confident the rule is
    rule_type   : which rule produced this result
    facts       : a dict of concrete, displayable facts (embedded in messages)
                  Keys are rule-specific; see each rule module for the schema.
    fingerprint_key : the stable string used to compute the dedup fingerprint.
                      Must not include timestamps — only semantically stable fields.
    """
    confidence:       Confidence
    rule_type:        RuleType
    facts:            dict[str, Any] = field(default_factory=dict)
    fingerprint_key:  str = ""

    @classmethod
    def none(cls, rule_type: RuleType) -> "RuleResult":
        """Convenience constructor for a NONE result."""
        return cls(confidence=Confidence.NONE, rule_type=rule_type)
