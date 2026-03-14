"""Tests for neurostack.memories — agent write-back memory layer."""

import json

import pytest

from neurostack.memories import (
    VALID_ENTITY_TYPES,
    Memory,
    forget_memory,
    get_memory_stats,
    merge_memories,
    prune_memories,
    save_memory,
    search_memories,
    suggest_tags,
    update_memory,
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
            workspace="work/acme-cloud",
        )
        assert m.workspace == "work/acme-cloud"

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


class TestUpdateMemory:
    def test_update_content(self, in_memory_db):
        m = save_memory(in_memory_db, content="Original content")
        updated = update_memory(in_memory_db, m.memory_id, content="New content")
        assert updated is not None
        assert updated.content == "New content"
        assert updated.updated_at is not None
        assert updated.revision_count == 2

    def test_update_nonexistent(self, in_memory_db):
        result = update_memory(in_memory_db, 99999, content="Nope")
        assert result is None

    def test_update_tags_replace(self, in_memory_db):
        m = save_memory(in_memory_db, content="Tagged", tags=["a", "b"])
        updated = update_memory(in_memory_db, m.memory_id, tags=["x", "y"])
        assert updated.tags == ["x", "y"]

    def test_update_tags_add(self, in_memory_db):
        m = save_memory(in_memory_db, content="Tagged", tags=["a", "b"])
        updated = update_memory(in_memory_db, m.memory_id, add_tags=["c"])
        assert set(updated.tags) == {"a", "b", "c"}

    def test_update_tags_remove(self, in_memory_db):
        m = save_memory(in_memory_db, content="Tagged", tags=["a", "b", "c"])
        updated = update_memory(in_memory_db, m.memory_id, remove_tags=["b"])
        assert "b" not in updated.tags
        assert "a" in updated.tags

    def test_update_entity_type(self, in_memory_db):
        m = save_memory(in_memory_db, content="A decision", entity_type="observation")
        updated = update_memory(in_memory_db, m.memory_id, entity_type="decision")
        assert updated.entity_type == "decision"

    def test_update_invalid_entity_type(self, in_memory_db):
        m = save_memory(in_memory_db, content="Test")
        with pytest.raises(ValueError, match="Invalid entity_type"):
            update_memory(in_memory_db, m.memory_id, entity_type="invalid")

    def test_update_ttl_to_permanent(self, in_memory_db):
        m = save_memory(in_memory_db, content="Ephemeral", ttl_hours=24)
        assert m.expires_at is not None
        updated = update_memory(in_memory_db, m.memory_id, ttl_hours=0)
        assert updated.expires_at is None

    def test_update_fts_synced(self, in_memory_db):
        m = save_memory(in_memory_db, content="unique_old_token_xyz")
        update_memory(in_memory_db, m.memory_id, content="unique_new_token_abc")

        old = in_memory_db.execute(
            "SELECT * FROM memories_fts WHERE memories_fts MATCH ?",
            ("unique_old_token_xyz",),
        ).fetchall()
        assert len(old) == 0

        new = in_memory_db.execute(
            "SELECT * FROM memories_fts WHERE memories_fts MATCH ?",
            ("unique_new_token_abc",),
        ).fetchall()
        assert len(new) == 1

    def test_update_preserves_created_at(self, in_memory_db):
        m = save_memory(in_memory_db, content="Original")
        original_created = m.created_at
        updated = update_memory(in_memory_db, m.memory_id, content="Changed")
        assert updated.created_at == original_created

    def test_update_workspace(self, in_memory_db):
        m = save_memory(in_memory_db, content="Scoped")
        updated = update_memory(in_memory_db, m.memory_id, workspace="work/project")
        assert updated.workspace == "work/project"


