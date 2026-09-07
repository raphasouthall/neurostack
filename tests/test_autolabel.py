"""Tests for neurostack.autolabel — vault-agnostic label generation (issue #66).

Offline by construction: labels come from stored summaries and titles, and #142
removed the model-written tier, so nothing here needs a network stub.
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
