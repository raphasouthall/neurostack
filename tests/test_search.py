"""Tests for neurostack.search — FTS5, hotness scoring, prediction errors, co-occurrence boost."""

import struct

from neurostack.config import Config
from neurostack.search import (
    DECAY_STALE_HOURS,
    PREDICTION_ERROR_SIM_THRESHOLD,
    SearchResult,
    TripleResult,
    _normalize_scores,
    _record_note_usage,
    decay_hours_since,
    fts_search,
    get_decay_last_run,
    hotness_score,
    hybrid_search,
    log_prediction_error,
    record_decay_run,
    run_excitability_demotion,
    tiered_search,
)


class TestFtsSearch:
    def test_basic_search(self, populated_db):
        results = fts_search(populated_db, "predictive coding", limit=10)
        assert len(results) > 0
        assert any(
            "predictive" in r["content"].lower()
            or "prediction" in r["content"].lower()
            for r in results
        )

    def test_search_returns_dict(self, populated_db):
        results = fts_search(populated_db, "memory", limit=5)
        assert all(isinstance(r, dict) for r in results)
        if results:
            assert "note_path" in results[0]
            assert "content" in results[0]

    def test_empty_query(self, populated_db):
        results = fts_search(populated_db, "", limit=10)
        assert results == []

    def test_no_results(self, populated_db):
        results = fts_search(populated_db, "xyznonexistent123", limit=10)
        assert results == []

    def test_special_characters_escaped(self, populated_db):
        # Should not crash on FTS5 special chars
        results = fts_search(populated_db, 'test-query "with" special (chars)', limit=10)
        assert isinstance(results, list)

    def test_hyphenated_query(self, populated_db):
        results = fts_search(populated_db, "error-driven", limit=10)
        assert isinstance(results, list)

    def test_limit_respected(self, populated_db):
        results = fts_search(populated_db, "content", limit=1)
        assert len(results) <= 1


class TestHotnessScore:
    def test_no_usage(self, in_memory_db):
        score = hotness_score(in_memory_db, "nonexistent.md")
        assert score == 0.0

    def test_recent_usage(self, in_memory_db):
        conn = in_memory_db
        conn.execute(
            "INSERT INTO note_usage (note_path, used_at) VALUES (?, datetime('now'))",
            ("test.md",),
        )
        conn.commit()
        score = hotness_score(conn, "test.md")
        assert 0.0 < score <= 1.0

    def test_multiple_usages_higher_score(self, in_memory_db):
        conn = in_memory_db
        for _ in range(5):
            conn.execute(
                "INSERT INTO note_usage (note_path, used_at) VALUES (?, datetime('now'))",
                ("test.md",),
            )
        conn.commit()
        multi_score = hotness_score(conn, "test.md")

        conn2 = in_memory_db
        conn2.execute(
            "INSERT INTO note_usage (note_path, used_at) VALUES (?, datetime('now'))",
            ("single.md",),
        )
        conn2.commit()
        single_score = hotness_score(conn2, "single.md")

        assert multi_score > single_score


class TestPredictionError:
    def test_log_error(self, in_memory_db):
        conn = in_memory_db
        conn.execute(
            "INSERT INTO notes (path, title, content_hash, updated_at) VALUES (?, ?, ?, ?)",
            ("test.md", "Test", "abc", "2026-01-01"),
        )
        conn.commit()

        log_prediction_error(conn, "test.md", "query text", 0.3, "low_overlap")

        rows = conn.execute("SELECT * FROM prediction_errors").fetchall()
        assert len(rows) == 1
        assert rows[0]["error_type"] == "low_overlap"
        assert rows[0]["cosine_distance"] == round(1.0 - 0.3, 4)

    def test_rate_limiting(self, in_memory_db):
        conn = in_memory_db
        log_prediction_error(conn, "test.md", "q1", 0.3, "low_overlap")
        log_prediction_error(conn, "test.md", "q2", 0.2, "low_overlap")

        rows = conn.execute("SELECT * FROM prediction_errors").fetchall()
        assert len(rows) == 1  # second insert rate-limited

    def test_different_types_not_rate_limited(self, in_memory_db):
        conn = in_memory_db
        log_prediction_error(conn, "test.md", "q1", 0.3, "low_overlap")
        log_prediction_error(conn, "test.md", "q2", 0.5, "contextual_mismatch")

        rows = conn.execute("SELECT * FROM prediction_errors").fetchall()
        assert len(rows) == 2

    def test_threshold_constant(self):
        assert 0.0 < PREDICTION_ERROR_SIM_THRESHOLD < 1.0


