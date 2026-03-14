"""Integration tests for NeuroStack MCP server tools.

Tests that the MCP tool functions (vault_stats, vault_search, vault_prediction_errors)
return valid JSON with expected structure when called directly as Python functions.

No network required — uses a temp file DB with test data and patches DB_PATH
so server tools read from the test database instead of the real vault.
"""

import json
import sqlite3

import pytest


@pytest.fixture
def server_db(tmp_path, monkeypatch):
    """Create an initialized test DB and patch neurostack.schema.DB_PATH to use it.

    Server tools do `from .schema import DB_PATH` inside each function, so patching
    the module attribute before calling the tool is sufficient.
    """
    from neurostack.schema import SCHEMA_SQL, SCHEMA_VERSION
    import neurostack.schema

    db_path = tmp_path / "test.db"
    monkeypatch.setattr(neurostack.schema, "DB_PATH", db_path)

    # Initialise schema in the temp file
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_SQL)
    conn.execute(
        "INSERT OR REPLACE INTO schema_version VALUES (?)", (SCHEMA_VERSION,)
    )

    # Insert two test notes and their chunks
    now = "2026-01-15T00:00:00+00:00"
    test_notes = [
        (
            "research/predictive-coding.md",
            "Predictive Coding",
            '{"tags": ["neuroscience", "prediction"]}',
            "abc123",
            "The brain generates predictions about incoming sensory data. "
            "Prediction errors drive learning.",
        ),
        (
            "research/memory-consolidation.md",
            "Memory Consolidation",
            '{"tags": ["neuroscience", "memory"]}',
            "def456",
            "Memory consolidation occurs during sleep through hippocampal replay.",
        ),
    ]
    for path, title, fm, chash, content in test_notes:
        conn.execute(
            "INSERT INTO notes (path, title, frontmatter, content_hash, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (path, title, fm, chash, now),
        )
        # Inserting into chunks triggers the chunks_ai trigger → populates chunks_fts
        conn.execute(
            "INSERT INTO chunks (note_path, heading_path, content, content_hash, position) "
            "VALUES (?, ?, ?, ?, ?)",
            (path, path.replace(".md", ""), content, "chunk_" + chash, 0),
        )
    conn.commit()
    conn.close()

    return db_path


# ---------------------------------------------------------------------------
# vault_stats
# ---------------------------------------------------------------------------

class TestVaultStats:
    def test_returns_valid_json(self, server_db):
        from neurostack.server import vault_stats

        result = vault_stats()
        data = json.loads(result)
        assert isinstance(data, dict)

    def test_has_required_keys(self, server_db):
        from neurostack.server import vault_stats

        result = vault_stats()
        data = json.loads(result)
        for key in [
            "notes", "chunks", "embedded", "embedding_coverage",
            "summaries", "summary_coverage", "stale_summaries",
            "graph_edges", "triples", "notes_with_triples", "triple_coverage",
        ]:
            assert key in data, f"Missing key in vault_stats response: {key!r}"

    def test_counts_match_inserted_data(self, server_db):
        from neurostack.server import vault_stats

        result = vault_stats()
        data = json.loads(result)
        assert data["notes"] == 2, "Expected 2 test notes"
        assert data["chunks"] == 2, "Expected 2 test chunks"
        assert data["embedded"] == 0, "No embeddings inserted in test data"
        assert data["embedding_coverage"] == "0%"
        assert data["triples"] == 0

    def test_coverage_strings_are_percentages(self, server_db):
        from neurostack.server import vault_stats

        result = vault_stats()
        data = json.loads(result)
        for key in ["embedding_coverage", "summary_coverage",
                    "triple_coverage", "triple_embedding_coverage"]:
            assert isinstance(data[key], str), f"{key} should be a string"
            assert data[key].endswith("%"), f"{key} should end with '%'"


# ---------------------------------------------------------------------------
# vault_prediction_errors
# ---------------------------------------------------------------------------

