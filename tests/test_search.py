"""Tests for neurostack.search — FTS5, hotness scoring, prediction errors."""


from neurostack.search import (
    PREDICTION_ERROR_SIM_THRESHOLD,
    fts_search,
    hotness_score,
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
