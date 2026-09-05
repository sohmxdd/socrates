"""tests/test_llm/test_groq_client.py — Tests for Groq LLM tiebreaker integration and degradation."""
import json
import os
import time
from unittest.mock import MagicMock, patch

import pytest

from socrates.config import SocratesConfig
from socrates.llm.groq_client import GroqClient, scrub_text
from socrates.rules.base import Confidence, RuleResult, RuleType


class TestScrubbing:
    def test_scrub_replaces_secrets(self) -> None:
        raw = "curl -H 'Authorization: Bearer sk-1234567890abcdef1234567890abcdef' https://api.example.com"
        scrubbed = scrub_text(raw)
        assert "sk-123456" not in scrubbed
        assert "[REDACTED:OpenAI API Key]" in scrubbed

    def test_scrub_leaves_benign_text_intact(self) -> None:
        raw = "npm run build -- --env production"
        assert scrub_text(raw) == raw


class TestGroqClientAvailability:
    def test_disabled_by_config(self) -> None:
        cfg = SocratesConfig(groq_enabled=False)
        client = GroqClient(cfg, api_key="dummy_key")
        assert client.is_available is False

        res = RuleResult(RuleType.SILENT_FAILURE, Confidence.LOW_CONFIDENCE, {"command": "make"})
        out = client.tiebreak(res)
        assert out.confidence == Confidence.NONE

    def test_missing_api_key(self) -> None:
        cfg = SocratesConfig(groq_enabled=True)
        with patch.dict(os.environ, {}, clear=True):
            client = GroqClient(cfg, api_key="")
            assert client.is_available is False

            res = RuleResult(RuleType.SILENT_FAILURE, Confidence.LOW_CONFIDENCE, {"command": "make"})
            out = client.tiebreak(res)
            assert out.confidence == Confidence.NONE

    def test_available_with_key(self) -> None:
        cfg = SocratesConfig(groq_enabled=True)
        client = GroqClient(cfg, api_key="gsk_test_key_123")
        assert client.is_available is True


class TestGroqClientRouting:
    def test_leaked_secrets_never_sent_to_groq(self) -> None:
        cfg = SocratesConfig(groq_enabled=True)
        client = GroqClient(cfg, api_key="gsk_test")
        res = RuleResult(
            rule_type=RuleType.LEAKED_SECRETS,
            confidence=Confidence.HIGH_CONFIDENCE,
            facts={"command": "AKIAIOSFODNN7EXAMPLE"},
            fingerprint_key="sec:123",
        )
        with patch.object(client, "_call_groq_with_retry") as mock_call:
            out = client.tiebreak(res)
            mock_call.assert_not_called()
            assert out.confidence == Confidence.HIGH_CONFIDENCE


class TestGroqTiebreakEvaluation:
    def test_intervene_true_upgrades_to_high_confidence(self) -> None:
        cfg = SocratesConfig(groq_enabled=True, groq_min_call_interval_seconds=0.0)
        client = GroqClient(cfg, api_key="gsk_test")

        res = RuleResult(
            rule_type=RuleType.SILENT_FAILURE,
            confidence=Confidence.LOW_CONFIDENCE,
            facts={"command": "make", "stderr_excerpt": "error ignored"},
            fingerprint_key="sf:make:1",
        )

        mock_resp = {"intervene": True, "reason": "The build produced an undetected error."}
        with patch.object(client, "_call_groq_with_retry", return_value=mock_resp):
            out = client.tiebreak(res)
            assert out.confidence == Confidence.HIGH_CONFIDENCE
            assert out.facts.get("groq_reason") == "The build produced an undetected error."

    def test_intervene_false_degrades_to_none(self) -> None:
        cfg = SocratesConfig(groq_enabled=True, groq_min_call_interval_seconds=0.0)
        client = GroqClient(cfg, api_key="gsk_test")

        res = RuleResult(
            rule_type=RuleType.SILENT_FAILURE,
            confidence=Confidence.LOW_CONFIDENCE,
            facts={"command": "npm install", "stderr_excerpt": "npm WARN deprecated"},
            fingerprint_key="sf:npm:1",
        )

        mock_resp = {"intervene": False, "reason": "Just standard deprecation warnings."}
        with patch.object(client, "_call_groq_with_retry", return_value=mock_resp):
            out = client.tiebreak(res)
            assert out.confidence == Confidence.NONE


class TestGroqDegradationAndErrors:
    def test_timeout_degrades_to_none(self) -> None:
        cfg = SocratesConfig(groq_enabled=True, groq_min_call_interval_seconds=0.0)
        client = GroqClient(cfg, api_key="gsk_test")
        res = RuleResult(RuleType.SILENT_FAILURE, Confidence.LOW_CONFIDENCE, {"command": "test"})

        with patch.object(client, "_call_groq_with_retry", return_value=None):
            out = client.tiebreak(res)
            assert out.confidence == Confidence.NONE

    def test_rate_limit_429_sets_backoff(self) -> None:
        cfg = SocratesConfig(
            groq_enabled=True,
            groq_min_call_interval_seconds=0.0,
            groq_rate_limit_backoff_seconds=10.0,
        )
        client = GroqClient(cfg, api_key="gsk_test")

        # Mock exception with status 429
        mock_exc = Exception("Rate limit reached (429)")
        setattr(mock_exc, "status_code", 429)

        with patch("groq.Groq") as mock_groq:
            mock_groq.return_value.chat.completions.create.side_effect = mock_exc
            with patch("time.sleep"):  # don't actually sleep in test
                res = RuleResult(RuleType.SILENT_FAILURE, Confidence.LOW_CONFIDENCE, {"command": "test"})
                out = client.tiebreak(res)
                assert out.confidence == Confidence.NONE
                assert client._backoff_until > time.time()

    def test_markdown_json_response_parsed(self) -> None:
        cfg = SocratesConfig(groq_enabled=True)
        client = GroqClient(cfg, api_key="gsk_test")
        raw = "```json\n{\"intervene\": true, \"reason\": \"Critical fault.\"}\n```"
        parsed = client._parse_response(raw)
        assert parsed is not None
        assert parsed["intervene"] is True
        assert parsed["reason"] == "Critical fault."

    def test_invalid_json_returns_none(self) -> None:
        cfg = SocratesConfig(groq_enabled=True)
        client = GroqClient(cfg, api_key="gsk_test")
        raw = "I think you should intervene because there is an error."
        assert client._parse_response(raw) is None
