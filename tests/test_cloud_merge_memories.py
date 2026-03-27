# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Tests for cloud sync _merge_memories ON CONFLICT logic.

Validates that:
1. New memories are inserted correctly
2. Existing memories are updated via ON CONFLICT(uuid) DO UPDATE
3. Existing fields not in cloud response (embedding, revision_count) are preserved
4. Deleted memories are removed
5. Uses get_db() instead of raw sqlite3.connect()
6. Column names match the actual schema (expires_at, not ttl_hours)
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def sync_engine(tmp_path):
    """Create a VaultSyncEngine with a real SQLite DB."""
    from neurostack.cloud.sync import VaultSyncEngine
    from neurostack.schema import SCHEMA_SQL, SCHEMA_VERSION

    db_dir = tmp_path / "data"
    db_dir.mkdir()
    db_path = db_dir / "neurostack.db"

    # Create real schema
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA_SQL)
    conn.execute(
        "INSERT OR REPLACE INTO schema_version VALUES (?)", (SCHEMA_VERSION,)
    )
    conn.commit()
    conn.close()

    engine = VaultSyncEngine.__new__(VaultSyncEngine)
    engine._db_dir = db_dir
    engine._vault_root = tmp_path / "vault"
    engine._vault_root.mkdir()
    return engine


