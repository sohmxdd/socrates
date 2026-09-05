"""tests/test_gate/test_intervention_gate.py — Tests for fingerprinting, intervention gate suppression, and pending files."""
import json
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from socrates.config import SocratesConfig
from socrates.daemon.db import init_db, upsert_suppression_fired, set_snooze
from socrates.gate.fingerprint import make_fingerprint, compute_fingerprint
from socrates.gate.intervention_gate import InterventionGate
from socrates.rules.base import Confidence, RuleResult, RuleType


def create_gate(tmp_dir: Path, **config_overrides) -> tuple[InterventionGate, Path, Path]:
    db_path = tmp_dir / "test.db"
    init_db(db_path)
    home_path = tmp_dir / "home"
    home_path.mkdir(parents=True, exist_ok=True)
    cfg = SocratesConfig(**config_overrides)
    gate = InterventionGate(db_path, cfg, home_path)
    return gate, db_path, home_path


class TestFingerprint:
    def test_empty_key_raises(self) -> None:
        with pytest.raises(ValueError):
            make_fingerprint("")

    def test_produces_32_char_hex(self) -> None:
        fp = make_fingerprint("test:key:123")
        assert len(fp) == 32
        int(fp, 16)  # must be valid hex

    def test_deterministic(self) -> None:
        fp1 = make_fingerprint("rule:repo:branch:42")
        fp2 = make_fingerprint("rule:repo:branch:42")
        assert fp1 == fp2

    def test_compute_fingerprint_all_rules(self) -> None:
        fp_push1 = compute_fingerprint("forgotten_push", {"repo_path": "/r", "branch": "main", "unpushed_count": 2})
        fp_push2 = compute_fingerprint("forgotten_push", {"repo_path": "/r", "branch": "main", "unpushed_count": 3})
        assert fp_push1 != fp_push2

        fp_sec = compute_fingerprint("leaked_secrets", {"command": "curl -H 'x: secret'"})
        assert len(fp_sec) == 32

        fp_sf = compute_fingerprint("silent_failure", {"command_sig": "make", "pattern_id": "error"})
        assert len(fp_sf) == 32

        fp_stuck = compute_fingerprint("stuck_process", {"command_sig": "cargo", "project_dir": "/p", "start_ts": "2026-01-01"})
        assert len(fp_stuck) == 32


class TestInterventionGateSuppression:
    def test_fresh_result_should_fire(self) -> None:
        with tempfile.TemporaryDirectory(prefix="socrates_gate_") as tmp:
            gate, _, _ = create_gate(Path(tmp))
            res = RuleResult(
                rule_type=RuleType.FORGOTTEN_PUSH,
                confidence=Confidence.HIGH_CONFIDENCE,
                facts={"repo_path": "/repo", "branch": "main"},
                fingerprint_key="push:/repo:main:1",
            )
            assert gate.should_fire(res) is True

    def test_empty_fingerprint_key_never_fires(self) -> None:
        with tempfile.TemporaryDirectory(prefix="socrates_gate_") as tmp:
            gate, _, _ = create_gate(Path(tmp))
            res = RuleResult(
                rule_type=RuleType.FORGOTTEN_PUSH,
                confidence=Confidence.HIGH_CONFIDENCE,
                facts={},
                fingerprint_key="",
            )
            assert gate.should_fire(res) is False

    def test_cooldown_suppression(self) -> None:
        with tempfile.TemporaryDirectory(prefix="socrates_gate_") as tmp:
            gate, _, _ = create_gate(Path(tmp), intervention_cooldown_seconds=3600)
            res = RuleResult(
                rule_type=RuleType.FORGOTTEN_PUSH,
                confidence=Confidence.HIGH_CONFIDENCE,
                facts={"repo_path": "/repo", "branch": "main"},
                fingerprint_key="push:/repo:main:1",
            )
            assert gate.should_fire(res) is True
            gate.record_fire(res)
            # Second check within cooldown must be suppressed
            assert gate.should_fire(res) is False

    def test_cooldown_expires(self) -> None:
        with tempfile.TemporaryDirectory(prefix="socrates_gate_") as tmp:
            gate, db_path, _ = create_gate(Path(tmp), intervention_cooldown_seconds=60)
            fp_key = "push:/repo:main:1"
            fp = make_fingerprint(fp_key)
            old_ts = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
            upsert_suppression_fired(db_path, fingerprint=fp, rule_type="forgotten_push", last_fired_ts=old_ts)

            res = RuleResult(
                rule_type=RuleType.FORGOTTEN_PUSH,
                confidence=Confidence.HIGH_CONFIDENCE,
                facts={"repo_path": "/repo", "branch": "main"},
                fingerprint_key=fp_key,
            )
            assert gate.should_fire(res) is True

    def test_snooze_suppression(self) -> None:
        with tempfile.TemporaryDirectory(prefix="socrates_gate_") as tmp:
            gate, _, _ = create_gate(Path(tmp))
            fp_key = "push:/repo:main:1"
            res = RuleResult(
                rule_type=RuleType.FORGOTTEN_PUSH,
                confidence=Confidence.HIGH_CONFIDENCE,
                facts={"repo_path": "/repo", "branch": "main"},
                fingerprint_key=fp_key,
            )
            gate.record_fire(res)
            fp = make_fingerprint(fp_key)
            gate.snooze(fp, hours=2.0)
            assert gate.should_fire(res) is False

    def test_snooze_branch(self) -> None:
        with tempfile.TemporaryDirectory(prefix="socrates_gate_") as tmp:
            gate, _, _ = create_gate(Path(tmp))
            res = RuleResult(
                rule_type=RuleType.FORGOTTEN_PUSH,
                confidence=Confidence.HIGH_CONFIDENCE,
                facts={"repo_path": "/repo", "branch": "feature-x"},
                fingerprint_key="push:/repo:feature-x:1",
            )
            gate.record_fire(res)
            gate.snooze_branch("/repo", "feature-x", hours=2.0)
            assert gate.should_fire(res) is False

    def test_dismiss_threshold_suppression(self) -> None:
        with tempfile.TemporaryDirectory(prefix="socrates_gate_") as tmp:
            gate, _, _ = create_gate(Path(tmp), dismiss_threshold=3)
            fp_key = "push:/repo:main:1"
            res = RuleResult(
                rule_type=RuleType.FORGOTTEN_PUSH,
                confidence=Confidence.HIGH_CONFIDENCE,
                facts={"repo_path": "/repo", "branch": "main"},
                fingerprint_key=fp_key,
            )
            gate.record_fire(res)
            fp = make_fingerprint(fp_key)
            assert gate.dismiss(fp) == 1
            assert gate.dismiss(fp) == 2
            assert gate.dismiss(fp) == 3
            assert gate.should_fire(res) is False

    def test_dismiss_widening_factor_increases_cooldown(self) -> None:
        with tempfile.TemporaryDirectory(prefix="socrates_gate_") as tmp:
            gate, _, _ = create_gate(
                Path(tmp),
                intervention_cooldown_seconds=100,
                dismiss_widening_factor=2.0,
            )
            # Result 1 in /repo was dismissed
            res1 = RuleResult(
                rule_type=RuleType.FORGOTTEN_PUSH,
                confidence=Confidence.HIGH_CONFIDENCE,
                facts={"repo_path": "/repo", "branch": "main"},
                fingerprint_key="push:/repo:main:commit1",
            )
            gate.record_fire(res1)
            fp1 = make_fingerprint(res1.fingerprint_key)
            gate.dismiss(fp1)

            # Result 2 in /repo with new commit
            res2 = RuleResult(
                rule_type=RuleType.FORGOTTEN_PUSH,
                confidence=Confidence.HIGH_CONFIDENCE,
                facts={"repo_path": "/repo", "branch": "main"},
                fingerprint_key="push:/repo:main:commit2",
            )
            # Before firing, res2 is fresh so it fires
            assert gate.should_fire(res2) is True
            gate.record_fire(res2)

            # Now res2 cooldown is widened by factor 2 (100 * 2 = 200s)
            assert gate.should_fire(res2) is False


