# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Tests for the vault diff / change feed (issue #11)."""

import pytest

from neurostack import config as nsconfig
from neurostack.diff import compute_diff, save_checkpoint


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROSTACK_DB_DIR", str(tmp_path))
    nsconfig._config = None
    from neurostack.schema import get_db

    conn = get_db(tmp_path / "t.db")
    yield conn
    conn.close()
    nsconfig._config = None


def _add(conn, path, content_hash, title=None,
         updated_at="2026-07-01T00:00:00+00:00"):
    conn.execute(
        "INSERT OR REPLACE INTO notes (path, title, content_hash, updated_at)"
        " VALUES (?, ?, ?, ?)",
        (path, title or path, content_hash, updated_at),
    )
    conn.commit()


class TestBaselineMode:
    def test_no_baseline_everything_is_added(self, db):
        _add(db, "a.md", "h1")
        _add(db, "b.md", "h2")
        d = compute_diff(db)
        assert d["mode"] == "baseline"
        assert d["has_baseline"] is False
        assert d["added_count"] == 2
        assert {x["path"] for x in d["added"]} == {"a.md", "b.md"}
        assert d["modified_count"] == 0 and d["deleted_count"] == 0

    def test_checkpoint_then_no_changes(self, db):
        _add(db, "a.md", "h1")
        ck = save_checkpoint(db)
        assert ck["notes"] == 1
        d = compute_diff(db)
        assert d["has_baseline"] is True
        assert d["added_count"] == d["modified_count"] == d["deleted_count"] == 0
        assert d["baseline_saved_at"] == ck["saved_at"]

    def test_add_modify_delete(self, db):
        _add(db, "keep.md", "h1")
        _add(db, "gone.md", "h2")
        _add(db, "edit.md", "h3")
        save_checkpoint(db)
        db.execute("DELETE FROM notes WHERE path = ?", ("gone.md",))
        db.execute(
            "UPDATE notes SET content_hash = ? WHERE path = ?", ("h3b", "edit.md")
        )
        _add(db, "new.md", "h4")
        d = compute_diff(db)
        assert {x["path"] for x in d["added"]} == {"new.md"}
        assert {x["path"] for x in d["modified"]} == {"edit.md"}
        assert {x["path"] for x in d["deleted"]} == {"gone.md"}
        # unchanged note must not appear anywhere
        touched = {x["path"] for x in d["added"] + d["modified"]} | {
            x["path"] for x in d["deleted"]
        }
        assert "keep.md" not in touched

    def test_named_baselines_are_independent(self, db):
        _add(db, "a.md", "h1")
        save_checkpoint(db, baseline="loop-a")
        _add(db, "b.md", "h2")  # added after loop-a's checkpoint
        da = compute_diff(db, baseline="loop-a")
        assert {x["path"] for x in da["added"]} == {"b.md"}
        db_fresh = compute_diff(db, baseline="loop-b")  # never checkpointed
        assert db_fresh["has_baseline"] is False
        assert db_fresh["added_count"] == 2

    def test_checkpoint_overwrites(self, db):
        _add(db, "a.md", "h1")
        save_checkpoint(db)
        _add(db, "b.md", "h2")
        save_checkpoint(db)  # baseline now includes both
        assert compute_diff(db)["added_count"] == 0


class TestDateMode:
    def test_since_filters_by_updated_at(self, db):
        _add(db, "old.md", "h1", updated_at="2026-06-01T00:00:00+00:00")
        _add(db, "new.md", "h2", updated_at="2026-07-04T00:00:00+00:00")
        d = compute_diff(db, since="2026-07-01")
        assert d["mode"] == "since_date"
        assert {x["path"] for x in d["changed"]} == {"new.md"}
        assert d["changed_count"] == 1

    def test_since_ignores_baseline_keys(self, db):
        _add(db, "n.md", "h1", updated_at="2026-07-04T00:00:00+00:00")
        d = compute_diff(db, since="2026-01-01", baseline="whatever")
        assert d["mode"] == "since_date"
        assert "added" not in d and "deleted" not in d


def test_fresh_db_has_diff_snapshots(db):
    # A fresh get_db stamps v20 via SCHEMA_SQL; the table must exist.
    row = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='diff_snapshots'"
    ).fetchone()
    assert row is not None
    v = db.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()["v"]
    assert v >= 20


def test_v19_upgrade_creates_diff_snapshots():
    # The path that runs on the live LXC 122 DB: the lazy migration must create
    # diff_snapshots and run cleanly through to the current schema version.
    import sqlite3

    from neurostack.schema import SCHEMA_VERSION, _run_migrations

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY)")
    conn.execute("INSERT INTO schema_version VALUES (19)")
    # A real v19 DB has prediction_errors (later migrations ALTER it), so seed it.
    conn.execute(
        "CREATE TABLE prediction_errors (error_id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " note_path TEXT NOT NULL, query TEXT NOT NULL, cosine_distance REAL NOT NULL,"
        " error_type TEXT NOT NULL, context TEXT,"
        " detected_at TEXT NOT NULL DEFAULT (datetime('now')), resolved_at TEXT)"
    )
    conn.commit()
    assert conn.execute(
        "SELECT name FROM sqlite_master WHERE name='diff_snapshots'"
    ).fetchone() is None

    _run_migrations(conn)

    assert conn.execute(
        "SELECT name FROM sqlite_master WHERE name='diff_snapshots'"
    ).fetchone() is not None
    assert conn.execute(
        "SELECT MAX(version) AS v FROM schema_version"
    ).fetchone()["v"] == SCHEMA_VERSION

