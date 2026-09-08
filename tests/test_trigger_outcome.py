# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Tests for fired-but-ignored triggers (#136) and the obey count (#159)."""

import json

import pytest

from neurostack import config as nsconfig
from neurostack.triggers import (
    RETIRE_AFTER_IGNORES,
    match_triggers,
    record_fired,
    record_outcome,
    trigger_stats,
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


def _log_rows(conn, mid):
    """(followed, outcome reported?) per firing, oldest first."""
    rows = conn.execute(
        "SELECT followed, outcome_at FROM trigger_log WHERE memory_id = ?"
        " ORDER BY log_id", (mid,),
    ).fetchall()
    return [(r["followed"], r["outcome_at"] is not None) for r in rows]


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
    def test_followed_marks_the_firing_and_writes_no_error(self, db):
        mid = _add_memory(db, "m", ["when-calling:vault_write_file"])
        _fire(db, "calling", "vault_write_file")
        out = record_outcome(db, mid, followed=True)
        assert out == {"memory_id": mid, "followed": True, "ignored_count": 0}
        assert _ignored_rows(db, mid) == []
        assert _log_rows(db, mid) == [(1, True)]

    def test_ignored_marks_the_firing_zero(self, db):
        mid = _add_memory(db, "m", ["when-calling:vault_write_file"])
        _fire(db, "calling", "vault_write_file")
        record_outcome(db, mid, followed=False)
        assert _log_rows(db, mid) == [(0, True)]

    def test_only_the_newest_pending_firing_is_marked(self, db):
        mid = _add_memory(db, "m", ["when-calling:vault_write_file"])
        _fire(db, "calling", "vault_write_file")
        _fire(db, "calling", "vault_write_file")
        record_outcome(db, mid, followed=True)
        # Oldest first: the second firing took the outcome, the first waits.
        assert _log_rows(db, mid) == [(None, False), (1, True)]
        record_outcome(db, mid, followed=False)
        assert _log_rows(db, mid) == [(0, True), (1, True)]

    def test_session_hint_picks_that_session_firing(self, db):
        mid = _add_memory(db, "m", ["when-calling:vault_write_file"])
        _fire(db, "calling", "vault_write_file", session_hint="sess-a")
        _fire(db, "calling", "vault_write_file", session_hint="sess-b")
        record_outcome(db, mid, followed=True, session_hint="sess-a")
        rows = db.execute(
            "SELECT session_hint, followed FROM trigger_log ORDER BY log_id"
        ).fetchall()
        assert [tuple(r) for r in rows] == [("sess-a", 1), ("sess-b", None)]

    def test_unknown_session_hint_falls_back_to_the_newest_firing(self, db):
        mid = _add_memory(db, "m", ["when-calling:vault_write_file"])
        _fire(db, "calling", "vault_write_file", session_hint="sess-a")
        record_outcome(db, mid, followed=True, session_hint="sess-gone")
        assert _log_rows(db, mid) == [(1, True)]

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


class TestTriggerStats:
    def test_counts_and_followed_rate(self, db):
        mid = _add_memory(db, "m", ["when-calling:vault_write_file"])
        for _ in range(4):
            _fire(db, "calling", "vault_write_file")
        record_outcome(db, mid, followed=True)
        record_outcome(db, mid, followed=True)
        record_outcome(db, mid, followed=False)

        stats = trigger_stats(db)

        assert stats["days"] == 30
        assert (stats["fired"], stats["followed"], stats["ignored"],
                stats["pending"]) == (4, 2, 1, 1)
        # Pending firings count as neither, so the rate is 2 of 3 settled.
        assert stats["followed_rate"] == 2 / 3
        entry = stats["memories"][0]
        assert entry["memory_id"] == mid
        assert entry["trigger"] == "when-calling:vault_write_file"
        assert entry["content"] == "m"
        assert (entry["fired"], entry["followed"], entry["ignored"],
                entry["pending"]) == (4, 2, 1, 1)
        assert entry["followed_rate"] == 2 / 3

    def test_pending_only_has_no_rate(self, db):
        _add_memory(db, "m", ["when-calling:vault_write_file"])
        _fire(db, "calling", "vault_write_file")
        stats = trigger_stats(db)
        assert (stats["fired"], stats["pending"]) == (1, 1)
        assert stats["followed_rate"] is None
        assert stats["memories"][0]["followed_rate"] is None

    def test_empty_window(self, db):
        stats = trigger_stats(db)
        assert (stats["fired"], stats["followed"], stats["ignored"],
                stats["pending"]) == (0, 0, 0, 0)
        assert stats["followed_rate"] is None
        assert stats["memories"] == []

    def test_window_excludes_older_firings(self, db):
        mid = _add_memory(db, "m", ["when-calling:vault_write_file"])
        db.execute(
            "INSERT INTO trigger_log (memory_id, event, value, fired_at, followed,"
            " outcome_at) VALUES (?, 'calling', 'vault_write_file',"
            " datetime('now', '-40 days'), 1, datetime('now', '-40 days'))",
            (mid,),
        )
        db.commit()
        assert trigger_stats(db, days=30)["fired"] == 0
        assert trigger_stats(db, days=60)["followed"] == 1

    def test_one_row_per_memory(self, db):
        a = _add_memory(db, "first", ["when-calling:vault_write_file"])
        b = _add_memory(db, "second", ["when-calling:vault_write_file"])
        _fire(db, "calling", "vault_write_file")
        record_outcome(db, a, followed=True)

        stats = trigger_stats(db)

        assert stats["fired"] == 2
        by_id = {e["memory_id"]: e for e in stats["memories"]}
        assert by_id[a]["followed"] == 1
        assert by_id[b]["pending"] == 1


class TestTriggersCli:
    def _run(self, days=30, as_json=False):
        from argparse import Namespace

        from neurostack.cli.triggers import cmd_triggers

        cmd_triggers(Namespace(triggers_command="stats", days=days, json=as_json))

    def test_stats_prints_totals_and_a_row_per_memory(self, db, capsys):
        mid = _add_memory(db, "Use vault_update_memory for existing notes",
                          ["when-calling:vault_write_file"])
        _fire(db, "calling", "vault_write_file")
        _fire(db, "calling", "vault_write_file")
        record_outcome(db, mid, followed=True)

        self._run()

        out = capsys.readouterr().out
        assert ("Triggers (30d): 2 fired, 1 followed, 0 ignored, 1 pending"
                " (100% followed)") in out
        assert f"{mid}" in out
        assert "when-calling:vault_write_file" in out

    def test_stats_says_so_on_an_empty_window(self, db, capsys):
        self._run()
        out = capsys.readouterr().out
        assert "Triggers (30d): 0 fired, 0 followed, 0 ignored, 0 pending" in out
        assert "No trigger fired in the window." in out

    def test_stats_json_carries_the_memories(self, db, capsys):
        mid = _add_memory(db, "m", ["when-calling:vault_write_file"])
        _fire(db, "calling", "vault_write_file")
        record_outcome(db, mid, followed=False)

        self._run(days=7, as_json=True)

        payload = json.loads(capsys.readouterr().out)
        assert payload["days"] == 7
        assert payload["followed_rate"] == 0.0
        assert payload["memories"][0]["memory_id"] == mid


class TestMigration:
    def test_creates_trigger_log_when_absent(self, db):
        from neurostack.schema import SCHEMA_VERSION, _run_migrations

        db.execute("DROP TABLE trigger_log")
        db.execute("UPDATE schema_version SET version = 24")
        db.commit()
        _run_migrations(db)
        assert db.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] == SCHEMA_VERSION
        cols = {r[1] for r in db.execute("PRAGMA table_info(trigger_log)")}
        assert {"log_id", "memory_id", "event", "value", "session_hint", "fired_at",
                "followed", "outcome_at"} <= cols

    def test_v25_to_v26_adds_the_outcome_columns(self, db):
        from neurostack.schema import SCHEMA_VERSION, _run_migrations

        mid = _add_memory(db, "m", ["when-calling:vault_write_file"])
        # The v25 table shape: a firing, no outcome to put on it.
        db.executescript("""
            DROP TABLE trigger_log;
            CREATE TABLE trigger_log (
                log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                memory_id INTEGER NOT NULL
                    REFERENCES memories(memory_id) ON DELETE CASCADE,
                event TEXT NOT NULL,
                value TEXT NOT NULL,
                session_hint TEXT,
                fired_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
        """)
        db.execute(
            "INSERT INTO trigger_log (memory_id, event, value, session_hint)"
            " VALUES (?, 'calling', 'vault_write_file', 'sess-old')",
            (mid,),
        )
        db.execute("UPDATE schema_version SET version = 25")
        db.commit()

        _run_migrations(db)

        assert db.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] == SCHEMA_VERSION
        cols = {r[1] for r in db.execute("PRAGMA table_info(trigger_log)")}
        assert {"followed", "outcome_at"} <= cols
        # The firing survives, and it is pending rather than ignored.
        row = db.execute(
            "SELECT value, session_hint, followed, outcome_at FROM trigger_log"
        ).fetchone()
        assert tuple(row) == ("vault_write_file", "sess-old", None, None)

    def test_v26_migration_skips_columns_that_exist(self, db):
        from neurostack.schema import _run_migrations

        # A v25 stamp on a table that already has both columns — an unguarded
        # ALTER would raise "duplicate column name".
        db.execute("UPDATE schema_version SET version = 25")
        db.commit()
        _run_migrations(db)
        cols = {r[1] for r in db.execute("PRAGMA table_info(trigger_log)")}
        assert {"followed", "outcome_at"} <= cols
