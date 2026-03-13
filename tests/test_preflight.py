"""Tests for neurostack.preflight — Ollama connectivity checks."""

from unittest.mock import MagicMock, patch

import httpx

from neurostack.preflight import (
    OllamaCheckResult,
    check_ollama,
    preflight_report,
)


class TestCheckOllama:
    def test_both_services_available(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "models": [
                {"name": "nomic-embed-text:latest"},
                {"name": "qwen2.5:3b"},
            ]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("neurostack.preflight.httpx.get", return_value=mock_response):
            result = check_ollama(
                "http://localhost:11435", "nomic-embed-text",
                "http://localhost:11434", "qwen2.5:3b",
            )
        assert result.embed_ok
        assert result.llm_ok
        assert result.any_ok

    def test_connection_refused(self):
        with patch(
            "neurostack.preflight.httpx.get",
            side_effect=httpx.ConnectError("refused"),
        ):
            result = check_ollama(
                "http://localhost:99999", "model",
                "http://localhost:99999", "model",
            )
        assert not result.embed_ok
        assert not result.llm_ok
        assert "Cannot connect" in result.embed_error

    def test_model_not_found(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "models": [{"name": "other-model:latest"}]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("neurostack.preflight.httpx.get", return_value=mock_response):
            result = check_ollama(
                "http://localhost:11435", "missing-model",
                "http://localhost:11434", "qwen2.5:3b",
            )
        assert not result.embed_ok
        assert "not found" in result.embed_error
        assert "ollama pull" in result.embed_error
        assert not result.llm_ok  # qwen2.5:3b also not in list


class TestPreflightReport:
    def test_all_ok(self):
        result = OllamaCheckResult()
        result.embed_ok = True
        result.llm_ok = True
        assert preflight_report(result) == ""

    def test_embed_down(self):
        result = OllamaCheckResult()
        result.embed_ok = False
        result.embed_error = "Cannot connect to Ollama"
        result.llm_ok = True
        report = preflight_report(result)
        assert "Embeddings: UNAVAILABLE" in report
        assert "FTS5-only" in report

    def test_both_down(self):
        result = OllamaCheckResult()
        result.embed_ok = False
        result.embed_error = "Connection refused"
        result.llm_ok = False
        result.llm_error = "Connection refused"
        report = preflight_report(result)
        assert "Embeddings: UNAVAILABLE" in report
        assert "Summaries/Triples: UNAVAILABLE" in report
