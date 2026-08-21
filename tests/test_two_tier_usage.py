"""Tests for the primed vs used two-tier activation signal (issue #95).

Synaptic tagging-and-capture: auto-RAG vault_context injections are 'primed'
(weak, capped below one real use, decaying), deliberate record_usage/reads stay
'used' (strong). Acceptance: a repeatedly-primed-never-used note must NOT
outrank a genuinely used one; stats expose both tiers.

Style mirrors test_prediction_errors.py: real in-memory sqlite,
monkeypatched get_db/get_embedding, never MagicMock.
"""

import sqlite3
import struct

import numpy as np
import pytest

from neurostack.context import build_vault_context
from neurostack.feedback import feedback_stats
from neurostack.search import (
    _record_note_usage,
    batch_hotness_scores,
    hotness_score,
    hybrid_search,
    search_triples,
)

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


def _add_usage(conn, path, tier, count=1, days_ago=0.0):
    conn.executemany(
        "INSERT INTO note_usage (note_path, tier, used_at) "
        "VALUES (?, ?, datetime('now', ?))",
        [(path, tier, f"-{days_ago} days")] * count,
    )
    conn.commit()


def _patch_search(monkeypatch, conn):
    import neurostack.search as search_mod

    monkeypatch.setattr(search_mod, "get_db", lambda path: conn)
    monkeypatch.setattr(search_mod, "get_embedding", lambda q, base_url=None: _query_emb())


class TestSchemaMigration:
    def test_v22_gets_tier_column_and_old_rows_become_used(self, tmp_path):
        from neurostack.schema import _run_migrations

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript("""
            CREATE TABLE schema_version (version INTEGER PRIMARY KEY);
            INSERT INTO schema_version VALUES (22);
            CREATE TABLE note_usage (
                usage_id INTEGER PRIMARY KEY AUTOINCREMENT,
                note_path TEXT NOT NULL,
                used_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            INSERT INTO note_usage (note_path) VALUES ('old.md');
        """)
        conn.commit()

        _run_migrations(conn)

        cols = {r[1] for r in conn.execute("PRAGMA table_info(note_usage)").fetchall()}
        assert "tier" in cols
        row = conn.execute("SELECT tier FROM note_usage WHERE note_path = 'old.md'").fetchone()
        assert row["tier"] == "used"
        version = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
        assert version >= 23


class TestRecordTier:
    def test_default_tier_is_used(self, in_memory_db):
        _record_note_usage(in_memory_db, ["a.md"])
        row = in_memory_db.execute("SELECT tier FROM note_usage").fetchone()
        assert row["tier"] == "used"

    def test_primed_tier_recorded(self, in_memory_db):
        _record_note_usage(in_memory_db, ["a.md"], tier="primed")
        row = in_memory_db.execute("SELECT tier FROM note_usage").fetchone()
        assert row["tier"] == "primed"


class TestTierWeightedHotness:
    def test_primed_never_outranks_used(self, in_memory_db):
        """Acceptance: capped primed contribution stays below one real use,
        regardless of prime volume."""
        conn = in_memory_db
        _add_usage(conn, "used-once.md", "used", count=1)
        _add_usage(conn, "primed-heavy.md", "primed", count=50)

        scores = batch_hotness_scores(conn, ["used-once.md", "primed-heavy.md"])

        assert scores["primed-heavy.md"] > 0.0  # priming is a real, weak signal
        assert scores["used-once.md"] > scores["primed-heavy.md"]

    def test_primed_contribution_capped(self, in_memory_db):
        conn = in_memory_db
        _add_usage(conn, "five.md", "primed", count=5)     # 5 * 0.1 = cap 0.5
        _add_usage(conn, "fifty.md", "primed", count=50)   # capped at 0.5 too

        scores = batch_hotness_scores(conn, ["five.md", "fifty.md"])

        assert scores["five.md"] == pytest.approx(scores["fifty.md"])

    def test_stale_primes_decay_to_nothing(self, in_memory_db):
        """Primed events older than the window contribute nothing — the note is
        omitted entirely (hotness 0.0), while an equally old 'used' event survives."""
        conn = in_memory_db
        _add_usage(conn, "stale-primed.md", "primed", count=20, days_ago=30)
        _add_usage(conn, "old-used.md", "used", count=1, days_ago=30)

        scores = batch_hotness_scores(conn, ["stale-primed.md", "old-used.md"])

        assert "stale-primed.md" not in scores
        assert hotness_score(conn, "stale-primed.md") == 0.0
        assert scores["old-used.md"] > 0.0

    def test_primed_adds_on_top_of_used(self, in_memory_db):
        conn = in_memory_db
        _add_usage(conn, "plain.md", "used", count=2)
        _add_usage(conn, "boosted.md", "used", count=2)
        _add_usage(conn, "boosted.md", "primed", count=3)

        scores = batch_hotness_scores(conn, ["plain.md", "boosted.md"])

        assert scores["boosted.md"] > scores["plain.md"]

    def test_ranking_through_hybrid_search(self, in_memory_db, monkeypatch):
        """End-to-end acceptance: equal-content notes, one primed 50x, one used
        once — the used note ranks first via the hotness blend."""
        conn = in_memory_db
        _add_note(conn, "primed-heavy.md")   # inserted first: wins ties without hotness
        _add_note(conn, "used-once.md")
        _add_usage(conn, "primed-heavy.md", "primed", count=50)
        _add_usage(conn, "used-once.md", "used", count=1)
        _patch_search(monkeypatch, conn)

        results = hybrid_search("usetoken", top_k=5, embed_url="http://fake", record=False)

        assert results[0].note_path == "used-once.md"
        assert {r.note_path for r in results} == {"used-once.md", "primed-heavy.md"}


