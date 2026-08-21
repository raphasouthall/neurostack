"""Tests for server-side usage capture (issue #103).

The strong 'used' signal is now OBSERVED, not DECLARED: opening a note the vault
just surfaced (read-after-surface) is inferred server-side as a deliberate use,
while merely returning a note from a search is downgraded to the weak 'primed'
tier. Acceptance: a search-then-read leaves a 'used'/'inferred' row plus a
feedback event with zero explicit calls; a search-and-ignore leaves only primed
rows; a cold read leaves nothing.

Style mirrors test_two_tier_usage.py: real in-memory sqlite, monkeypatched
get_db/get_embedding, never MagicMock.
"""

import dataclasses
import sqlite3
import struct

import numpy as np

from neurostack.feedback import capture_read, feedback_stats, log_search, record_use
from neurostack.search import hybrid_search

DIM = 768


def _emb_blob() -> bytes:
    v = [0.0] * DIM
    v[0] = 1.0
    return struct.pack(f"{DIM}f", *v)


def _query_emb() -> np.ndarray:
    q = np.zeros(DIM, dtype=np.float32)
    q[0] = 1.0
    return q


def _add_note(conn, path, title="N", with_chunk=True):
    conn.execute(
        "INSERT INTO notes (path, title, content_hash, updated_at) VALUES (?, ?, ?, ?)",
        (path, title, f"h_{path}", "2026-01-01"),
    )
    if with_chunk:
        conn.execute(
            "INSERT INTO chunks (note_path, heading_path, content, content_hash, "
            "position, embedding) VALUES (?, ?, ?, ?, ?, ?)",
            (path, "## H", "usetoken body text", f"hc_{path}", 0, _emb_blob()),
        )
    conn.commit()


def _patch_search(monkeypatch, conn):
    import neurostack.search as search_mod

    monkeypatch.setattr(search_mod, "get_db", lambda path: conn)
    monkeypatch.setattr(search_mod, "get_embedding", lambda q, base_url=None: _query_emb())


def _enable_feedback(monkeypatch, **overrides):
    """Turn capture on for this test — it is opt-in and off by default."""
    import neurostack.config as config_mod

    cfg = dataclasses.replace(
        config_mod.get_config(), feedback_enabled=True, **overrides
    )
    monkeypatch.setattr(config_mod, "get_config", lambda: cfg)
    return cfg


def _usage_rows(conn):
    return conn.execute(
        "SELECT note_path, tier, source FROM note_usage ORDER BY usage_id"
    ).fetchall()


def _feedback_count(conn):
    return conn.execute("SELECT COUNT(*) FROM search_feedback").fetchone()[0]


class TestSchemaMigration:
    def test_v23_gets_source_column_defaulting_explicit(self):
        from neurostack.schema import _run_migrations

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript("""
            CREATE TABLE schema_version (version INTEGER PRIMARY KEY);
            INSERT INTO schema_version VALUES (23);
            CREATE TABLE note_usage (
                usage_id INTEGER PRIMARY KEY AUTOINCREMENT,
                note_path TEXT NOT NULL,
                used_at TEXT NOT NULL DEFAULT (datetime('now')),
                tier TEXT NOT NULL DEFAULT 'used'
            );
            INSERT INTO note_usage (note_path) VALUES ('old.md');
        """)
        conn.commit()

        _run_migrations(conn)

        cols = {r[1] for r in conn.execute("PRAGMA table_info(note_usage)").fetchall()}
        assert "source" in cols
        row = conn.execute(
            "SELECT source FROM note_usage WHERE note_path = 'old.md'"
        ).fetchone()
        assert row["source"] == "explicit"
        version = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
        assert version >= 24

    def test_partial_db_without_note_usage_gets_the_table(self):
        """The v23 gotcha: fixture DBs can lack note_usage entirely, so the
        migration must create it rather than ALTER a missing table."""
        from neurostack.schema import _run_migrations

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript("""
            CREATE TABLE schema_version (version INTEGER PRIMARY KEY);
            INSERT INTO schema_version VALUES (23);
        """)
        conn.commit()

        _run_migrations(conn)

        cols = {r[1] for r in conn.execute("PRAGMA table_info(note_usage)").fetchall()}
        assert cols == {"usage_id", "note_path", "used_at", "tier", "source"}
        conn.execute("INSERT INTO note_usage (note_path) VALUES ('n.md')")
        row = conn.execute("SELECT tier, source FROM note_usage").fetchone()
        assert (row["tier"], row["source"]) == ("used", "explicit")


