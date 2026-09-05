"""tests/test_daemon/test_sweep.py — Tests for repo sweep and in-flight stuck process sweep."""
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from socrates.config import SocratesConfig
from socrates.daemon.db import (
    init_db,
    upsert_known_repo,
    get_all_known_repos,
    insert_in_flight,
    upsert_baseline,
    get_all_in_flight,
)
from socrates.daemon.sweep import (
    run_repo_sweep,
    run_in_flight_sweep,
    _get_latest_commit_age_seconds,
)
from socrates.rules.base import Confidence, RuleResult, RuleType


def create_env(tmp_dir: Path, **config_overrides) -> tuple[Path, SocratesConfig, Path]:
    db_path = tmp_dir / "test.db"
    init_db(db_path)
    home = tmp_dir / "home"
    home.mkdir(parents=True, exist_ok=True)
    cfg = SocratesConfig(**config_overrides)
    return db_path, cfg, home


class TestRepoSweep:
    def test_skips_nonexistent_repo(self) -> None:
        with tempfile.TemporaryDirectory(prefix="socrates_sweep_") as tmp:
            db_path, cfg, home = create_env(Path(tmp))
            fake_repo = "/non/existent/path/to/repo"
            upsert_known_repo(db_path, fake_repo)

            with patch("socrates.rules.forgotten_push.check_forgotten_push") as mock_check:
                run_repo_sweep(db_path, cfg, home)
                mock_check.assert_not_called()

    def test_skips_actively_committing_repo(self) -> None:
        with tempfile.TemporaryDirectory(prefix="socrates_sweep_") as tmp:
            db_path, cfg, home = create_env(Path(tmp), active_commit_window_seconds=300)
            repo_dir = Path(tmp) / "active_repo"
            repo_dir.mkdir()
            upsert_known_repo(db_path, str(repo_dir))

            # Simulate commit made 60s ago (< 300s window)
            with patch("socrates.daemon.sweep._get_latest_commit_age_seconds", return_value=60.0), \
                 patch("socrates.rules.forgotten_push.check_forgotten_push") as mock_check:
                run_repo_sweep(db_path, cfg, home)
                mock_check.assert_not_called()

    def test_fires_when_quiet_and_unpushed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="socrates_sweep_") as tmp:
            db_path, cfg, home = create_env(Path(tmp), active_commit_window_seconds=300)
            repo_dir = Path(tmp) / "quiet_repo"
            repo_dir.mkdir()
            upsert_known_repo(db_path, str(repo_dir))

            push_result = RuleResult(
                rule_type=RuleType.FORGOTTEN_PUSH,
                confidence=Confidence.HIGH_CONFIDENCE,
                facts={"repo_path": str(repo_dir), "branch": "main", "unpushed_count": 2},
                fingerprint_key=f"push:{repo_dir}:main:2",
            )

            # Inactive for 600s (> 300s)
            with patch("socrates.daemon.sweep._get_latest_commit_age_seconds", return_value=600.0), \
                 patch("socrates.rules.forgotten_push.check_forgotten_push", return_value=push_result), \
                 patch.object(Path, "exists", return_value=True):
                run_repo_sweep(db_path, cfg, home)

            # Check that a pending file was written
            pending_dir = cfg.pending_dir(home)
            pending_files = list(pending_dir.glob("*.json"))
            assert len(pending_files) == 1

            # Check that repo was marked swept
            repos = get_all_known_repos(db_path)
            assert repos[0]["last_swept_ts"] is not None

    def test_repo_error_does_not_abort_sweep(self) -> None:
        with tempfile.TemporaryDirectory(prefix="socrates_sweep_") as tmp:
            db_path, cfg, home = create_env(Path(tmp))
            repo1 = Path(tmp) / "repo1"
            repo2 = Path(tmp) / "repo2"
            repo1.mkdir()
            repo2.mkdir()
            upsert_known_repo(db_path, str(repo1))
            upsert_known_repo(db_path, str(repo2))

            call_count = 0

            def fake_check(repo_path):
                nonlocal call_count
                call_count += 1
                if "repo1" in repo_path:
                    raise RuntimeError("Corrupted git repo")
                return RuleResult(RuleType.FORGOTTEN_PUSH, Confidence.NONE, {})

            with patch("socrates.daemon.sweep._get_latest_commit_age_seconds", return_value=999.0), \
                 patch("socrates.rules.forgotten_push.check_forgotten_push", side_effect=fake_check):
                # Should not raise exception
                run_repo_sweep(db_path, cfg, home)

            assert call_count == 2