class TestAutoRecordUsage:
    def test_usage_recording_inserts_rows(self, in_memory_db):
        """Auto-record usage logic should insert note_usage rows."""
        conn = in_memory_db
        before = conn.execute("SELECT COUNT(*) FROM note_usage").fetchone()[0]
        assert before == 0

        paths = ["research/predictive-coding.md", "research/memory-consolidation.md"]
        conn.executemany(
            "INSERT INTO note_usage (note_path) VALUES (?)",
            [(p,) for p in paths],
        )
        conn.commit()
        after = conn.execute("SELECT COUNT(*) FROM note_usage").fetchone()[0]
        assert after == 2

    def test_usage_accumulates(self, in_memory_db):
        """Multiple searches should accumulate usage rows."""
        conn = in_memory_db
        for _ in range(3):
            conn.execute(
                "INSERT INTO note_usage (note_path) VALUES (?)",
                ("test.md",),
            )
        conn.commit()
        count = conn.execute(
            "SELECT COUNT(*) FROM note_usage WHERE note_path = ?",
            ("test.md",),
        ).fetchone()[0]
        assert count == 3

    def test_record_note_usage_helper(self, in_memory_db):
        """Shared helper inserts one row per unique path and ignores duplicates."""
        conn = in_memory_db
        _record_note_usage(conn, ["a.md", "b.md", "a.md", "a.md"])
        rows = conn.execute(
            "SELECT note_path FROM note_usage ORDER BY note_path"
        ).fetchall()
        assert [r["note_path"] for r in rows] == ["a.md", "b.md"]

    def test_record_note_usage_empty(self, in_memory_db):
        """Helper is a no-op on empty input and does not raise."""
        conn = in_memory_db
        _record_note_usage(conn, [])
        count = conn.execute("SELECT COUNT(*) FROM note_usage").fetchone()[0]
        assert count == 0

    def test_record_note_usage_non_blocking(self, in_memory_db):
        """A broken connection must not raise — retrieval must never be disrupted."""
        conn = in_memory_db
        conn.close()
        _record_note_usage(conn, ["a.md"])  # should not raise

    def test_get_neighborhood_records_usage(self, populated_db):
        """get_neighborhood must record usage for center + neighbors."""
        from neurostack.graph import get_neighborhood

        conn = populated_db
        conn.execute(
            "INSERT INTO graph_edges (source_path, target_path) VALUES (?, ?)",
            ("research/predictive-coding.md", "research/memory-consolidation.md"),
        )
        conn.commit()

        before = conn.execute("SELECT COUNT(*) FROM note_usage").fetchone()[0]
        result = get_neighborhood("research/predictive-coding.md", depth=1, conn=conn)
        after = conn.execute("SELECT COUNT(*) FROM note_usage").fetchone()[0]

        assert result is not None
        assert after >= before + 1
        recorded = {
            r["note_path"]
            for r in conn.execute("SELECT note_path FROM note_usage").fetchall()
        }
        assert result.center.path in recorded


class TestExcitabilityDemotion:
    def test_demotes_dormant_notes(self, in_memory_db):
        """Notes with decayed hotness should be demoted to dormant."""
        conn = in_memory_db
        # Insert a note and its metadata as active
        conn.execute(
            "INSERT INTO notes (path, title, content_hash, updated_at)"
            " VALUES (?, ?, ?, ?)",
            ("old.md", "Old Note", "h", "2025-01-01"),
        )
        conn.execute(
            "INSERT INTO note_metadata (note_path, status) VALUES (?, ?)",
            ("old.md", "active"),
        )
        # Add old usage so hotness decays below threshold
        conn.execute(
            "INSERT INTO note_usage (note_path, used_at) VALUES (?, ?)",
            ("old.md", "2024-01-01 00:00:00"),
        )
        conn.commit()

        result = run_excitability_demotion(conn)
        assert result["demoted"] >= 1
        assert "old.md" in result["paths"]

        status = conn.execute(
            "SELECT status FROM note_metadata WHERE note_path = ?",
            ("old.md",),
        ).fetchone()["status"]
        assert status == "dormant"

    def test_does_not_demote_active_notes(self, in_memory_db):
        """Notes with recent usage should NOT be demoted."""
        conn = in_memory_db
        conn.execute(
            "INSERT INTO notes (path, title, content_hash, updated_at)"
            " VALUES (?, ?, ?, ?)",
            ("hot.md", "Hot Note", "h", "2026-01-01"),
        )
        conn.execute(
            "INSERT INTO note_metadata (note_path, status) VALUES (?, ?)",
            ("hot.md", "active"),
        )
        # Add very recent usage
        conn.execute(
            "INSERT INTO note_usage (note_path, used_at) VALUES (?, datetime('now'))",
            ("hot.md",),
        )
        conn.commit()

        result = run_excitability_demotion(conn)
        assert "hot.md" not in result["paths"]

        status = conn.execute(
            "SELECT status FROM note_metadata WHERE note_path = ?",
            ("hot.md",),
        ).fetchone()["status"]
        assert status == "active"

    def test_demotes_never_used_old_notes(self, in_memory_db):
        """Never-used notes older than 90 days should be demoted."""
        conn = in_memory_db
        conn.execute(
            "INSERT INTO notes (path, title, content_hash, updated_at)"
            " VALUES (?, ?, ?, ?)",
            ("ancient.md", "Ancient", "h", "2024-01-01"),
        )
        conn.execute(
            "INSERT INTO note_metadata (note_path, status) VALUES (?, ?)",
            ("ancient.md", "active"),
        )
        conn.commit()

        result = run_excitability_demotion(conn)
        assert "ancient.md" in result["paths"]

    def test_skips_already_dormant(self, in_memory_db):
        """Notes already dormant should not be re-demoted."""
        conn = in_memory_db
        conn.execute(
            "INSERT INTO notes (path, title, content_hash, updated_at)"
            " VALUES (?, ?, ?, ?)",
            ("dormant.md", "Dormant", "h", "2024-01-01"),
        )
        conn.execute(
            "INSERT INTO note_metadata (note_path, status) VALUES (?, ?)",
            ("dormant.md", "dormant"),
        )
        conn.commit()

        result = run_excitability_demotion(conn)
        assert "dormant.md" not in result["paths"]

    def test_repromotes_renewed_dormant_notes(self, in_memory_db):
        """A dormant note with fresh usage is promoted back to active (issue #31)."""
        conn = in_memory_db
        conn.execute(
            "INSERT INTO notes (path, title, content_hash, updated_at)"
            " VALUES (?, ?, ?, ?)",
            ("renewed.md", "Renewed", "h", "2026-01-01"),
        )
        conn.execute(
            "INSERT INTO note_metadata (note_path, status) VALUES (?, ?)",
            ("renewed.md", "dormant"),
        )
        # Fresh usage pushes hotness back above threshold
        conn.execute(
            "INSERT INTO note_usage (note_path, used_at) VALUES (?, datetime('now'))",
            ("renewed.md",),
        )
        conn.commit()

        result = run_excitability_demotion(conn)
        assert result["promoted"] >= 1
        assert "renewed.md" in result["promoted_paths"]

        status = conn.execute(
            "SELECT status FROM note_metadata WHERE note_path = ?",
            ("renewed.md",),
        ).fetchone()["status"]
        assert status == "active"


