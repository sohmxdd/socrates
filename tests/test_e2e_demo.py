"""
tests/test_e2e_demo.py — End-to-end verification of the 4 demo scenarios and Section 12 criteria.
"""
import json
import os
import tempfile
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from socrates.config import SocratesConfig
from socrates.daemon.db import (
    init_db,
    upsert_known_repo,
    insert_in_flight,
    upsert_baseline,
    get_all_in_flight,
)
from socrates.daemon.sweep import run_repo_sweep, run_in_flight_sweep
from socrates.gate.fingerprint import make_fingerprint
from socrates.gate.intervention_gate import InterventionGate
from socrates.llm.groq_client import GroqClient
from socrates.personality.messages import generate_message
from socrates.rules.base import Confidence, RuleResult, RuleType
from socrates.rules.forgotten_push import check_forgotten_push
from socrates.rules.leaked_secrets import check_leaked_secrets
from socrates.rules.silent_failure import check_silent_failure
from socrates.rules.stuck_process import check_in_flight


def create_demo_env(tmp_dir: Path) -> tuple[Path, SocratesConfig, Path]:
    db_path = tmp_dir / "history.db"
    init_db(db_path)
    home = tmp_dir / "socrates_home"
    home.mkdir(parents=True, exist_ok=True)
    cfg = SocratesConfig(
        sweep_interval_seconds=600,
        stuck_sweep_interval_seconds=30,
        active_commit_window_seconds=300,
        min_baseline_samples=3,
        baseline_k_factor=2.0,
        dismiss_threshold=3,
    )
    return db_path, cfg, home