class TestInFlightSweep:
    def test_empty_in_flight_noop(self) -> None:
        with tempfile.TemporaryDirectory(prefix="socrates_sweep_") as tmp:
            db_path, cfg, home = create_env(Path(tmp))
            with patch("socrates.rules.stuck_process.check_in_flight") as mock_check:
                run_in_flight_sweep(db_path, cfg, home)
                mock_check.assert_not_called()

    def test_skips_immature_baseline(self) -> None:
        with tempfile.TemporaryDirectory(prefix="socrates_sweep_") as tmp:
            db_path, cfg, home = create_env(Path(tmp), min_baseline_samples=5)
            # Insert in_flight
            start = (datetime.now(timezone.utc) - timedelta(seconds=100)).isoformat()
            insert_in_flight(
                db_path,
                session_id="s1",
                command="npm test",
                command_sig="npm test",
                cwd="/proj",
                repo_path="/proj",
                capture_class="SAFE",
                start_ts=start,
            )
            # Baseline with only 2 samples
            upsert_baseline(db_path, project_dir="/proj", command_sig="npm test", duration_secs=10.0)
            upsert_baseline(db_path, project_dir="/proj", command_sig="npm test", duration_secs=12.0)

            with patch("socrates.daemon.sweep._deliver_os_notification") as mock_notify:
                run_in_flight_sweep(db_path, cfg, home)
                mock_notify.assert_not_called()

    def test_fires_when_process_is_stuck(self) -> None:
        with tempfile.TemporaryDirectory(prefix="socrates_sweep_") as tmp:
            db_path, cfg, home = create_env(Path(tmp), min_baseline_samples=3, stuck_sweep_interval_seconds=30)
            # Seed mature baseline: mean ~ 10s
            for _ in range(5):
                upsert_baseline(db_path, project_dir="/proj", command_sig="pytest", duration_secs=10.0)

            # Insert in-flight process running for 100s (10x mean)
            start = (datetime.now(timezone.utc) - timedelta(seconds=100)).isoformat()
            insert_in_flight(
                db_path,
                session_id="s1",
                command="pytest",
                command_sig="pytest",
                cwd="/proj",
                repo_path="/proj",
                capture_class="SAFE",
                start_ts=start,
            )

            with patch("socrates.daemon.sweep._deliver_os_notification") as mock_notify:
                run_in_flight_sweep(db_path, cfg, home)
                mock_notify.assert_called_once()

            # Verify stuck_fired flag was updated in in_flight
            rows = get_all_in_flight(db_path)
            assert len(rows) == 1
            assert rows[0]["stuck_fired"] == 1

            # Second sweep must NOT fire again for the same invocation
            with patch("socrates.daemon.sweep._deliver_os_notification") as mock_notify2:
                run_in_flight_sweep(db_path, cfg, home)
                mock_notify2.assert_not_called()


class TestCommitAgeHelper:
    def test_get_latest_commit_age_valid(self) -> None:
        # Mock git log returning timestamp 1000000000
        mock_proc = MagicMock(returncode=0, stdout="1000000000\n")
        with patch("subprocess.run", return_value=mock_proc), \
             patch("time.time", return_value=1000000050.0):
            age = _get_latest_commit_age_seconds("/any/repo")
            assert age == 50.0

    def test_get_latest_commit_age_failure(self) -> None:
        mock_proc = MagicMock(returncode=128, stdout="")
        with patch("subprocess.run", return_value=mock_proc):
            age = _get_latest_commit_age_seconds("/any/repo")
            assert age is None
