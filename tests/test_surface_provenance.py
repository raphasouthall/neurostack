"""Tests for surface-provenance downgrades (issue #109).

vault_graph, vault_related, and vault_summary return notes the model may never
act on — a return is a 'primed' surface, not a use. These call sites used to
record tier='used' source='explicit' (the _record_note_usage defaults), which
polluted the strong signal #103 made observable. Acceptance: each tool's
returns leave only 'primed' rows with a distinct provenance source
('graph'/'related'/'summary'), never a 'used' row; with feedback enabled, the
surfacing is search-logged so a later read-after-surface infers the strong
'used'/'inferred' signal.

Style mirrors test_inferred_usage.py: real in-memory sqlite, monkeypatched
get_db, never MagicMock.
"""

import dataclasses
import json
import struct

DIM = 768


def _emb_blob(axis: int = 0) -> bytes:
    v = [0.0] * DIM
    v[axis] = 1.0
    return struct.pack(f"{DIM}f", *v)


def _add_note(conn, path, title="N", with_chunk=True, axis=0):
    conn.execute(
        "INSERT INTO notes (path, title, content_hash, updated_at) VALUES (?, ?, ?, ?)",
        (path, title, f"h_{path}", "2026-01-01"),
    )
    if with_chunk:
        conn.execute(
            "INSERT INTO chunks (note_path, heading_path, content, content_hash, "
            "position, embedding) VALUES (?, ?, ?, ?, ?, ?)",
            (path, "## H", "body text", f"hc_{path}", 0, _emb_blob(axis)),
        )
    conn.commit()


def _enable_feedback(monkeypatch):
    import neurostack.config as config_mod

    cfg = dataclasses.replace(config_mod.get_config(), feedback_enabled=True)
    monkeypatch.setattr(config_mod, "get_config", lambda: cfg)
    return cfg


def _usage_rows(conn):
    return conn.execute(
        "SELECT note_path, tier, source FROM note_usage ORDER BY usage_id"
    ).fetchall()


def _search_log(conn):
    return conn.execute(
        "SELECT query, shown_paths FROM search_log ORDER BY search_id"
    ).fetchall()


def _patch_schema_db(monkeypatch, conn):
    import neurostack.schema as schema_mod

    monkeypatch.setattr(schema_mod, "get_db", lambda path: conn)


class TestGraphSurfacing:
    def _seed(self, conn):
        _add_note(conn, "a.md", with_chunk=False)
        _add_note(conn, "b.md", with_chunk=False)
        conn.execute(
            "INSERT INTO graph_edges (source_path, target_path) VALUES ('a.md', 'b.md')"
        )
        conn.commit()

    def test_neighborhood_returns_are_primed_graph(self, in_memory_db):
        from neurostack.graph import get_neighborhood

        self._seed(in_memory_db)
        result = get_neighborhood("a.md", conn=in_memory_db)

        assert result is not None
        rows = _usage_rows(in_memory_db)
        assert {r["note_path"] for r in rows} == {"a.md", "b.md"}
        assert all((r["tier"], r["source"]) == ("primed", "graph") for r in rows)

    def test_feedback_enabled_logs_the_surfacing(self, in_memory_db, monkeypatch):
        from neurostack.graph import get_neighborhood

        self._seed(in_memory_db)
        _enable_feedback(monkeypatch)
        get_neighborhood("a.md", conn=in_memory_db)

        logged = _search_log(in_memory_db)
        assert len(logged) == 1
        assert logged[0]["query"] == "a.md"
        assert set(json.loads(logged[0]["shown_paths"])) == {"a.md", "b.md"}

    def test_feedback_disabled_logs_nothing(self, in_memory_db):
        from neurostack.graph import get_neighborhood

        self._seed(in_memory_db)
        get_neighborhood("a.md", conn=in_memory_db)

        assert _search_log(in_memory_db) == []


