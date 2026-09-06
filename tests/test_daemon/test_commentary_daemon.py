"""
tests/test_daemon/test_commentary_daemon.py — End-to-end unit tests for daemon commentary flow.
"""
from pathlib import Path
import json
import pytest

from socrates.config import SocratesConfig
from socrates.daemon.server import SocratesDaemon
from socrates.daemon.db import init_db


def test_daemon_postcmd_generates_commentary(tmp_path: Path):
    cfg_file = tmp_path / ".socrates.yaml"
    cfg_file.write_text("commentary_enabled: true\ncommentary_rate: 1.0\ncommentary_cooldown_seconds: 0\n", encoding="utf-8")

    cfg = SocratesConfig(
        commentary_enabled=True,
        commentary_rate=1.0,
        commentary_cooldown_seconds=0,
    )
    home = tmp_path / "home"
    home.mkdir()
    init_db(cfg.db_path(home))

    daemon = SocratesDaemon(cfg, home=home)

    payload = {
        "event": "postcmd",
        "session_id": "test-session-1",
        "command": "git status",
        "command_sig": "git status",
        "cwd": str(tmp_path),
        "capture_class": "SAFE",
        "start_ts": "2026-09-06T12:00:00Z",
        "end_ts": "2026-09-06T12:00:01Z",
        "exit_code": 0,
        "stderr_tail": "",
        "repo_path": str(tmp_path),
    }

    # Process event
    daemon._handle_postcmd(payload)

    # Check pending directory
    pending_dir = cfg.pending_dir(home)
    pending_files = list(pending_dir.glob("commentary_*.json"))
    assert len(pending_files) == 1

    with open(pending_files[0], "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["is_commentary"] is True
    assert data["rule_type"] == "commentary"
    assert "Socrates observes:" in data["formatted_message"] or len(data["formatted_message"]) > 0


def test_daemon_postcmd_respects_skip_commands(tmp_path: Path):
    cfg = SocratesConfig(
        commentary_enabled=True,
        commentary_rate=1.0,
        commentary_cooldown_seconds=0,
        commentary_skip_commands=["clear"],
    )
    home = tmp_path / "home2"
    home.mkdir()
    init_db(cfg.db_path(home))

    daemon = SocratesDaemon(cfg, home=home)

    payload = {
        "event": "postcmd",
        "session_id": "test-session-2",
        "command": "clear",
        "command_sig": "clear",
        "cwd": str(tmp_path),
        "capture_class": "SAFE",
        "start_ts": "2026-09-06T12:00:00Z",
        "end_ts": "2026-09-06T12:00:00Z",
        "exit_code": 0,
        "stderr_tail": "",
    }

    daemon._handle_postcmd(payload)

    pending_dir = cfg.pending_dir(home)
    assert not list(pending_dir.glob("commentary_*.json"))