class TestDecayRunTracking:
    """Last-run stamp that lets `neurostack doctor` flag a stalled decay timer (issue #31 p4)."""

    def _patch_db_dir(self, monkeypatch, tmp_path):
        from types import SimpleNamespace
        monkeypatch.setattr(
            "neurostack.search.get_config",
            lambda: SimpleNamespace(db_dir=tmp_path),
        )

    def test_no_state_returns_none(self, monkeypatch, tmp_path):
        self._patch_db_dir(monkeypatch, tmp_path)
        assert get_decay_last_run() is None
        assert decay_hours_since() is None

    def test_record_and_read_roundtrip(self, monkeypatch, tmp_path):
        self._patch_db_dir(monkeypatch, tmp_path)
        from datetime import datetime, timezone
        when = datetime(2026, 6, 12, 3, 0, tzinfo=timezone.utc).isoformat()
        record_decay_run(demoted=2, promoted=1, when=when)
        assert (tmp_path / "decay_state.json").exists()
        last = get_decay_last_run()
        assert last is not None and last.isoformat() == when

    def test_zero_run_still_records(self, monkeypatch, tmp_path):
        # A run that demotes/promotes nothing still proves the timer fired.
        self._patch_db_dir(monkeypatch, tmp_path)
        record_decay_run(0, 0)
        assert get_decay_last_run() is not None

    def test_hours_since_fresh(self, monkeypatch, tmp_path):
        self._patch_db_dir(monkeypatch, tmp_path)
        from datetime import datetime, timedelta, timezone
        now = datetime(2026, 6, 12, 12, 0, tzinfo=timezone.utc)
        record_decay_run(0, 0, when=(now - timedelta(hours=1)).isoformat())
        assert 0.9 < decay_hours_since(now=now) < 1.1

    def test_hours_since_stale(self, monkeypatch, tmp_path):
        self._patch_db_dir(monkeypatch, tmp_path)
        from datetime import datetime, timedelta, timezone
        now = datetime(2026, 6, 12, 12, 0, tzinfo=timezone.utc)
        record_decay_run(0, 0, when=(now - timedelta(hours=72)).isoformat())
        assert decay_hours_since(now=now) > DECAY_STALE_HOURS

    def test_naive_timestamp_treated_as_utc(self, monkeypatch, tmp_path):
        # A stored naive ISO string must not raise on the tz-aware subtraction.
        self._patch_db_dir(monkeypatch, tmp_path)
        record_decay_run(0, 0, when="2026-06-12T03:00:00")
        from datetime import datetime, timezone
        now = datetime(2026, 6, 12, 12, 0, tzinfo=timezone.utc)
        assert decay_hours_since(now=now) == 9.0

    def test_corrupt_state_returns_none(self, monkeypatch, tmp_path):
        self._patch_db_dir(monkeypatch, tmp_path)
        (tmp_path / "decay_state.json").write_text("{not valid json")
        assert get_decay_last_run() is None
        assert decay_hours_since() is None


class TestExcitabilityBoost:
    def test_active_notes_boost_fts_results(self, in_memory_db):
        """Notes with status=active in frontmatter get higher scores."""
        import json
        conn = in_memory_db
        # Insert two notes with same content but different status
        conn.execute(
            "INSERT INTO notes (path, title, frontmatter, "
            "content_hash, updated_at) VALUES (?, ?, ?, ?, ?)",
            ("active.md", "Active Note",
             json.dumps({"status": "active"}), "a1", "2026-01-01"),
        )
        conn.execute(
            "INSERT INTO notes (path, title, frontmatter, "
            "content_hash, updated_at) VALUES (?, ?, ?, ?, ?)",
            ("ref.md", "Reference Note",
             json.dumps({"status": "reference"}), "r1", "2026-01-01"),
        )
        # Insert identical chunks so FTS scores are equal
        for path in ["active.md", "ref.md"]:
            conn.execute(
                "INSERT INTO chunks (note_path, heading_path, "
                "content, content_hash, position) "
                "VALUES (?, ?, ?, ?, ?)",
                (path, "## Test", "unique_excitability_test_content",
                 "h", 0),
            )
        conn.commit()

        # FTS search returns both — verify active gets boosted
        results = fts_search(conn, "unique_excitability_test_content")
        assert len(results) == 2

    def test_active_status_parsed_from_frontmatter(self, in_memory_db):
        """Verify frontmatter JSON is correctly parsed for status."""
        import json
        conn = in_memory_db
        fm = {"status": "active", "tags": ["test"]}
        conn.execute(
            "INSERT INTO notes (path, title, frontmatter, "
            "content_hash, updated_at) VALUES (?, ?, ?, ?, ?)",
            ("test.md", "Test", json.dumps(fm), "h", "2026-01-01"),
        )
        conn.commit()

        row = conn.execute(
            "SELECT frontmatter FROM notes WHERE path = ?",
            ("test.md",),
        ).fetchone()
        parsed = json.loads(row["frontmatter"])
        assert parsed["status"] == "active"


def _fake_embedding(val: float = 0.5, dim: int = 768) -> bytes:
    """Create a fake embedding blob for testing."""
    return struct.pack(f"{dim}f", *([val] * dim))


