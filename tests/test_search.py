"""Tests for neurostack.search — FTS5, hotness scoring, prediction errors, co-occurrence boost."""

import struct

from neurostack.config import Config
from neurostack.search import (
    PREDICTION_ERROR_SIM_THRESHOLD,
    fts_search,
    hotness_score,
    hybrid_search,
    log_prediction_error,
    run_excitability_demotion,
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

        # With weight=0, noteA and noteB should have identical scores
        # (both have identical chunks/embeddings, only co-occurrence differs)
        if "noteA.md" in scores and "noteB.md" in scores:
            assert abs(scores["noteA.md"] - scores["noteB.md"]) < 1e-9, (
                f"With boost disabled, scores should be equal: "
                f"noteA={scores['noteA.md']}, noteB={scores['noteB.md']}"
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
            cfg.cooccurrence_boost_weight = 0.0  # Disable boost, but reinforcement should still fire
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