class TestRelatedSurfacing:
    def test_related_returns_are_primed_related(self, in_memory_db, monkeypatch):
        from neurostack.related import find_related

        _add_note(in_memory_db, "src.md", axis=0)
        _add_note(in_memory_db, "kin.md", axis=0)
        _patch_schema_db(monkeypatch, in_memory_db)

        results = find_related("src.md", top_k=5)

        assert [r["path"] for r in results] == ["kin.md"]
        rows = _usage_rows(in_memory_db)
        assert rows
        assert all((r["tier"], r["source"]) == ("primed", "related") for r in rows)
        assert {r["note_path"] for r in rows} == {"kin.md"}

    def test_feedback_enabled_logs_the_surfacing(self, in_memory_db, monkeypatch):
        from neurostack.related import find_related

        _add_note(in_memory_db, "src.md", axis=0)
        _add_note(in_memory_db, "kin.md", axis=0)
        _patch_schema_db(monkeypatch, in_memory_db)
        _enable_feedback(monkeypatch)

        find_related("src.md", top_k=5)

        logged = _search_log(in_memory_db)
        assert len(logged) == 1
        assert logged[0]["query"] == "src.md"
        assert json.loads(logged[0]["shown_paths"]) == ["kin.md"]

    def test_no_results_records_nothing(self, in_memory_db, monkeypatch):
        from neurostack.related import find_related

        _add_note(in_memory_db, "lonely.md", axis=0)
        _patch_schema_db(monkeypatch, in_memory_db)
        _enable_feedback(monkeypatch)

        assert find_related("lonely.md", top_k=5) == []
        assert _usage_rows(in_memory_db) == []
        assert _search_log(in_memory_db) == []


class TestSummarySurfacing:
    def test_summary_return_is_primed_summary(self, in_memory_db, monkeypatch):
        from neurostack.tools.search_tools import vault_summary

        _add_note(in_memory_db, "doc.md", with_chunk=False)
        in_memory_db.execute(
            "INSERT INTO summaries (note_path, summary_text, content_hash) "
            "VALUES ('doc.md', 'A summary.', 'h')"
        )
        in_memory_db.commit()
        _patch_schema_db(monkeypatch, in_memory_db)

        out = vault_summary("doc.md")

        assert out["path"] == "doc.md"
        rows = _usage_rows(in_memory_db)
        assert len(rows) == 1
        assert (rows[0]["tier"], rows[0]["source"]) == ("primed", "summary")

    def test_feedback_enabled_logs_the_surfacing(self, in_memory_db, monkeypatch):
        from neurostack.tools.search_tools import vault_summary

        _add_note(in_memory_db, "doc.md", with_chunk=False)
        in_memory_db.commit()
        _patch_schema_db(monkeypatch, in_memory_db)
        _enable_feedback(monkeypatch)

        vault_summary("doc.md")

        logged = _search_log(in_memory_db)
        assert len(logged) == 1
        assert logged[0]["query"] == "doc.md"
        assert json.loads(logged[0]["shown_paths"]) == ["doc.md"]


class TestNoStrongRowsFromSurfacing:
    def test_no_used_rows_anywhere(self, in_memory_db, monkeypatch):
        """The point of #109: none of the three surfaces may write tier='used'."""
        from neurostack.graph import get_neighborhood
        from neurostack.related import find_related
        from neurostack.tools.search_tools import vault_summary

        _add_note(in_memory_db, "a.md", axis=0)
        _add_note(in_memory_db, "b.md", axis=0)
        in_memory_db.execute(
            "INSERT INTO graph_edges (source_path, target_path) VALUES ('a.md', 'b.md')"
        )
        in_memory_db.commit()
        _patch_schema_db(monkeypatch, in_memory_db)

        get_neighborhood("a.md", conn=in_memory_db)
        find_related("a.md", top_k=5)
        vault_summary("a.md")

        used = in_memory_db.execute(
            "SELECT COUNT(*) FROM note_usage WHERE tier = 'used'"
        ).fetchone()[0]
        assert used == 0
