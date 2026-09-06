"""
tests/test_personality/test_messages.py

Tests for generate_message() dispatcher behaviour:
  - quiet mode always returns deterministic terse fallback (no LLM)
  - LEAKED_SECRETS always uses hardcoded fallback (no LLM)
  - All other events attempt LLM first via personality_writer
  - Empty / error from LLM -> hardcoded fallback
  - Architecture: top-level module imports stay clean (no socrates.rules/gate/daemon/presentation)
"""
import inspect
from unittest.mock import patch

import pytest

import socrates.personality.messages as messages_module
from socrates.personality.messages import generate_message


# ── Architecture ─────────────────────────────────────────────────────────────

class TestArchitectureSeparation:
    def test_top_level_imports_clean(self) -> None:
        """
        Module-level imports must not reference rules, gate, daemon, or presentation.
        (Lazy imports inside function bodies are allowed -- they won't show up as
        top-level import statements in the module source before the first def.)
        """
        source = inspect.getsource(messages_module)
        # Check that forbidden modules do not appear as top-level imports.
        # We check the lines before the first function definition.
        preamble_lines = []
        for line in source.splitlines():
            if line.startswith("def ") or line.startswith("class "):
                break
            preamble_lines.append(line)
        preamble = "\n".join(preamble_lines)
        assert "socrates.rules" not in preamble
        assert "socrates.gate" not in preamble
        assert "socrates.daemon" not in preamble
        assert "socrates.presentation" not in preamble


# ── Dispatcher: LLM used when personality_writer returns content ──────────────

class TestDynamicDispatch:
    def test_llm_message_used_when_available(self) -> None:
        """When LLM returns content, generate_message() uses it, not the hardcoded template."""
        llm_msg = "Another one. Three commits on feat-login, visible to nobody but you."
        with patch("socrates.personality.messages._try_dynamic", return_value=llm_msg):
            result = generate_message("forgotten_push", {"unpushed_count": 3, "branch": "feat-login"})
        assert result == llm_msg

    def test_falls_back_to_hardcoded_when_llm_returns_empty(self) -> None:
        """When LLM returns empty string, the hardcoded fallback is used."""
        with patch("socrates.personality.messages._try_dynamic", return_value=""):
            result = generate_message("forgotten_push", {"unpushed_count": 2, "branch": "main"})
        # The hardcoded fallback should mention the count and branch
        assert "2" in result
        assert "main" in result

    def test_falls_back_to_hardcoded_when_llm_raises(self) -> None:
        """If _try_dynamic raises (shouldn't, but defensive), fallback is used."""
        with patch("socrates.personality.messages._try_dynamic", side_effect=RuntimeError("boom")):
            # generate_message itself wraps _try_dynamic so it shouldn't propagate
            # but if it does, the test catches it properly
            try:
                result = generate_message("silent_failure", {"command": "make"})
                # If it returns something, it's the hardcoded fallback
                assert "make" in result or "success" in result or "Socrates" in result
            except RuntimeError:
                pytest.fail("RuntimeError from _try_dynamic should not propagate")

    def test_llm_not_called_in_quiet_mode(self) -> None:
        """quiet=True must never hit _try_dynamic."""
        with patch("socrates.personality.messages._try_dynamic") as mock_dyn:
            result = generate_message("forgotten_push", {"unpushed_count": 4, "branch": "main"}, quiet=True)
        mock_dyn.assert_not_called()
        assert "4" in result
        assert "main" in result

    def test_llm_not_called_for_leaked_secrets(self) -> None:
        """LEAKED_SECRETS must never hit _try_dynamic regardless of config."""
        with patch("socrates.personality.messages._try_dynamic") as mock_dyn:
            result = generate_message("leaked_secrets", {"pattern_names": ["AWS Access Key ID"]})
        mock_dyn.assert_not_called()
        assert "AWS Access Key ID" in result


# ── Quiet mode: always deterministic ─────────────────────────────────────────

class TestForgottenPushQuiet:
    def test_quiet_plural(self) -> None:
        facts = {"unpushed_count": 4, "branch": "main"}
        msg = generate_message("forgotten_push", facts, quiet=True)
        assert msg == "4 unpushed commits on 'main'."

    def test_quiet_singular(self) -> None:
        facts = {"unpushed_count": 1, "branch": "dev"}
        msg = generate_message("forgotten_push", facts, quiet=True)
        assert msg == "1 unpushed commit on 'dev'."


class TestLeakedSecretsQuiet:
    def test_quiet(self) -> None:
        facts = {"pattern_names": ["GitHub Personal Access Token"]}
        msg = generate_message("leaked_secrets", facts, quiet=True)
        assert msg == "Detected potential secret in command: GitHub Personal Access Token."


class TestSilentFailureQuiet:
    def test_missing_artifact_quiet(self) -> None:
        facts = {"missing_artifact": "build/app.bin"}
        msg = generate_message("silent_failure", facts, quiet=True)
        assert msg == "Command exited 0 but expected artifact was not created: 'build/app.bin'."

    def test_error_keyword_quiet(self) -> None:
        facts = {"error_keyword": "SEGFAULT"}
        msg = generate_message("silent_failure", facts, quiet=True)
        assert msg == "Command exited 0 but produced error in stderr: 'SEGFAULT'."


class TestStuckProcessQuiet:
    def test_quiet(self) -> None:
        facts = {
            "command_sig": "cargo build",
            "elapsed_secs": 60,
            "baseline_mean_secs": 10,
        }
        msg = generate_message("stuck_process", facts, quiet=True)
        assert "Process 'cargo build'" in msg
        assert "running for 1 minute" in msg or "60 seconds" in msg
        assert "historical baseline: 10 seconds" in msg


# ── Hardcoded fallback content (when LLM is mocked out) ─────────────────────

class TestHardcodedFallbacks:
    """When _try_dynamic returns "", verify hardcoded messages contain key facts."""

    def _no_llm(self, rule_type, facts):
        with patch("socrates.personality.messages._try_dynamic", return_value=""):
            return generate_message(rule_type, facts, quiet=False)

    def test_forgotten_push_has_count_and_branch(self) -> None:
        msg = self._no_llm("forgotten_push", {"unpushed_count": 3, "branch": "feat-login"})
        assert "3" in msg
        assert "feat-login" in msg

    def test_leaked_secrets_always_hardcoded(self) -> None:
        # LEAKED_SECRETS never calls _try_dynamic; assert fallback has key terms
        msg = generate_message("leaked_secrets", {"pattern_names": ["AWS Access Key ID"]})
        assert "AWS Access Key ID" in msg

    def test_silent_failure_missing_artifact(self) -> None:
        msg = self._no_llm("silent_failure", {"missing_artifact": "dist/bundle.js"})
        assert "dist/bundle.js" in msg

    def test_silent_failure_error_keyword(self) -> None:
        msg = self._no_llm("silent_failure", {"error_keyword": "fatal error"})
        assert "fatal error" in msg

    def test_stuck_process_has_times(self) -> None:
        facts = {"command_sig": "pytest", "elapsed_secs": 180, "baseline_mean_secs": 12}
        msg = self._no_llm("stuck_process", facts)
        assert "pytest" in msg
        assert "3 minutes" in msg or "180" in msg
        assert "12 seconds" in msg
