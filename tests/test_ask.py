"""Tests for neurostack.ask — RAG synthesis context construction (issue #40)."""

import neurostack.ask as ask_mod
from neurostack.ask import ask_vault
from neurostack.search import SearchResult


class _FakeResp:
    def __init__(self, content):
        self._content = content

    def raise_for_status(self):
        pass

    def json(self):
        return {"choices": [{"message": {"content": self._content}}]}


def _patch(monkeypatch, results, answer="ok [[Widget]]"):
    """Patch hybrid_search to return `results` and capture the synthesis prompt."""
    captured = {}
    monkeypatch.setattr(ask_mod, "hybrid_search", lambda *a, **k: results)

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["prompt"] = json["messages"][0]["content"]
        return _FakeResp(answer)

    monkeypatch.setattr(ask_mod.httpx, "post", fake_post)
    return captured


def test_full_chunk_passed_not_just_snippet(monkeypatch):
    """The fix: a fact past char 300 of the matched chunk reaches synthesis (#40)."""
    filler = "preamble text. " * 30  # ~450 chars of lead-in
    fact = "The widget service is deployed on host alpha-07."
    chunk = filler + fact
    sr = SearchResult(
        note_path="notes/widget.md",
        heading_path="## Deployment",
        snippet=chunk[:300],          # display snippet — fact is NOT in here
        score=0.9,
        summary="Covers widget deployment.",
        title="Widget",
        chunk_content=chunk,          # full chunk — fact IS in here
    )
    captured = _patch(monkeypatch, [sr])

    result = ask_vault("where is the widget service deployed?")

    # Before the fix only snippet[:300] was passed, so `fact` never reached the LLM.
    assert fact in captured["prompt"]
    # sources[] now carries the excerpt actually synthesised.
    assert result["sources"][0]["excerpt"].endswith(fact)


def test_summary_included_in_context(monkeypatch):
    """The note summary (which often states the fact) is passed to synthesis."""
    sr = SearchResult(
        note_path="notes/x.md",
        heading_path="## Misc",
        snippet="unrelated lead paragraph",
        score=0.8,
        summary="X is NOT deployed — verified 2026-06-11.",
        title="X",
        chunk_content="unrelated lead paragraph about something else entirely",
    )
    captured = _patch(monkeypatch, [sr])

    ask_vault("is X deployed?")

    assert "X is NOT deployed — verified 2026-06-11." in captured["prompt"]


def test_prompt_distinguishes_absent_from_unspecific(monkeypatch):
    """The prompt must not instruct a blunt 'say it's absent' on thin context."""
    sr = SearchResult(
        note_path="notes/x.md", heading_path="## A", snippet="s",
        score=0.5, summary="", title="X", chunk_content="some content",
    )
    captured = _patch(monkeypatch, [sr])
    ask_vault("q?")
    prompt = captured["prompt"]
    assert "did not include that detail" in prompt
    assert "Do NOT assert" in prompt


def test_no_results_short_circuits(monkeypatch):
    """Empty retrieval returns the no-notes message without calling the LLM."""
    called = {"post": False}
    monkeypatch.setattr(ask_mod, "hybrid_search", lambda *a, **k: [])

    def fake_post(*a, **k):
        called["post"] = True
        return _FakeResp("x")

    monkeypatch.setattr(ask_mod.httpx, "post", fake_post)
    result = ask_vault("q?")
    assert result["sources"] == []
    assert called["post"] is False
