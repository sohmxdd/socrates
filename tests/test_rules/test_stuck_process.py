"""tests/test_rules/test_stuck_process.py"""
import sqlite3
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

import pytest

from socrates.rules.base import Confidence, RuleType
from socrates.rules.base import EventData
from socrates.rules.stuck_process import check_in_flight, check_postcmd


def _make_event(
    command: str = "pytest tests/",
    command_sig: str = "pytest tests/",
    cwd: str = "/project",
    duration_seconds: float = 300.0,
    repo_path: str | None = "/project",
) -> EventData:
    """Create an EventData with a given effective duration."""
    now = datetime.now(timezone.utc)
    start = now - timedelta(seconds=duration_seconds)
    return EventData(
        session_id="test-sess",
        command=command,
        command_sig=command_sig,
        cwd=cwd,
        capture_class="SAFE",
        start_ts=start.isoformat(),
        end_ts=now.isoformat(),
        exit_code=0,
        repo_path=repo_path,
    )


def _make_in_flight_row(
    command: str = "pytest tests/",
    command_sig: str = "pytest tests/",
    cwd: str = "/project",
    repo_path: str | None = "/project",
    elapsed_seconds: float = 300.0,
    stuck_fired: int = 0,
) -> MagicMock:
    """Create a mock sqlite3.Row-like object for an in_flight row."""
    now = datetime.now(timezone.utc)
    start = now - timedelta(seconds=elapsed_seconds)
    row = MagicMock(spec=sqlite3.Row)
    row.__getitem__ = lambda self, key: {
        "command": command,
        "command_sig": command_sig,
        "cwd": cwd,
        "repo_path": repo_path,
        "start_ts": start.isoformat(),
        "session_id": "test-sess",
        "stuck_fired": stuck_fired,
    }[key]
    return row


def _mature_baseline(mean: float, stddev: float, count: int = 10) -> dict:
    return {"count": count, "mean_secs": mean, "stddev_secs": stddev}


class TestCheckInFlight:
    def test_returns_none_if_already_fired(self) -> None:
        row = _make_in_flight_row(elapsed_seconds=3000.0, stuck_fired=1)
        baseline = _mature_baseline(mean=60.0, stddev=10.0)
        result = check_in_flight(row, baseline)
        assert result.confidence == Confidence.NONE

    def test_returns_none_if_no_baseline(self) -> None:
        row = _make_in_flight_row(elapsed_seconds=3000.0)
        result = check_in_flight(row, None)
        assert result.confidence == Confidence.NONE

    def test_returns_none_if_baseline_immature(self) -> None:
        row = _make_in_flight_row(elapsed_seconds=3000.0)
        immature = {"count": 2, "mean_secs": 60.0, "stddev_secs": 5.0}
        result = check_in_flight(row, immature, min_baseline_samples=5)
        assert result.confidence == Confidence.NONE

    def test_high_confidence_when_over_3x_mean(self) -> None:
        """3x mean → HIGH_CONFIDENCE."""
        row = _make_in_flight_row(elapsed_seconds=250.0)
        baseline = _mature_baseline(mean=60.0, stddev=10.0)  # 250 > 3*60 = 180
        result = check_in_flight(row, baseline)
        assert result.confidence == Confidence.HIGH_CONFIDENCE
        assert result.rule_type == RuleType.STUCK_PROCESS

    def test_low_confidence_between_threshold_and_3x_mean(self) -> None:
        """mean + k*stddev < elapsed < 3*mean → LOW_CONFIDENCE."""
        row = _make_in_flight_row(elapsed_seconds=120.0)
        baseline = _mature_baseline(mean=80.0, stddev=10.0)  # threshold=100, 3x=240
        result = check_in_flight(row, baseline)
        assert result.confidence == Confidence.LOW_CONFIDENCE

    def test_none_within_normal_range(self) -> None:
        row = _make_in_flight_row(elapsed_seconds=70.0)
        baseline = _mature_baseline(mean=60.0, stddev=10.0)  # threshold=80
        result = check_in_flight(row, baseline)
        assert result.confidence == Confidence.NONE

    def test_facts_contain_elapsed_and_baseline(self) -> None:
        row = _make_in_flight_row(elapsed_seconds=250.0)
        baseline = _mature_baseline(mean=60.0, stddev=10.0)
        result = check_in_flight(row, baseline)
        assert result.confidence != Confidence.NONE
        assert "elapsed_seconds" in result.facts
        assert "baseline_mean_seconds" in result.facts
        assert result.facts["detection_path"] == "in_flight_sweep"

    def test_fingerprint_includes_start_ts(self) -> None:
        row = _make_in_flight_row(elapsed_seconds=250.0)
        baseline = _mature_baseline(mean=60.0, stddev=10.0)
        result = check_in_flight(row, baseline)
        assert len(result.fingerprint_key) > 0

    def test_short_elapsed_always_none(self) -> None:
        """Sub-5-second processes should never be flagged."""
        row = _make_in_flight_row(elapsed_seconds=3.0)
        baseline = _mature_baseline(mean=0.5, stddev=0.1)  # Even 3x mean would be 1.5s
        result = check_in_flight(row, baseline)
        assert result.confidence == Confidence.NONE


class TestCheckPostcmd:
    def test_none_if_no_baseline(self) -> None:
        event = _make_event(duration_seconds=1000.0)
        result = check_postcmd(event, None)
        assert result.confidence == Confidence.NONE

    def test_none_if_baseline_immature(self) -> None:
        event = _make_event(duration_seconds=1000.0)
        immature = {"count": 3, "mean_secs": 60.0, "stddev_secs": 5.0}
        result = check_postcmd(event, immature, min_baseline_samples=5)
        assert result.confidence == Confidence.NONE

    def test_high_confidence_over_3x_mean(self) -> None:
        """Only HIGH_CONFIDENCE from the postcmd retrospective path."""
        event = _make_event(duration_seconds=250.0)
        baseline = _mature_baseline(mean=60.0, stddev=10.0)
        result = check_postcmd(event, baseline)
        assert result.confidence == Confidence.HIGH_CONFIDENCE

    def test_no_low_confidence_from_postcmd(self) -> None:
        """The postcmd path should NOT fire LOW_CONFIDENCE (between threshold and 3x mean)."""
        event = _make_event(duration_seconds=120.0)
        baseline = _mature_baseline(mean=80.0, stddev=10.0)  # threshold=100 < 120 < 240=3x
        result = check_postcmd(event, baseline)
        # The postcmd path only fires on > 3x mean, so 120 < 240 → NONE
        assert result.confidence == Confidence.NONE

    def test_facts_detection_path_is_postcmd(self) -> None:
        event = _make_event(duration_seconds=250.0)
        baseline = _mature_baseline(mean=60.0, stddev=10.0)
        result = check_postcmd(event, baseline)
        if result.confidence != Confidence.NONE:
            assert result.facts["detection_path"] == "postcmd_retrospective"

    def test_very_short_duration_returns_none(self) -> None:
        event = _make_event(duration_seconds=2.0)
        baseline = _mature_baseline(mean=0.5, stddev=0.1)
        result = check_postcmd(event, baseline)
        assert result.confidence == Confidence.NONE
