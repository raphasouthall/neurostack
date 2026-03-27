"""Tests for neurostack.triples — triple extraction and formatting."""

import json
from unittest.mock import MagicMock, patch

from neurostack.triples import extract_triples, triple_to_text


def _mock_response(content: str) -> MagicMock:
    """Build a mock httpx response returning the given LLM content string."""
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {
        "choices": [{"message": {"content": content}}],
    }
    return resp


class TestTripleToText:
    def test_basic(self):
        assert triple_to_text({"s": "Python", "p": "uses", "o": "GIL"}) == "Python | uses | GIL"

    def test_whitespace_preserved(self):
        result = triple_to_text({"s": "Foo Bar", "p": "depends on", "o": "Baz Qux"})
        assert result == "Foo Bar | depends on | Baz Qux"


class TestExtractTriplesValid:
    @patch("neurostack.triples.httpx.post")
    def test_returns_valid_triples(self, mock_post):
        triples_json = json.dumps([
            {"s": "Kubernetes", "p": "runs on", "o": "Linux"},
            {"s": "PostgreSQL", "p": "stores", "o": "data"},
        ])
        mock_post.return_value = _mock_response(triples_json)

        result = extract_triples("Test Note", "Some content about K8s and Postgres.")

        assert len(result) == 2
        assert result[0] == {"s": "Kubernetes", "p": "runs on", "o": "Linux"}
        assert result[1] == {"s": "PostgreSQL", "p": "stores", "o": "data"}

    @patch("neurostack.triples.httpx.post")
    def test_calls_httpx_with_correct_args(self, mock_post):
        mock_post.return_value = _mock_response("[]")

        extract_triples("My Note", "content here", base_url="http://test:1234", model="test-model")

        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert call_args[0][0] == "http://test:1234/v1/chat/completions"
        body = call_args[1]["json"]
        assert body["model"] == "test-model"
        assert body["messages"][0]["role"] == "user"
        assert "My Note" in body["messages"][0]["content"]
        assert "content here" in body["messages"][0]["content"]

    @patch("neurostack.triples.httpx.post")
    def test_raise_for_status_called(self, mock_post):
        mock_post.return_value = _mock_response("[]")

        extract_triples("Note", "content")

        mock_post.return_value.raise_for_status.assert_called_once()


class TestExtractTriplesMarkdownFences:
    @patch("neurostack.triples.httpx.post")
    def test_strips_json_fence(self, mock_post):
        raw = '```json\n[{"s": "A", "p": "b", "o": "C"}]\n```'
        mock_post.return_value = _mock_response(raw)

        result = extract_triples("Note", "content")

        assert len(result) == 1
        assert result[0] == {"s": "A", "p": "b", "o": "C"}

    @patch("neurostack.triples.httpx.post")
    def test_strips_plain_fence(self, mock_post):
        raw = '```\n[{"s": "X", "p": "y", "o": "Z"}]\n```'
        mock_post.return_value = _mock_response(raw)

        result = extract_triples("Note", "content")

        assert len(result) == 1
        assert result[0] == {"s": "X", "p": "y", "o": "Z"}


class TestExtractTriplesJsonError:
    @patch("neurostack.triples.httpx.post")
    def test_invalid_json_returns_empty(self, mock_post):
        mock_post.return_value = _mock_response("this is not json at all")

        result = extract_triples("Note", "content")

        assert result == []

    @patch("neurostack.triples.httpx.post")
    def test_partial_json_returns_empty(self, mock_post):
        mock_post.return_value = _mock_response('[{"s": "A", "p": "b"')

        result = extract_triples("Note", "content")

        assert result == []


class TestExtractTriplesValidation:
    @patch("neurostack.triples.httpx.post")
    def test_missing_key_filtered(self, mock_post):
        triples_json = json.dumps([
            {"s": "A", "p": "b", "o": "C"},
            {"s": "X", "p": "y"},           # missing "o"
            {"s": "D", "o": "F"},            # missing "p"
        ])
        mock_post.return_value = _mock_response(triples_json)

        result = extract_triples("Note", "content")

        assert len(result) == 1
        assert result[0] == {"s": "A", "p": "b", "o": "C"}

    @patch("neurostack.triples.httpx.post")
    def test_empty_values_filtered(self, mock_post):
        triples_json = json.dumps([
            {"s": "A", "p": "b", "o": "C"},
            {"s": "", "p": "b", "o": "C"},
            {"s": "A", "p": "", "o": "C"},
            {"s": "A", "p": "b", "o": ""},
        ])
        mock_post.return_value = _mock_response(triples_json)

        result = extract_triples("Note", "content")

        assert len(result) == 1
        assert result[0] == {"s": "A", "p": "b", "o": "C"}

    @patch("neurostack.triples.httpx.post")
    def test_whitespace_only_values_filtered(self, mock_post):
        triples_json = json.dumps([
            {"s": "A", "p": "b", "o": "C"},
            {"s": "  ", "p": "b", "o": "C"},
        ])
        mock_post.return_value = _mock_response(triples_json)

        result = extract_triples("Note", "content")

        assert len(result) == 1

    @patch("neurostack.triples.httpx.post")
    def test_non_dict_entries_filtered(self, mock_post):
        triples_json = json.dumps([
            {"s": "A", "p": "b", "o": "C"},
            "not a dict",
            42,
            None,
        ])
        mock_post.return_value = _mock_response(triples_json)

        result = extract_triples("Note", "content")

        assert len(result) == 1
        assert result[0] == {"s": "A", "p": "b", "o": "C"}

    @patch("neurostack.triples.httpx.post")
    def test_values_are_stripped(self, mock_post):
        triples_json = json.dumps([
            {"s": "  Kubernetes  ", "p": "  runs on  ", "o": "  Linux  "},
        ])
        mock_post.return_value = _mock_response(triples_json)

        result = extract_triples("Note", "content")

        assert result[0] == {"s": "Kubernetes", "p": "runs on", "o": "Linux"}


class TestExtractTriplesTruncation:
    @patch("neurostack.triples.httpx.post")
    def test_content_over_4000_is_truncated(self, mock_post):
        mock_post.return_value = _mock_response("[]")
        long_content = "x" * 5000

        extract_triples("Note", long_content)

        call_args = mock_post.call_args
        prompt = call_args[1]["json"]["messages"][0]["content"]
        # The prompt should contain the truncated content (4000 chars) plus marker
        assert "[... truncated]" in prompt
        # Original 5000-char string should NOT appear in full
        assert "x" * 5000 not in prompt

    @patch("neurostack.triples.httpx.post")
    def test_content_under_4000_not_truncated(self, mock_post):
        mock_post.return_value = _mock_response("[]")
        short_content = "x" * 3000

        extract_triples("Note", short_content)

        call_args = mock_post.call_args
        prompt = call_args[1]["json"]["messages"][0]["content"]
        assert "[... truncated]" not in prompt
        assert "x" * 3000 in prompt