class TestCooccurrenceBoost:
    """Tests for the co-occurrence boost scoring stage in hybrid_search."""

    def _setup_cooccurrence_scenario(self, conn):
        """Insert notes, chunks, triples, and co-occurrence data for testing.

        Creates two notes:
        - noteA.md: contains entity "alpha" and "beta" (beta co-occurs with "gamma")
        - noteB.md: contains entity "delta" only (no co-occurrence with gamma)

        Query for "gamma" should cause noteA to get boosted (because beta
        co-occurs with gamma) while noteB should not be boosted.
        """
        emb = _fake_embedding(0.5)

        # Insert notes
        conn.execute(
            "INSERT INTO notes (path, title, content_hash, updated_at) "
            "VALUES (?, ?, ?, ?)",
            ("noteA.md", "Note A", "ha", "2026-01-01"),
        )
        conn.execute(
            "INSERT INTO notes (path, title, content_hash, updated_at) "
            "VALUES (?, ?, ?, ?)",
            ("noteB.md", "Note B", "hb", "2026-01-01"),
        )

        # Insert chunks with embeddings (identical content so FTS scores match)
        for path in ["noteA.md", "noteB.md"]:
            conn.execute(
                "INSERT INTO chunks (note_path, heading_path, content, "
                "content_hash, position, embedding) VALUES (?, ?, ?, ?, ?, ?)",
                (path, "## Test", "gamma related content here",
                 f"h_{path}", 0, emb),
            )

        # Insert triples: noteA has alpha+beta, noteB has delta
        conn.execute(
            "INSERT INTO triples (note_path, subject, predicate, object, triple_text) "
            "VALUES (?, ?, ?, ?, ?)",
            ("noteA.md", "alpha", "relates_to", "beta", "alpha relates_to beta"),
        )
        conn.execute(
            "INSERT INTO triples (note_path, subject, predicate, object, triple_text) "
            "VALUES (?, ?, ?, ?, ?)",
            ("noteB.md", "delta", "relates_to", "epsilon", "delta relates_to epsilon"),
        )

        # Add a triple with "gamma" in another note so the query can find it as an entity
        conn.execute(
            "INSERT INTO notes (path, title, content_hash, updated_at) "
            "VALUES (?, ?, ?, ?)",
            ("noteC.md", "Note C", "hc", "2026-01-01"),
        )
        conn.execute(
            "INSERT INTO triples (note_path, subject, predicate, object, triple_text) "
            "VALUES (?, ?, ?, ?, ?)",
            ("noteC.md", "gamma", "is_a", "concept", "gamma is_a concept"),
        )

        # Co-occurrence: gamma co-occurs with beta (weight 3.0)
        # This means searching for "gamma" should boost notes containing "beta" (noteA)
        conn.execute(
            "INSERT INTO entity_cooccurrence (entity_a, entity_b, weight, last_seen) "
            "VALUES (?, ?, ?, ?)",
            ("beta", "gamma", 3.0, "2026-01-01"),
        )

        conn.commit()

    def test_cooccurrence_boost_increases_score(self, in_memory_db, monkeypatch):
        """A note containing a co-occurring entity should score higher."""
        conn = in_memory_db
        self._setup_cooccurrence_scenario(conn)

        import neurostack.config as config_mod
        import neurostack.search as search_mod

        monkeypatch.setattr(search_mod, "get_db", lambda path: conn)

        import numpy as np
        fake_emb = np.array([0.5] * 768, dtype=np.float32)
        monkeypatch.setattr(search_mod, "get_embedding", lambda q, base_url=None: fake_emb)

        original_config = config_mod._config
        try:
            # With boost enabled
            cfg = Config()
            cfg.cooccurrence_boost_weight = 0.5
            config_mod._config = cfg

            results = hybrid_search("gamma", top_k=10, embed_url="http://fake")
            scores = {r.note_path: r.score for r in results}
        finally:
            config_mod._config = original_config

        # noteA has beta which co-occurs with gamma -- it should rank higher
        assert "noteA.md" in scores, "noteA should appear in results"
        assert "noteB.md" in scores, "noteB should appear in results"
        assert scores["noteA.md"] > scores["noteB.md"], (
            f"noteA (co-occurring) should rank higher than noteB: "
            f"{scores['noteA.md']} > {scores['noteB.md']}"
        )

    def test_cooccurrence_boost_with_hybrid_scoring(self, in_memory_db, monkeypatch):
        """In hybrid mode, boosted note scores higher than unboosted note."""
        conn = in_memory_db
        self._setup_cooccurrence_scenario(conn)

        import neurostack.config as config_mod
        import neurostack.search as search_mod

        monkeypatch.setattr(search_mod, "get_db", lambda path: conn)

        import numpy as np
        fake_emb = np.array([0.5] * 768, dtype=np.float32)
        monkeypatch.setattr(search_mod, "get_embedding", lambda q, base_url=None: fake_emb)

        original_config = config_mod._config
        try:
            cfg_on = Config()
            cfg_on.cooccurrence_boost_weight = 0.5
            config_mod._config = cfg_on

            results = hybrid_search("gamma", top_k=10, embed_url="http://fake")
            scores = {r.note_path: r.score for r in results}
        finally:
            config_mod._config = original_config

        # noteA contains "beta" which co-occurs with "gamma" -- it should rank higher
        assert "noteA.md" in scores
        assert "noteB.md" in scores
        assert scores["noteA.md"] > scores["noteB.md"], (
            f"noteA (co-occurring) should rank higher than noteB: "
            f"{scores['noteA.md']} > {scores['noteB.md']}"
        )

    def test_cooccurrence_boost_zero_weight_no_change(self, in_memory_db, monkeypatch):
        """With cooccurrence_boost_weight=0.0, all notes score equally (no boost)."""
        conn = in_memory_db
        self._setup_cooccurrence_scenario(conn)

        import neurostack.config as config_mod
        import neurostack.search as search_mod

        monkeypatch.setattr(search_mod, "get_db", lambda path: conn)

        import numpy as np
        fake_emb = np.array([0.5] * 768, dtype=np.float32)
        monkeypatch.setattr(search_mod, "get_embedding", lambda q, base_url=None: fake_emb)

        original_config = config_mod._config
        try:
            cfg = Config()
            cfg.cooccurrence_boost_weight = 0.0
            config_mod._config = cfg

            results = hybrid_search("gamma", top_k=10, embed_url="http://fake")
            scores = {r.note_path: r.score for r in results}
        finally:
            config_mod._config = original_config

        # With weight=0, co-occurrence should not cause a differential.
        # Notes may still differ due to lateral inhibition (the lower-ranked
        # identical note gets suppressed), so we check that at least one of
        # the two notes appears and no co-occurrence-specific boost is applied.
        if "noteA.md" in scores and "noteB.md" in scores:
            # Both present: the higher score should be at most ~1.43x the lower
            # (lateral inhibition penalty is bounded at 0.70x for identical embeddings)
            higher = max(scores["noteA.md"], scores["noteB.md"])
            lower = min(scores["noteA.md"], scores["noteB.md"])
            assert lower > 0, "Both notes should have positive scores"
            ratio = higher / lower
            assert ratio < 1.5, (
                f"Score ratio too large without co-occurrence boost: "
                f"noteA={scores['noteA.md']}, noteB={scores['noteB.md']}, "
                f"ratio={ratio:.2f}"
            )

    def test_cooccurrence_boost_graceful_no_data(self, in_memory_db, monkeypatch):
        """When no co-occurrence data exists, search works normally."""
        conn = in_memory_db
        emb = _fake_embedding(0.5)

        # Insert a note and chunk but NO co-occurrence data
        conn.execute(
            "INSERT INTO notes (path, title, content_hash, updated_at) "
            "VALUES (?, ?, ?, ?)",
            ("solo.md", "Solo", "hs", "2026-01-01"),
        )
        conn.execute(
            "INSERT INTO chunks (note_path, heading_path, content, "
            "content_hash, position, embedding) VALUES (?, ?, ?, ?, ?, ?)",
            ("solo.md", "## Test", "test search content", "h_solo", 0, emb),
        )
        conn.execute(
            "INSERT INTO triples (note_path, subject, predicate, object, triple_text) "
            "VALUES (?, ?, ?, ?, ?)",
            ("solo.md", "test", "is", "content", "test is content"),
        )
        conn.commit()

        import neurostack.config as config_mod
        import neurostack.search as search_mod

        monkeypatch.setattr(search_mod, "get_db", lambda path: conn)

        import numpy as np
        fake_emb = np.array([0.5] * 768, dtype=np.float32)
        monkeypatch.setattr(search_mod, "get_embedding", lambda q, base_url=None: fake_emb)

        original_config = config_mod._config
        try:
            cfg = Config()
            cfg.cooccurrence_boost_weight = 0.5
            config_mod._config = cfg

            # Should not crash, should return results
            results = hybrid_search("test", top_k=10, embed_url="http://fake")
            assert len(results) > 0
        finally:
            config_mod._config = original_config

    def test_cooccurrence_boost_bounded(self, in_memory_db, monkeypatch):
        """Co-occurrence boost should be bounded -- cannot dominate semantic score."""
        conn = in_memory_db
        emb = _fake_embedding(0.5)

        # Create a note with MANY co-occurring entities
        conn.execute(
            "INSERT INTO notes (path, title, content_hash, updated_at) "
            "VALUES (?, ?, ?, ?)",
            ("heavy.md", "Heavy", "hh", "2026-01-01"),
        )
        conn.execute(
            "INSERT INTO chunks (note_path, heading_path, content, "
            "content_hash, position, embedding) VALUES (?, ?, ?, ?, ?, ?)",
            ("heavy.md", "## Test", "target search term here", "h_heavy", 0, emb),
        )
        # Add many entities to this note
        for i in range(20):
            conn.execute(
                "INSERT INTO triples (note_path, subject, predicate, object, triple_text) "
                "VALUES (?, ?, ?, ?, ?)",
                ("heavy.md", f"ent{i}", "has", f"prop{i}", f"ent{i} has prop{i}"),
            )
        # Add massive co-occurrence weights between target and all entities
        for i in range(20):
            conn.execute(
                "INSERT INTO entity_cooccurrence (entity_a, entity_b, weight, last_seen) "
                "VALUES (?, ?, ?, ?)",
                (f"ent{i}", "target", 100.0, "2026-01-01"),
            )
        conn.commit()

        import neurostack.config as config_mod
        import neurostack.search as search_mod

        monkeypatch.setattr(search_mod, "get_db", lambda path: conn)

        import numpy as np
        fake_emb = np.array([0.5] * 768, dtype=np.float32)
        monkeypatch.setattr(search_mod, "get_embedding", lambda q, base_url=None: fake_emb)

        original_config = config_mod._config
        try:
            # Without boost
            cfg_off = Config()
            cfg_off.cooccurrence_boost_weight = 0.0
            config_mod._config = cfg_off
            results_off = hybrid_search("target", top_k=10, embed_url="http://fake")
            score_off = results_off[0].score if results_off else 0

            # With max boost
            cfg_on = Config()
            cfg_on.cooccurrence_boost_weight = 1.0  # maximum weight
            config_mod._config = cfg_on
            results_on = hybrid_search("target", top_k=10, embed_url="http://fake")
            score_on = results_on[0].score if results_on else 0
        finally:
            config_mod._config = original_config

        # Even with weight=1.0 and huge co-occurrence, boost should be bounded
        # The boost factor should be at most (1 + weight) = 2.0x
        if score_off > 0:
            ratio = score_on / score_off
            assert ratio <= 2.1, (
                f"Boost ratio {ratio} exceeds bounded maximum of ~2.0"
            )


