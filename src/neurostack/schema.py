# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""SQLite schema and database management for NeuroStack."""

import logging
import sqlite3
import uuid
from pathlib import Path

from .config import get_config

log = logging.getLogger("neurostack")

_cfg = get_config()
DB_DIR = _cfg.db_dir
DB_PATH = _cfg.db_path

SCHEMA_VERSION = 10

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS notes (
    path TEXT PRIMARY KEY,
    title TEXT,
    frontmatter JSON,
    content_hash TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS chunks (
    chunk_id INTEGER PRIMARY KEY AUTOINCREMENT,
    note_path TEXT REFERENCES notes(path) ON DELETE CASCADE,
    heading_path TEXT,
    content TEXT,
    content_hash TEXT,
    position INTEGER,
    embedding BLOB
);

CREATE INDEX IF NOT EXISTS idx_chunks_note ON chunks(note_path);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    content,
    content='chunks',
    content_rowid='chunk_id'
);

-- FTS sync triggers
CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts(rowid, content) VALUES (new.chunk_id, new.content);
END;

CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, content) VALUES('delete', old.chunk_id, old.content);
END;

CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, content) VALUES('delete', old.chunk_id, old.content);
    INSERT INTO chunks_fts(rowid, content) VALUES (new.chunk_id, new.content);
END;

