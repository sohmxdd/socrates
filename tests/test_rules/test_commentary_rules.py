"""
tests/test_rules/test_commentary_rules.py — Unit tests for RuleType.COMMENTARY and CommentaryContext.
"""
from socrates.rules.base import RuleType, CommentaryContext


def test_ruletype_has_commentary():
    assert RuleType.COMMENTARY == "commentary"
    assert RuleType.COMMENTARY.value == "commentary"


def test_commentary_context_defaults():
    ctx = CommentaryContext(
        session_id="sess-1",
        command="git status",
        exit_code=0,
        duration_seconds=0.15,
        cwd="/workspace/proj",
    )
    assert ctx.session_id == "sess-1"
    assert ctx.command == "git status"
    assert ctx.exit_code == 0
    assert ctx.duration_seconds == 0.15
    assert ctx.cwd == "/workspace/proj"
    assert ctx.repo_path is None
    assert ctx.stderr_tail is None
    assert ctx.recent_commands == ()
    assert ctx.retry_count == 0
    assert ctx.prev_cwd is None
    assert ctx.is_arrival is False


def test_commentary_context_full():
    ctx = CommentaryContext(
        session_id="sess-2",
        command="pytest",
        exit_code=1,
        duration_seconds=3.5,
        cwd="/workspace/proj/tests",
        repo_path="/workspace/proj",
        stderr_tail="AssertionError: 1 != 2",
        recent_commands=("git status", "pytest", "pytest"),
        retry_count=2,
        prev_cwd="/workspace/proj",
        is_arrival=True,
    )
    assert ctx.retry_count == 2
    assert ctx.is_arrival is True
    assert ctx.prev_cwd == "/workspace/proj"
    assert len(ctx.recent_commands) == 3
