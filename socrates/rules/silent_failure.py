"""
socrates/rules/silent_failure.py — Rule 3: Silent failures (exit 0, bad output).

Detects commands that claim success (exit code 0) but show clear signs of failure:
  - stderr contains error-pattern keywords despite a clean exit code
  - An expected output artifact (from the command syntax) doesn't exist
    or wasn't modified after the command ran

Confidence levels:
  HIGH_CONFIDENCE — Clear keyword match in stderr AND/OR artifact definitely missing
  LOW_CONFIDENCE  — Ambiguous stderr noise (warnings that could be benign);
                    artifact check inconclusive
  NONE            — Exit code != 0 (that's a real failure, handled differently),
                    or UNSAFE capture class (no stderr available), or clean output

Note: if the command's capture_class is UNSAFE, we have no stderr tail and cannot
run the output-based check. In that case the rule only runs the artifact check
(if the command structure implies one), and only at LOW_CONFIDENCE at most.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
from pathlib import Path
from typing import Optional

from socrates.rules.base import Confidence, EventData, RuleResult, RuleType

logger = logging.getLogger(__name__)


# ── Stderr error keyword patterns ─────────────────────────────────────────────

# HIGH_CONFIDENCE patterns: these are unambiguous failure signals even at exit 0.
_HIGH_CONFIDENCE_PATTERNS: list[re.Pattern] = [
    re.compile(r'\bERROR\b', re.IGNORECASE),
    re.compile(r'\bFailed to\b', re.IGNORECASE),
    re.compile(r'\bCould not\b', re.IGNORECASE),
    re.compile(r'\bNo such file or directory\b', re.IGNORECASE),
    re.compile(r'\bPermission denied\b', re.IGNORECASE),
    re.compile(r'\bConnection refused\b', re.IGNORECASE),
    re.compile(r'\bSegmentation fault\b', re.IGNORECASE),
    re.compile(r'\bAborted\b'),
    re.compile(r'\bTraceback \(most recent call last\)', re.IGNORECASE),
    re.compile(r'\bException:\s'),
    re.compile(r'\bFATAL\b', re.IGNORECASE),
    re.compile(r'\bPANIC\b'),
    re.compile(r'\bcore dumped\b', re.IGNORECASE),
    re.compile(r'npm ERR!'),
    re.compile(r'\bFAILED\b.*\['),          # pytest FAILED path [n%]

    re.compile(r'\d+ failed'),            # pytest: "1 failed, 2 passed"
    re.compile(r'Build FAILED', re.IGNORECASE),
    re.compile(r'make.*Error\s+\d+', re.IGNORECASE),
    re.compile(r'error\[E\d+\]'),         # Rust compiler errors
    re.compile(r'SyntaxError:'),
    re.compile(r'NameError:'),
    re.compile(r'ImportError:'),
    re.compile(r'ModuleNotFoundError:'),
]

# LOW_CONFIDENCE patterns: often benign, but worth flagging for LLM review.
_LOW_CONFIDENCE_PATTERNS: list[re.Pattern] = [
    re.compile(r'\bWARNING\b', re.IGNORECASE),
    re.compile(r'\bwarn\b', re.IGNORECASE),
    re.compile(r'\bdeprecated\b', re.IGNORECASE),
    re.compile(r'\bskipped\b', re.IGNORECASE),
    re.compile(r'\bignored\b', re.IGNORECASE),
    re.compile(r'\bfallback\b', re.IGNORECASE),
    re.compile(r'\bnot found\b', re.IGNORECASE),
    re.compile(r'\bunreachable\b', re.IGNORECASE),
]

# Patterns to explicitly ignore: these are almost always benign.
_IGNORE_PATTERNS: list[re.Pattern] = [
    re.compile(r'^\s*$'),                               # blank lines
    re.compile(r'^\s*#'),                               # comment lines
    re.compile(r'npm warn', re.IGNORECASE),             # npm warnings are very noisy
    re.compile(r'DeprecationWarning.*site-packages'),   # Python stdlib warnings
    re.compile(r'UserWarning.*matplotlib'),             # matplotlib warnings
    re.compile(r'git: .warning.'),
]


def _classify_stderr(stderr_tail: str) -> Confidence:
    """
    Classify stderr content as HIGH_CONFIDENCE, LOW_CONFIDENCE, or NONE.
    Returns the highest-confidence classification found.
    """
    # Filter out known-benign lines.
    lines = stderr_tail.splitlines()
    relevant_lines = []
    for line in lines:
        if any(ignore.search(line) for ignore in _IGNORE_PATTERNS):
            continue
        relevant_lines.append(line)

    if not relevant_lines:
        return Confidence.NONE

    relevant_text = "\n".join(relevant_lines)

    # Check high-confidence patterns first.
    for pattern in _HIGH_CONFIDENCE_PATTERNS:
        if pattern.search(relevant_text):
            return Confidence.HIGH_CONFIDENCE

    # Check low-confidence patterns.
    for pattern in _LOW_CONFIDENCE_PATTERNS:
        if pattern.search(relevant_text):
            return Confidence.LOW_CONFIDENCE

    return Confidence.NONE


# ── Artifact inference ────────────────────────────────────────────────────────

def _infer_output_artifact(command: str, cwd: str) -> Optional[str]:
    """
    Try to infer the expected output file from the command structure.
    Returns an absolute path if one can be confidently inferred, else None.
    """
    parts = command.strip().split()
    if not parts:
        return None

    cmd = parts[0].split("/")[-1]  # strip path

    # gcc/clang/rustc: look for -o <file>
    if cmd in ("gcc", "g++", "clang", "clang++", "rustc", "cc"):
        for i, part in enumerate(parts):
            if part == "-o" and i + 1 < len(parts):
                artifact = parts[i + 1]
                return _resolve_path(artifact, cwd)


    # cp: cp src dst  → dst is the artifact
    if cmd == "cp" and len(parts) >= 3:
        return _resolve_path(parts[-1], cwd)

    # mv: mv src dst  → dst is the artifact (src should disappear)
    if cmd == "mv" and len(parts) >= 3:
        return _resolve_path(parts[-1], cwd)

    # make: if a target is specified, it might be a file
    if cmd == "make" and len(parts) >= 2:
        target = parts[1]
        if not target.startswith("-") and "." in target:
            return _resolve_path(target, cwd)

    # go build -o <file> or go build (defaults to package name)
    if cmd == "go" and len(parts) >= 2 and parts[1] == "build":
        for i, part in enumerate(parts):
            if part == "-o" and i + 1 < len(parts):
                return _resolve_path(parts[i + 1], cwd)

    return None


def _resolve_path(path_str: str, cwd: str) -> str:
    """Resolve a potentially relative path against cwd."""
    p = Path(path_str)
    if p.is_absolute():
        return str(p)
    return str(Path(cwd) / p)


def _check_artifact_exists(artifact_path: str) -> bool:
    """Return True if the artifact exists and is non-empty."""
    try:
        p = Path(artifact_path)
        return p.exists() and p.stat().st_size > 0
    except OSError:
        return False


# ── Main rule function ─────────────────────────────────────────────────────────

def check_silent_failure(event: EventData) -> RuleResult:
    """
    Check whether a command silently failed (exit code 0 with failure signals).

    Args:
        event: Completed command event data.

    Returns:
        RuleResult with HIGH_CONFIDENCE, LOW_CONFIDENCE, or NONE.
    """
    # Only fire on exit code 0 — a nonzero exit is an explicit failure,
    # not a "silent" one, and is handled differently.
    if event.exit_code != 0:
        return RuleResult.none(RuleType.SILENT_FAILURE)

    best_confidence = Confidence.NONE
    symptom = ""

    # Stderr-based check (SAFE commands only — UNSAFE have no stderr tail).
    if event.capture_class == "SAFE" and event.stderr_tail:
        stderr_confidence = _classify_stderr(event.stderr_tail)
        if stderr_confidence.value > best_confidence.value:
            best_confidence = stderr_confidence
            # Extract a short representative snippet for the message.
            symptom = _extract_symptom_line(event.stderr_tail)

    # Artifact-based check (works for both SAFE and UNSAFE, based on command text).
    artifact_path = _infer_output_artifact(event.command, event.cwd)
    if artifact_path:
        if not _check_artifact_exists(artifact_path):
            # Expected artifact is missing — this is HIGH_CONFIDENCE regardless
            # of stderr content.
            best_confidence = Confidence.HIGH_CONFIDENCE
            artifact_name = Path(artifact_path).name
            symptom = f"expected output '{artifact_name}' does not exist"

    if best_confidence == Confidence.NONE:
        return RuleResult.none(RuleType.SILENT_FAILURE)

    # Build fingerprint from command signature + symptom type.
    fp_data = f"silent_failure:{event.command_sig}:{symptom[:60]}"
    fingerprint_key = hashlib.sha256(fp_data.encode()).hexdigest()[:24]

    return RuleResult(
        confidence=best_confidence,
        rule_type=RuleType.SILENT_FAILURE,
        facts={
            "command": event.command,
            "command_sig": event.command_sig,
            "exit_code": event.exit_code,
            "symptom": symptom,
            "artifact_path": artifact_path,
            "stderr_excerpt": _truncate(event.stderr_tail or "", 300),
        },
        fingerprint_key=fingerprint_key,
    )


# ── Helpers ────────────────────────────────────────────────────────────────────

def _extract_symptom_line(stderr_tail: str) -> str:
    """
    Extract the most informative single line from stderr for the message.
    Prefers lines matching high-confidence patterns.
    """
    lines = stderr_tail.splitlines()
    for pattern in _HIGH_CONFIDENCE_PATTERNS:
        for line in lines:
            if pattern.search(line):
                return line.strip()[:120]
    for line in reversed(lines):  # Last non-empty line as fallback
        if line.strip():
            return line.strip()[:120]
    return ""


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + "…"