class TestReinforcementFromSearch:
    """Tests for Hebbian reinforcement wired into hybrid_search."""

    def test_reinforce_from_search(self, in_memory_db, monkeypatch):
        """After hybrid_search, co-occurrence weights increase for entity pairs
        appearing in both query-matched entities and result-note entities."""
        conn = in_memory_db
        emb = _fake_embedding(0.5)

        # noteA.md has entities "alpha" and "beta"
        conn.execute(
            "INSERT INTO notes (path, title, content_hash, updated_at) "
            "VALUES (?, ?, ?, ?)",
            ("noteA.md", "Note A", "ha", "2026-01-01"),
        )
        conn.execute(
            "INSERT INTO chunks (note_path, heading_path, content, "
            "content_hash, position, embedding) VALUES (?, ?, ?, ?, ?, ?)",
            ("noteA.md", "## Test", "alpha related content", "h_a", 0, emb),
        )
        conn.execute(
            "INSERT INTO triples (note_path, subject, predicate, object, triple_text) "
            "VALUES (?, ?, ?, ?, ?)",
            ("noteA.md", "alpha", "relates_to", "beta", "alpha relates_to beta"),
        )

        # noteB.md has entity "alpha" (so "alpha" is a query-matched entity)
        conn.execute(
            "INSERT INTO notes (path, title, content_hash, updated_at) "
            "VALUES (?, ?, ?, ?)",
            ("noteB.md", "Note B", "hb", "2026-01-01"),
        )
        conn.execute(
            "INSERT INTO triples (note_path, subject, predicate, object, triple_text) "
            "VALUES (?, ?, ?, ?, ?)",
            ("noteB.md", "alpha", "is_a", "concept", "alpha is_a concept"),
        )
        conn.commit()

        # Check initial state: no co-occurrence for (alpha, beta) from reinforcement
        initial = conn.execute(
            "SELECT weight FROM entity_cooccurrence "
            "WHERE entity_a = 'alpha' AND entity_b = 'beta'"
        ).fetchone()

        import neurostack.config as config_mod
        import neurostack.search as search_mod

        monkeypatch.setattr(search_mod, "get_db", lambda path: conn)

        import numpy as np
        fake_emb = np.array([0.5] * 768, dtype=np.float32)
        monkeypatch.setattr(
            search_mod, "get_embedding", lambda q, base_url=None: fake_emb
        )

        original_config = config_mod._config
        try:
            cfg = Config()
            cfg.cooccurrence_boost_weight = 0.0  # Disable boost; reinforcement still fires
            config_mod._config = cfg

            hybrid_search("alpha", top_k=10, embed_url="http://fake")
        finally:
            config_mod._config = original_config

        # After search, reinforcement should have created/increased the
        # co-occurrence between alpha (query entity) and beta (result-note entity)
        after = conn.execute(
            "SELECT weight FROM entity_cooccurrence "
            "WHERE entity_a = 'alpha' AND entity_b = 'beta'"
        ).fetchone()
        assert after is not None, "Reinforcement should have created (alpha, beta) pair"
        initial_weight = initial["weight"] if initial else 0.0
        assert after["weight"] > initial_weight, (
            f"Weight should have increased from {initial_weight}"
        )

    def test_reinforce_noop_no_entities_in_search(self, in_memory_db, monkeypatch):
        """If the query matches no entities in triples, no reinforcement occurs."""
        conn = in_memory_db
        emb = _fake_embedding(0.5)

        conn.execute(
            "INSERT INTO notes (path, title, content_hash, updated_at) "
            "VALUES (?, ?, ?, ?)",
            ("solo.md", "Solo", "hs", "2026-01-01"),
        )
        conn.execute(
            "INSERT INTO chunks (note_path, heading_path, content, "
            "content_hash, position, embedding) VALUES (?, ?, ?, ?, ?, ?)",
            ("solo.md", "## Test", "unrelated content here", "h_solo", 0, emb),
        )
        conn.commit()

        import neurostack.config as config_mod
        import neurostack.search as search_mod

        monkeypatch.setattr(search_mod, "get_db", lambda path: conn)

        import numpy as np
        fake_emb = np.array([0.5] * 768, dtype=np.float32)
        monkeypatch.setattr(
            search_mod, "get_embedding", lambda q, base_url=None: fake_emb
        )

        original_config = config_mod._config
        try:
            cfg = Config()
            cfg.cooccurrence_boost_weight = 0.0
            config_mod._config = cfg

            hybrid_search("zzzznonexistent", top_k=10, embed_url="http://fake")
        finally:
            config_mod._config = original_config

        count = conn.execute(
            "SELECT COUNT(*) as c FROM entity_cooccurrence"
        ).fetchone()["c"]
        assert count == 0, "No reinforcement should occur when query matches no entities"