CREATE TABLE IF NOT EXISTS summaries (
    note_path TEXT PRIMARY KEY REFERENCES notes(path) ON DELETE CASCADE,
    summary_text TEXT,
    content_hash TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS graph_edges (
    source_path TEXT,
    target_path TEXT,
    link_text TEXT,
    PRIMARY KEY (source_path, target_path)
);

CREATE TABLE IF NOT EXISTS graph_stats (
    note_path TEXT PRIMARY KEY,
    in_degree INTEGER DEFAULT 0,
    out_degree INTEGER DEFAULT 0,
    pagerank REAL DEFAULT 0.0
);

-- Knowledge graph triples (Phase 2: structured encoding)
CREATE TABLE IF NOT EXISTS triples (
    triple_id INTEGER PRIMARY KEY AUTOINCREMENT,
    note_path TEXT REFERENCES notes(path) ON DELETE CASCADE,
    subject TEXT NOT NULL,
    predicate TEXT NOT NULL,
    object TEXT NOT NULL,
    triple_text TEXT NOT NULL,
    embedding BLOB,
    content_hash TEXT,
    updated_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_triples_note ON triples(note_path);
CREATE INDEX IF NOT EXISTS idx_triples_subject ON triples(subject);
CREATE INDEX IF NOT EXISTS idx_triples_object ON triples(object);

CREATE VIRTUAL TABLE IF NOT EXISTS triples_fts USING fts5(
    triple_text,
    content='triples',
    content_rowid='triple_id'
);

-- FTS sync triggers for triples
CREATE TRIGGER IF NOT EXISTS triples_ai AFTER INSERT ON triples BEGIN
    INSERT INTO triples_fts(rowid, triple_text) VALUES (new.triple_id, new.triple_text);
END;

CREATE TRIGGER IF NOT EXISTS triples_ad AFTER DELETE ON triples BEGIN
    INSERT INTO triples_fts(triples_fts, rowid, triple_text)
        VALUES('delete', old.triple_id, old.triple_text);
END;

CREATE TRIGGER IF NOT EXISTS triples_au AFTER UPDATE ON triples BEGIN
    INSERT INTO triples_fts(triples_fts, rowid, triple_text)
        VALUES('delete', old.triple_id, old.triple_text);
    INSERT INTO triples_fts(rowid, triple_text)
        VALUES (new.triple_id, new.triple_text);
END;

-- GraphRAG community tables (Phase 3: Leiden community detection)
CREATE TABLE IF NOT EXISTS communities (
    community_id INTEGER PRIMARY KEY AUTOINCREMENT,
    level INTEGER NOT NULL,
    title TEXT,
    summary TEXT,
    summary_embedding BLOB,
    entity_count INTEGER DEFAULT 0,
    member_notes INTEGER DEFAULT 0,
    updated_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_communities_level ON communities(level);

CREATE TABLE IF NOT EXISTS community_members (
    community_id INTEGER REFERENCES communities(community_id) ON DELETE CASCADE,
    entity TEXT NOT NULL,
    PRIMARY KEY (community_id, entity)
);

CREATE INDEX IF NOT EXISTS idx_community_members_entity ON community_members(entity);

-- Folder-level aggregate summaries for semantic context= boosting
CREATE TABLE IF NOT EXISTS folder_summaries (
    folder_path TEXT PRIMARY KEY,
    summary_text TEXT,
    embedding BLOB,
    note_count INTEGER DEFAULT 0,
    generated_at TEXT
);

-- Usage tracking for hotness scoring
CREATE TABLE IF NOT EXISTS note_usage (
    usage_id INTEGER PRIMARY KEY AUTOINCREMENT,
    note_path TEXT NOT NULL,
    used_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_note_usage_path ON note_usage(note_path);
CREATE INDEX IF NOT EXISTS idx_note_usage_time ON note_usage(used_at);

-- Prediction error log: signal-driven vault maintenance
-- Populated at retrieval time when cosine distance exceeds threshold.
-- error_type: 'low_overlap' | 'contextual_mismatch'
CREATE TABLE IF NOT EXISTS prediction_errors (
    error_id INTEGER PRIMARY KEY AUTOINCREMENT,
    note_path TEXT NOT NULL,
    query TEXT NOT NULL,
    cosine_distance REAL NOT NULL,
    error_type TEXT NOT NULL,
    context TEXT,
    detected_at TEXT NOT NULL DEFAULT (datetime('now')),
    resolved_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_pred_errors_note ON prediction_errors(note_path);
CREATE INDEX IF NOT EXISTS idx_pred_errors_type ON prediction_errors(error_type);
CREATE INDEX IF NOT EXISTS idx_pred_errors_unresolved
    ON prediction_errors(resolved_at) WHERE resolved_at IS NULL;

-- Agent-written memories (write-back layer)
CREATE TABLE IF NOT EXISTS memories (
    memory_id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,
    tags JSON,
    entity_type TEXT NOT NULL DEFAULT 'observation',
    source_agent TEXT,
    workspace TEXT,
    session_id INTEGER REFERENCES memory_sessions(session_id),
    embedding BLOB,
    updated_at TEXT,
    revision_count INTEGER NOT NULL DEFAULT 1,
    merge_count INTEGER NOT NULL DEFAULT 0,
    merged_from JSON,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at TEXT,
    uuid TEXT,
    file_path TEXT
);

CREATE INDEX IF NOT EXISTS idx_memories_type ON memories(entity_type);
CREATE INDEX IF NOT EXISTS idx_memories_workspace ON memories(workspace);
CREATE INDEX IF NOT EXISTS idx_memories_expires ON memories(expires_at)
    WHERE expires_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_memories_session
    ON memories(session_id) WHERE session_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_memories_embedded ON memories(memory_id)
    WHERE embedding IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_memories_uuid ON memories(uuid);

CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    content,
    content='memories',
    content_rowid='memory_id'
);

CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, content) VALUES (new.memory_id, new.content);
END;

CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content)
        VALUES('delete', old.memory_id, old.content);
END;

CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content)
        VALUES('delete', old.memory_id, old.content);
    INSERT INTO memories_fts(rowid, content)
        VALUES (new.memory_id, new.content);
END;

-- Session lifecycle tracking for memories
CREATE TABLE IF NOT EXISTS memory_sessions (
    session_id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL DEFAULT (datetime('now')),
    ended_at TEXT,
    source_agent TEXT,
    workspace TEXT,
    summary TEXT
);

CREATE INDEX IF NOT EXISTS idx_memory_sessions_workspace
    ON memory_sessions(workspace);
"""

# Migration from v1 to v2: add triples tables
MIGRATION_V2 = """
CREATE TABLE IF NOT EXISTS triples (
    triple_id INTEGER PRIMARY KEY AUTOINCREMENT,
    note_path TEXT REFERENCES notes(path) ON DELETE CASCADE,
    subject TEXT NOT NULL,
    predicate TEXT NOT NULL,
    object TEXT NOT NULL,
    triple_text TEXT NOT NULL,
    embedding BLOB,
    content_hash TEXT,
    updated_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_triples_note ON triples(note_path);
CREATE INDEX IF NOT EXISTS idx_triples_subject ON triples(subject);
CREATE INDEX IF NOT EXISTS idx_triples_object ON triples(object);

CREATE VIRTUAL TABLE IF NOT EXISTS triples_fts USING fts5(
    triple_text,
    content='triples',
    content_rowid='triple_id'
);

CREATE TRIGGER IF NOT EXISTS triples_ai AFTER INSERT ON triples BEGIN
    INSERT INTO triples_fts(rowid, triple_text) VALUES (new.triple_id, new.triple_text);
END;

CREATE TRIGGER IF NOT EXISTS triples_ad AFTER DELETE ON triples BEGIN
    INSERT INTO triples_fts(triples_fts, rowid, triple_text)
        VALUES('delete', old.triple_id, old.triple_text);
END;

CREATE TRIGGER IF NOT EXISTS triples_au AFTER UPDATE ON triples BEGIN
    INSERT INTO triples_fts(triples_fts, rowid, triple_text)
        VALUES('delete', old.triple_id, old.triple_text);
    INSERT INTO triples_fts(rowid, triple_text)
        VALUES (new.triple_id, new.triple_text);
END;
"""

# Migration from v2 to v3: add GraphRAG community tables
MIGRATION_V3 = """
CREATE TABLE IF NOT EXISTS communities (
    community_id INTEGER PRIMARY KEY AUTOINCREMENT,
    level INTEGER NOT NULL,
    title TEXT,
    summary TEXT,
    summary_embedding BLOB,
    entity_count INTEGER DEFAULT 0,
    member_notes INTEGER DEFAULT 0,
    updated_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_communities_level ON communities(level);

CREATE TABLE IF NOT EXISTS community_members (
    community_id INTEGER REFERENCES communities(community_id) ON DELETE CASCADE,
    entity TEXT NOT NULL,
    PRIMARY KEY (community_id, entity)
);

CREATE INDEX IF NOT EXISTS idx_community_members_entity ON community_members(entity);
"""

# Migration from v3 to v4: add note_usage table for hotness scoring
MIGRATION_V4 = """
CREATE TABLE IF NOT EXISTS note_usage (
    usage_id INTEGER PRIMARY KEY AUTOINCREMENT,
    note_path TEXT NOT NULL,
    used_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_note_usage_path ON note_usage(note_path);
CREATE INDEX IF NOT EXISTS idx_note_usage_time ON note_usage(used_at);
"""

# Migration from v4 to v5: add folder_summaries table
MIGRATION_V5 = """
CREATE TABLE IF NOT EXISTS folder_summaries (
    folder_path TEXT PRIMARY KEY,
    summary_text TEXT,
    embedding BLOB,
    note_count INTEGER DEFAULT 0,
    generated_at TEXT
);
"""

# Migration from v5 to v6: add prediction_errors table
MIGRATION_V6 = """
CREATE TABLE IF NOT EXISTS prediction_errors (
    error_id INTEGER PRIMARY KEY AUTOINCREMENT,
    note_path TEXT NOT NULL,
    query TEXT NOT NULL,
    cosine_distance REAL NOT NULL,
    error_type TEXT NOT NULL,
    context TEXT,
    detected_at TEXT NOT NULL DEFAULT (datetime('now')),
    resolved_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_pred_errors_note ON prediction_errors(note_path);
CREATE INDEX IF NOT EXISTS idx_pred_errors_type ON prediction_errors(error_type);
CREATE INDEX IF NOT EXISTS idx_pred_errors_unresolved
    ON prediction_errors(resolved_at) WHERE resolved_at IS NULL;
"""


# Migration from v6 to v7: add memories table (agent write-back)
MIGRATION_V7 = """
CREATE TABLE IF NOT EXISTS memories (
    memory_id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,
    tags JSON,
    entity_type TEXT NOT NULL DEFAULT 'observation',
    source_agent TEXT,
    workspace TEXT,
    embedding BLOB,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_memories_type ON memories(entity_type);
CREATE INDEX IF NOT EXISTS idx_memories_workspace ON memories(workspace);
CREATE INDEX IF NOT EXISTS idx_memories_expires ON memories(expires_at)
    WHERE expires_at IS NOT NULL;

CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    content,
    content='memories',
    content_rowid='memory_id'
);

CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, content) VALUES (new.memory_id, new.content);
END;

CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content)
        VALUES('delete', old.memory_id, old.content);
END;

CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content)
        VALUES('delete', old.memory_id, old.content);
    INSERT INTO memories_fts(rowid, content)
        VALUES (new.memory_id, new.content);
END;
"""

# Migration from v7 to v8: add session lifecycle tracking
MIGRATION_V8 = """
CREATE TABLE IF NOT EXISTS memory_sessions (
    session_id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL DEFAULT (datetime('now')),
    ended_at TEXT,
    source_agent TEXT,
    workspace TEXT,
    summary TEXT
);

CREATE INDEX IF NOT EXISTS idx_memory_sessions_workspace
    ON memory_sessions(workspace);

ALTER TABLE memories ADD COLUMN session_id INTEGER
    REFERENCES memory_sessions(session_id);

CREATE INDEX IF NOT EXISTS idx_memories_session
    ON memories(session_id) WHERE session_id IS NOT NULL;
"""


# Migration from v8 to v9: add memory revision tracking columns
MIGRATION_V9 = """
ALTER TABLE memories ADD COLUMN updated_at TEXT;
ALTER TABLE memories ADD COLUMN revision_count INTEGER NOT NULL DEFAULT 1;
ALTER TABLE memories ADD COLUMN merge_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE memories ADD COLUMN merged_from JSON;
CREATE INDEX IF NOT EXISTS idx_memories_embedded ON memories(memory_id)
    WHERE embedding IS NOT NULL;
"""


# Migration from v9 to v10: add uuid and file_path to memories
MIGRATION_V10 = """
ALTER TABLE memories ADD COLUMN uuid TEXT;
ALTER TABLE memories ADD COLUMN file_path TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS idx_memories_uuid
    ON memories(uuid);
"""


def _run_migrations(conn: sqlite3.Connection):
    """Run schema migrations if needed."""
    row = conn.execute("SELECT MAX(version) as v FROM schema_version").fetchone()
    current = row["v"] if row else 0

    if current < 2:
        log.info("Migrating schema v1 -> v2: adding triples tables...")
        conn.executescript(MIGRATION_V2)
        conn.execute("INSERT OR REPLACE INTO schema_version VALUES (2)")
        conn.commit()
        log.info("Migration to v2 complete.")

    if current < 3:
        log.info("Migrating schema v2 -> v3: adding GraphRAG community tables...")
        conn.executescript(MIGRATION_V3)
        conn.execute("INSERT OR REPLACE INTO schema_version VALUES (3)")
        conn.commit()
        log.info("Migration to v3 complete.")

    if current < 4:
        log.info("Migrating schema v3 -> v4: adding note_usage table...")
        conn.executescript(MIGRATION_V4)
        conn.execute("INSERT OR REPLACE INTO schema_version VALUES (4)")
        conn.commit()
        log.info("Migration to v4 complete.")

    if current < 5:
        log.info("Migrating schema v4 -> v5: adding folder_summaries table...")
        conn.executescript(MIGRATION_V5)
        conn.execute("INSERT OR REPLACE INTO schema_version VALUES (5)")
        conn.commit()
        log.info("Migration to v5 complete.")

    if current < 6:
        log.info("Migrating schema v5 -> v6: adding prediction_errors table...")
        conn.executescript(MIGRATION_V6)
        conn.execute("INSERT OR REPLACE INTO schema_version VALUES (6)")
        conn.commit()
        log.info("Migration to v6 complete.")

    if current < 7:
        log.info("Migrating schema v6 -> v7: adding memories table...")
        conn.executescript(MIGRATION_V7)
        conn.execute("INSERT OR REPLACE INTO schema_version VALUES (7)")
        conn.commit()
        log.info("Migration to v7 complete.")

    if current < 8:
        log.info("Migrating schema v7 -> v8: adding session lifecycle...")
        # Create session table and index (idempotent)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS memory_sessions (
                session_id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL DEFAULT (datetime('now')),
                ended_at TEXT,
                source_agent TEXT,
                workspace TEXT,
                summary TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_memory_sessions_workspace
                ON memory_sessions(workspace);
            CREATE INDEX IF NOT EXISTS idx_memories_session
                ON memories(session_id)
                WHERE session_id IS NOT NULL;
        """)
        # ALTER TABLE doesn't support IF NOT EXISTS -
        # check column existence first
        cols = {
            r[1] for r in conn.execute(
                "PRAGMA table_info(memories)"
            ).fetchall()
        }
        if "session_id" not in cols:
            conn.execute(
                "ALTER TABLE memories ADD COLUMN session_id"
                " INTEGER REFERENCES memory_sessions(session_id)"
            )
        conn.execute(
            "INSERT OR REPLACE INTO schema_version VALUES (8)"
        )
        conn.commit()
        log.info("Migration to v8 complete.")

    if current < 9:
        log.info("Migrating schema v8 -> v9: adding memory revision tracking...")
        # Create partial index (idempotent)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_memories_embedded"
            " ON memories(memory_id) WHERE embedding IS NOT NULL"
        )
        # ALTER TABLE doesn't support IF NOT EXISTS -
        # check column existence first
        cols = {
            r[1] for r in conn.execute(
                "PRAGMA table_info(memories)"
            ).fetchall()
        }
        if "updated_at" not in cols:
            conn.execute(
                "ALTER TABLE memories ADD COLUMN updated_at TEXT"
            )
        if "revision_count" not in cols:
            conn.execute(
                "ALTER TABLE memories ADD COLUMN"
                " revision_count INTEGER NOT NULL DEFAULT 1"
            )
        if "merge_count" not in cols:
            conn.execute(
                "ALTER TABLE memories ADD COLUMN"
                " merge_count INTEGER NOT NULL DEFAULT 0"
            )
        if "merged_from" not in cols:
            conn.execute(
                "ALTER TABLE memories ADD COLUMN merged_from JSON"
            )
        conn.execute(
            "INSERT OR REPLACE INTO schema_version VALUES (9)"
        )
        conn.commit()
        log.info("Migration to v9 complete.")

    if current < 10:
        log.info(
            "Migrating schema v9 -> v10: "
            "adding uuid and file_path to memories..."
        )
        # ALTER TABLE doesn't support IF NOT EXISTS -
        # check column existence first
        cols = {
            r[1] for r in conn.execute(
                "PRAGMA table_info(memories)"
            ).fetchall()
        }
        if "uuid" not in cols:
            conn.execute(
                "ALTER TABLE memories ADD COLUMN uuid TEXT"
            )
        if "file_path" not in cols:
            conn.execute(
                "ALTER TABLE memories"
                " ADD COLUMN file_path TEXT"
            )
        # Backfill existing rows with UUID4 values
        rows = conn.execute(
            "SELECT memory_id FROM memories"
            " WHERE uuid IS NULL"
        ).fetchall()
        for r in rows:
            conn.execute(
                "UPDATE memories SET uuid = ?"
                " WHERE memory_id = ?",
                (str(uuid.uuid4()), r[0]),
            )
        # Recreate index after backfill
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS"
            " idx_memories_uuid ON memories(uuid)"
        )
        conn.execute(
            "INSERT OR REPLACE INTO schema_version"
            " VALUES (10)"
        )
        conn.commit()
        log.info("Migration to v10 complete.")


def get_db(db_path: Path = DB_PATH) -> sqlite3.Connection:
    """Get a database connection, creating schema if needed."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=60.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=60000")  # Wait up to 60s for locks
    conn.row_factory = sqlite3.Row

    # Check if schema exists
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
    ).fetchone()

    if not tables:
        conn.executescript(SCHEMA_SQL)
        conn.execute(
            "INSERT OR REPLACE INTO schema_version VALUES (?)", (SCHEMA_VERSION,)
        )
        conn.commit()
    else:
        _run_migrations(conn)

    return conn
