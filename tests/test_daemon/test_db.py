"""tests/test_daemon/test_db.py — Unit tests for the SQLite schema and query helpers."""
import math
import tempfile
from pathlib import Path

import pytest

from socrates.daemon.db import (
    clear_suppression_state,
    delete_in_flight,
    get_all_in_flight,
    get_baseline,
    get_recent_events,
    get_suppression,
    increment_dismiss,
    init_db,
    insert_in_flight,
    insert_preexec_event,
    mark_in_flight_stuck_fired,
    purge_orphan_in_flight,
    set_snooze,
    update_postcmd_event,
    update_repo_swept_ts,
    upsert_baseline,
    upsert_known_repo,
    upsert_suppression_fired,
    utcnow,
)


@pytest.fixture
def db_path():
    """Use a self-managed tempdir to avoid Windows AppData permission issues."""
    with tempfile.TemporaryDirectory(prefix="socrates_test_") as tmp:
        path = Path(tmp) / "test_history.db"
        init_db(path)
        yield path


# ── Schema initialisation ─────────────────────────────────────────────────────

class TestInitDb:
    def test_creates_db_file(self) -> None:
        with tempfile.TemporaryDirectory(prefix="socrates_test_") as tmp:
            path = Path(tmp) / "fresh.db"
            assert not path.exists()
            init_db(path)
            assert path.exists()

    def test_idempotent(self) -> None:
        with tempfile.TemporaryDirectory(prefix="socrates_test_") as tmp:
            path = Path(tmp) / "idempotent.db"
            init_db(path)
            init_db(path)  # Should not raise


# ── events table ──────────────────────────────────────────────────────────────

class TestEvents:
    def test_insert_preexec_returns_id(self, db_path: Path) -> None:
        row_id = insert_preexec_event(
            db_path,
            session_id="sess-1",
            command="git status",
            command_sig="git status",
            cwd="/home/user/myrepo",
            repo_path="/home/user/myrepo",
            capture_class="SAFE",
            start_ts=utcnow(),
        )
        assert isinstance(row_id, int)
        assert row_id > 0

    def test_update_postcmd_fills_exit_code(self, db_path: Path) -> None:
        start = utcnow()
        insert_preexec_event(
            db_path,
            session_id="sess-2",
            command="make build",
            command_sig="make build",
            cwd="/project",
            repo_path="/project",
            capture_class="SAFE",
            start_ts=start,
        )
        update_postcmd_event(
            db_path,
            session_id="sess-2",
            command_sig="make build",
            start_ts=start,
            end_ts=utcnow(),
            exit_code=0,
            stderr_tail=None,
        )
        events = get_recent_events(db_path, limit=1)
        assert len(events) == 1
        assert events[0]["exit_code"] == 0

    def test_update_postcmd_stores_stderr_tail(self, db_path: Path) -> None:
        start = utcnow()
        insert_preexec_event(
            db_path,
            session_id="sess-3",
            command="cargo build",
            command_sig="cargo build",
            cwd="/project",
            repo_path="/project",
            capture_class="SAFE",
            start_ts=start,
        )
        tail = "warning: unused variable `x`\nwarning: 1 warning emitted"
        update_postcmd_event(
            db_path,
            session_id="sess-3",
            command_sig="cargo build",
            start_ts=start,
            end_ts=utcnow(),
            exit_code=0,
            stderr_tail=tail,
        )
        events = get_recent_events(db_path, limit=1)
        assert events[0]["stderr_tail"] == tail

    def test_get_recent_events_excludes_incomplete(self, db_path: Path) -> None:
        """Events without an end_ts (preexec but no postcmd) are excluded."""
        insert_preexec_event(
            db_path,
            session_id="sess-4",
            command="vim",
            command_sig="vim",
            cwd="/home",
            repo_path=None,
            capture_class="UNSAFE",
            start_ts=utcnow(),
        )
        events = get_recent_events(db_path)
        assert all(e["command"] != "vim" for e in events)

    def test_get_recent_events_respects_limit(self, db_path: Path) -> None:
        for i in range(5):
            start = utcnow()
            insert_preexec_event(
                db_path,
                session_id=f"sess-lim-{i}",
                command=f"ls -{i}",
                command_sig="ls",
                cwd="/",
                repo_path=None,
                capture_class="UNSAFE",
                start_ts=start,
            )
            update_postcmd_event(
                db_path,
                session_id=f"sess-lim-{i}",
                command_sig="ls",
                start_ts=start,
                end_ts=utcnow(),
                exit_code=0,
                stderr_tail=None,
            )
        assert len(get_recent_events(db_path, limit=3)) == 3


