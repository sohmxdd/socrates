"""
socrates/rules/forgotten_push.py — Rule 1: Forgotten git push.

Checks whether the current branch has commits that haven't been pushed
to its tracked upstream remote.

Detection mechanism: `git rev-list @{u}..HEAD --count`
  - Returns N > 0 if there are N unpushed commits.
  - Returns 0 (or errors) if the branch is clean or has no upstream.

This rule is called ONLY from the periodic sweep (daemon/sweep.py),
never from preexec/postcmd event processing. The sweep runs on its own
clock, independent of any terminal session.

Network: NONE. Everything stays local — git talks to local refs only.
LLM: NEVER. This is a fully deterministic check.
"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Optional

from socrates.rules.base import Confidence, RuleResult, RuleType

logger = logging.getLogger(__name__)


def check_forgotten_push(repo_path: str) -> RuleResult:
    """
    Check whether the given git repo has unpushed commits on its current branch.

    Args:
        repo_path: Absolute path to the git repository root.

    Returns:
        RuleResult with:
          - NONE            if branch is clean, no upstream, or not a git repo
          - HIGH_CONFIDENCE if there are unpushed commits (count > 0)
    """
    path = Path(repo_path)
    if not path.exists() or not (path / ".git").exists():
        return RuleResult.none(RuleType.FORGOTTEN_PUSH)

    # Get unpushed commit count.
    commit_count = _get_unpushed_count(repo_path)
    if commit_count is None or commit_count == 0:
        return RuleResult.none(RuleType.FORGOTTEN_PUSH)

    # Get the current branch name for context.
    branch = _get_current_branch(repo_path) or "unknown"

    # Get the commit hashes ahead of upstream — used for fingerprinting.
    # The fingerprint changes when new commits are added, which correctly
    # signals "still actively in progress" vs. "actually forgotten."
    commit_range_hash = _get_commit_range_hash(repo_path)

    facts = {
        "repo_path": repo_path,
        "branch": branch,
        "unpushed_count": commit_count,
    }

    # fingerprint_key is the commit range hash, not the count.
    # New commits → new fingerprint → re-evaluation (but suppressed by
    # "still actively committing" logic in the sweep).
    fingerprint_key = f"forgotten_push:{repo_path}:{branch}:{commit_range_hash}"

    return RuleResult(
        confidence=Confidence.HIGH_CONFIDENCE,
        rule_type=RuleType.FORGOTTEN_PUSH,
        facts=facts,
        fingerprint_key=fingerprint_key,
    )


# ── Git helpers ────────────────────────────────────────────────────────────────

def _run_git(args: list[str], cwd: str, timeout: int = 5) -> Optional[str]:
    """
    Run a git command and return stdout as a stripped string.
    Returns None on error (not a repo, no upstream, timeout, etc.).
    """
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            return None
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None


def _get_unpushed_count(repo_path: str) -> Optional[int]:
    """
    Return the number of commits on HEAD that are not on the upstream.
    Returns None if the upstream isn't configured or the command fails.
    """
    output = _run_git(["rev-list", "@{u}..HEAD", "--count"], cwd=repo_path)
    if output is None:
        return None
    try:
        return int(output)
    except ValueError:
        return None


def _get_current_branch(repo_path: str) -> Optional[str]:
    """Return the current branch name, or None if detached/error."""
    return _run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_path)


def _get_commit_range_hash(repo_path: str) -> str:
    """
    Return a short hash representing the set of commits ahead of upstream.
    Used as the fingerprint component — changes when new commits are added.
    """
    # Get the list of commit hashes ahead of upstream, pipe through a stable sort.
    output = _run_git(["rev-list", "@{u}..HEAD"], cwd=repo_path)
    if not output:
        return "empty"
    # Hash the sorted commit list for a stable fingerprint.
    import hashlib
    commits = sorted(output.splitlines())
    return hashlib.sha256("\n".join(commits).encode()).hexdigest()[:16]
