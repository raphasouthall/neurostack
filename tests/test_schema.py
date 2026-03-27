"""Tests for neurostack.schema — database creation and migrations."""

import sqlite3 as _sqlite3

import pytest

from neurostack.schema import (
    SCHEMA_VERSION,
    _run_migrations,
)


def test_schema_creation(in_memory_db):
    """Fresh schema has all required tables."""
    conn = in_memory_db
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    expected = {
        "schema_version",
        "notes",
        "chunks",
        "summaries",
        "graph_edges",
        "graph_stats",
        "triples",
        "communities",
        "community_members",
        "folder_summaries",
        "note_usage",
        "prediction_errors",
        "memories",
        "entity_cooccurrence",
    }
    assert expected.issubset(tables)


def test_schema_version(in_memory_db):
    """Schema version matches SCHEMA_VERSION constant."""
    row = in_memory_db.execute("SELECT MAX(version) as v FROM schema_version").fetchone()
    assert row["v"] == SCHEMA_VERSION


def test_fts_virtual_tables(in_memory_db):
    """FTS5 virtual tables exist."""
    tables = {
        row[0]
        for row in in_memory_db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "chunks_fts" in tables
    assert "triples_fts" in tables
    assert "memories_fts" in tables


def test_fts_sync_trigger_insert(in_memory_db):
    """Inserting a chunk auto-populates chunks_fts."""
    conn = in_memory_db
    conn.execute(
        "INSERT INTO notes (path, title, content_hash, updated_at) VALUES (?, ?, ?, ?)",
        ("test.md", "Test", "abc", "2026-01-01"),
    )
    conn.execute(
        "INSERT INTO chunks (note_path, heading_path, content, "
        "content_hash, position) VALUES (?, ?, ?, ?, ?)",
        ("test.md", "## Test", "hello world searchable content", "abc", 0),
    )
    conn.commit()

    results = conn.execute(
        "SELECT * FROM chunks_fts WHERE chunks_fts MATCH ?", ("searchable",)
    ).fetchall()
    assert len(results) == 1


def test_fts_sync_trigger_delete(in_memory_db):
    """Deleting a chunk removes it from chunks_fts."""
    conn = in_memory_db
    conn.execute(
        "INSERT INTO notes (path, title, content_hash, updated_at) VALUES (?, ?, ?, ?)",
        ("test.md", "Test", "abc", "2026-01-01"),
    )
    conn.execute(
        "INSERT INTO chunks (note_path, heading_path, content, "
        "content_hash, position) VALUES (?, ?, ?, ?, ?)",
        ("test.md", "## Test", "unique_token_xyz", "abc", 0),
    )
    conn.commit()

    conn.execute("DELETE FROM chunks WHERE note_path = ?", ("test.md",))
    conn.commit()

    results = conn.execute(
        "SELECT * FROM chunks_fts WHERE chunks_fts MATCH ?", ("unique_token_xyz",)
    ).fetchall()
    assert len(results) == 0


def test_cascade_delete(in_memory_db):
    """Deleting a note cascades to chunks and summaries."""
    conn = in_memory_db
    conn.execute(
        "INSERT INTO notes (path, title, content_hash, updated_at) VALUES (?, ?, ?, ?)",
        ("test.md", "Test", "abc", "2026-01-01"),
    )
    conn.execute(
        "INSERT INTO chunks (note_path, heading_path, content, "
        "content_hash, position) VALUES (?, ?, ?, ?, ?)",
        ("test.md", "## Test", "chunk content", "abc", 0),
    )
    conn.execute(
        "INSERT INTO summaries (note_path, summary_text, "
        "content_hash, updated_at) VALUES (?, ?, ?, ?)",
        ("test.md", "A summary", "abc", "2026-01-01"),
    )
    conn.commit()

    conn.execute("DELETE FROM notes WHERE path = ?", ("test.md",))
    conn.commit()

    chunks = conn.execute(
        "SELECT COUNT(*) as c FROM chunks WHERE note_path = ?",
        ("test.md",),
    ).fetchone()["c"]
    summaries = conn.execute(
        "SELECT COUNT(*) as c FROM summaries WHERE note_path = ?",
        ("test.md",),
    ).fetchone()["c"]
    assert chunks == 0
    assert summaries == 0


def test_migration_from_v1(in_memory_db):
    """Migration pipeline handles v1 → v6 gracefully."""
    conn = in_memory_db
    # Simulate v1 by setting version back
    conn.execute("DELETE FROM schema_version")
    conn.execute("INSERT INTO schema_version VALUES (1)")
    conn.commit()

    _run_migrations(conn)

    row = conn.execute("SELECT MAX(version) as v FROM schema_version").fetchone()
    assert row["v"] == SCHEMA_VERSION


def test_cooccurrence_table_columns(in_memory_db):
    """entity_cooccurrence has correct columns and types."""
    cols = {
        r[1]: r[2]
        for r in in_memory_db.execute(
            "PRAGMA table_info(entity_cooccurrence)"
        ).fetchall()
    }
    assert "entity_a" in cols
    assert "entity_b" in cols
    assert "weight" in cols
    assert "last_seen" in cols


def test_cooccurrence_indexes(in_memory_db):
    """Bidirectional indexes exist on entity_a and entity_b."""
    indexes = {
        row[1]
        for row in in_memory_db.execute(
            "PRAGMA index_list(entity_cooccurrence)"
        ).fetchall()
    }
    assert "idx_cooccurrence_a" in indexes
    assert "idx_cooccurrence_b" in indexes


def test_cooccurrence_composite_pk(in_memory_db):
    """Composite PK rejects duplicate (entity_a, entity_b) pairs."""
    conn = in_memory_db
    conn.execute(
        "INSERT INTO entity_cooccurrence (entity_a, entity_b, weight) "
        "VALUES (?, ?, ?)",
        ("alpha", "beta", 1.0),
    )
    with pytest.raises(_sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO entity_cooccurrence (entity_a, entity_b, weight) "
            "VALUES (?, ?, ?)",
            ("alpha", "beta", 2.0),
        )


def test_migration_v11_to_v12(in_memory_db):
    """Migration from v11 creates entity_cooccurrence without affecting existing tables."""
    conn = in_memory_db
    # Insert test data in existing tables
    conn.execute(
        "INSERT INTO notes (path, title, content_hash, updated_at) "
        "VALUES (?, ?, ?, ?)",
        ("test.md", "Test", "abc", "2026-01-01"),
    )
    conn.commit()

    # Simulate v11 state
    conn.execute("DELETE FROM schema_version")
    conn.execute("INSERT INTO schema_version VALUES (11)")
    conn.commit()

    # Drop the cooccurrence table to simulate pre-v12
    conn.execute("DROP TABLE IF EXISTS entity_cooccurrence")
    conn.commit()

    _run_migrations(conn)

    # Table exists
    tables = {
        row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "entity_cooccurrence" in tables

    # Existing data preserved
    note = conn.execute("SELECT title FROM notes WHERE path = ?", ("test.md",)).fetchone()
    assert note["title"] == "Test"

    # Version bumped
    row = conn.execute("SELECT MAX(version) as v FROM schema_version").fetchone()
    assert row["v"] == 13


def test_migration_v12_idempotent(in_memory_db):
    """Running migration v12 twice does not fail."""
    conn = in_memory_db
    # Simulate v11 state
    conn.execute("DELETE FROM schema_version")
    conn.execute("INSERT INTO schema_version VALUES (11)")
    conn.commit()
    conn.execute("DROP TABLE IF EXISTS entity_cooccurrence")
    conn.commit()

    _run_migrations(conn)
    # Reset version to 11 and run again
    conn.execute("DELETE FROM schema_version")
    conn.execute("INSERT INTO schema_version VALUES (11)")
    conn.commit()
    _run_migrations(conn)

    row = conn.execute("SELECT MAX(version) as v FROM schema_version").fetchone()
    assert row["v"] == 13
