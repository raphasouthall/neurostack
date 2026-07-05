# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Tests for memory drift detection (issue #38)."""

import pytest

from neurostack import config as nsconfig

np = pytest.importorskip("numpy")

from neurostack.memory_drift import (  # noqa: E402
    DRIFT_THRESHOLD,
    detect_memory_drift,
    resolve_memory_drift,
)


@pytest.fixture
def db(tmp_path, monkeypatch):
    # Default DB path so registry tools (which open get_db(DB_PATH)) share the file.
    monkeypatch.setenv("NEUROSTACK_DB_DIR", str(tmp_path))
    nsconfig._config = None
    from neurostack.schema import get_db

    conn = get_db()
    yield conn
    conn.close()
    nsconfig._config = None


def _vec(*xs):
    return np.array(xs, dtype=np.float32)


def _add_note(conn, path, chunk_text, chunk_vec, title=None):
    conn.execute(
        "INSERT OR REPLACE INTO notes (path, title, content_hash, updated_at)"
        " VALUES (?, ?, ?, ?)",
        (path, title or path, "h", "2026-07-01T00:00:00+00:00"),
    )
    conn.execute(
        "INSERT INTO chunks (note_path, heading_path, content, content_hash,"
        " position, embedding) VALUES (?, ?, ?, ?, ?, ?)",
        (path, "", chunk_text, "h", 0, chunk_vec.tobytes()),
    )
    conn.commit()


def _add_memory(conn, content, vec, tags=None):
    cur = conn.execute(
        "INSERT INTO memories (content, entity_type, embedding, tags)"
        " VALUES (?, 'observation', ?, ?)",
        (content, vec.tobytes(), tags),
    )
    conn.commit()
    return cur.lastrowid


def _drift_count(conn):
    return conn.execute(
        "SELECT COUNT(*) FROM prediction_errors WHERE error_type = 'memory_drift'"
    ).fetchone()[0]


def _unresolved_count(conn):
    return conn.execute(
        "SELECT COUNT(*) FROM prediction_errors WHERE resolved_at IS NULL"
    ).fetchone()[0]


CONTENT = "X is a blocker in [[project]]"


class TestDriftDetection:
    def test_aligned_memory_no_drift(self, db):
        _add_note(db, "work/project.md", "X is a blocker.", _vec(1, 0, 0, 0))
        mid = _add_memory(db, CONTENT, _vec(1, 0, 0, 0))
        assert detect_memory_drift(db, mid, CONTENT, _vec(1, 0, 0, 0)) == []
        assert _drift_count(db) == 0

    def test_drifted_memory_flags(self, db):
        # Note now says "resolved" (embedding orthogonal to the memory) → drift.
        _add_note(db, "work/project.md", "X was resolved.", _vec(1, 0, 0, 0))
        mid = _add_memory(db, CONTENT, _vec(0, 1, 0, 0))
        written = detect_memory_drift(db, mid, CONTENT, _vec(0, 1, 0, 0))
        assert len(written) == 1
        assert written[0]["note_path"] == "work/project.md"
        assert written[0]["cosine_distance"] > DRIFT_THRESHOLD
        row = db.execute(
            "SELECT memory_id, note_path, error_type, query FROM prediction_errors"
        ).fetchone()
        assert row["memory_id"] == mid
        assert row["note_path"] == "work/project.md"
        assert row["error_type"] == "memory_drift"
        assert row["query"] == f"memory:{mid}"

    def test_no_wiki_links_skipped(self, db):
        mid = _add_memory(db, "plain memory, no links", _vec(0, 1, 0, 0))
        assert detect_memory_drift(
            db, mid, "plain memory, no links", _vec(0, 1, 0, 0)
        ) == []

    def test_unresolvable_link_skipped(self, db):
        content = "refers to [[nonexistent-note]]"
        mid = _add_memory(db, content, _vec(0, 1, 0, 0))
        assert detect_memory_drift(db, mid, content, _vec(0, 1, 0, 0)) == []

    def test_no_embedding_skipped(self, db):
        _add_note(db, "work/project.md", "X was resolved.", _vec(1, 0, 0, 0))
        mid = _add_memory(db, CONTENT, _vec(0, 1, 0, 0))
        assert detect_memory_drift(db, mid, CONTENT, None) == []

    def test_debounce_updates_in_place(self, db):
        _add_note(db, "work/project.md", "X was resolved.", _vec(1, 0, 0, 0))
        mid = _add_memory(db, CONTENT, _vec(0, 1, 0, 0))
        detect_memory_drift(db, mid, CONTENT, _vec(0, 1, 0, 0))
        detect_memory_drift(db, mid, CONTENT, _vec(0, 1, 0, 0))  # again, in window
        assert _drift_count(db) == 1  # debounced, not duplicated