# ── in_flight table ───────────────────────────────────────────────────────────

class TestInFlight:
    def test_insert_and_retrieve(self, db_path: Path) -> None:
        insert_in_flight(
            db_path,
            session_id="sess-if-1",
            command="pytest tests/",
            command_sig="pytest tests/",
            cwd="/project",
            repo_path="/project",
            capture_class="SAFE",
            start_ts=utcnow(),
        )
        rows = get_all_in_flight(db_path)
        assert len(rows) == 1
        assert rows[0]["command"] == "pytest tests/"

    def test_delete_on_postcmd(self, db_path: Path) -> None:
        start = utcnow()
        insert_in_flight(
            db_path,
            session_id="sess-if-2",
            command="cargo test",
            command_sig="cargo test",
            cwd="/project",
            repo_path="/project",
            capture_class="SAFE",
            start_ts=start,
        )
        delete_in_flight(
            db_path,
            session_id="sess-if-2",
            command_sig="cargo test",
            start_ts=start,
        )
        assert get_all_in_flight(db_path) == []

    def test_mark_stuck_fired(self, db_path: Path) -> None:
        start = utcnow()
        insert_in_flight(
            db_path,
            session_id="sess-if-3",
            command="npm install",
            command_sig="npm install",
            cwd="/project",
            repo_path="/project",
            capture_class="SAFE",
            start_ts=start,
        )
        mark_in_flight_stuck_fired(
            db_path,
            session_id="sess-if-3",
            command_sig="npm install",
            start_ts=start,
        )
        rows = get_all_in_flight(db_path)
        assert rows[0]["stuck_fired"] == 1

    def test_insert_or_ignore_duplicate(self, db_path: Path) -> None:
        """Duplicate (session_id, command_sig, start_ts) should be silently ignored."""
        args = dict(
            session_id="sess-if-dup",
            command="make",
            command_sig="make",
            cwd="/",
            repo_path=None,
            capture_class="SAFE",
            start_ts="2026-01-01T00:00:00+00:00",
        )
        insert_in_flight(db_path, **args)
        insert_in_flight(db_path, **args)  # Should not raise
        assert len(get_all_in_flight(db_path)) == 1


# ── baselines table ───────────────────────────────────────────────────────────

class TestBaselines:
    def test_no_baseline_returns_none(self, db_path: Path) -> None:
        assert get_baseline(db_path, project_dir="/x", command_sig="unknown") is None

    def test_single_sample(self, db_path: Path) -> None:
        upsert_baseline(db_path, project_dir="/p", command_sig="pytest", duration_secs=10.0)
        b = get_baseline(db_path, project_dir="/p", command_sig="pytest")
        assert b is not None
        assert b["count"] == 1
        assert abs(b["mean_secs"] - 10.0) < 1e-9
        assert b["stddev_secs"] == 0.0

    def test_welford_convergence(self, db_path: Path) -> None:
        """After many samples, mean and stddev should converge to the true values."""
        import random
        random.seed(42)
        samples = [random.gauss(mu=30.0, sigma=5.0) for _ in range(100)]
        for s in samples:
            upsert_baseline(db_path, project_dir="/w", command_sig="make build", duration_secs=s)
        b = get_baseline(db_path, project_dir="/w", command_sig="make build")
        assert b is not None
        assert b["count"] == 100
        assert abs(b["mean_secs"] - 30.0) < 1.0   # within 1s of true mean
        assert abs(b["stddev_secs"] - 5.0) < 1.0  # within 1s of true stddev

    def test_upsert_increments_count(self, db_path: Path) -> None:
        for _ in range(3):
            upsert_baseline(db_path, project_dir="/p2", command_sig="go build", duration_secs=5.0)
        b = get_baseline(db_path, project_dir="/p2", command_sig="go build")
        assert b["count"] == 3