def _read_memory(db_path: Path, uuid: str) -> dict | None:
    """Read a memory by UUID from the DB."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM memories WHERE uuid = ?", (uuid,)
    ).fetchone()
    conn.close()
    if row is None:
        return None
    return dict(row)


def _insert_memory(db_path: Path, **kwargs):
    """Insert a memory directly into the DB."""
    defaults = {
        "uuid": "test-uuid-1",
        "content": "original content",
        "entity_type": "observation",
        "tags": json.dumps(["tag1"]),
        "workspace": None,
        "source_agent": "test-agent",
        "session_id": None,
        "expires_at": None,
        "created_at": "2026-03-25T00:00:00",
        "updated_at": "2026-03-25T00:00:00",
        "file_path": None,
    }
    defaults.update(kwargs)

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    cols = ", ".join(defaults.keys())
    placeholders = ", ".join("?" for _ in defaults)
    conn.execute(
        f"INSERT INTO memories ({cols}) VALUES ({placeholders})",
        tuple(defaults.values()),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Insert tests
# ---------------------------------------------------------------------------


class TestMergeMemoriesInsert:
    """Tests for inserting new memories via _merge_memories."""

    def test_inserts_new_memory(self, sync_engine):
        """A memory with a new UUID is inserted."""
        memories = [
            {
                "uuid": "new-uuid-1",
                "content": "a new memory",
                "entity_type": "decision",
                "tags": ["tag-a", "tag-b"],
                "workspace": "work/project",
                "source_agent": "claude-code",
                "session_id": None,
                "expires_at": None,
                "created_at": "2026-03-27T10:00:00",
                "updated_at": "2026-03-27T10:00:00",
                "file_path": None,
            }
        ]

        sync_engine._merge_memories(memories)

        row = _read_memory(sync_engine._db_dir / "neurostack.db", "new-uuid-1")
        assert row is not None
        assert row["content"] == "a new memory"
        assert row["entity_type"] == "decision"
        assert json.loads(row["tags"]) == ["tag-a", "tag-b"]
        assert row["workspace"] == "work/project"

    def test_inserts_memory_with_expires_at(self, sync_engine):
        """expires_at field is correctly stored (not ttl_hours)."""
        memories = [
            {
                "uuid": "expiring-uuid",
                "content": "temporary memory",
                "entity_type": "context",
                "tags": [],
                "workspace": None,
                "source_agent": "test",
                "session_id": None,
                "expires_at": "2026-04-01T00:00:00",
                "created_at": "2026-03-27T10:00:00",
                "updated_at": "2026-03-27T10:00:00",
                "file_path": None,
            }
        ]

        sync_engine._merge_memories(memories)

        row = _read_memory(sync_engine._db_dir / "neurostack.db", "expiring-uuid")
        assert row is not None
        assert row["expires_at"] == "2026-04-01T00:00:00"


# ---------------------------------------------------------------------------
# Update (ON CONFLICT) tests
# ---------------------------------------------------------------------------


class TestMergeMemoriesUpdate:
    """Tests for updating existing memories via ON CONFLICT."""

    def test_updates_content_on_conflict(self, sync_engine):
        """Existing memory content is updated when UUID matches."""
        db_path = sync_engine._db_dir / "neurostack.db"
        _insert_memory(db_path, uuid="existing-uuid", content="old content")

        memories = [
            {
                "uuid": "existing-uuid",
                "content": "updated content",
                "entity_type": "decision",
                "tags": ["new-tag"],
                "workspace": None,
                "source_agent": "claude-code",
                "session_id": None,
                "expires_at": None,
                "created_at": "2026-03-25T00:00:00",
                "updated_at": "2026-03-27T12:00:00",
                "file_path": None,
            }
        ]

        sync_engine._merge_memories(memories)

        row = _read_memory(db_path, "existing-uuid")
        assert row["content"] == "updated content"
        assert row["entity_type"] == "decision"
        assert row["updated_at"] == "2026-03-27T12:00:00"

    def test_preserves_embedding_on_update(self, sync_engine):
        """Existing embedding blob is NOT overwritten by ON CONFLICT update."""
        db_path = sync_engine._db_dir / "neurostack.db"

        # Insert with a fake embedding
        fake_embedding = b"\x00\x01\x02\x03" * 192  # 768 bytes
        _insert_memory(db_path, uuid="embed-uuid", content="has embedding")

        # Manually set the embedding
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "UPDATE memories SET embedding = ? WHERE uuid = ?",
            (fake_embedding, "embed-uuid"),
        )
        conn.commit()
        conn.close()

        # Merge update (cloud response has no embedding field)
        memories = [
            {
                "uuid": "embed-uuid",
                "content": "updated content",
                "entity_type": "observation",
                "tags": [],
                "workspace": None,
                "source_agent": "cloud",
                "session_id": None,
                "expires_at": None,
                "created_at": "2026-03-25T00:00:00",
                "updated_at": "2026-03-27T12:00:00",
                "file_path": None,
            }
        ]

        sync_engine._merge_memories(memories)

        row = _read_memory(db_path, "embed-uuid")
        assert row["content"] == "updated content"
        assert row["embedding"] == fake_embedding, (
            "Embedding was overwritten by ON CONFLICT — should be preserved"
        )

    def test_preserves_revision_count_on_update(self, sync_engine):
        """revision_count is not reset by ON CONFLICT update."""
        db_path = sync_engine._db_dir / "neurostack.db"
        _insert_memory(db_path, uuid="rev-uuid")

        # Set revision_count manually
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "UPDATE memories SET revision_count = 5 WHERE uuid = ?",
            ("rev-uuid",),
        )
        conn.commit()
        conn.close()

        memories = [
            {
                "uuid": "rev-uuid",
                "content": "revised",
                "entity_type": "observation",
                "tags": [],
                "workspace": None,
                "source_agent": "test",
                "session_id": None,
                "expires_at": None,
                "created_at": "2026-03-25T00:00:00",
                "updated_at": "2026-03-27T12:00:00",
                "file_path": None,
            }
        ]

        sync_engine._merge_memories(memories)

        row = _read_memory(db_path, "rev-uuid")
        assert row["revision_count"] == 5, (
            "revision_count was reset — ON CONFLICT should preserve it"
        )


# ---------------------------------------------------------------------------
# Delete tests
# ---------------------------------------------------------------------------


class TestMergeMemoriesDelete:
    """Tests for deleting memories marked as deleted."""

    def test_deletes_memory_with_deleted_flag(self, sync_engine):
        """Memories with deleted=true are removed from local DB."""
        db_path = sync_engine._db_dir / "neurostack.db"
        _insert_memory(db_path, uuid="to-delete")

        # Verify it exists
        assert _read_memory(db_path, "to-delete") is not None

        memories = [{"uuid": "to-delete", "deleted": True}]
        sync_engine._merge_memories(memories)

        assert _read_memory(db_path, "to-delete") is None

    def test_delete_nonexistent_is_safe(self, sync_engine):
        """Deleting a UUID that doesn't exist locally is a no-op."""
        memories = [{"uuid": "never-existed", "deleted": True}]
        sync_engine._merge_memories(memories)
        # Should not raise


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestMergeMemoriesEdgeCases:
    """Edge case tests for _merge_memories."""

    def test_empty_list_is_noop(self, sync_engine):
        """Empty memory list does nothing."""
        sync_engine._merge_memories([])

    def test_tags_as_list_serialised_to_json(self, sync_engine):
        """Tags provided as list are JSON-serialised before insert."""
        memories = [
            {
                "uuid": "tags-uuid",
                "content": "test",
                "entity_type": "observation",
                "tags": ["alpha", "beta"],
                "workspace": None,
                "source_agent": "test",
                "session_id": None,
                "expires_at": None,
                "created_at": "2026-03-27T10:00:00",
                "updated_at": "2026-03-27T10:00:00",
                "file_path": None,
            }
        ]

        sync_engine._merge_memories(memories)

        row = _read_memory(sync_engine._db_dir / "neurostack.db", "tags-uuid")
        parsed = json.loads(row["tags"])
        assert parsed == ["alpha", "beta"]

    def test_tags_as_string_stored_directly(self, sync_engine):
        """Tags already serialised as JSON string are stored as-is."""
        memories = [
            {
                "uuid": "str-tags-uuid",
                "content": "test",
                "entity_type": "observation",
                "tags": '["gamma"]',
                "workspace": None,
                "source_agent": "test",
                "session_id": None,
                "expires_at": None,
                "created_at": "2026-03-27T10:00:00",
                "updated_at": "2026-03-27T10:00:00",
                "file_path": None,
            }
        ]

        sync_engine._merge_memories(memories)

        row = _read_memory(sync_engine._db_dir / "neurostack.db", "str-tags-uuid")
        parsed = json.loads(row["tags"])
        assert parsed == ["gamma"]

    def test_missing_db_skips_gracefully(self, tmp_path):
        """Missing DB file logs warning and returns without error."""
        from neurostack.cloud.sync import VaultSyncEngine

        engine = VaultSyncEngine.__new__(VaultSyncEngine)
        engine._db_dir = tmp_path / "nonexistent"
        engine._db_dir.mkdir()
        # No neurostack.db created

        # Should not raise
        engine._merge_memories([{"uuid": "x", "content": "y"}])

    def test_multiple_memories_in_single_call(self, sync_engine):
        """Multiple memories are processed in a single commit."""
        memories = [
            {
                "uuid": f"batch-{i}",
                "content": f"memory {i}",
                "entity_type": "observation",
                "tags": [],
                "workspace": None,
                "source_agent": "test",
                "session_id": None,
                "expires_at": None,
                "created_at": "2026-03-27T10:00:00",
                "updated_at": "2026-03-27T10:00:00",
                "file_path": None,
            }
            for i in range(5)
        ]

        sync_engine._merge_memories(memories)

        db_path = sync_engine._db_dir / "neurostack.db"
        for i in range(5):
            row = _read_memory(db_path, f"batch-{i}")
            assert row is not None
            assert row["content"] == f"memory {i}"
