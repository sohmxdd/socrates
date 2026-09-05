"""tests/test_personality/test_messages.py — Tests for in-character message generation and quiet mode."""
import inspect
import pytest

import socrates.personality.messages as messages_module
from socrates.personality.messages import generate_message


class TestArchitectureSeparation:
    def test_zero_internal_dependencies(self) -> None:
        """Module must have zero dependencies on other socrates modules."""
        source = inspect.getsource(messages_module)
        assert "socrates.rules" not in source
        assert "socrates.gate" not in source
        assert "socrates.daemon" not in source
        assert "socrates.presentation" not in source


class TestForgottenPushMessages:
    def test_in_character_plural(self) -> None:
        facts = {"unpushed_count": 3, "branch": "feat-login"}
        msg = generate_message("forgotten_push", facts, quiet=False)
        assert "3 commits on 'feat-login'" in msg
        assert "trapped upon this machine" in msg
        assert "socrates snooze" in msg

    def test_in_character_singular(self) -> None:
        facts = {"unpushed_count": 1, "branch": "main"}
        msg = generate_message("forgotten_push", facts, quiet=False)
        assert "1 commit on 'main'" in msg

    def test_quiet_mode(self) -> None:
        facts = {"unpushed_count": 4, "branch": "main"}
        msg = generate_message("forgotten_push", facts, quiet=True)
        assert msg == "4 unpushed commits on 'main'."
        assert "trapped" not in msg


class TestLeakedSecretsMessages:
    def test_in_character(self) -> None:
        facts = {"pattern_names": ["AWS Access Key ID"]}
        msg = generate_message("leaked_secrets", facts, quiet=False)
        assert "AWS Access Key ID" in msg
        assert "shouted it into your terminal" in msg

    def test_quiet_mode(self) -> None:
        facts = {"pattern_names": ["GitHub Personal Access Token"]}
        msg = generate_message("leaked_secrets", facts, quiet=True)
        assert msg == "Detected potential secret in command: GitHub Personal Access Token."


class TestSilentFailureMessages:
    def test_missing_artifact_in_character(self) -> None:
        facts = {"missing_artifact": "dist/bundle.js"}
        msg = generate_message("silent_failure", facts, quiet=False)
        assert "dist/bundle.js" in msg
        assert "which one of you is lying" in msg

    def test_missing_artifact_quiet(self) -> None:
        facts = {"missing_artifact": "build/app.bin"}
        msg = generate_message("silent_failure", facts, quiet=True)
        assert msg == "Command exited 0 but expected artifact was not created: 'build/app.bin'."

    def test_error_keyword_in_character(self) -> None:
        facts = {"error_keyword": "fatal error"}
        msg = generate_message("silent_failure", facts, quiet=False)
        assert "fatal error" in msg
        assert "what does success truly mean to you" in msg

    def test_error_keyword_quiet(self) -> None:
        facts = {"error_keyword": "SEGFAULT"}
        msg = generate_message("silent_failure", facts, quiet=True)
        assert msg == "Command exited 0 but produced error in stderr: 'SEGFAULT'."


class TestStuckProcessMessages:
    def test_in_character(self) -> None:
        facts = {
            "command_sig": "pytest",
            "elapsed_secs": 180,
            "baseline_mean_secs": 12,
        }
        msg = generate_message("stuck_process", facts, quiet=False)
        assert "pytest" in msg
        assert "3 minutes" in msg or "180 seconds" in msg
        assert "12 seconds" in msg
        assert "running' become 'waiting'" in msg

    def test_quiet_mode(self) -> None:
        facts = {
            "command_sig": "cargo build",
            "elapsed_secs": 60,
            "baseline_mean_secs": 10,
        }
        msg = generate_message("stuck_process", facts, quiet=True)
        assert "Process 'cargo build'" in msg
        assert "running for 1 minute" in msg or "60 seconds" in msg
        assert "historical baseline: 10 seconds" in msg
