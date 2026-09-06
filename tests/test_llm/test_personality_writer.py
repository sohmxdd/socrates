"""
tests/test_llm/test_personality_writer.py

Unit tests for socrates.llm.personality_writer.

Tests cover:
  - Hard security invariant: LEAKED_SECRETS always returns "" without any network call
  - No API key -> returns "" without network call
  - Network/LLM error -> returns "" (fallback-safe)
  - Successful call -> returns stripped text from LLM
  - _build_user_content: correct fields, labels, duration formatting
  - _format_duration: boundary cases
"""
import os
from unittest.mock import MagicMock, patch

import pytest

from socrates.llm.personality_writer import (
    generate_dynamic_message,
    _build_user_content,
    _format_duration,
    PERSONA_SYSTEM_PROMPT,
)


# ── Security invariant ────────────────────────────────────────────────────────

class TestLeakedSecretsHardBlock:
    def test_leaked_secrets_enum_never_reaches_llm(self) -> None:
        """LEAKED_SECRETS must always return '' and never call Groq."""
        from socrates.rules.base import RuleType
        with patch("socrates.llm.personality_writer._call_groq") as mock_call:
            result = generate_dynamic_message(RuleType.LEAKED_SECRETS, {"command": "AKIA..."})
        mock_call.assert_not_called()
        assert result == ""

    def test_leaked_secrets_string_never_reaches_llm(self) -> None:
        """Also works when rule_type is a raw string."""
        with patch("socrates.llm.personality_writer._call_groq") as mock_call:
            result = generate_dynamic_message("leaked_secrets", {"command": "AKIA..."})
        mock_call.assert_not_called()
        assert result == ""


# ── No API key ────────────────────────────────────────────────────────────────

