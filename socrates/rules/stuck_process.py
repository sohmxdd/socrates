"""
socrates/rules/stuck_process.py — Rule 4: Stuck / unusually long processes.

Detects when a process is taking significantly longer than its own historical
baseline for that exact (project_dir, command_signature) pair.

Two detection paths:
  check_in_flight(row, baseline) — called by the periodic sweep while the process
    is STILL RUNNING. This is the primary path. Routes to OS notification since
    the user may have tabbed away. This is the path that delivers the intervention
    "in time to be useful" rather than retrospectively.

  check_postcmd(event, baseline) — called at postcmd time (after the process exits).
    This is a retrospective edge-case path: catches cases where the process exited
    before the sweep fired. Less immediately useful (the process is done) but still
    valuable as a "that took way too long" signal.

Baseline mechanics:
  - Uses Welford's online algorithm for running mean + variance (see db.py).
  - Only fires if count >= min_baseline_samples (default: 5) to ensure the
    baseline is statistically meaningful before making claims.
  - HIGH_CONFIDENCE if elapsed > 3x mean (unambiguously stuck)
  - LOW_CONFIDENCE if elapsed > mean + k * stddev (needs Groq tiebreaker)
  - NONE if elapsed is within normal range, or baseline is immature.

Per-command/per-project baselines (not global) are what prevent false positives:
  - 'npm install' in a large project may take 5 minutes → that's its baseline
  - 'pytest' in a small repo may take 2 seconds → flagged at 20 seconds
  - A global timeout would either be useless for one or annoyingly trigger on the other
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from socrates.rules.base import Confidence, EventData, RuleResult, RuleType

logger = logging.getLogger(__name__)


def _elapsed_seconds_from_ts(start_ts: str) -> float:
    """Return seconds elapsed since start_ts (ISO-8601 UTC) until now."""
    try:
        start = datetime.fromisoformat(start_ts)
        now = datetime.now(timezone.utc)
        return max(0.0, (now - start).total_seconds())
    except Exception:
        return 0.0


def _evaluate_against_baseline(
    elapsed: float,
    baseline: Optional[dict],
    min_samples: int,
    k_factor: float,
) -> Confidence:
    """
    Core threshold logic shared between the two detection paths.

    Returns:
        HIGH_CONFIDENCE if elapsed > 3x baseline mean
        LOW_CONFIDENCE  if elapsed > mean + k * stddev
        NONE            if within range or baseline immature
    """
    if baseline is None:
        return Confidence.NONE
    if baseline["count"] < min_samples:
        return Confidence.NONE

    mean = baseline["mean_secs"]
    stddev = baseline["stddev_secs"]

    if mean <= 0:
        return Confidence.NONE

    # Require a minimum absolute elapsed time to avoid firing on sub-second commands.
    if elapsed < 5.0:
        return Confidence.NONE

    if elapsed > 3.0 * mean:
        return Confidence.HIGH_CONFIDENCE

    threshold = mean + k_factor * stddev
    if elapsed > threshold:
        return Confidence.LOW_CONFIDENCE

    return Confidence.NONE


def check_in_flight(
    row: Any,  # sqlite3.Row from in_flight table
    baseline: Optional[dict],
    *,
    min_baseline_samples: int = 5,
    k_factor: float = 2.0,
) -> RuleResult:
    """
    Check an in-flight (currently running) process against its baseline.
    Called by the periodic sweep while the process is still running.

    Args:
        row: An in_flight table row (sqlite3.Row).
        baseline: Dict from db.get_baseline(), or None if no history yet.
        min_baseline_samples: Minimum samples before firing.
        k_factor: Stddev multiplier for the LOW_CONFIDENCE threshold.

    Returns:
        RuleResult with HIGH_CONFIDENCE, LOW_CONFIDENCE, or NONE.
    """
    command = row["command"]
    command_sig = row["command_sig"]
    project_dir = row["repo_path"] or row["cwd"]
    start_ts = row["start_ts"]
    session_id = row["session_id"]
    already_fired = bool(row["stuck_fired"])

    # Don't double-fire for the same invocation.
    if already_fired:
        return RuleResult.none(RuleType.STUCK_PROCESS)

    elapsed = _elapsed_seconds_from_ts(start_ts)
    confidence = _evaluate_against_baseline(elapsed, baseline, min_baseline_samples, k_factor)

    if confidence == Confidence.NONE:
        return RuleResult.none(RuleType.STUCK_PROCESS)

    baseline_mean = baseline["mean_secs"] if baseline else None
    fingerprint_key = _make_fingerprint(command_sig, project_dir, start_ts)

    return RuleResult(
        confidence=confidence,
        rule_type=RuleType.STUCK_PROCESS,
        facts={
            "command": command,
            "command_sig": command_sig,
            "project_dir": project_dir,
            "elapsed_seconds": elapsed,
            "baseline_mean_seconds": baseline_mean,
            "baseline_count": baseline["count"] if baseline else 0,
            "session_id": session_id,
            "start_ts": start_ts,
            "detection_path": "in_flight_sweep",
        },
        fingerprint_key=fingerprint_key,
    )


def check_postcmd(
    event: EventData,
    baseline: Optional[dict],
    *,
    min_baseline_samples: int = 5,
    k_factor: float = 2.0,
) -> RuleResult:
    """
    Retrospective check at postcmd time (after the process has already exited).
    This is a secondary path — the in_flight sweep is the primary detection mechanism.

    Useful for catching cases where a process exits between sweep cycles,
    and for building the context ("this took 40 minutes") into the event log
    even if the in_flight sweep didn't fire.

    Returns NONE unless the duration is extreme (> 3x mean only — we don't
    fire LOW_CONFIDENCE retrospectively since the Groq call would be too late
    to be actionable).
    """
    elapsed = event.duration_seconds
    if elapsed < 5.0:
        return RuleResult.none(RuleType.STUCK_PROCESS)

    if baseline is None or baseline.get("count", 0) < min_baseline_samples:
        return RuleResult.none(RuleType.STUCK_PROCESS)

    mean = baseline["mean_secs"]
    if mean <= 0 or elapsed <= 3.0 * mean:
        return RuleResult.none(RuleType.STUCK_PROCESS)

    # Only HIGH_CONFIDENCE retrospectively (> 3x mean).
    project_dir = event.repo_path or event.cwd
    fingerprint_key = _make_fingerprint(event.command_sig, project_dir, event.start_ts)

    return RuleResult(
        confidence=Confidence.HIGH_CONFIDENCE,
        rule_type=RuleType.STUCK_PROCESS,
        facts={
            "command": event.command,
            "command_sig": event.command_sig,
            "project_dir": project_dir,
            "elapsed_seconds": elapsed,
            "baseline_mean_seconds": mean,
            "baseline_count": baseline["count"],
            "detection_path": "postcmd_retrospective",
        },
        fingerprint_key=fingerprint_key,
    )


def _make_fingerprint(command_sig: str, project_dir: str, start_ts: str) -> str:
    """
    Fingerprint for a stuck-process result.
    Includes start_ts so the same command run at different times gets
    distinct fingerprints (we want to alert on each unusually long run,
    not suppress all future alerts after the first).
    """
    fp_data = f"stuck_process:{command_sig}:{project_dir}:{start_ts}"
    return hashlib.sha256(fp_data.encode()).hexdigest()[:24]
