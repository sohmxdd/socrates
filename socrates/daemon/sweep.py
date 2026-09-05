"""
socrates/daemon/sweep.py — Periodic sweeps run by the daemon.

Sweeps running on independent clocks:

  run_repo_sweep(db_path, config, home)
    Called every `sweep_interval_seconds` (default: 600s / 10 min).
    For each known repo in the DB:
      1. Run forgotten_push check.
      2. Apply "still actively committing" guard: if the latest commit on the branch
         was made within the last N minutes (default: 5), skip — the developer is
         in the middle of a commit series, not "forgetting" to push.
      3. Route through the intervention gate (dedup + suppression check).
      4. Also check for long-pending messages that need escalation to OS notification.

  run_in_flight_sweep(db_path, config, home)
    Called every `stuck_sweep_interval_seconds` (default: 30s).
    For each in_flight row:
      1. Retrieve the baseline for this (project_dir, command_sig).
      2. Run stuck_process.check_in_flight().
      3. If HIGH_CONFIDENCE or LOW_CONFIDENCE: mark stuck_fired, deliver
         an OS notification immediately (not via pending file — the user has
         likely tabbed away).

Both sweeps are designed to be idempotent and safe to interrupt mid-run.
They catch and log exceptions per-item to avoid one bad repo killing the sweep.
"""
from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path
from typing import Optional, Any

logger = logging.getLogger(__name__)


def run_repo_sweep(db_path: Path, config: Any, home: Path) -> None:
    """
    Sweep known repos for unpushed commits.
    Called by the daemon's periodic sweep task on its own clock.
    """
    from socrates.daemon import db
    from socrates.gate.intervention_gate import InterventionGate

    repos = db.get_all_known_repos(db_path)
    gate = InterventionGate(db_path, config, home)

    for repo in repos:
        repo_path = repo["repo_path"]
        try:
            _sweep_one_repo(repo_path, db_path, gate, config)
            db.update_repo_swept_ts(db_path, repo_path)
        except Exception:
            logger.debug("Error sweeping repo %s", repo_path, exc_info=True)

    # Check for stale pending messages that need escalation
    try:
        gate.check_and_escalate_pending()
    except Exception:
        logger.debug("Error during pending escalation check.", exc_info=True)


def _sweep_one_repo(
    repo_path: str,
    db_path: Path,
    gate: Any,
    config: Any,
) -> None:
    """Sweep a single repo for forgotten pushes."""
    from socrates.rules.forgotten_push import check_forgotten_push
    from socrates.rules.base import Confidence

    # Guard: skip if the repo doesn't exist anymore.
    if not Path(repo_path).exists():
        return

    # Guard: "still actively committing" — if the latest commit was recent,
    # the developer is mid-session, not forgetting to push.
    active_window = getattr(config, "active_commit_window_seconds", 300)
    recent_commit_age = _get_latest_commit_age_seconds(repo_path)
    if recent_commit_age is not None and recent_commit_age < active_window:
        logger.debug("Skipping %s — latest commit is only %ds old", repo_path, recent_commit_age)
        return

    result = check_forgotten_push(repo_path)
    if result.confidence == Confidence.NONE:
        return

    # Route through the intervention gate (dedup + suppression check).
    if gate.should_fire(result):
        gate.record_fire(result)
        gate.write_pending(result, repo_path=repo_path)


def run_in_flight_sweep(db_path: Path, config: Any, home: Path) -> None:
    """
    Sweep in-flight (currently-running) processes for stuck detection.
    Called by the daemon's periodic sweep task every ~30s.
    """
    from socrates.daemon import db
    from socrates.gate.intervention_gate import InterventionGate

    rows = db.get_all_in_flight(db_path)
    if not rows:
        return

    gate = InterventionGate(db_path, config, home)

    for row in rows:
        try:
            _check_one_in_flight(row, db_path, gate, config)
        except Exception:
            logger.debug(
                "Error checking in_flight row %s", row.get("command"), exc_info=True
            )


def _check_one_in_flight(row: Any, db_path: Path, gate: Any, config: Any) -> None:
    """Check one in-flight row for stuck-process condition."""
    from socrates.daemon import db
    from socrates.rules.stuck_process import check_in_flight
    from socrates.rules.base import Confidence

    # Retrieve the baseline for this (project_dir, command_sig).
    project_dir = row["repo_path"] or row["cwd"]
    command_sig = row["command_sig"]
    baseline = db.get_baseline(db_path, project_dir=project_dir, command_sig=command_sig)

    min_samples = getattr(config, "min_baseline_samples", 5)
    k_factor = getattr(config, "stuck_k_factor", getattr(config, "baseline_k_factor", 2.0))

    result = check_in_flight(
        row,
        baseline,
        min_baseline_samples=min_samples,
        k_factor=k_factor,
    )

    if result.confidence == Confidence.NONE:
        return

    # Route through the gate first.
    if not gate.should_fire(result):
        return

    gate.record_fire(result)

    # Mark stuck_fired so the sweep doesn't re-fire on the same invocation.
    db.mark_in_flight_stuck_fired(
        db_path,
        session_id=row["session_id"],
        command_sig=command_sig,
        start_ts=row["start_ts"],
    )

    # Deliver as OS notification immediately (user has likely tabbed away).
    # This does NOT go through the pending file system — it fires directly.
    try:
        message = _format_message(result)
        _deliver_os_notification(title="Socrates", message=message)
    except Exception:
        logger.debug("Error delivering stuck-process notification.", exc_info=True)


# ── Delivery & formatting helpers ─────────────────────────────────────────────

def _deliver_os_notification(title: str, message: str) -> None:
    """Deliver an OS notification, safely handling missing presentation modules."""
    try:
        from socrates.presentation.notify import send_os_notification
        send_os_notification(title=title, body=message)
    except Exception:
        logger.debug("OS notification delivery skipped or not available.", exc_info=True)


def _format_message(result: Any) -> str:
    """Safely format an intervention message."""
    try:
        from socrates.personality.messages import generate_message
        return generate_message(result.rule_type, result.facts)
    except Exception:
        rule_name = getattr(result.rule_type, "value", str(result.rule_type))
        return f"Socrates: {rule_name.replace('_', ' ').capitalize()} detected."


# ── Git helpers for the "actively committing" guard ───────────────────────────

def _get_latest_commit_age_seconds(repo_path: str) -> Optional[float]:
    """
    Return how many seconds ago the most recent commit on HEAD was made.
    Returns None if the repo has no commits or the command fails.
    """
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%ct"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None
        commit_ts = int(result.stdout.strip())
        return time.time() - commit_ts
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError, ValueError):
        return None
