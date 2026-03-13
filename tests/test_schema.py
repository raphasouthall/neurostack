"""Tests for neurostack.schema — database creation and migrations."""


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
