"""Tests for neurostack.summarizer — note and folder summarization via LLM."""

from unittest.mock import MagicMock, patch


def _mock_httpx_response(content: str) -> MagicMock:
    """Create a mock httpx response returning the given content string."""
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {
        "choices": [{"message": {"content": content}}],
    }
    return resp


class TestSummarizeNote:
    @patch("neurostack.summarizer.httpx.post")
    def test_returns_llm_response(self, mock_post):
        from neurostack.summarizer import summarize_note

        mock_post.return_value = _mock_httpx_response("A concise summary.")
        result = summarize_note("My Note", "Some content here.")
        assert result == "A concise summary."
        mock_post.assert_called_once()

    @patch("neurostack.summarizer.httpx.post")
    def test_truncates_long_content(self, mock_post):
        from neurostack.summarizer import summarize_note

        mock_post.return_value = _mock_httpx_response("Summary of long note.")
        long_content = "x" * 5000
        result = summarize_note("Long Note", long_content)
        assert result == "Summary of long note."

        # Verify the prompt sent to the LLM has truncated content
        call_kwargs = mock_post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1]["json"]
        prompt_text = payload["messages"][0]["content"]
        assert "[... truncated]" in prompt_text
        # Original 5000 chars should be cut to 3000 + truncation marker
        assert "x" * 3000 in prompt_text
        assert "x" * 3001 not in prompt_text

    @patch("neurostack.summarizer.httpx.post")
    def test_strips_think_tags(self, mock_post):
        from neurostack.summarizer import summarize_note

        mock_post.return_value = _mock_httpx_response(
            "<think>reasoning here</think>Actual summary"
        )
        result = summarize_note("Think Note", "Content.")
        assert result == "Actual summary"

    @patch("neurostack.summarizer.httpx.post")
    def test_strips_think_tags_multiline(self, mock_post):
        from neurostack.summarizer import summarize_note

        mock_post.return_value = _mock_httpx_response(
            "<think>\nlong\nreasoning\n</think>\nClean result"
        )
        result = summarize_note("Think Note", "Content.")
        assert result == "Clean result"


class TestSummarizeFolder:
    def test_returns_empty_for_no_children(self):
        from neurostack.summarizer import summarize_folder

        result = summarize_folder("some/folder", [])
        assert result == ""

    def test_returns_empty_for_none_children(self):
        from neurostack.summarizer import summarize_folder

        result = summarize_folder("some/folder", [])
        assert result == ""

    @patch("neurostack.summarizer.httpx.post")
    def test_returns_summary_for_valid_children(self, mock_post):
        from neurostack.summarizer import summarize_folder

        mock_post.return_value = _mock_httpx_response("Folder covers Python and Rust.")
        children = [
            {"title": "Python Basics", "summary": "Covers Python fundamentals."},
            {"title": "Rust Intro", "summary": "Introduction to Rust language."},
        ]
        result = summarize_folder("programming/", children)
        assert result == "Folder covers Python and Rust."
        mock_post.assert_called_once()

    @patch("neurostack.summarizer.httpx.post")
    def test_strips_think_tags(self, mock_post):
        from neurostack.summarizer import summarize_folder

        mock_post.return_value = _mock_httpx_response(
            "<think>internal reasoning</think>Clean folder summary"
        )
        children = [{"title": "Note", "summary": "A summary."}]
        result = summarize_folder("folder/", children)
        assert result == "Clean folder summary"

    def test_skips_entries_without_summary_text(self):
        from neurostack.summarizer import summarize_folder

        # All entries lack summary text, so lines list is empty → returns ""
        children = [
            {"title": "Empty Note", "summary": ""},
            {"title": "None Note", "summary": None},
            {"title": "Missing Note"},
        ]
        result = summarize_folder("empty/folder", children)
        assert result == ""