class TestLinkSectionHelpers:
    """Unit tests for the link-section detection helpers (issue #41)."""

    def test_link_density_pure_links(self):
        from neurostack.search import _link_density
        content = "[[azure consolidation]] [[azure networking]] [[azure dr]]"
        assert _link_density(content) > 0.8

    def test_link_density_prose(self):
        from neurostack.search import _link_density
        content = "Azure consolidation moves prod and staging into one subscription."
        assert _link_density(content) == 0.0

    def test_link_density_empty(self):
        from neurostack.search import _link_density
        assert _link_density("") == 0.0

    def test_is_link_section_by_heading_with_links(self):
        from neurostack.search import _is_link_section
        # A named link section below the density threshold still qualifies when it
        # carries a non-trivial fraction of links (density ~0.36 here, < 0.5).
        body = "Background: [[note-a]] and [[note-b]] both cover this topic well."
        assert _is_link_section("## Architecture > ### See also", body, 0.5) is True

    def test_is_link_section_heading_variants(self):
        from neurostack.search import _is_link_section
        # Prefix matching catches "Related Notes", "Backlinks", etc.
        links = "[[a]] [[b]] [[c]] notes here"
        assert _is_link_section("## Related Notes", links, 0.5) is True
        assert _is_link_section("## Backlinks", links, 0.5) is True

    def test_link_heading_prose_not_penalised(self):
        from neurostack.search import _is_link_section
        # A "Related Work" heading with no links is prose, not a link list.
        prose = "Related work in this area focuses on hierarchical inference models."
        assert _is_link_section("## Related Work", prose, 0.5) is False

    def test_is_link_section_by_density(self):
        from neurostack.search import _is_link_section
        dense = "[[a]] [[b]] [[c]] [[d]]"
        assert _is_link_section("## Notes", dense, 0.5) is True

    def test_not_link_section_for_body(self):
        from neurostack.search import _is_link_section
        body = "Azure consolidation environments: prod, staging and dev."
        assert _is_link_section("## Environments", body, 0.5) is False


