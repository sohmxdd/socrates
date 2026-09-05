"""
socrates/gate/fingerprint.py — Stable fingerprints for deduplication.

A fingerprint is a stable hash of a rule result's semantically meaningful fields
— not timestamps, not incidental details. Two results with the same fingerprint
represent "the same intervention" for suppression purposes.

Fingerprint lifecycle:
  1. Generated from RuleResult.fingerprint_key (set by each rule).
  2. Stored in suppression_state table when the result fires.
  3. Checked before delivery: if a recent fire with the same fingerprint exists
     and the snooze/dismiss conditions hold, the result is suppressed.
  4. Reset when the underlying condition changes (e.g., new commits on the branch
     produce a new commit-range hash → new fingerprint → re-evaluation).

Design: this module is a pure function — no DB access, no config, no side effects.
"""
from __future__ import annotations

import hashlib


def make_fingerprint(fingerprint_key: str) -> str:
    """
    Convert a rule's fingerprint_key into a canonical fingerprint string.

    The fingerprint_key is already a semantically meaningful string (set by
    each rule). We hash it here to produce a fixed-length, safe identifier.

    Args:
        fingerprint_key: A stable string produced by a rule (e.g.,
            "forgotten_push:/home/user/myrepo:main:deadbeef1234")

    Returns:
        A 32-character hex string fingerprint.
    """
    if not fingerprint_key:
        raise ValueError("fingerprint_key must not be empty")
    return hashlib.sha256(fingerprint_key.encode("utf-8")).hexdigest()[:32]


def compute_fingerprint(rule_type: str, facts: dict) -> str:
    """
    Compute a fingerprint directly from rule_type and facts dictionary.
    Useful when a RuleResult.fingerprint_key is not pre-computed.
    """
    rt = str(rule_type).lower().replace("ruletype.", "")
    if "forgotten_push" in rt:
        repo = facts.get("repo_path", "")
        branch = facts.get("branch", "")
        commit_range = facts.get("commit_range", facts.get("unpushed_count", ""))
        key = f"forgotten_push:{repo}:{branch}:{commit_range}"
    elif "leaked_secrets" in rt:
        cmd_part = facts.get("command_hash", facts.get("command", ""))
        key = f"leaked_secrets:{cmd_part}"
    elif "silent_failure" in rt:
        cmd_sig = facts.get("command_sig", facts.get("command", ""))
        pattern = facts.get("pattern_id", facts.get("error_pattern", ""))
        key = f"silent_failure:{cmd_sig}:{pattern}"
    elif "stuck_process" in rt:
        cmd_sig = facts.get("command_sig", facts.get("command", ""))
        pdir = facts.get("project_dir", facts.get("cwd", ""))
        start_ts = facts.get("start_ts", "")
        key = f"stuck_process:{cmd_sig}:{pdir}:{start_ts}"
    else:
        key = f"{rt}:{sorted(facts.items())}"

    return make_fingerprint(key)
