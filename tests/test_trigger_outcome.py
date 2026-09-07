# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Tests for fired-but-ignored triggers (issue #136)."""

import json

import pytest

from neurostack import config as nsconfig
from neurostack.triggers import (
    RETIRE_AFTER_IGNORES,
    match_triggers,
    record_fired,
    record_outcome,
)


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROSTACK_DB_DIR", str(tmp_path))
    nsconfig._config = None
    from neurostack.schema import get_db

    conn = get_db()
    yield conn
    conn.close()
    nsconfig._config = None


def _add_memory(conn, content, tags):
    cur = conn.execute(
        "INSERT INTO memories (content, entity_type, tags)"
        " VALUES (?, 'convention', ?)",
        (content, json.dumps(tags)),
    )
    conn.commit()
    return cur.lastrowid


def _ignored_rows(conn, mid):
    return conn.execute(
        "SELECT note_path, cosine_distance, context, resolved_at FROM prediction_errors"
        " WHERE memory_id = ? AND error_type = 'trigger_ignored'", (mid,),
    ).fetchall()


def _fire(conn, event, value, session_hint=None):
    hits = match_triggers(conn, event, value)
    record_fired(conn, hits, event, value, session_hint=session_hint)
    return hits


class TestTriggerLog:
    def test_one_row_per_hit(self, db):
        a = _add_memory(db, "Use vault_update_memory for existing notes",
                        ["when-calling:vault_write_file"])
        b = _add_memory(db, "Push after every vault write", ["when-calling:vault_write_file"])
        hits = _fire(db, "calling", "vault_write_file", session_hint="sess-1")
        assert {h["memory_id"] for h in hits} == {a, b}
        rows = db.execute(
            "SELECT memory_id, event, value, session_hint FROM trigger_log ORDER BY memory_id"
        ).fetchall()
        assert [tuple(r) for r in rows] == [
            (a, "calling", "vault_write_file", "sess-1"),
            (b, "calling", "vault_write_file", "sess-1"),
        ]

    def test_zero_hits_write_nothing(self, db):
        _add_memory(db, "Unrelated", ["when-calling:other_tool"])
        assert _fire(db, "calling", "vault_write_file") == []
        assert db.execute("SELECT COUNT(*) FROM trigger_log").fetchone()[0] == 0

    def test_cascade_on_memory_delete(self, db):
        mid = _add_memory(db, "m", ["when-calling:x"])
        _fire(db, "calling", "x")
        db.execute("DELETE FROM memories WHERE memory_id = ?", (mid,))
        db.commit()
        assert db.execute("SELECT COUNT(*) FROM trigger_log").fetchone()[0] == 0


class TestRecordOutcome:
    def test_followed_writes_nothing(self, db):
        mid = _add_memory(db, "m", ["when-calling:vault_write_file"])
        _fire(db, "calling", "vault_write_file")
        out = record_outcome(db, mid, followed=True)
        assert out == {"memory_id": mid, "followed": True, "ignored_count": 0}
        assert _ignored_rows(db, mid) == []

    def test_ignored_writes_one_prediction_error(self, db):
        mid = _add_memory(db, "m", ["when-calling:vault_write_file"])
        _fire(db, "calling", "vault_write_file")
        out = record_outcome(db, mid, followed=False, note="re-issued the same call")
        assert out["ignored_count"] == 1
        assert "suggest" not in out
        rows = _ignored_rows(db, mid)
        assert len(rows) == 1
        note_path, dist, context, resolved = rows[0]
        assert (note_path, dist, resolved) == ("", 0.0, None)
        # context names the trigger that fired, not the caller's free-text note.
        assert context == "when-calling:vault_write_file"

    def test_third_ignore_suggests_retire(self, db):
        mid = _add_memory(db, "m", ["when-calling:vault_write_file"])
        for i in range(RETIRE_AFTER_IGNORES):
            _fire(db, "calling", "vault_write_file")
            out = record_outcome(db, mid, followed=False)
        assert out["ignored_count"] == RETIRE_AFTER_IGNORES
        assert out["suggest"] == "retire"
        # The memory row itself is untouched: no auto-delete, no decay.
        assert db.execute("SELECT COUNT(*) FROM memories WHERE memory_id = ?",
                          (mid,)).fetchone()[0] == 1

    def test_unknown_memory(self, db):
        out = record_outcome(db, 999, followed=False)
        assert "error" in out
        assert db.execute("SELECT COUNT(*) FROM prediction_errors").fetchone()[0] == 0

    def test_never_fired_falls_back_to_tag(self, db):
        # No trigger_log row (older client): context still names the trigger tag.
        mid = _add_memory(db, "m", ["misc", "when-error:no commits between"])
        record_outcome(db, mid, followed=False)
        assert _ignored_rows(db, mid)[0][2] == "when-error:no commits between"


class TestDriftBucket:
    def test_ignored_trigger_in_drift_bucket(self, db):
        from neurostack.promotion import compute_promotion_queue

        mid = _add_memory(db, "m", ["when-calling:vault_write_file"])
        _fire(db, "calling", "vault_write_file")
        record_outcome(db, mid, followed=False)
        q = compute_promotion_queue(db)
        assert q["counts"]["drift"] == 1
        entry = q["drift"][0]
        assert entry["memory_id"] == mid
        assert entry["ignored_trigger"] == "when-calling:vault_write_file"
        assert entry["ignored_count"] == 1
        assert "suggest" not in entry

    def test_three_ignores_collapse_to_one_entry_with_retire(self, db):
        from neurostack.promotion import compute_promotion_queue

        mid = _add_memory(db, "m", ["when-calling:vault_write_file"])
        for _ in range(RETIRE_AFTER_IGNORES):
            record_outcome(db, mid, followed=False)
        q = compute_promotion_queue(db)
        assert q["counts"]["drift"] == 1
        assert q["drift"][0]["ignored_count"] == RETIRE_AFTER_IGNORES
        assert q["drift"][0]["suggest"] == "retire"

    def test_memory_drift_rows_unchanged(self, db):
        from neurostack.promotion import compute_promotion_queue

        mid = _add_memory(db, "Drifted memory", ["x"])
        db.execute(
            "INSERT INTO prediction_errors (note_path, query, cosine_distance,"
            " error_type, memory_id) VALUES ('a.md', '', 0.7, 'memory_drift', ?)",
            (mid,),
        )
        db.commit()
        q = compute_promotion_queue(db)
        assert q["counts"]["drift"] == 1
        assert q["drift"][0]["drifted_from"] == "a.md"
        assert "ignored_trigger" not in q["drift"][0]


class TestMigration:
    def test_creates_trigger_log_when_absent(self, db):
        from neurostack.schema import SCHEMA_VERSION, _run_migrations

        db.execute("DROP TABLE trigger_log")
        db.execute("UPDATE schema_version SET version = 24")
        db.commit()
        _run_migrations(db)
        assert db.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] == SCHEMA_VERSION
        cols = {r[1] for r in db.execute("PRAGMA table_info(trigger_log)")}
        assert {"log_id", "memory_id", "event", "value", "session_hint", "fired_at"} <= cols