class TestE2EScenarios:
    def test_scenario_1_forgotten_push_end_to_end(self) -> None:
        """
        Demo Scenario 1:
        Developer has commits ahead of upstream.
        Daemon sweep checks on its own clock.
        Because developer has stopped committing (> 300s), writes pending file.
        A new terminal session reads and displays the Socratic message.
        """
        with tempfile.TemporaryDirectory(prefix="socrates_demo_") as tmp:
            db_path, cfg, home = create_demo_env(Path(tmp))
            repo_path = Path(tmp) / "demo_project"
            repo_path.mkdir()
            upsert_known_repo(db_path, str(repo_path))

            # Simulate 2 unpushed commits on 'main'
            fake_res = RuleResult(
                rule_type=RuleType.FORGOTTEN_PUSH,
                confidence=Confidence.HIGH_CONFIDENCE,
                facts={"repo_path": str(repo_path), "branch": "main", "unpushed_count": 2},
                fingerprint_key=f"push:{repo_path}:main:2",
            )

            # Inactivity is 600s (> 300s window)
            with patch("socrates.daemon.sweep._get_latest_commit_age_seconds", return_value=600.0), \
                 patch("socrates.rules.forgotten_push.check_forgotten_push", return_value=fake_res), \
                 patch.object(Path, "exists", return_value=True):
                run_repo_sweep(db_path, cfg, home)

            # Pending file created
            pending_dir = cfg.pending_dir(home)
            pending_files = list(pending_dir.glob("*.json"))
            assert len(pending_files) == 1

            # Verify contents of the pending message
            payload = json.loads(pending_files[0].read_text(encoding="utf-8"))
            assert payload["rule_type"] == "forgotten_push"
            msg = payload["formatted_message"]
            assert "2 commits on 'main'" in msg
            assert "trapped upon this machine" in msg
            assert "socrates snooze" in msg

    def test_scenario_2_leaked_secrets_end_to_end(self) -> None:
        """
        Demo Scenario 2:
        Developer enters command containing AWS key.
        Pre-exec scan identifies secret with HIGH_CONFIDENCE locally.
        Message generated with concrete secret name and zero network access.
        """
        cmd = "aws s3 cp s3://bucket/data . --profile default AKIAIOSFODNN7EXAMPLE"
        res = check_leaked_secrets(cmd)
        assert res.confidence == Confidence.HIGH_CONFIDENCE
        assert res.rule_type == RuleType.LEAKED_SECRETS
        assert "AWS Access Key ID" in res.facts["pattern_types"]

        # Formatted in-character message
        msg = generate_message(res.rule_type, res.facts)
        assert "AWS Access Key ID" in msg
        assert "shouted it into your terminal" in msg

    def test_scenario_3_silent_failure_missing_artifact_end_to_end(self) -> None:
        """
        Demo Scenario 3:
        Build command exited 0, but output binary does not exist.
        Rule flags HIGH_CONFIDENCE silent failure.
        """
        with tempfile.TemporaryDirectory(prefix="socrates_demo_") as tmp:
            missing_file = Path(tmp) / "build" / "app.bin"

            from socrates.rules.base import EventData
            event = EventData(
                session_id="s1",
                command=f"gcc -o {missing_file} main.c",
                command_sig="gcc",
                cwd=tmp,
                repo_path=tmp,
                capture_class="SAFE",
                start_ts="2026-01-01T00:00:00Z",
                end_ts="2026-01-01T00:00:01Z",
                exit_code=0,
                stderr_tail=None,
            )

            res = check_silent_failure(event)
            assert res.confidence == Confidence.HIGH_CONFIDENCE
            assert res.facts.get("artifact_path") == str(missing_file)

            msg = generate_message(res.rule_type, res.facts)
            # Message must be non-empty and mention the missing artifact.
            # We don't assert on specific hardcoded phrases because the LLM
            # generates unique copy each time; we verify factual grounding.
            assert msg.strip()
            # The LLM weaves in specific facts -- at minimum a portion of the path
            # or the command should appear. Accept either.
            assert str(missing_file) in msg or "app.bin" in msg or "gcc" in msg

    def test_scenario_4_stuck_process_end_to_end(self) -> None:
        """
        Demo Scenario 4:
        In-flight test process runs 10x historical baseline.
        In-flight sweep detects anomaly, marks stuck_fired, delivers OS notification.
        """
        with tempfile.TemporaryDirectory(prefix="socrates_demo_") as tmp:
            db_path, cfg, home = create_demo_env(Path(tmp))
            # Baseline: pytest normally finishes in 10s
            for _ in range(5):
                upsert_baseline(db_path, project_dir="/proj", command_sig="pytest", duration_secs=10.0)

            # In-flight process running for 100s
            start = (datetime.now(timezone.utc) - timedelta(seconds=100)).isoformat()
            insert_in_flight(
                db_path,
                session_id="sess_demo",
                command="pytest tests/ -v",
                command_sig="pytest",
                cwd="/proj",
                repo_path="/proj",
                capture_class="SAFE",
                start_ts=start,
            )

            with patch("socrates.daemon.sweep._deliver_os_notification") as mock_notify:
                run_in_flight_sweep(db_path, cfg, home)
                mock_notify.assert_called_once()
                title, msg = mock_notify.call_args[1].get("title") or mock_notify.call_args[0][0], mock_notify.call_args[1].get("message") or mock_notify.call_args[0][1]
                assert title == "Socrates"
                # Message must be non-empty and reference the process/timing.
                # We don't assert on specific hardcoded phrases because the LLM
                # generates unique copy each time.
                assert msg.strip()
                assert "pytest" in msg or "running" in msg or "minute" in msg

    def test_actively_committing_guard_suppresses_push_nag(self) -> None:
        """
        Section 12 requirement:
        A multi-commit sequence with no push produces zero push-reminder nags mid-session.
        """
        with tempfile.TemporaryDirectory(prefix="socrates_demo_") as tmp:
            db_path, cfg, home = create_demo_env(Path(tmp))
            repo_path = Path(tmp) / "demo_repo"
            repo_path.mkdir()
            upsert_known_repo(db_path, str(repo_path))

            # Latest commit was 30s ago (< 300s)
            with patch("socrates.daemon.sweep._get_latest_commit_age_seconds", return_value=30.0), \
                 patch("socrates.rules.forgotten_push.check_forgotten_push") as mock_check:
                run_repo_sweep(db_path, cfg, home)
                mock_check.assert_not_called()

            # No pending file generated
            pending_dir = cfg.pending_dir(home)
            assert len(list(pending_dir.glob("*.json"))) == 0

    def test_groq_degradation_offline(self) -> None:
        """
        Section 12 requirement:
        System degrades gracefully if GROQ_API_KEY is missing or offline.
        """
        cfg = SocratesConfig(groq_enabled=True)
        with patch.dict(os.environ, {}, clear=True):
            client = GroqClient(cfg, api_key="")
            assert client.is_available is False

            ambiguous = RuleResult(
                rule_type=RuleType.SILENT_FAILURE,
                confidence=Confidence.LOW_CONFIDENCE,
                facts={"command": "make"},
            )
            res = client.tiebreak(ambiguous)
            assert res.confidence == Confidence.NONE
