"""Integration tests for the NeuroStack MCP server layer.

These tests import tool functions directly from neurostack.server and call them
as plain Python callables, without going through stdio or network transport.
Each test patches neurostack.schema.DB_PATH to point to a temporary test
database, keeping tests hermetic and avoiding any real vault on disk.
"""

import json
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def server_db(tmp_path):
    """Temp file DB with full schema + minimal test data.

    Uses get_db() to initialise the schema (including all migrations), then
    inserts two notes, two chunks (which auto-populate the FTS index via
    triggers), and one prediction error — enough for all three tools to
    return non-trivial results.
    """
    from neurostack.schema import get_db

    db_file = tmp_path / "test_server.db"
    conn = get_db(db_file)

    now = "2026-01-15T00:00:00+00:00"
    conn.execute(
        "INSERT OR REPLACE INTO notes (path, title, frontmatter, content_hash, updated_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (
            "research/predictive-coding.md",
            "Predictive Coding",
            json.dumps({"tags": ["neuroscience", "prediction"]}),
            "abc123",
            now,
        ),
    )
    conn.execute(
        "INSERT OR REPLACE INTO notes (path, title, frontmatter, content_hash, updated_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (
            "research/memory-consolidation.md",
            "Memory Consolidation",
            json.dumps({"tags": ["neuroscience", "memory"]}),
            "def456",
            now,
        ),
    )
    # Chunks are inserted via INSERT — the FTS5 trigger populates chunks_fts.
    conn.execute(
        "INSERT INTO chunks (note_path, heading_path, content, content_hash, position)"
        " VALUES (?, ?, ?, ?, ?)",
        (
            "research/predictive-coding.md",
            "Predictive Coding",
            "The brain generates predictions about incoming sensory data."
            " When predictions fail, prediction errors propagate upward.",
            "chunk-abc1",
            0,
        ),
    )
    conn.execute(
        "INSERT INTO chunks (note_path, heading_path, content, content_hash, position)"
        " VALUES (?, ?, ?, ?, ?)",
        (
            "research/memory-consolidation.md",
            "Memory Consolidation",
            "Memory consolidation occurs during sleep through hippocampal replay."
            " Spindle-ripple coupling stabilises new memories.",
            "chunk-def1",
            0,
        ),
    )
    # One unresolved prediction error on the first note.
    conn.execute(
        "INSERT INTO prediction_errors"
        " (note_path, query, cosine_distance, error_type, detected_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (
            "research/predictive-coding.md",
            "hippocampal memory retrieval",
            0.71,
            "low_overlap",
            "2026-01-15T10:00:00",
        ),
    )
    conn.commit()
    conn.close()

    return db_file


# ---------------------------------------------------------------------------
# vault_stats
# ---------------------------------------------------------------------------


class TestVaultStats:
    def test_returns_valid_json(self, server_db):
        from neurostack.server import vault_stats

        with patch("neurostack.schema.DB_PATH", server_db):
            result = vault_stats()

        assert isinstance(result, str)
        data = json.loads(result)
        assert isinstance(data, dict)

    def test_has_required_keys(self, server_db):
        from neurostack.server import vault_stats

        required = {
            "notes",
            "chunks",
            "embedded",
            "embedding_coverage",
            "summaries",
            "summary_coverage",
            "stale_summaries",
            "graph_edges",
            "triples",
            "notes_with_triples",
            "triple_coverage",
            "triple_embedding_coverage",
            "communities_coarse",
            "communities_fine",
            "communities_summarized",
        }
        with patch("neurostack.schema.DB_PATH", server_db):
            result = vault_stats()

        data = json.loads(result)
        assert required <= data.keys(), (
            f"Missing keys: {required - data.keys()}"
        )

    def test_counts_reflect_test_data(self, server_db):
        from neurostack.server import vault_stats

        with patch("neurostack.schema.DB_PATH", server_db):
            result = vault_stats()

        data = json.loads(result)
        assert data["notes"] == 2
        assert data["chunks"] == 2
        assert data["embedded"] == 0  # no embeddings in test data
        assert data["embedding_coverage"] == "0%"
        assert data["triples"] == 0
        assert data["graph_edges"] == 0

    def test_stale_summaries_counts_notes_without_summaries(self, server_db):
        """All notes start with no summaries, so stale_summaries == notes."""
        from neurostack.server import vault_stats

        with patch("neurostack.schema.DB_PATH", server_db):
            result = vault_stats()

        data = json.loads(result)
        assert data["stale_summaries"] == data["notes"]

    def test_empty_vault(self, tmp_path):
        """vault_stats on an empty DB returns zeros without error."""
        from neurostack.schema import get_db
        from neurostack.server import vault_stats

        empty_db = tmp_path / "empty.db"
        get_db(empty_db).close()

        with patch("neurostack.schema.DB_PATH", empty_db):
            result = vault_stats()

        data = json.loads(result)
        assert data["notes"] == 0
        assert data["chunks"] == 0


