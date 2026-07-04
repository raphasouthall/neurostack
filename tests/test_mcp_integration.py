# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Integration tests for the MCP server layer (issue #5).

Exercises the registered MCP tools end-to-end against a fixture vault:
registry registration, the FastMCP adapter, and the tool functions
themselves (vault_search, vault_stats, vault_prediction_errors), asserting
response structure and JSON serialisability.

The tools are regular Python functions behind the protocol-agnostic
registry, so we call them through ``registry.call`` (the same entry point
every adapter uses) rather than over a stdio transport. Search runs in
keyword mode so no embedder is needed.
"""

import asyncio
import json

import pytest

from neurostack import config as nsconfig


@pytest.fixture
def mcp_vault(tmp_path, tmp_vault, monkeypatch):
    """Point config at the fixture vault + a fresh on-disk DB, and index it."""
    db_dir = tmp_path / "db"
    monkeypatch.setenv("NEUROSTACK_VAULT_ROOT", str(tmp_vault))
    monkeypatch.setenv("NEUROSTACK_DB_DIR", str(db_dir))
    nsconfig._config = None

    from neurostack.chunker import parse_note
    from neurostack.schema import get_db

    conn = get_db(db_dir / "neurostack.db")
    now = "2026-01-15T00:00:00+00:00"
    for md_file in sorted(tmp_vault.rglob("*.md")):
        parsed = parse_note(md_file, tmp_vault)
        conn.execute(
            "INSERT OR REPLACE INTO notes "
            "(path, title, frontmatter, content_hash, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (parsed.path, parsed.title, json.dumps(parsed.frontmatter, default=str),
             parsed.content_hash, now),
        )
        for chunk in parsed.chunks:
            conn.execute(
                "INSERT INTO chunks "
                "(note_path, heading_path, content, content_hash, position) "
                "VALUES (?, ?, ?, ?, ?)",
                (parsed.path, chunk.heading_path, chunk.content, "test",
                 chunk.position),
            )
    conn.commit()
    conn.close()
    yield tmp_vault
    nsconfig._config = None


def _registry():
    from neurostack.tools import ensure_registered
    return ensure_registered()


def test_registry_registers_expected_tools(mcp_vault):
    names = {t.name for t in _registry().list_tools()}
    assert {"vault_search", "vault_stats", "vault_prediction_errors"} <= names


def test_mcp_server_exposes_registry_tools(mcp_vault):
    from neurostack.server import mcp  # noqa: F401 — module-level server builds
    from neurostack.tools.mcp_adapter import create_mcp_server

    server = create_mcp_server()
    tool_names = {t.name for t in asyncio.run(server.list_tools())}
    registry_names = {t.name for t in _registry().list_tools()}
    assert tool_names == registry_names


def test_vault_search_keyword(mcp_vault):
    result = _registry().call(
        "vault_search", query="prediction", mode="keyword", depth="full",
    )
    assert isinstance(result, dict)
    assert "results" in result
    json.dumps(result)  # response must be serialisable over the wire
    paths = [r["path"] for r in result["results"]]
    assert any("predictive-coding" in p for p in paths)


def test_vault_stats_structure(mcp_vault):
    result = _registry().call("vault_stats")
    for key in ("notes", "chunks", "embedded", "summaries", "graph_edges",
                "triples", "excitability", "memories"):
        assert key in result, key
    assert result["notes"] == 4  # fixture vault: 3 notes + index.md
    assert result["chunks"] > 0
    json.dumps(result)


def test_vault_prediction_errors_structure(mcp_vault):
    # Seed one note flagged twice (threshold: PREDICTION_ERROR_MIN_OCCURRENCES=2)
    # and one flagged once, which must stay below the reporting threshold.
    from neurostack.config import get_config
    from neurostack.schema import get_db

    conn = get_db(get_config().db_path)
    conn.executemany(
        "INSERT INTO prediction_errors "
        "(note_path, query, cosine_distance, error_type) VALUES (?, ?, ?, ?)",
        [
            ("research/long-note.md", "unrelated query", 0.8, "low_overlap"),
            ("research/long-note.md", "another query", 0.7, "low_overlap"),
            ("research/memory-consolidation.md", "one-off", 0.9, "low_overlap"),
        ],
    )
    conn.commit()
    conn.close()

    result = _registry().call("vault_prediction_errors")

    assert set(result) == {"total_flagged_notes", "showing", "errors"}
    assert result["total_flagged_notes"] == 1
    assert result["showing"] == 1
    err = result["errors"][0]
    assert err["note_path"] == "research/long-note.md"
    assert err["error_type"] == "low_overlap"
    assert err["occurrences"] == 2
    json.dumps(result)
