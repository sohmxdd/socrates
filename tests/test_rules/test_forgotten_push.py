"""tests/test_rules/test_forgotten_push.py"""
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from socrates.rules.base import Confidence, RuleType
from socrates.rules.forgotten_push import (
    check_forgotten_push,
    _get_current_branch,
    _get_unpushed_count,
)


class TestCheckForgottenPush:
    def test_nonexistent_directory_returns_none(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory(prefix="socrates_fp_") as tmp:
            fake = str(Path(tmp) / "nonexistent_repo")
            result = check_forgotten_push(fake)
            assert result.confidence == Confidence.NONE
            assert result.rule_type == RuleType.FORGOTTEN_PUSH

    def test_not_a_git_repo_returns_none(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory(prefix="socrates_fp_") as tmp:
            result = check_forgotten_push(tmp)
            assert result.confidence == Confidence.NONE

    @pytest.mark.skipif(sys.platform == "win32", reason="git subprocess has handle issues on Windows in test environment")
    def test_returns_none_when_no_upstream(self) -> None:
        """Branch with no upstream configured → NONE (not an error)."""
        # Init a fresh repo — it has no upstream by definition.
        import tempfile, os
        with tempfile.TemporaryDirectory(prefix="socrates_fp_") as tmpdir:
            subprocess.run(["git", "init", tmpdir], capture_output=True)
            subprocess.run(["git", "-C", tmpdir, "config", "user.email", "t@t.com"], capture_output=True)
            subprocess.run(["git", "-C", tmpdir, "config", "user.name", "T"], capture_output=True)
            # Add a commit so HEAD exists.
            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("hello")
            subprocess.run(["git", "-C", tmpdir, "add", "."], capture_output=True)
            subprocess.run(["git", "-C", tmpdir, "commit", "-m", "init"], capture_output=True)
            result = check_forgotten_push(tmpdir)
            assert result.confidence == Confidence.NONE

    def test_high_confidence_when_unpushed(self) -> None:
        """Simulate unpushed commits by mocking _get_unpushed_count."""
        with patch("socrates.rules.forgotten_push._get_unpushed_count", return_value=3), \
             patch("socrates.rules.forgotten_push._get_current_branch", return_value="main"), \
             patch("socrates.rules.forgotten_push._get_commit_range_hash", return_value="abc123"), \
             patch.object(Path, "exists", return_value=True), \
             patch("socrates.rules.forgotten_push.Path") as MockPath:
            # Set up the mock path to look like a real git repo
            mock_instance = MagicMock()
            mock_instance.exists.return_value = True
            mock_instance.__truediv__ = lambda s, x: MagicMock(exists=lambda: True)
            MockPath.return_value = mock_instance

            result = check_forgotten_push("/fake/repo")
            assert result.confidence == Confidence.HIGH_CONFIDENCE
            assert result.facts["unpushed_count"] == 3
            assert result.facts["branch"] == "main"

    def test_fingerprint_key_includes_commit_range(self) -> None:
        """Fingerprint should include the commit range hash, not just the count."""
        with patch("socrates.rules.forgotten_push._get_unpushed_count", return_value=2), \
             patch("socrates.rules.forgotten_push._get_current_branch", return_value="dev"), \
             patch("socrates.rules.forgotten_push._get_commit_range_hash", return_value="deadbeef"), \
             patch.object(Path, "exists", return_value=True), \
             patch("socrates.rules.forgotten_push.Path") as MockPath:
            mock_instance = MagicMock()
            mock_instance.exists.return_value = True
            mock_instance.__truediv__ = lambda s, x: MagicMock(exists=lambda: True)
            MockPath.return_value = mock_instance

            result = check_forgotten_push("/fake/repo")
            assert "deadbeef" in result.fingerprint_key
            assert "dev" in result.fingerprint_key

    def test_zero_unpushed_returns_none(self) -> None:
        with patch("socrates.rules.forgotten_push._get_unpushed_count", return_value=0), \
             patch("socrates.rules.forgotten_push.Path") as MockPath:
            mock_instance = MagicMock()
            mock_instance.exists.return_value = True
            mock_instance.__truediv__ = lambda s, x: MagicMock(exists=lambda: True)
            MockPath.return_value = mock_instance

            result = check_forgotten_push("/fake/repo")
            assert result.confidence == Confidence.NONE


class TestGetUnpushedCount:
    def test_returns_none_on_git_failure(self) -> None:
        """When git isn't a repo or has no upstream, _get_unpushed_count returns None."""
        import tempfile
        with tempfile.TemporaryDirectory(prefix="socrates_up_") as tmpdir:
            result = _get_unpushed_count(tmpdir)
            assert result is None

    def test_returns_int_on_success(self) -> None:
        with patch("socrates.rules.forgotten_push._run_git", return_value="5"):
            result = _get_unpushed_count("/fake")
            assert result == 5

    def test_handles_invalid_git_output(self) -> None:
        with patch("socrates.rules.forgotten_push._run_git", return_value="not_a_number"):
            result = _get_unpushed_count("/fake")
            assert result is None
