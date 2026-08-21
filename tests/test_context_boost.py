"""Tests for the context= soft attention boost on vault_context's sub-retrievals (issue #94).

vault_search already had the 1.4x/1.2x convergence boost; this covers its extension to
the three vault_context sub-retrievals: triples (via _get_context_notes note sets),
memories (workspace/tag match), and the build_vault_context passthrough. Style mirrors
test_prediction_errors.py: real in-memory sqlite, monkeypatched get_db/get_embedding,
never MagicMock.
"""

import json
import struct

import numpy as np

from neurostack.context import build_vault_context
from neurostack.memories import _boost_memories_by_context, search_memories
from neurostack.search import search_triples

DIM = 768


def _emb_blob() -> bytes:
    """Unit embedding e0 — identical for every row so base scores tie exactly."""
    v = [0.0] * DIM
    v[0] = 1.0
    return struct.pack(f"{DIM}f", *v)


def _query_emb() -> np.ndarray:
    q = np.zeros(DIM, dtype=np.float32)
    q[0] = 1.0
    return q


def _add_note(conn, path, title="N"):
    conn.execute(
        "INSERT INTO notes (path, title, content_hash, updated_at) VALUES (?, ?, ?, ?)",
        (path, title, f"h_{path}", "2026-01-01"),
    )


def _add_triple(conn, note_path, subject):
    conn.execute(
        "INSERT INTO triples (note_path, subject, predicate, object, triple_text, embedding)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (note_path, subject, "relates to", "thing", f"tripletoken {subject}", _emb_blob()),
    )


def _add_memory(conn, content, workspace=None, tags=None):
    conn.execute(
        "INSERT INTO memories (content, workspace, tags, embedding) VALUES (?, ?, ?, ?)",
        (content, workspace, json.dumps(tags or []), _emb_blob()),
    )


def _patch_search(monkeypatch, conn):
    import neurostack.search as search_mod

    monkeypatch.setattr(search_mod, "get_db", lambda path: conn)
    monkeypatch.setattr(search_mod, "get_embedding", lambda q, base_url=None: _query_emb())


def _patch_memories(monkeypatch):
    import neurostack.embedder as embedder_mod

    monkeypatch.setattr(embedder_mod, "get_embedding", lambda q, base_url=None: _query_emb())


class TestBoostMemoriesByContext:
    def test_workspace_match_boosted(self):
        rows = [{"workspace": "home/projects/strake", "tags": "[]", "score": 0.5}]
        _boost_memories_by_context(rows, "strake")
        assert rows[0]["score"] == 0.7

    def test_tag_match_boosted(self):
        rows = [{"workspace": None, "tags": json.dumps(["strake", "adr"]), "score": 0.5}]
        _boost_memories_by_context(rows, "strake")
        assert rows[0]["score"] == 0.7

    def test_no_match_untouched(self):
        rows = [{"workspace": "work/nyk", "tags": "[]", "score": 0.5}]
        _boost_memories_by_context(rows, "strake")
        assert rows[0]["score"] == 0.5

    def test_no_context_noop(self):
        rows = [{"workspace": "home/projects/strake", "tags": "[]", "score": 0.5}]
        _boost_memories_by_context(rows, None)
        assert rows[0]["score"] == 0.5

    def test_malformed_tags_tolerated(self):
        rows = [{"workspace": "strake", "tags": "not json", "score": 0.5}]
        _boost_memories_by_context(rows, "strake")
        assert rows[0]["score"] == 0.7


class TestTripleContextBoost:
    """Acceptance: in-context triples outrank equal-scored out-of-context ones;
    out-of-context triples still surface (re-ranking, not filtering)."""

    def _setup(self, conn):
        _add_note(conn, "other/note-b.md", title="B")
        _add_note(conn, "strake/note-a.md", title="A")
        # out-of-context triple inserted FIRST so, on a tie, it wins without boost
        _add_triple(conn, "other/note-b.md", "beta")
        _add_triple(conn, "strake/note-a.md", "alpha")
        conn.commit()

    def test_in_context_ranks_first(self, in_memory_db, monkeypatch):
        conn = in_memory_db
        self._setup(conn)
        _patch_search(monkeypatch, conn)

        results = search_triples(
            "tripletoken", top_k=5, embed_url="http://fake", context="strake",
        )

        assert results[0].note_path == "strake/note-a.md"
        # not filtered: the out-of-context triple still surfaces
        assert {r.note_path for r in results} == {"strake/note-a.md", "other/note-b.md"}

    def test_without_context_tie_stands(self, in_memory_db, monkeypatch):
        """Guard: the ordering above comes from the boost, not from luck."""
        conn = in_memory_db
        self._setup(conn)
        _patch_search(monkeypatch, conn)

        results = search_triples("tripletoken", top_k=5, embed_url="http://fake")

        assert results[0].note_path == "other/note-b.md"


class TestMemoryContextBoost:
    def _setup(self, conn):
        # out-of-context memory inserted FIRST so, on a tie, it wins without boost
        _add_memory(conn, "memtoken beta", workspace="work/nyk")
        _add_memory(conn, "memtoken alpha", workspace="home/projects/strake")
        conn.commit()

    def test_in_context_ranks_first(self, in_memory_db, monkeypatch):
        conn = in_memory_db
        self._setup(conn)
        _patch_memories(monkeypatch)

        results = search_memories(
            conn, query="memtoken", embed_url="http://fake", context="strake",
        )

        assert results[0].workspace == "home/projects/strake"
        assert {m.workspace for m in results} == {"home/projects/strake", "work/nyk"}

    def test_without_context_tie_stands(self, in_memory_db, monkeypatch):
        conn = in_memory_db
        self._setup(conn)
        _patch_memories(monkeypatch)

        results = search_memories(conn, query="memtoken", embed_url="http://fake")

        assert results[0].workspace == "work/nyk"

    def test_workspace_filter_unchanged(self, in_memory_db, monkeypatch):
        """workspace stays a hard filter; context does not resurrect filtered rows."""
        conn = in_memory_db
        self._setup(conn)
        _patch_memories(monkeypatch)

        results = search_memories(
            conn, query="memtoken", embed_url="http://fake",
            workspace="work/nyk", context="strake",
        )

        assert {m.workspace for m in results} == {"work/nyk"}


class TestBuildVaultContextPassthrough:
    def test_context_reaches_all_three_subretrievals(self, in_memory_db, monkeypatch):
        conn = in_memory_db
        seen: dict[str, str | None] = {}

        import neurostack.memories as memories_mod
        import neurostack.search as search_mod

        def fake_search_memories(conn, query=None, workspace=None, limit=10,
                                 embed_url=None, context=None, **kw):
            seen["memories"] = context
            return []

        def fake_search_triples(task, top_k=15, mode="hybrid", embed_url=None,
                                workspace=None, context=None, **kw):
            seen["triples"] = context
            return []

        def fake_hybrid_search(task, top_k=5, mode="hybrid", embed_url=None,
                               workspace=None, context=None, **kw):
            seen["summaries"] = context
            return []

        monkeypatch.setattr(memories_mod, "search_memories", fake_search_memories)
        monkeypatch.setattr(search_mod, "search_triples", fake_search_triples)
        monkeypatch.setattr(search_mod, "hybrid_search", fake_hybrid_search)

        result = build_vault_context(conn, task="t", context="strake")

        assert seen == {"memories": "strake", "triples": "strake", "summaries": "strake"}
        # return shape unchanged: no new top-level keys
        assert set(result) == {"task", "tokens_used", "workspace", "context"}
