"""Tests for neurostack.memories — agent write-back memory layer."""

import json

import pytest

from neurostack.memories import (
    VALID_ENTITY_TYPES,
    Memory,
    forget_memory,
    get_memory_stats,
    prune_memories,
    save_memory,
    search_memories,
)


class TestSaveMemory:
    def test_basic_save(self, in_memory_db):
        m = save_memory(in_memory_db, content="Test observation")
        assert isinstance(m, Memory)
        assert m.memory_id > 0
        assert m.content == "Test observation"
        assert m.entity_type == "observation"
        assert m.tags == []
        assert m.expires_at is None

    def test_save_with_tags(self, in_memory_db):
        m = save_memory(
            in_memory_db, content="Tagged memory",
            tags=["auth", "security"],
        )
        assert m.tags == ["auth", "security"]

    def test_save_with_entity_type(self, in_memory_db):
        for etype in VALID_ENTITY_TYPES:
            m = save_memory(
                in_memory_db, content=f"Type: {etype}",
                entity_type=etype,
            )
            assert m.entity_type == etype

    def test_save_invalid_entity_type(self, in_memory_db):
        with pytest.raises(ValueError, match="Invalid entity_type"):
            save_memory(in_memory_db, content="Bad", entity_type="invalid")

    def test_save_with_source_agent(self, in_memory_db):
        m = save_memory(
            in_memory_db, content="From cursor",
            source_agent="cursor",
        )
        assert m.source_agent == "cursor"

    def test_save_with_workspace(self, in_memory_db):
        m = save_memory(
            in_memory_db, content="Scoped memory",
            workspace="work/nyk-europe-azure",
        )
        assert m.workspace == "work/nyk-europe-azure"

    def test_save_workspace_normalized(self, in_memory_db):
        m = save_memory(
            in_memory_db, content="Slash stripped",
            workspace="/work/project/",
        )
        assert m.workspace == "work/project"

    def test_save_with_ttl(self, in_memory_db):
        m = save_memory(
            in_memory_db, content="Ephemeral",
            ttl_hours=24,
        )
        assert m.expires_at is not None

    def test_save_without_ttl_no_expiry(self, in_memory_db):
        m = save_memory(in_memory_db, content="Permanent")
        assert m.expires_at is None

    def test_save_persists_to_db(self, in_memory_db):
        save_memory(in_memory_db, content="Persisted")
        row = in_memory_db.execute(
            "SELECT content FROM memories WHERE content = ?",
            ("Persisted",),
        ).fetchone()
        assert row is not None

    def test_save_creates_fts_entry(self, in_memory_db):
        save_memory(in_memory_db, content="unique_searchable_token_abc")
        results = in_memory_db.execute(
            "SELECT * FROM memories_fts WHERE memories_fts MATCH ?",
            ("unique_searchable_token_abc",),
        ).fetchall()
        assert len(results) == 1

    def test_save_tags_stored_as_json(self, in_memory_db):
        save_memory(in_memory_db, content="JSON tags", tags=["a", "b"])
        row = in_memory_db.execute(
            "SELECT tags FROM memories WHERE content = ?",
            ("JSON tags",),
        ).fetchone()
        assert json.loads(row["tags"]) == ["a", "b"]

    def test_sequential_ids(self, in_memory_db):
        m1 = save_memory(in_memory_db, content="First")
        m2 = save_memory(in_memory_db, content="Second")
        assert m2.memory_id > m1.memory_id


class TestForgetMemory:
    def test_forget_existing(self, in_memory_db):
        m = save_memory(in_memory_db, content="To delete")
        assert forget_memory(in_memory_db, m.memory_id) is True

        row = in_memory_db.execute(
            "SELECT * FROM memories WHERE memory_id = ?",
            (m.memory_id,),
        ).fetchone()
        assert row is None

    def test_forget_nonexistent(self, in_memory_db):
        assert forget_memory(in_memory_db, 99999) is False

    def test_forget_removes_fts(self, in_memory_db):
        m = save_memory(in_memory_db, content="fts_delete_test_token")
        forget_memory(in_memory_db, m.memory_id)

        results = in_memory_db.execute(
            "SELECT * FROM memories_fts WHERE memories_fts MATCH ?",
            ("fts_delete_test_token",),
        ).fetchall()
        assert len(results) == 0