class TestResolutionAndLifecycle:
    def test_resolve_marks_rows_resolved(self, db):
        _add_note(db, "work/project.md", "X was resolved.", _vec(1, 0, 0, 0))
        mid = _add_memory(db, CONTENT, _vec(0, 1, 0, 0))
        detect_memory_drift(db, mid, CONTENT, _vec(0, 1, 0, 0))
        assert _unresolved_count(db) == 1
        assert resolve_memory_drift(db, mid) == 1
        db.commit()
        assert _unresolved_count(db) == 0

    def test_tags_only_update_keeps_drift(self, db):
        # A tags-only edit leaves the embedding unchanged, so the drift still
        # holds and must NOT be resolved.
        from neurostack.memories import update_memory

        _add_note(db, "work/project.md", "X was resolved.", _vec(1, 0, 0, 0))
        mid = _add_memory(db, CONTENT, _vec(0, 1, 0, 0))
        detect_memory_drift(db, mid, CONTENT, _vec(0, 1, 0, 0))
        update_memory(db, mid, tags=["seen"])
        assert _unresolved_count(db) == 1

    def test_content_update_resolves_drift(self, db, monkeypatch):
        # A content edit re-embeds the memory, so the drift is reconciled.
        from neurostack import embedder
        from neurostack.memories import update_memory

        monkeypatch.setattr(embedder, "get_embedding",
                            lambda *a, **k: _vec(1, 0, 0, 0))
        _add_note(db, "work/project.md", "X was resolved.", _vec(1, 0, 0, 0))
        mid = _add_memory(db, CONTENT, _vec(0, 1, 0, 0))
        detect_memory_drift(db, mid, CONTENT, _vec(0, 1, 0, 0))
        update_memory(db, mid, content="X was resolved.")
        assert _unresolved_count(db) == 0

    def test_stronger_signal_updates_in_place(self, db):
        _add_note(db, "work/project.md", "X was resolved.", _vec(1, 0, 0, 0))
        mid = _add_memory(db, CONTENT, _vec(0, 1, 0, 0))
        detect_memory_drift(db, mid, CONTENT, _vec(0.5, 0.866, 0, 0))  # dist ~0.5
        d1 = db.execute(
            "SELECT cosine_distance FROM prediction_errors"
        ).fetchone()["cosine_distance"]
        detect_memory_drift(db, mid, CONTENT, _vec(0, 1, 0, 0))  # dist 1.0, stronger
        assert _drift_count(db) == 1  # updated in place, no duplicate
        d2 = db.execute(
            "SELECT cosine_distance FROM prediction_errors"
        ).fetchone()["cosine_distance"]
        assert d2 > d1

    def test_new_open_row_after_resolution(self, db):
        # Dedup only suppresses a second OPEN row; once resolved, a genuinely new
        # drift event opens a fresh row.
        _add_note(db, "work/project.md", "X was resolved.", _vec(1, 0, 0, 0))
        mid = _add_memory(db, CONTENT, _vec(0, 1, 0, 0))
        detect_memory_drift(db, mid, CONTENT, _vec(0, 1, 0, 0))
        resolve_memory_drift(db, mid)
        db.commit()
        detect_memory_drift(db, mid, CONTENT, _vec(0, 1, 0, 0))
        assert _unresolved_count(db) == 1  # a fresh open row
        assert _drift_count(db) == 2       # one resolved + one open

    def test_forget_memory_cleans_drift(self, db):
        from neurostack.memories import forget_memory

        _add_note(db, "work/project.md", "X was resolved.", _vec(1, 0, 0, 0))
        mid = _add_memory(db, CONTENT, _vec(0, 1, 0, 0))
        detect_memory_drift(db, mid, CONTENT, _vec(0, 1, 0, 0))
        forget_memory(db, mid)
        assert db.execute(
            "SELECT COUNT(*) FROM prediction_errors WHERE memory_id = ?", (mid,)
        ).fetchone()[0] == 0


def test_v20_to_v21_adds_memory_id_preserving_rows():
    # The migration that runs on the live v20 prod DB: adds memory_id via ALTER
    # (no rebuild) and keeps every existing note-centric row intact.
    import sqlite3

    from neurostack.schema import _run_migrations

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY)")
    conn.execute("INSERT INTO schema_version VALUES (20)")
    conn.execute(
        "CREATE TABLE prediction_errors (error_id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " note_path TEXT NOT NULL, query TEXT NOT NULL, cosine_distance REAL NOT NULL,"
        " error_type TEXT NOT NULL, context TEXT,"
        " detected_at TEXT NOT NULL DEFAULT (datetime('now')), resolved_at TEXT)"
    )
    conn.execute(
        "INSERT INTO prediction_errors (note_path, query, cosine_distance, error_type)"
        " VALUES ('a.md', 'q', 0.7, 'low_overlap')"
    )
    conn.commit()

    _run_migrations(conn)

    cols = {r[1] for r in conn.execute("PRAGMA table_info(prediction_errors)")}
    assert "memory_id" in cols
    row = conn.execute(
        "SELECT note_path, memory_id, error_type FROM prediction_errors"
    ).fetchone()
    assert row["note_path"] == "a.md"          # pre-existing row preserved
    assert row["memory_id"] is None
    assert row["error_type"] == "low_overlap"
    assert conn.execute(
        "SELECT MAX(version) FROM schema_version"
    ).fetchone()[0] == 21


def test_tool_surfaces_memory_drift(db):
    from neurostack.tools import ensure_registered

    _add_note(db, "work/project.md", "X was resolved.", _vec(1, 0, 0, 0))
    mid = _add_memory(db, CONTENT, _vec(0, 1, 0, 0))
    detect_memory_drift(db, mid, CONTENT, _vec(0, 1, 0, 0))

    res = ensure_registered().call(
        "vault_prediction_errors", error_type="memory_drift"
    )
    assert res["total_flagged_memories"] == 1
    err = res["errors"][0]
    assert err["error_type"] == "memory_drift"
    assert err["memory_id"] == mid
    assert err["note_path"] == "work/project.md"
    assert err["memory"]["content"] == CONTENT
