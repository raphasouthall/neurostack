"""Tests for neurostack.autolabel — vault-agnostic label generation (issue #66).

Offline: the heuristic tier needs no network, and the LLM tier is exercised with
a stubbed httpx.post so the caching and parsing are tested without a model.
"""

import pytest

from neurostack import autolabel
from neurostack.schema import get_db


@pytest.fixture
def label_corpus(tmp_path):
    """Four notes: two with summaries, one title-only, one with neither."""
    db_file = tmp_path / "labels.db"
    conn = get_db(db_file)

    def add(path, title, summary, hash_):
        conn.execute(
            "INSERT INTO notes (path, title, frontmatter, content_hash, updated_at) "
            "VALUES (?, ?, '{}', ?, '2026-01-01T00:00:00+00:00')",
            (path, title, hash_),
        )
        conn.execute(
            "INSERT INTO chunks (note_path, heading_path, content, content_hash, position) "
            "VALUES (?, '', ?, ?, 0)",
            (path, f"body text for {path}", hash_),
        )
        if summary is not None:
            conn.execute(
                "INSERT INTO summaries (note_path, summary_text, content_hash, updated_at) "
                "VALUES (?, ?, ?, '2026-01-01T00:00:00+00:00')",
                (path, summary, hash_),
            )

    add("notes/alpha.md", "Alpha", "Configures the alpha subsystem. Owns the retry policy.", "h1")
    add("notes/beta.md", "Beta", "Beta handles ingestion batching and backpressure.", "h2")
    add("notes/gamma.md", "Gamma", None, "h3")          # title only, no summary
    add("notes/delta.md", "", None, "h4")               # neither summary nor title
    conn.commit()
    return db_file, conn


# ── helpers ─────────────────────────────────────────────────────────────────


def test_target_for_strips_md():
    assert autolabel._target_for("a/b/note.md") == "a/b/note"
    assert autolabel._target_for("a/b/note") == "a/b/note"


def test_first_sentence():
    assert autolabel._first_sentence("Owns retries. And more.") == "Owns retries."
    assert autolabel._first_sentence("no end punctuation") == "no end punctuation"


def test_parse_query_lines_strips_numbering_and_quotes():
    raw = '1. "how to configure retries"\n- what owns the retry policy\n\n3) alpha subsystem setup'
    got = autolabel._parse_query_lines(raw, k=2)
    assert got == ["how to configure retries", "what owns the retry policy"]


def test_parse_query_lines_drops_think_block():
    raw = "<think>reasoning here</think>\nfind the alpha config"
    assert autolabel._parse_query_lines(raw, k=5) == ["find the alpha config"]


# ── heuristic tier ──────────────────────────────────────────────────────────


def test_heuristic_prefers_summary_falls_back_to_title(label_corpus):
    _, conn = label_corpus
    labels = autolabel.heuristic_labels(conn, n=10, seed=0)
    by_target = {q.targets[0]: q for q in labels}

    # summary note → summary-derived query (first sentence), category autolabel-summary
    assert by_target["notes/alpha"].query == "Configures the alpha subsystem."
    assert by_target["notes/alpha"].category == "autolabel-summary"
    # title-only note → title query
    assert by_target["notes/gamma"].query == "Gamma"
    assert by_target["notes/gamma"].category == "autolabel-title"
    # note with neither is skipped entirely
    assert "notes/delta" not in by_target


def test_heuristic_is_deterministic(label_corpus):
    _, conn = label_corpus
    a = [(q.query, q.targets) for q in autolabel.heuristic_labels(conn, n=2, seed=7)]
    b = [(q.query, q.targets) for q in autolabel.heuristic_labels(conn, n=2, seed=7)]
    assert a == b


def test_sampling_respects_n(label_corpus):
    _, conn = label_corpus
    labels = autolabel.heuristic_labels(conn, n=2, seed=0)
    # at most n notes sampled → at most n labels (delta may drop out)
    assert len(labels) <= 2


# ── LLM tier (stubbed) ──────────────────────────────────────────────────────


class _FakeResp:
    def __init__(self, text):
        self._text = text

    def raise_for_status(self):
        pass

    def json(self):
        return {"choices": [{"message": {"content": self._text}}]}


def test_llm_labels_generate_and_cache(label_corpus, tmp_path, monkeypatch):
    calls = {"n": 0}

    def fake_post(url, **kwargs):
        calls["n"] += 1
        return _FakeResp("query one\nquery two")

    monkeypatch.setattr(autolabel.httpx, "post", fake_post)
    cache_path = tmp_path / "qgen.json"

    labels = autolabel.llm_labels(conn=label_corpus[1], n=10, seed=0, k_per_note=2,
                                  cache_path=cache_path, llm_url="http://x")
    # 3 notes have body content (alpha/beta/gamma); delta has a chunk too → 4 notes,
    # 2 queries each = 8 labels, and one LLM call per note.
    assert all(q.category == "autolabel-llm" for q in labels)
    assert len(labels) == calls["n"] * 2
    first_calls = calls["n"]
    assert cache_path.exists()

    # Second run hits the cache — no new LLM calls.
    autolabel.llm_labels(conn=label_corpus[1], n=10, seed=0, k_per_note=2,
                         cache_path=cache_path, llm_url="http://x")
    assert calls["n"] == first_calls


# ── dispatcher ──────────────────────────────────────────────────────────────


def test_generate_labels_bad_mode(label_corpus):
    with pytest.raises(ValueError, match="mode must be"):
        autolabel.generate_labels(label_corpus[1], mode="magic")


def test_generate_labels_auto_falls_back_when_llm_unreachable(label_corpus, monkeypatch):
    monkeypatch.setattr(autolabel, "_llm_reachable", lambda *a, **k: False)
    labels = autolabel.generate_labels(label_corpus[1], mode="auto", n=10)
    # heuristic floor produced summary/title labels, not LLM ones
    assert labels
    assert all(q.category in ("autolabel-summary", "autolabel-title") for q in labels)


def test_generate_labels_auto_uses_llm_when_reachable(label_corpus, monkeypatch):
    monkeypatch.setattr(autolabel, "_llm_reachable", lambda *a, **k: True)
    monkeypatch.setattr(autolabel.httpx, "post", lambda url, **k: _FakeResp("q1\nq2"))
    labels = autolabel.generate_labels(label_corpus[1], mode="auto", n=10, k_per_note=2)
    assert labels
    assert all(q.category == "autolabel-llm" for q in labels)