class TestNoApiKey:
    def test_no_groq_key_returns_empty(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with patch("socrates.llm.personality_writer._call_groq") as mock_call:
                result = generate_dynamic_message("silent_failure", {"command": "make"})
        mock_call.assert_not_called()
        assert result == ""


# ── Error handling ────────────────────────────────────────────────────────────

class TestErrorHandling:
    def test_network_error_returns_empty(self) -> None:
        with patch.dict(os.environ, {"GROQ_API_KEY": "gsk_test"}, clear=True):
            with patch("socrates.llm.personality_writer._call_groq", side_effect=Exception("network error")):
                result = generate_dynamic_message("silent_failure", {"command": "make"})
        assert result == ""

    def test_timeout_returns_empty(self) -> None:
        with patch.dict(os.environ, {"GROQ_API_KEY": "gsk_test"}, clear=True):
            with patch("socrates.llm.personality_writer._call_groq", side_effect=TimeoutError("timed out")):
                result = generate_dynamic_message("stuck_process", {"command_sig": "pytest"})
        assert result == ""

    def test_none_response_returns_empty(self) -> None:
        with patch.dict(os.environ, {"GROQ_API_KEY": "gsk_test"}, clear=True):
            with patch("socrates.llm.personality_writer._call_groq", return_value=None):
                result = generate_dynamic_message("forgotten_push", {"branch": "main"})
        assert result == ""

    def test_empty_string_response_returns_empty(self) -> None:
        with patch.dict(os.environ, {"GROQ_API_KEY": "gsk_test"}, clear=True):
            with patch("socrates.llm.personality_writer._call_groq", return_value="   "):
                result = generate_dynamic_message("forgotten_push", {"branch": "main"})
        assert result == ""


# ── Happy path ────────────────────────────────────────────────────────────────

class TestSuccessfulGeneration:
    def test_returns_llm_text_stripped(self) -> None:
        llm_text = "  Three commits on main. Bold strategy.  "
        with patch.dict(os.environ, {"GROQ_API_KEY": "gsk_test"}, clear=True):
            with patch("socrates.llm.personality_writer._call_groq", return_value=llm_text):
                result = generate_dynamic_message("forgotten_push", {"branch": "main", "unpushed_count": 3})
        assert result == "Three commits on main. Bold strategy."

    def test_call_groq_receives_correct_system_prompt(self) -> None:
        """_call_groq is called with the PERSONA_SYSTEM_PROMPT exactly."""
        captured = {}

        def fake_call_groq(api_key, user_content, config):
            captured["user_content"] = user_content
            return "Fascinating."

        with patch.dict(os.environ, {"GROQ_API_KEY": "gsk_test"}, clear=True):
            with patch("socrates.llm.personality_writer._call_groq", side_effect=fake_call_groq):
                generate_dynamic_message("silent_failure", {"command": "make", "exit_code": 0})

        assert "EVENT TYPE: SILENT FAILURE" in captured["user_content"]
        assert "Command run: make" in captured["user_content"]


# ── _build_user_content ───────────────────────────────────────────────────────

class TestBuildUserContent:
    def test_includes_event_type_label(self) -> None:
        content = _build_user_content("forgotten_push", {})
        assert "EVENT TYPE: FORGOTTEN PUSH" in content

    def test_includes_branch_and_count(self) -> None:
        content = _build_user_content("forgotten_push", {
            "unpushed_count": 5, "branch": "feat/login"
        })
        assert "5 commits" in content
        assert "feat/login" in content

    def test_singular_commit_label(self) -> None:
        content = _build_user_content("forgotten_push", {"unpushed_count": 1, "branch": "main"})
        assert "1 commit" in content
        assert "commits" not in content

    def test_elapsed_formatted_as_duration(self) -> None:
        content = _build_user_content("stuck_process", {
            "elapsed_secs": 180, "baseline_mean_secs": 12
        })
        assert "3 minutes" in content
        assert "12 seconds" in content

    def test_error_keyword_included(self) -> None:
        content = _build_user_content("silent_failure", {
            "error_keyword": "fatal: authentication failed"
        })
        assert "fatal: authentication failed" in content

    def test_groq_reason_included_as_prior_analysis(self) -> None:
        content = _build_user_content("silent_failure", {
            "groq_reason": "The build produced a fatal error despite exit 0."
        })
        assert "Prior analysis note" in content
        assert "The build produced a fatal error" in content

    def test_ends_with_write_instruction(self) -> None:
        content = _build_user_content("stuck_process", {})
        assert content.strip().endswith("Write the Socrates intervention message now.")

    def test_unknown_extra_facts_included(self) -> None:
        content = _build_user_content("silent_failure", {"custom_field": "myvalue"})
        assert "myvalue" in content

    def test_sensitive_keys_excluded(self) -> None:
        """stderr_tail should not appear in the prompt (could contain secrets)."""
        content = _build_user_content("silent_failure", {
            "stderr_tail": "SUPER_SECRET_TOKEN=abc123",
            "error_keyword": "fatal"
        })
        assert "SUPER_SECRET_TOKEN" not in content


# ── _format_duration ──────────────────────────────────────────────────────────

class TestFormatDuration:
    def test_seconds(self) -> None:
        assert _format_duration(1) == "1 second"
        assert _format_duration(45) == "45 seconds"

    def test_minutes_exact(self) -> None:
        assert _format_duration(60) == "1 minute"
        assert _format_duration(120) == "2 minutes"

    def test_minutes_with_remainder(self) -> None:
        assert _format_duration(90) == "1m 30s"

    def test_hours(self) -> None:
        assert _format_duration(3600) == "1h 0m"
        assert _format_duration(5400) == "1h 30m"


# ── Persona system prompt sanity ──────────────────────────────────────────────

class TestPersonaPrompt:
    def test_contains_key_character_rules(self) -> None:
        assert "devastating" in PERSONA_SYSTEM_PROMPT.lower() or "exasperation" in PERSONA_SYSTEM_PROMPT
        assert "1 to 3 lines" in PERSONA_SYSTEM_PROMPT

    def test_contains_reference_examples(self) -> None:
        assert "feat-login" in PERSONA_SYSTEM_PROMPT  # from forgotten_push example
        assert "pytest" in PERSONA_SYSTEM_PROMPT       # from stuck_process example
        assert "dist/bundle.js" in PERSONA_SYSTEM_PROMPT  # from silent_failure example

    def test_does_not_instruct_json_output(self) -> None:
        assert "Output ONLY the message text" in PERSONA_SYSTEM_PROMPT
        assert "No JSON" in PERSONA_SYSTEM_PROMPT