class TestWritePendingAndEscalation:
    def test_write_pending_creates_file(self) -> None:
        with tempfile.TemporaryDirectory(prefix="socrates_gate_") as tmp:
            gate, _, home = create_gate(Path(tmp))
            res = RuleResult(
                rule_type=RuleType.FORGOTTEN_PUSH,
                confidence=Confidence.HIGH_CONFIDENCE,
                facts={"repo_path": "/repo", "branch": "main", "stderr_tail": "secret_error_line"},
                fingerprint_key="push:/repo:main:1",
            )
            pfile = gate.write_pending(res, repo_path="/repo")
            assert pfile is not None
            assert pfile.exists()

            data = json.loads(pfile.read_text(encoding="utf-8"))
            assert data["rule_type"] == "forgotten_push"
            assert "formatted_message" in data
            assert data["fingerprint"] == make_fingerprint("push:/repo:main:1")
            # Sensitive keys must be sanitized
            assert "stderr_tail" not in data["facts"]

    def test_write_pending_non_repo(self) -> None:
        with tempfile.TemporaryDirectory(prefix="socrates_gate_") as tmp:
            gate, _, home = create_gate(Path(tmp))
            res = RuleResult(
                rule_type=RuleType.STUCK_PROCESS,
                confidence=Confidence.HIGH_CONFIDENCE,
                facts={"command": "build.sh"},
                fingerprint_key="stuck:build.sh:123",
            )
            pfile = gate.write_pending(res, repo_path=None)
            assert pfile is not None
            assert pfile.exists()

    def test_escalation_ignores_recent_pending(self) -> None:
        with tempfile.TemporaryDirectory(prefix="socrates_gate_") as tmp:
            gate, _, home = create_gate(Path(tmp), notification_escalation_hours=2.0)
            res = RuleResult(
                rule_type=RuleType.FORGOTTEN_PUSH,
                confidence=Confidence.HIGH_CONFIDENCE,
                facts={"repo_path": "/repo"},
                fingerprint_key="push:/repo:1",
            )
            pfile = gate.write_pending(res, repo_path="/repo")
            assert pfile is not None

            escalated = gate.check_and_escalate_pending()
            assert len(escalated) == 0
            assert pfile.exists()

    def test_escalation_triggers_for_stale_pending(self) -> None:
        with tempfile.TemporaryDirectory(prefix="socrates_gate_") as tmp:
            gate, _, home = create_gate(Path(tmp), notification_escalation_hours=2.0)
            res = RuleResult(
                rule_type=RuleType.FORGOTTEN_PUSH,
                confidence=Confidence.HIGH_CONFIDENCE,
                facts={"repo_path": "/repo"},
                fingerprint_key="push:/repo:1",
            )
            pfile = gate.write_pending(res, repo_path="/repo")
            assert pfile is not None

            # Manually backdate written_at to 3 hours ago
            data = json.loads(pfile.read_text(encoding="utf-8"))
            data["written_at"] = (datetime.now(timezone.utc) - timedelta(hours=3.0)).isoformat()
            pfile.write_text(json.dumps(data), encoding="utf-8")

            with patch("socrates.gate.intervention_gate._deliver_notification") as mock_notify:
                escalated = gate.check_and_escalate_pending()
                assert len(escalated) == 1
                mock_notify.assert_called_once()
                # Stale pending file should have been deleted
                assert not pfile.exists()