class TestSearchMemories:
    @pytest.fixture(autouse=True)
    def seed_memories(self, in_memory_db):
        self.conn = in_memory_db
        save_memory(self.conn, content="Database migration to PostgreSQL",
                    entity_type="decision", tags=["database"])
        save_memory(self.conn, content="Always use parameterized SQL queries",
                    entity_type="convention", tags=["security"])
        save_memory(self.conn, content="Auth module needs refactoring",
                    entity_type="context", workspace="work/auth")
        save_memory(self.conn, content="Fixed race condition in worker pool",
                    entity_type="bug", source_agent="cursor")

    def test_list_all(self):
        results = search_memories(self.conn)
        assert len(results) == 4

    def test_filter_by_type(self):
        results = search_memories(self.conn, entity_type="decision")
        assert len(results) == 1
        assert results[0].entity_type == "decision"

    def test_filter_by_workspace(self):
        results = search_memories(self.conn, workspace="work/auth")
        assert len(results) == 1
        assert "Auth module" in results[0].content

    def test_fts_search(self):
        results = search_memories(self.conn, query="database migration")
        assert len(results) > 0
        assert any("Database" in m.content for m in results)

    def test_fts_search_no_match(self):
        # FTS returns nothing; semantic may return low-score fallbacks
        results = search_memories(self.conn, query="xyznonexistent999")
        # All results should have low scores (< 0.5) if any
        for m in results:
            assert m.score < 0.5

    def test_limit_respected(self):
        results = search_memories(self.conn, limit=2)
        assert len(results) <= 2

    def test_combined_type_and_query(self):
        results = search_memories(
            self.conn, query="SQL", entity_type="convention",
        )
        assert len(results) == 1
        assert results[0].entity_type == "convention"

    def test_expired_excluded(self):
        save_memory(self.conn, content="Already expired", ttl_hours=0)
        # Manually set expiry in the past
        self.conn.execute(
            "UPDATE memories SET expires_at = datetime('now', '-1 hour') "
            "WHERE content = 'Already expired'"
        )
        self.conn.commit()

        results = search_memories(self.conn)
        assert not any("Already expired" in m.content for m in results)


class TestPruneMemories:
    def test_prune_expired(self, in_memory_db):
        save_memory(in_memory_db, content="Active")
        save_memory(in_memory_db, content="Expired", ttl_hours=1)
        # Force expiry into the past
        in_memory_db.execute(
            "UPDATE memories SET expires_at = datetime('now', '-2 hours') "
            "WHERE content = 'Expired'"
        )
        in_memory_db.commit()

        count = prune_memories(in_memory_db, expired_only=True)
        assert count == 1

        remaining = in_memory_db.execute(
            "SELECT COUNT(*) as c FROM memories"
        ).fetchone()["c"]
        assert remaining == 1

    def test_prune_older_than(self, in_memory_db):
        save_memory(in_memory_db, content="Recent")
        save_memory(in_memory_db, content="Old")
        # Force old memory 60 days back
        in_memory_db.execute(
            "UPDATE memories SET created_at = datetime('now', '-60 days') "
            "WHERE content = 'Old'"
        )
        in_memory_db.commit()

        count = prune_memories(in_memory_db, older_than_days=30)
        assert count == 1

    def test_prune_no_args_does_nothing(self, in_memory_db):
        save_memory(in_memory_db, content="Safe")
        count = prune_memories(in_memory_db)
        assert count == 0


class TestMemoryStats:
    def test_empty_stats(self, in_memory_db):
        stats = get_memory_stats(in_memory_db)
        assert stats["total"] == 0
        assert stats["expired"] == 0
        assert stats["embedded"] == 0
        assert stats["by_type"] == {}

    def test_stats_with_data(self, in_memory_db):
        save_memory(in_memory_db, content="Dec 1", entity_type="decision")
        save_memory(in_memory_db, content="Dec 2", entity_type="decision")
        save_memory(in_memory_db, content="Bug 1", entity_type="bug")

        stats = get_memory_stats(in_memory_db)
        assert stats["total"] == 3
        assert stats["by_type"]["decision"] == 2
        assert stats["by_type"]["bug"] == 1


class TestMemorySchemaIntegration:
    def test_memories_table_exists(self, in_memory_db):
        tables = {
            row[0]
            for row in in_memory_db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "memories" in tables
        assert "memories_fts" in tables

    def test_fts_trigger_update(self, in_memory_db):
        m = save_memory(in_memory_db, content="original_token_xyz")

        # Update content
        in_memory_db.execute(
            "UPDATE memories SET content = ? WHERE memory_id = ?",
            ("updated_token_abc", m.memory_id),
        )
        in_memory_db.commit()

        # Old token gone from FTS
        old = in_memory_db.execute(
            "SELECT * FROM memories_fts WHERE memories_fts MATCH ?",
            ("original_token_xyz",),
        ).fetchall()
        assert len(old) == 0

        # New token in FTS
        new = in_memory_db.execute(
            "SELECT * FROM memories_fts WHERE memories_fts MATCH ?",
            ("updated_token_abc",),
        ).fetchall()
        assert len(new) == 1
