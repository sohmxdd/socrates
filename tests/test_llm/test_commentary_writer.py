"""
tests/test_llm/test_commentary_writer.py — Unit tests for the ambient commentary writer.
"""
import os
from unittest.mock import patch, MagicMock
import pytest

from socrates.rules.base import CommentaryContext
from socrates.llm.commentary_writer import (
    _build_commentary_prompt,
    _select_fallback,
    generate_commentary,
    OFFLINE_FALLBACKS,
)
from socrates.llm.command_classifier import CommandCategory, classify_command


def test_command_classifier():
    assert classify_command("git status") == CommandCategory.GIT
    assert classify_command("git commit -m 'feat'") == CommandCategory.GIT
    assert classify_command("cd ..") == CommandCategory.NAVIGATION
    assert classify_command("ls -la") == CommandCategory.NAVIGATION
    assert classify_command("dir") == CommandCategory.NAVIGATION
    assert classify_command("pytest") == CommandCategory.TEST
    assert classify_command("npm test") == CommandCategory.TEST
    assert classify_command("cargo build") == CommandCategory.BUILD
    assert classify_command("npm run build") == CommandCategory.BUILD
    assert classify_command("cat file.txt") == CommandCategory.DEBUG
    assert classify_command("rg pattern") == CommandCategory.DEBUG
    assert classify_command("git diff", retry_count=2) == CommandCategory.DESPERATE_RETRY


def test_build_commentary_prompt_basic():
    ctx = CommentaryContext(
        session_id="sess-1",
        command="git status",
        exit_code=0,
        duration_seconds=0.12,
        cwd="/repo",
    )
    prompt = _build_commentary_prompt(ctx)
    assert "COMMAND: git status" in prompt
    assert "CATEGORY: GIT" in prompt
    assert "EXIT CODE: 0" in prompt
    assert "DURATION: 0.12s" in prompt
    assert "CWD: /repo" in prompt


def test_build_commentary_prompt_retry_and_arrival():
    ctx = CommentaryContext(
        session_id="sess-2",
        command="pytest",
        exit_code=1,
        duration_seconds=2.0,
        cwd="/repo/tests",
        prev_cwd="/repo",
        is_arrival=True,
        retry_count=3,
        stderr_tail="FAILED test_foo.py::test_bar",
        recent_commands=("git checkout main", "pytest", "pytest"),
    )
    prompt = _build_commentary_prompt(ctx)
    assert "CATEGORY: DESPERATE_RETRY" in prompt
    assert "PREVIOUS CWD: /repo" in prompt
    assert "CONTEXT: User just arrived in a new workspace directory." in prompt
    assert "RETRY COUNT: 3" in prompt
    assert "CRITICAL: User is caught in a desperate retry loop." in prompt
    assert "STDERR TAIL: FAILED" in prompt
    assert "RECENT COMMAND HISTORY:" in prompt


def test_select_fallback_categories():
    # Arrival
    ctx_arrival = CommentaryContext("s", "ls", 0, 0.1, "/repo", is_arrival=True)
    assert _select_fallback(ctx_arrival) in OFFLINE_FALLBACKS["arrival"]

    # Retry
    ctx_retry = CommentaryContext("s", "cargo test", 1, 0.5, "/repo", retry_count=2)
    res_retry = _select_fallback(ctx_retry)
    assert "2" in res_retry or "insanity" in res_retry.lower() or "desperation" in res_retry.lower()

    # Failure
    ctx_fail = CommentaryContext("s", "npm run build", 127, 0.1, "/repo")
    assert "127" in _select_fallback(ctx_fail) or "Failure recorded" in _select_fallback(ctx_fail)

    # Git status
    ctx_status = CommentaryContext("s", "git status", 0, 0.1, "/repo")
    assert _select_fallback(ctx_status) in OFFLINE_FALLBACKS["git_status"]

    # Git commit
    ctx_commit = CommentaryContext("s", "git commit -m 'wip'", 0, 0.1, "/repo")
    assert _select_fallback(ctx_commit) in OFFLINE_FALLBACKS["git_commit"]

    # Nav
    ctx_nav = CommentaryContext("s", "cd /tmp", 0, 0.1, "/repo")
    assert _select_fallback(ctx_nav) in OFFLINE_FALLBACKS["cd"]


def test_generate_commentary_without_api_key(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    ctx = CommentaryContext("s", "git status", 0, 0.1, "/repo")
    comment = generate_commentary(ctx)
    assert isinstance(comment, str)
    assert len(comment) > 5


def test_generate_commentary_mocked_llm(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "fake_key_123")
    ctx = CommentaryContext("s", "pytest", 1, 1.0, "/repo", retry_count=2)

    with patch("socrates.llm.commentary_writer._call_groq_commentary") as mock_groq:
        mock_groq.return_value = "Socrates observes: Your persistent faith in this failing test is staggering."
        comment = generate_commentary(ctx)
        assert "persistent faith" in comment
        mock_groq.assert_called_once()


def test_generate_commentary_llm_exception_falls_back(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "fake_key_123")
    ctx = CommentaryContext("s", "git status", 0, 0.1, "/repo")

    with patch("socrates.llm.commentary_writer._call_groq_commentary") as mock_groq:
        mock_groq.side_effect = RuntimeError("Groq rate limit or connection error")
        comment = generate_commentary(ctx)
        # Should gracefully fall back to an offline line
        assert isinstance(comment, str)
        assert comment in OFFLINE_FALLBACKS["git_status"]