class TestVaultPredictionErrors:
    def test_returns_valid_json(self, server_db):
        from neurostack.server import vault_prediction_errors

        result = vault_prediction_errors()
        data = json.loads(result)
        assert isinstance(data, dict)

    def test_has_required_keys(self, server_db):
        from neurostack.server import vault_prediction_errors

        result = vault_prediction_errors()
        data = json.loads(result)
        assert "total_flagged_notes" in data
        assert "showing" in data
        assert "errors" in data
        assert isinstance(data["errors"], list)

    def test_empty_when_no_errors_exist(self, server_db):
        from neurostack.server import vault_prediction_errors

        result = vault_prediction_errors()
        data = json.loads(result)
        assert data["total_flagged_notes"] == 0
        assert data["showing"] == 0
        assert data["errors"] == []

    def test_surfaces_inserted_error(self, server_db):
        # Insert a prediction error directly into the test DB
        conn = sqlite3.connect(str(server_db))
        conn.execute(
            "INSERT INTO prediction_errors "
            "(note_path, query, cosine_distance, error_type) "
            "VALUES (?, ?, ?, ?)",
            ("research/predictive-coding.md", "hippocampus query", 0.75, "low_overlap"),
        )
        conn.commit()
        conn.close()

        from neurostack.server import vault_prediction_errors

        result = vault_prediction_errors()
        data = json.loads(result)
        assert data["total_flagged_notes"] == 1
        assert data["showing"] == 1
        assert len(data["errors"]) == 1

        err = data["errors"][0]
        for field in ["note_path", "error_type", "avg_cosine_distance",
                      "occurrences", "last_seen", "sample_query"]:
            assert field in err, f"Missing field in error entry: {field!r}"
        assert err["note_path"] == "research/predictive-coding.md"
        assert err["error_type"] == "low_overlap"

    def test_error_type_filter(self, server_db):
        conn = sqlite3.connect(str(server_db))
        conn.execute(
            "INSERT INTO prediction_errors "
            "(note_path, query, cosine_distance, error_type) "
            "VALUES (?, ?, ?, ?)",
            ("research/predictive-coding.md", "q1", 0.75, "low_overlap"),
        )
        conn.execute(
            "INSERT INTO prediction_errors "
            "(note_path, query, cosine_distance, error_type) "
            "VALUES (?, ?, ?, ?)",
            ("research/memory-consolidation.md", "q2", 0.65, "contextual_mismatch"),
        )
        conn.commit()
        conn.close()

        from neurostack.server import vault_prediction_errors

        overlap_only = json.loads(vault_prediction_errors(error_type="low_overlap"))
        assert all(e["error_type"] == "low_overlap" for e in overlap_only["errors"])

        mismatch_only = json.loads(vault_prediction_errors(error_type="contextual_mismatch"))
        assert all(e["error_type"] == "contextual_mismatch" for e in mismatch_only["errors"])

    def test_resolve_clears_errors(self, server_db):
        conn = sqlite3.connect(str(server_db))
        conn.execute(
            "INSERT INTO prediction_errors "
            "(note_path, query, cosine_distance, error_type) "
            "VALUES (?, ?, ?, ?)",
            ("research/predictive-coding.md", "sleep query", 0.80, "low_overlap"),
        )
        conn.commit()
        conn.close()

        from neurostack.server import vault_prediction_errors

        before = json.loads(vault_prediction_errors())
        assert before["total_flagged_notes"] == 1

        resolve_result = json.loads(
            vault_prediction_errors(resolve=["research/predictive-coding.md"])
        )
        assert resolve_result["resolved"] == 1

        after = json.loads(vault_prediction_errors())
        assert after["total_flagged_notes"] == 0


# ---------------------------------------------------------------------------
# vault_search
# ---------------------------------------------------------------------------

class TestVaultSearch:
    def test_returns_valid_json(self, server_db):
        from neurostack.server import vault_search

        result = vault_search("predictive coding", mode="keyword", depth="full")
        data = json.loads(result)
        assert isinstance(data, list)

    def test_keyword_search_finds_relevant_note(self, server_db):
        from neurostack.server import vault_search

        result = vault_search("prediction errors", mode="keyword", depth="full")
        data = json.loads(result)
        paths = [r.get("path") for r in data if isinstance(r, dict) and "path" in r]
        assert any("predictive-coding" in (p or "") for p in paths), (
            "Expected predictive-coding.md in results for 'prediction errors' query"
        )

    def test_result_items_have_required_fields(self, server_db):
        from neurostack.server import vault_search

        result = vault_search("memory", mode="keyword", depth="full")
        data = json.loads(result)
        for item in data:
            if isinstance(item, dict) and "path" in item and "_memories" not in item:
                for field in ["path", "title", "section", "score", "snippet"]:
                    assert field in item, f"Result item missing field: {field!r}"

    def test_no_results_for_unknown_query(self, server_db):
        from neurostack.server import vault_search

        result = vault_search("zzz_xyzzy_nonexistent", mode="keyword", depth="full")
        data = json.loads(result)
        # Valid JSON list; may be empty or contain only a _memories entry
        assert isinstance(data, list)
        non_memory_results = [
            r for r in data
            if isinstance(r, dict) and "path" in r
        ]
        assert non_memory_results == [], "Expected no content results for nonsense query"

    def test_hybrid_falls_back_to_fts_without_embeddings(self, server_db):
        """hybrid mode with no Ollama available should fall back to FTS5 results."""
        from neurostack.server import vault_search

        # hybrid mode with no embed_url will attempt embedding, fail, fall back to FTS
        result = vault_search(
            "hippocampal replay", mode="hybrid", depth="full",
        )
        data = json.loads(result)
        # Should still return valid JSON list (not raise)
        assert isinstance(data, list)