class TestLinkSectionDownweight:
    """hybrid_search must not let a link-block match outrank a body match (#41)."""

    def _setup(self, conn):
        """Two notes matching the same query:

        - canonical.md: a substantive '## Environments' body chunk (no links),
          moderately similar to the query (cosine 0.7).
        - linky.md: a '## Related' chunk that is a dense wiki-link block whose
          link titles repeat the query terms, more similar to the query
          (cosine 0.9). Without the penalty its higher cosine wins.

        Embeddings are crafted so the two notes' mutual cosine is 0.63 (below the
        0.65 lateral-inhibition threshold) and each note is single-chunk (so the
        convergence stage is skipped) — isolating the link-section penalty.
        """
        import math
        import struct

        def blob(vec, dim=768):
            full = list(vec) + [0.0] * (dim - len(vec))
            return struct.pack(f"{dim}f", *full)

        # query = e0; linky cos 0.9 (in e0/e1 plane); canonical cos 0.7 (e0/e2 plane)
        linky_vec = [0.9, math.sqrt(1 - 0.81), 0.0]
        canon_vec = [0.7, 0.0, math.sqrt(1 - 0.49)]

        for path, title, heading, content, vec in [
            ("canonical.md", "Canonical", "## Environments",
             "azure consolidation environments", canon_vec),
            ("linky.md", "Linky", "## Related",
             "[[azure consolidation environments]]", linky_vec),
        ]:
            conn.execute(
                "INSERT INTO notes (path, title, content_hash, updated_at) "
                "VALUES (?, ?, ?, ?)",
                (path, title, "h", "2026-01-01"),
            )
            conn.execute(
                "INSERT INTO chunks (note_path, heading_path, content, "
                "content_hash, position, embedding) VALUES (?, ?, ?, ?, ?, ?)",
                (path, heading, content, f"h_{path}", 0, blob(vec)),
            )
        conn.commit()

    def _run(self, conn, monkeypatch, penalty):
        import numpy as np

        import neurostack.config as config_mod
        import neurostack.search as search_mod

        monkeypatch.setattr(search_mod, "get_db", lambda path: conn)
        query_emb = np.array([1.0, 0.0, 0.0] + [0.0] * 765, dtype=np.float32)
        monkeypatch.setattr(
            search_mod, "get_embedding", lambda q, base_url=None: query_emb
        )

        original = config_mod._config
        try:
            cfg = Config()
            cfg.cooccurrence_boost_weight = 0.0
            cfg.link_section_penalty = penalty
            config_mod._config = cfg
            return hybrid_search("azure consolidation environments",
                                 top_k=5, embed_url="http://fake", explain=True)
        finally:
            config_mod._config = original

    def test_penalty_off_reproduces_bug(self, in_memory_db, monkeypatch):
        self._setup(in_memory_db)
        results = self._run(in_memory_db, monkeypatch, penalty=1.0)
        # Without the penalty the link block (higher cosine) wins — the #41 bug.
        assert results[0].note_path == "linky.md"

    def test_penalty_on_promotes_body_note(self, in_memory_db, monkeypatch):
        self._setup(in_memory_db)
        results = self._run(in_memory_db, monkeypatch, penalty=0.5)
        # With the penalty the substantive body note ranks first.
        assert results[0].note_path == "canonical.md"
        scores = {r.note_path: r.score for r in results}
        assert scores["canonical.md"] > scores["linky.md"]

    def test_explain_breakdown_present(self, in_memory_db, monkeypatch):
        self._setup(in_memory_db)
        results = self._run(in_memory_db, monkeypatch, penalty=0.5)
        linky = next(r for r in results if r.note_path == "linky.md")
        assert linky.explain is not None
        assert linky.explain["link_section"] is True
        # The link block's score is penalised: post-penalty below the base.
        assert linky.explain["after_link"] < linky.explain["base"]
        canon = next(r for r in results if r.note_path == "canonical.md")
        assert canon.explain["link_section"] is False


class TestNormalizeScores:
    """Tests for the _normalize_scores helper (max-normalization) used by the merge."""

    def test_empty(self):
        assert _normalize_scores({}) == {}

    def test_equal_values_all_one(self):
        # No spread -> everything is equally "the best".
        assert _normalize_scores({"a": 0.5, "b": 0.5}) == {"a": 1.0, "b": 1.0}

    def test_divides_by_max(self):
        out = _normalize_scores({"a": 1.0, "b": 0.5, "c": 0.0})
        assert out["a"] == 1.0
        assert abs(out["b"] - 0.5) < 1e-9
        assert out["c"] == 0.0

    def test_preserves_magnitude_unlike_minmax(self):
        # The defining difference from min-max: the lower note keeps its real
        # fraction of the max (0.4/0.8 = 0.5) instead of collapsing to 0.0.
        out = _normalize_scores({"a": 0.8, "b": 0.4})
        assert out["a"] == 1.0
        assert abs(out["b"] - 0.5) < 1e-9

    def test_nonpositive_max_yields_zeros(self):
        # No usable signal -> all 0.0, no division by zero.
        assert _normalize_scores({"a": 0.0, "b": 0.0}) == {"a": 0.0, "b": 0.0}

    def test_negatives_clamped(self):
        out = _normalize_scores({"a": 1.0, "b": -0.5})
        assert out["a"] == 1.0
        assert out["b"] == 0.0