# ── known_repos table ─────────────────────────────────────────────────────────

class TestKnownRepos:
    def test_upsert_creates_row(self, db_path: Path) -> None:
        upsert_known_repo(db_path, "/home/user/myrepo")
        from socrates.daemon.db import get_all_known_repos
        repos = get_all_known_repos(db_path)
        assert any(r["repo_path"] == "/home/user/myrepo" for r in repos)

    def test_upsert_idempotent(self, db_path: Path) -> None:
        upsert_known_repo(db_path, "/repo")
        upsert_known_repo(db_path, "/repo")
        from socrates.daemon.db import get_all_known_repos
        assert len([r for r in get_all_known_repos(db_path) if r["repo_path"] == "/repo"]) == 1

    def test_update_swept_ts(self, db_path: Path) -> None:
        upsert_known_repo(db_path, "/repo2")
        update_repo_swept_ts(db_path, "/repo2")
        from socrates.daemon.db import get_all_known_repos
        repo = next(r for r in get_all_known_repos(db_path) if r["repo_path"] == "/repo2")
        assert repo["last_swept_ts"] is not None


# ── suppression_state table ───────────────────────────────────────────────────

class TestSuppressionState:
    def test_get_nonexistent_returns_none(self, db_path: Path) -> None:
        assert get_suppression(db_path, "nonexistent-fp") is None

    def test_upsert_fired_creates_row(self, db_path: Path) -> None:
        upsert_suppression_fired(
            db_path,
            fingerprint="fp-abc123",
            rule_type="forgotten_push",
            repo_path="/repo",
            branch="main",
        )
        row = get_suppression(db_path, "fp-abc123")
        assert row is not None
        assert row["rule_type"] == "forgotten_push"
        assert row["dismiss_count"] == 0

    def test_upsert_fired_is_idempotent(self, db_path: Path) -> None:
        for _ in range(3):
            upsert_suppression_fired(
                db_path,
                fingerprint="fp-dup",
                rule_type="silent_failure",
                repo_path="/r",
                branch=None,
            )
        row = get_suppression(db_path, "fp-dup")
        assert row is not None

    def test_set_snooze(self, db_path: Path) -> None:
        upsert_suppression_fired(
            db_path,
            fingerprint="fp-snooze",
            rule_type="forgotten_push",
            repo_path="/r",
            branch="dev",
        )
        snooze_ts = "2099-01-01T00:00:00+00:00"
        set_snooze(db_path, fingerprint="fp-snooze", snoozed_until=snooze_ts)
        row = get_suppression(db_path, "fp-snooze")
        assert row["snoozed_until"] == snooze_ts

    def test_increment_dismiss(self, db_path: Path) -> None:
        upsert_suppression_fired(
            db_path,
            fingerprint="fp-dismiss",
            rule_type="stuck_process",
            repo_path=None,
            branch=None,
        )
        count1 = increment_dismiss(db_path, "fp-dismiss")
        count2 = increment_dismiss(db_path, "fp-dismiss")
        assert count1 == 1
        assert count2 == 2

    def test_clear_suppression_state(self, db_path: Path) -> None:
        for i in range(3):
            upsert_suppression_fired(
                db_path,
                fingerprint=f"fp-clear-{i}",
                rule_type="forgotten_push",
                repo_path="/r",
                branch=None,
            )
        count = clear_suppression_state(db_path)
        assert count == 3
        assert get_suppression(db_path, "fp-clear-0") is None