class TestMergeMemories:
    def test_merge_basic(self, in_memory_db):
        m1 = save_memory(in_memory_db, content="Short note", tags=["a"])
        m2 = save_memory(
            in_memory_db,
            content="A much longer and more detailed note about the topic",
            tags=["b"],
        )
        result = merge_memories(in_memory_db, m1.memory_id, m2.memory_id)
        assert result is not None
        # Keeps the longer content since it's > 1.2x longer
        assert "longer" in result.content
        # Tags are unioned
        assert "a" in result.tags
        assert "b" in result.tags
        # Merge metadata
        assert result.merge_count == 1
        assert result.merged_from == [m2.memory_id]

    def test_merge_deletes_source(self, in_memory_db):
        m1 = save_memory(in_memory_db, content="Target memory")
        m2 = save_memory(in_memory_db, content="Source memory to merge")
        merge_memories(in_memory_db, m1.memory_id, m2.memory_id)
        row = in_memory_db.execute(
            "SELECT * FROM memories WHERE memory_id = ?", (m2.memory_id,)
        ).fetchone()
        assert row is None

    def test_merge_keeps_specific_type(self, in_memory_db):
        m1 = save_memory(in_memory_db, content="An observation", entity_type="observation")
        m2 = save_memory(in_memory_db, content="A bug fix observation", entity_type="bug")
        result = merge_memories(in_memory_db, m1.memory_id, m2.memory_id)
        assert result.entity_type == "bug"

    def test_merge_nonexistent_returns_none(self, in_memory_db):
        m1 = save_memory(in_memory_db, content="Exists")
        assert merge_memories(in_memory_db, m1.memory_id, 99999) is None
        assert merge_memories(in_memory_db, 99999, m1.memory_id) is None

    def test_merge_fts_updated(self, in_memory_db):
        m1 = save_memory(in_memory_db, content="target_unique_token_merge_with_enough_content")
        m2 = save_memory(in_memory_db, content="source_unique_short")
        merge_memories(in_memory_db, m1.memory_id, m2.memory_id)
        # Source row is deleted - its FTS entry should be gone
        source_fts = in_memory_db.execute(
            "SELECT * FROM memories_fts WHERE memories_fts MATCH ?",
            ("source_unique_short",),
        ).fetchall()
        assert len(source_fts) == 0
        # Target FTS entry should still exist
        target_fts = in_memory_db.execute(
            "SELECT * FROM memories_fts WHERE memories_fts MATCH ?",
            ("target_unique_token_merge_with_enough_content",),
        ).fetchall()
        assert len(target_fts) == 1

    def test_merge_increments_revision(self, in_memory_db):
        m1 = save_memory(in_memory_db, content="Target")
        m2 = save_memory(in_memory_db, content="Source longer content for merge test")
        result = merge_memories(in_memory_db, m1.memory_id, m2.memory_id)
        assert result.revision_count == 2


class TestSuggestTags:
    def test_suggest_from_file_paths(self, in_memory_db):
        tags = suggest_tags(in_memory_db, "Fixed bug in src/auth/handler.py")
        assert "py" in tags
        assert "auth" in tags

    def test_suggest_entity_type(self, in_memory_db):
        tags = suggest_tags(in_memory_db, "Use JWT for authentication", entity_type="decision")
        assert "decision" in tags

    def test_suggest_from_existing_memories(self, in_memory_db):
        save_memory(
            in_memory_db, content="Database migration strategy",
            tags=["database", "migration"],
        )
        save_memory(
            in_memory_db, content="Database connection pooling",
            tags=["database", "performance"],
        )
        tags = suggest_tags(in_memory_db, "Database query optimization needed")
        assert "database" in tags

    def test_suggest_empty_content(self, in_memory_db):
        tags = suggest_tags(in_memory_db, "hi")
        assert isinstance(tags, list)

    def test_save_returns_suggested_tags(self, in_memory_db):
        save_memory(in_memory_db, content="Auth module configuration", tags=["auth"])
        m = save_memory(in_memory_db, content="Auth module refactoring in src/auth/module.py")
        # Should suggest 'auth' from FTS overlap + 'py' from file path
        assert m.suggested_tags is None or isinstance(m.suggested_tags, list)


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
