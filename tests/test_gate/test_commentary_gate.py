"""
tests/test_gate/test_commentary_gate.py — Unit tests for CommentaryGate.
"""
from pathlib import Path
import json
import time
import pytest

from socrates.config import SocratesConfig
from socrates.gate.commentary_gate import CommentaryGate


def test_commentary_gate_disabled_by_default():
    cfg = SocratesConfig(commentary_enabled=False)
    gate = CommentaryGate(cfg, home=Path(".socrates_test_home"))
    assert gate.should_comment(session_id="s1", command="git status") is False


def test_commentary_gate_skips_commands():
    cfg = SocratesConfig(
        commentary_enabled=True,
        commentary_rate=1.0,
        commentary_skip_commands=["clear", "cls", "pwd", "exit"],
    )
    gate = CommentaryGate(cfg, home=Path(".socrates_test_home"))
    assert gate.should_comment(session_id="s1", command="clear") is False
    assert gate.should_comment(session_id="s1", command="pwd") is False
    assert gate.should_comment(session_id="s1", command="cls") is False
    assert gate.should_comment(session_id="s1", command="ls") is True


def test_commentary_gate_cooldown():
    cfg = SocratesConfig(
        commentary_enabled=True,
        commentary_rate=1.0,
        commentary_cooldown_seconds=10,
    )
    gate = CommentaryGate(cfg, home=Path(".socrates_test_home"))
    assert gate.should_comment(session_id="s1", command="git status") is True

    # Record a comment now
    gate.record_comment(session_id="s1", ts=time.time())

    # Immediately after, should be on cooldown
    assert gate.should_comment(session_id="s1", command="git diff") is False

    # Another session is unaffected
    assert gate.should_comment(session_id="s2", command="git diff") is True

    # After cooldown expires
    gate.record_comment(session_id="s1", ts=time.time() - 15)
    assert gate.should_comment(session_id="s1", command="git status") is True


def test_commentary_gate_rate_limiting(monkeypatch):
    cfg = SocratesConfig(
        commentary_enabled=True,
        commentary_rate=0.5,
        commentary_cooldown_seconds=0,
    )
    gate = CommentaryGate(cfg, home=Path(".socrates_test_home"))

    # If random roll is 0.4 (< 0.5), should_comment is True
    monkeypatch.setattr("random.random", lambda: 0.4)
    assert gate.should_comment(session_id="s1", command="git status") is True

    # If random roll is 0.6 (>= 0.5), should_comment is False
    monkeypatch.setattr("random.random", lambda: 0.6)
    assert gate.should_comment(session_id="s1", command="git status") is False


def test_commentary_gate_write_pending(tmp_path: Path):
    cfg = SocratesConfig(commentary_enabled=True)
    gate = CommentaryGate(cfg, home=tmp_path)

    msg = "Socrates observes: Listing files again."
    out_file = gate.write_pending(msg, session_id="test-session")
    assert out_file.exists()

    with open(out_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["formatted_message"] == msg
    assert data["session_id"] == "test-session"
    assert data["is_commentary"] is True
    assert data["rule_type"] == "commentary"