class TestReadAfterSurface:
    def test_read_of_surfaced_note_infers_use(self, in_memory_db, monkeypatch):
        """Acceptance: search then read leaves the strong signal with zero
        explicit record_usage calls."""
        conn = in_memory_db
        _enable_feedback(monkeypatch)
        log_search(conn, "retry config", ["research/foo.md", "research/bar.md"])

        capture_read("research/foo.md", conn=conn)

        rows = _usage_rows(conn)
        assert len(rows) == 1
        assert (rows[0]["note_path"], rows[0]["tier"], rows[0]["source"]) == (
            "research/foo.md", "used", "inferred",
        )
        row = conn.execute(
            "SELECT query, chosen_path, rank FROM search_feedback"
        ).fetchone()
        assert (row["query"], row["chosen_path"], row["rank"]) == (
            "retry config", "research/foo.md", 1,
        )

    def test_cold_read_records_nothing(self, in_memory_db, monkeypatch):
        """No search surfaced it, so there is nothing to attribute and no
        evidence retrieval earned the read."""
        conn = in_memory_db
        _enable_feedback(monkeypatch)
        log_search(conn, "retry config", ["research/foo.md"])

        capture_read("work/unrelated.md", conn=conn)

        assert _usage_rows(conn) == []
        assert _feedback_count(conn) == 0

    def test_read_outside_window_records_nothing(self, in_memory_db, monkeypatch):
        conn = in_memory_db
        _enable_feedback(monkeypatch, feedback_window_seconds=1800.0)
        log_search(conn, "retry config", ["research/foo.md"])
        conn.execute(
            "UPDATE search_log SET searched_at = datetime('now', '-2 hours')"
        )
        conn.commit()

        capture_read("research/foo.md", conn=conn)

        assert _usage_rows(conn) == []
        assert _feedback_count(conn) == 0

    def test_disabled_feedback_records_nothing(self, in_memory_db):
        """Capture is opt-in; a default deploy writes nothing on read."""
        conn = in_memory_db
        log_search(conn, "retry config", ["research/foo.md"])

        capture_read("research/foo.md", conn=conn)

        assert _usage_rows(conn) == []
        assert _feedback_count(conn) == 0

    def test_repeated_reopens_each_count(self, in_memory_db, monkeypatch):
        """Parity with explicit record_usage: each open is a use event, while
        attribution stays deduped per (query, path) inside the window."""
        conn = in_memory_db
        _enable_feedback(monkeypatch)
        log_search(conn, "retry config", ["research/foo.md"])

        capture_read("research/foo.md", conn=conn)
        capture_read("research/foo.md", conn=conn)

        assert len(_usage_rows(conn)) == 2
        assert _feedback_count(conn) == 1

    def test_broken_connection_does_not_raise(self, in_memory_db, monkeypatch):
        conn = in_memory_db
        _enable_feedback(monkeypatch)
        log_search(conn, "retry config", ["research/foo.md"])
        conn.close()

        capture_read("research/foo.md", conn=conn)  # must not raise


class TestSearchAndIgnore:
    def test_hybrid_search_returns_are_primed_only(self, in_memory_db, monkeypatch):
        """Acceptance: surfacing without a read leaves no strong signal."""
        conn = in_memory_db
        _add_note(conn, "research/foo.md")
        _add_note(conn, "research/bar.md")
        _patch_search(monkeypatch, conn)

        results = hybrid_search("usetoken", top_k=5, embed_url="http://fake")

        assert results
        rows = _usage_rows(conn)
        assert rows
        assert all((r["tier"], r["source"]) == ("primed", "search") for r in rows)
        assert conn.execute(
            "SELECT COUNT(*) FROM note_usage WHERE tier = 'used'"
        ).fetchone()[0] == 0


class TestRecordUse:
    def test_records_explicit_tier_and_attributes(self, in_memory_db, monkeypatch):
        """The shared MCP + CLI path: strong row plus attribution."""
        conn = in_memory_db
        _enable_feedback(monkeypatch)
        log_search(conn, "retry config", ["research/foo.md", "research/bar.md"])

        assert record_use(["research/bar.md"], conn=conn) == 1

        rows = _usage_rows(conn)
        assert len(rows) == 1
        assert (rows[0]["note_path"], rows[0]["tier"], rows[0]["source"]) == (
            "research/bar.md", "used", "explicit",
        )
        row = conn.execute("SELECT chosen_path, rank FROM search_feedback").fetchone()
        assert (row["chosen_path"], row["rank"]) == ("research/bar.md", 2)

    def test_records_without_feedback_enabled(self, in_memory_db):
        """Hotness has always counted declared uses; only attribution is opt-in."""
        conn = in_memory_db

        assert record_use(["research/foo.md", "research/foo.md"], conn=conn) == 1

        rows = _usage_rows(conn)
        assert len(rows) == 1
        assert (rows[0]["tier"], rows[0]["source"]) == ("used", "explicit")
        assert _feedback_count(conn) == 0

    def test_empty_paths_is_a_noop(self, in_memory_db):
        assert record_use([], conn=in_memory_db) == 0
        assert _usage_rows(in_memory_db) == []


class TestFeedbackStatsProvenance:
    def test_used_events_split_by_source(self, in_memory_db, monkeypatch):
        conn = in_memory_db
        _enable_feedback(monkeypatch)
        record_use(["research/foo.md"], conn=conn)
        log_search(conn, "retry config", ["research/bar.md"])
        capture_read("research/bar.md", conn=conn)

        stats = feedback_stats(conn)

        assert stats["used_events"] == 2
        assert stats["used_explicit"] == 1
        assert stats["used_inferred"] == 1