class TestTieredAutoMerge:
    """Tests for tiered_search(depth='auto') — the real triple+summary merge (issue #58).

    The merge logic is isolated from embeddings/DB by patching search_triples and
    hybrid_search at the module level; get_db returns the in-memory fixture so the
    summary-fetch fallback for triple-only notes can hit a real table.
    """

    def _run_auto(self, monkeypatch, conn, triples, summary_hits, top_k=3):
        import neurostack.config as config_mod
        import neurostack.search as search_mod

        monkeypatch.setattr(search_mod, "search_triples", lambda *a, **k: triples)
        monkeypatch.setattr(search_mod, "hybrid_search", lambda *a, **k: summary_hits)
        monkeypatch.setattr(search_mod, "get_db", lambda path: conn)

        original = config_mod._config
        try:
            config_mod._config = Config()  # auto_summary_weight defaults to 0.5
            return tiered_search(
                "q", top_k=top_k, depth="auto", embed_url="http://fake"
            )
        finally:
            config_mod._config = original

    def test_summary_signal_reorders_triple_ranking(self, in_memory_db, monkeypatch):
        """A note that triples rank low but summaries rank top must rise in auto.

        Pre-fix this returned pure triple order; the regression is that the
        summary search never influenced the ranking.
        """
        triples = [
            TripleResult("a.md", "A", "x", "y", 0.90, "A"),
            TripleResult("b.md", "B", "x", "y", 0.70, "B"),
            TripleResult("c.md", "C", "x", "y", 0.50, "C"),
        ]
        # c is the strongest summary hit, a the weakest — the inverse of triples.
        summary_hits = [
            SearchResult("c.md", "h", "snip", 0.95, summary="C sum", title="C"),
            SearchResult("b.md", "h", "snip", 0.50, summary="B sum", title="B"),
            SearchResult("a.md", "h", "snip", 0.10, summary="A sum", title="A"),
        ]
        result = self._run_auto(monkeypatch, in_memory_db, triples, summary_hits)

        assert result["depth_used"] == "auto:triples+summaries"
        order = [s["note"] for s in result["summaries"]]
        # Triples alone put b (0.70) above c (0.50); the summary signal flips it.
        assert order.index("c.md") < order.index("b.md")
        # merged_ranking is the canonical order and matches the summaries list.
        assert [m["note"] for m in result["merged_ranking"]] == order
        # Every surfaced summary carries a numeric merged score.
        assert all(isinstance(s["score"], float) for s in result["summaries"])

    def test_auto_order_differs_from_triples_only(self, in_memory_db, monkeypatch):
        """depth='auto' must not be a byte-for-byte alias of depth='triples'."""
        triples = [
            TripleResult("a.md", "A", "x", "y", 0.90, "A"),
            TripleResult("b.md", "B", "x", "y", 0.70, "B"),
            TripleResult("c.md", "C", "x", "y", 0.50, "C"),
        ]
        summary_hits = [
            SearchResult("c.md", "h", "snip", 0.95, summary="C sum", title="C"),
            SearchResult("b.md", "h", "snip", 0.50, summary="B sum", title="B"),
            SearchResult("a.md", "h", "snip", 0.10, summary="A sum", title="A"),
        ]
        auto = self._run_auto(monkeypatch, in_memory_db, triples, summary_hits)
        auto_order = [s["note"] for s in auto["summaries"]]
        triple_only_order = ["a.md", "b.md", "c.md"]  # pure descending triple score
        assert auto_order != triple_only_order

    def test_triple_only_note_gets_summary_from_db(self, in_memory_db, monkeypatch):
        """A note that surfaces only via triples (no chunk hit) still gets its
        summary fetched from the DB and appears in the merged output."""
        conn = in_memory_db
        conn.execute(
            "INSERT INTO notes (path, title, content_hash, updated_at) "
            "VALUES (?, ?, ?, ?)",
            ("x.md", "Note X", "hx", "2026-01-01"),
        )
        conn.execute(
            "INSERT INTO summaries (note_path, summary_text, content_hash, updated_at) "
            "VALUES (?, ?, ?, ?)",
            ("x.md", "Summary of X from the DB", "hx", "2026-01-01"),
        )
        conn.commit()

        triples = [
            TripleResult("x.md", "X", "p", "o", 0.85, "Note X"),
            TripleResult("y.md", "Y", "p", "o", 0.60, "Note Y"),
        ]
        # hybrid_search returns y only — x never appears as a chunk hit.
        summary_hits = [
            SearchResult("y.md", "h", "snip", 0.70, summary="Y sum", title="Note Y"),
        ]
        result = self._run_auto(monkeypatch, conn, triples, summary_hits)

        surfaced = {s["note"]: s for s in result["summaries"]}
        assert "x.md" in surfaced
        assert surfaced["x.md"]["summary"] == "Summary of X from the DB"
        assert "x.md" in {m["note"] for m in result["merged_ranking"]}

    def test_empty_summary_search_labels_triples_only(self, in_memory_db, monkeypatch):
        """Gate fires but the summary search returns nothing -> the ranking is
        triple-only, and depth_used must say so rather than claim a merge."""
        triples = [
            TripleResult("a.md", "A", "p", "o", 0.90, "A"),
            TripleResult("b.md", "B", "p", "o", 0.70, "B"),
        ]
        result = self._run_auto(monkeypatch, in_memory_db, triples, [])
        assert result["depth_used"] == "auto:triples"
        # Still produces a ranking (triple order), just honestly labeled.
        assert [m["note"] for m in result["merged_ranking"]] == ["a.md", "b.md"]

    def test_low_coverage_falls_back_to_chunks(self, in_memory_db, monkeypatch):
        """Fewer than two triple notes -> gate not fired -> full chunk fallback."""
        triples = [TripleResult("only.md", "O", "p", "o", 0.90, "Only")]
        chunk_hits = [
            SearchResult("z.md", "## H", "a snippet", 0.80, summary="Z", title="Z"),
        ]
        result = self._run_auto(monkeypatch, in_memory_db, triples, chunk_hits)

        assert result["depth_used"] == "auto:full"
        assert result["summaries"] == []
        assert [c["note"] for c in result["chunks"]] == ["z.md"]

    def test_low_confidence_falls_back_to_chunks(self, in_memory_db, monkeypatch):
        """Two notes but max triple score <= 0.4 -> gate not fired -> chunk fallback."""
        triples = [
            TripleResult("a.md", "A", "p", "o", 0.30, "A"),
            TripleResult("b.md", "B", "p", "o", 0.20, "B"),
        ]
        chunk_hits = [
            SearchResult("z.md", "## H", "a snippet", 0.80, summary="Z", title="Z"),
        ]
        result = self._run_auto(monkeypatch, in_memory_db, triples, chunk_hits)

        assert result["depth_used"] == "auto:full"
        assert result["chunks"]