# ---------------------------------------------------------------------------
# vault_prediction_errors
# ---------------------------------------------------------------------------


class TestVaultPredictionErrors:
    def test_returns_valid_json(self, server_db):
        from neurostack.server import vault_prediction_errors

        with patch("neurostack.schema.DB_PATH", server_db):
            result = vault_prediction_errors()

        assert isinstance(result, str)
        data = json.loads(result)
        assert isinstance(data, dict)

    def test_has_required_keys(self, server_db):
        from neurostack.server import vault_prediction_errors

        with patch("neurostack.schema.DB_PATH", server_db):
            result = vault_prediction_errors()

        data = json.loads(result)
        assert "total_flagged_notes" in data
        assert "showing" in data
        assert "errors" in data
        assert isinstance(data["errors"], list)

    def test_returns_inserted_error(self, server_db):
        from neurostack.server import vault_prediction_errors

        with patch("neurostack.schema.DB_PATH", server_db):
            result = vault_prediction_errors()

        data = json.loads(result)
        assert data["total_flagged_notes"] == 1
        assert data["showing"] == 1

        err = data["errors"][0]
        assert err["note_path"] == "research/predictive-coding.md"
        assert err["error_type"] == "low_overlap"
        assert isinstance(err["avg_cosine_distance"], float)
        assert err["occurrences"] == 1

    def test_filter_by_error_type(self, server_db):
        from neurostack.server import vault_prediction_errors

        with patch("neurostack.schema.DB_PATH", server_db):
            matching = json.loads(vault_prediction_errors(error_type="low_overlap"))
            no_match = json.loads(
                vault_prediction_errors(error_type="contextual_mismatch")
            )

        assert matching["showing"] == 1
        assert no_match["showing"] == 0

    def test_resolve_clears_error(self, server_db):
        from neurostack.server import vault_prediction_errors

        with patch("neurostack.schema.DB_PATH", server_db):
            result = vault_prediction_errors(
                resolve=["research/predictive-coding.md"]
            )

        data = json.loads(result)
        assert data["resolved"] == 1

        # After resolving, the error should no longer appear
        with patch("neurostack.schema.DB_PATH", server_db):
            after = json.loads(vault_prediction_errors())
        assert after["total_flagged_notes"] == 0

    def test_empty_vault(self, tmp_path):
        from neurostack.schema import get_db
        from neurostack.server import vault_prediction_errors

        empty_db = tmp_path / "empty.db"
        get_db(empty_db).close()

        with patch("neurostack.schema.DB_PATH", empty_db):
            result = vault_prediction_errors()

        data = json.loads(result)
        assert data["total_flagged_notes"] == 0
        assert data["errors"] == []


# ---------------------------------------------------------------------------
# vault_search
# ---------------------------------------------------------------------------


class TestVaultSearch:
    """Tests use mode='keyword' (pure FTS5) to avoid requiring the Ollama
    embedding service. Embedding-dependent modes fall back to FTS5 when the
    service is unreachable, but keyword mode is explicit and always available.
    """

    def test_returns_valid_json(self, server_db):
        from neurostack.server import vault_search

        with patch("neurostack.schema.DB_PATH", server_db):
            result = vault_search("prediction", mode="keyword", depth="full")

        assert isinstance(result, str)
        data = json.loads(result)
        assert isinstance(data, list)

    def test_keyword_search_finds_matching_note(self, server_db):
        from neurostack.server import vault_search

        with patch("neurostack.schema.DB_PATH", server_db):
            result = vault_search("predictions sensory", mode="keyword", depth="full")

        data = json.loads(result)
        paths = [r["path"] for r in data if "path" in r]
        assert "research/predictive-coding.md" in paths

    def test_result_has_required_fields(self, server_db):
        from neurostack.server import vault_search

        with patch("neurostack.schema.DB_PATH", server_db):
            result = vault_search("memory", mode="keyword", depth="full")

        data = json.loads(result)
        # Filter out any _memories entries
        results = [r for r in data if "path" in r]
        if results:
            r = results[0]
            assert "path" in r
            assert "title" in r
            assert "section" in r
            assert "score" in r
            assert "snippet" in r

    def test_no_results_returns_empty_list(self, server_db):
        from neurostack.server import vault_search

        with patch("neurostack.schema.DB_PATH", server_db):
            result = vault_search(
                "xyzzy_nonexistent_term_42", mode="keyword", depth="full"
            )

        data = json.loads(result)
        content_results = [r for r in data if "path" in r]
        assert content_results == []

    def test_top_k_limits_results(self, server_db):
        from neurostack.server import vault_search

        with patch("neurostack.schema.DB_PATH", server_db):
            result = vault_search(
                "memory prediction", mode="keyword", depth="full", top_k=1
            )

        data = json.loads(result)
        content_results = [r for r in data if "path" in r]
        assert len(content_results) <= 1