class TestContextPrimes:
    def _setup(self, conn):
        _add_note(conn, "research/alpha.md", title="Alpha")
        conn.execute(
            "INSERT INTO triples (note_path, subject, predicate, object, "
            "triple_text, embedding) VALUES (?, ?, ?, ?, ?, ?)",
            ("research/alpha.md", "usetoken", "relates to", "thing",
             "usetoken thing", _emb_blob()),
        )
        conn.commit()

    def test_returned_paths_logged_primed_only(self, in_memory_db, monkeypatch):
        """vault_context logs every returned note path as 'primed'; its
        sub-retrievals must not write strong 'used' events."""
        conn = in_memory_db
        self._setup(conn)
        _patch_search(monkeypatch, conn)
        import neurostack.embedder as embedder_mod
        monkeypatch.setattr(
            embedder_mod, "get_embedding", lambda q, base_url=None: _query_emb()
        )

        result = build_vault_context(conn, task="usetoken thing")

        assert result["context"].get("summaries") or result["context"].get("triples")
        rows = conn.execute("SELECT note_path, tier FROM note_usage").fetchall()
        assert rows, "returned paths must be logged as primed events"
        assert {r["tier"] for r in rows} == {"primed"}
        assert "research/alpha.md" in {r["note_path"] for r in rows}

    def test_feedback_enabled_logs_search(self, in_memory_db, monkeypatch):
        """Tag-and-capture: with feedback on, the surfacing is search-logged so a
        later deliberate use attributes back to the task."""
        import dataclasses

        import neurostack.config as config_mod
        import neurostack.search as search_mod

        conn = in_memory_db
        self._setup(conn)
        _patch_search(monkeypatch, conn)
        import neurostack.embedder as embedder_mod
        monkeypatch.setattr(
            embedder_mod, "get_embedding", lambda q, base_url=None: _query_emb()
        )
        cfg = dataclasses.replace(config_mod.get_config(), feedback_enabled=True)
        monkeypatch.setattr(config_mod, "get_config", lambda: cfg)
        monkeypatch.setattr(search_mod, "get_config", lambda: cfg)

        build_vault_context(conn, task="usetoken thing")

        logged = conn.execute("SELECT query FROM search_log").fetchall()
        assert any(r["query"] == "usetoken thing" for r in logged)


class TestSearchTriplesRecordGate:
    def test_record_false_writes_nothing(self, in_memory_db, monkeypatch):
        conn = in_memory_db
        _add_note(conn, "a.md", with_chunk=False)
        conn.execute(
            "INSERT INTO triples (note_path, subject, predicate, object, "
            "triple_text, embedding) VALUES (?, ?, ?, ?, ?, ?)",
            ("a.md", "usetoken", "p", "o", "usetoken o", _emb_blob()),
        )
        conn.commit()
        _patch_search(monkeypatch, conn)

        results = search_triples("usetoken", top_k=5, embed_url="http://fake", record=False)

        assert results
        assert conn.execute("SELECT COUNT(*) FROM note_usage").fetchone()[0] == 0

    def test_record_true_writes_primed(self, in_memory_db, monkeypatch):
        conn = in_memory_db
        _add_note(conn, "a.md", with_chunk=False)
        conn.execute(
            "INSERT INTO triples (note_path, subject, predicate, object, "
            "triple_text, embedding) VALUES (?, ?, ?, ?, ?, ?)",
            ("a.md", "usetoken", "p", "o", "usetoken o", _emb_blob()),
        )
        conn.commit()
        _patch_search(monkeypatch, conn)

        search_triples("usetoken", top_k=5, embed_url="http://fake")

        rows = conn.execute("SELECT tier, source FROM note_usage").fetchall()
        # Returning a triple's note is surfacing, not use (issue #103).
        assert rows and all(r["tier"] == "primed" for r in rows)
        assert all(r["source"] == "search" for r in rows)


class TestFeedbackStatsTiers:
    def test_stats_expose_both_tiers(self, in_memory_db):
        conn = in_memory_db
        _add_usage(conn, "a.md", "used", count=2)
        _add_usage(conn, "b.md", "primed", count=3)
        _add_usage(conn, "c.md", "primed", count=4, days_ago=400)  # out of window

        stats = feedback_stats(conn)

        assert stats["used_events"] == 2
        assert stats["primed_events"] == 7
        assert stats["primed_in_window"] == 3
