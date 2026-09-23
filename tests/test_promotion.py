# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Tests for the promotion queue (issue #92)."""

import json

import pytest

from neurostack import config as nsconfig

np = pytest.importorskip("numpy")

from neurostack.promotion import compute_promotion_queue  # noqa: E402


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROSTACK_DB_DIR", str(tmp_path))
    nsconfig._config = None
    from neurostack.schema import get_db

    conn = get_db()
    yield conn
    conn.close()
    nsconfig._config = None


def _vec(*xs):
    return np.array(xs, dtype=np.float32)


def _add_note_chunk(conn, path, vec):
    conn.execute(
        "INSERT OR REPLACE INTO notes (path, title, content_hash, updated_at)"
        " VALUES (?, ?, 'h', '2026-07-01T00:00:00+00:00')",
        (path, path),
    )
    conn.execute(
        "INSERT INTO chunks (note_path, heading_path, content, content_hash,"
        " position, embedding) VALUES (?, '', 'chunk', 'h', 0, ?)",
        (path, vec.tobytes()),
    )
    conn.commit()


def _add_memory(conn, content, entity_type="decision", vec=None, tags=None,
                workspace=None, created_at=None):
    cur = conn.execute(
        "INSERT INTO memories (content, entity_type, embedding, tags, workspace)"
        " VALUES (?, ?, ?, ?, ?)",
        (content, entity_type,
         vec.tobytes() if vec is not None else None,
         json.dumps(tags) if tags else None, workspace),
    )
    if created_at:
        conn.execute(
            "UPDATE memories SET created_at = ? WHERE memory_id = ?",
            (created_at, cur.lastrowid),
        )
    conn.commit()
    return cur.lastrowid


class _Judge:
    """Stands in for the judgement model: scores by memory text, logs asks."""

    def __init__(self):
        self.scores: dict[str, float | None] = {}
        self.asked: list[str] = []

    def __call__(self, states, questions, cfg=None):
        out = []
        for state in states:
            memory = state.split("\n")[1]
            self.asked.append(memory)
            score = self.scores.get(memory)
            out.append(None if score is None else {"coverage": {"score": score}})
        return out


@pytest.fixture
def judge(monkeypatch):
    import neurostack.judge as judge_mod

    stub = _Judge()
    monkeypatch.setattr(judge_mod, "decide_many", stub)
    return stub


class TestPromotionQueue:
    def test_empty_db_empty_queue(self, db):
        q = compute_promotion_queue(db)
        assert q["counts"] == {
            "debt": 0, "drift": 0, "dead_handoffs": 0, "uncovered": 0,
        }

    def test_debt_bucket_by_tag(self, db):
        mid = _add_memory(db, "Skipped vault-save", tags=["promotion-debt"])
        _add_memory(db, "Normal memory", tags=["other"])
        q = compute_promotion_queue(db)
        assert [e["memory_id"] for e in q["debt"]] == [mid]

    def test_drift_bucket_from_prediction_errors(self, db):
        mid = _add_memory(db, "Drifted memory")
        db.execute(
            "INSERT INTO prediction_errors (note_path, query, cosine_distance,"
            " error_type, memory_id) VALUES ('a.md', '', 0.7, 'memory_drift', ?)",
            (mid,),
        )
        db.commit()
        q = compute_promotion_queue(db)
        assert q["counts"]["drift"] == 1
        assert q["drift"][0]["drifted_from"] == "a.md"

    def test_resolved_drift_excluded(self, db):
        mid = _add_memory(db, "Resolved drift")
        db.execute(
            "INSERT INTO prediction_errors (note_path, query, cosine_distance,"
            " error_type, memory_id, resolved_at)"
            " VALUES ('a.md', '', 0.7, 'memory_drift', ?, datetime('now'))",
            (mid,),
        )
        db.commit()
        assert compute_promotion_queue(db)["counts"]["drift"] == 0

    def test_dead_handoff_needs_marker_age_and_type(self, db):
        old = "2026-01-01 00:00:00"
        dead = _add_memory(db, "HANDOFF (session 1): continue X",
                           entity_type="context", created_at=old)
        _add_memory(db, "HANDOFF but fresh", entity_type="context")
        _add_memory(db, "Old context, no marker",
                     entity_type="context", created_at=old)
        _add_memory(db, "HANDOFF but a decision",
                     entity_type="decision", created_at=old)
        q = compute_promotion_queue(db)
        assert [e["memory_id"] for e in q["dead_handoffs"]] == [dead]

    def test_open_thread_tag_exempts_handoff(self, db):
        _add_memory(db, "CONTINUATION: still live thread",
                     entity_type="context", tags=["open-thread"],
                     created_at="2026-01-01 00:00:00")
        assert compute_promotion_queue(db)["counts"]["dead_handoffs"] == 0

    def test_uncovered_is_what_the_judge_says_not_similarity(self, db, judge):
        _add_note_chunk(db, "n.md", _vec(1, 0, 0, 0))
        orphan = _add_memory(db, "Close in embedding, missing from the note",
                             vec=_vec(1, 0, 0, 0))
        _add_memory(db, "Far in embedding, already in the note", vec=_vec(0, 1, 0, 0))
        judge.scores = {
            "Close in embedding, missing from the note": 0.0,
            "Far in embedding, already in the note": 3.0,
        }
        q = compute_promotion_queue(db)
        assert [e["memory_id"] for e in q["uncovered"]] == [orphan]
        entry = q["uncovered"][0]
        assert entry["coverage"] == 0.0
        assert entry["nearest_note"] == "n.md"

    def test_verdict_reused_until_memory_or_note_changes(self, db, judge):
        _add_note_chunk(db, "n.md", _vec(1, 0, 0, 0))
        mid = _add_memory(db, "Orphan fact", vec=_vec(1, 0, 0, 0))
        judge.scores = {"Orphan fact": 0.0, "Orphan fact, now promoted": 3.0}

        assert compute_promotion_queue(db)["counts"]["uncovered"] == 1
        assert compute_promotion_queue(db)["counts"]["uncovered"] == 1
        assert judge.asked == ["Orphan fact"]

        db.execute("UPDATE memories SET content = 'Orphan fact, now promoted'"
                   " WHERE memory_id = ?", (mid,))
        db.commit()
        assert compute_promotion_queue(db)["counts"]["uncovered"] == 0
        assert len(judge.asked) == 2

        db.execute("UPDATE notes SET content_hash = 'h2' WHERE path = 'n.md'")
        db.commit()
        compute_promotion_queue(db)
        assert len(judge.asked) == 3

    def test_unanswered_memory_is_pending_and_asked_again(self, db, judge):
        _add_note_chunk(db, "n.md", _vec(1, 0, 0, 0))
        _add_memory(db, "Judge outage", vec=_vec(1, 0, 0, 0))
        judge.scores = {"Judge outage": None}

        q = compute_promotion_queue(db)
        assert q["counts"]["uncovered"] == 0
        assert q["uncovered_pending"] == 1
        compute_promotion_queue(db)
        assert judge.asked == ["Judge outage", "Judge outage"]

    def test_uncovered_skips_non_durable_and_other_buckets(self, db, judge):
        _add_note_chunk(db, "n.md", _vec(1, 0, 0, 0))
        _add_memory(db, "Ephemeral obs", entity_type="observation",
                     vec=_vec(0, 1, 0, 0))
        debt = _add_memory(db, "Tagged debt", vec=_vec(0, 1, 0, 0),
                           tags=["promotion-debt"])
        q = compute_promotion_queue(db)
        assert q["uncovered"] == []
        assert judge.asked == []
        assert [e["memory_id"] for e in q["debt"]] == [debt]

    def test_workspace_scoping(self, db):
        _add_memory(db, "In scope", tags=["promotion-debt"], workspace="work/x")
        _add_memory(db, "Out of scope", tags=["promotion-debt"], workspace="home/y")
        q = compute_promotion_queue(db, workspace="work/x")
        assert q["counts"]["debt"] == 1
        assert q["debt"][0]["workspace"] == "work/x"


class TestSessionEndDebtWarning:
    def test_warns_when_durable_memories_but_no_note_change(self, db):
        from neurostack.memories import end_session, save_memory, start_session

        sid = start_session(db)["session_id"]
        save_memory(db, content="A durable decision", entity_type="decision",
                    session_id=sid, dedup=False)
        result = end_session(db, sid)
        assert result["promotion_debt_warning"]["durable_memories"] == 1

    def test_no_warning_when_note_updated_during_session(self, db):
        from neurostack.memories import end_session, save_memory, start_session

        sid = start_session(db)["session_id"]
        save_memory(db, content="A durable decision", entity_type="decision",
                    session_id=sid, dedup=False)
        # Note indexed after session start (ISO-with-T format, as the watcher writes)
        db.execute(
            "INSERT INTO notes (path, title, content_hash, updated_at)"
            " VALUES ('fresh.md', 'fresh', 'h',"
            " strftime('%Y-%m-%dT%H:%M:%S+00:00', datetime('now', '+1 hour')))"
        )
        db.commit()
        result = end_session(db, sid)
        assert "promotion_debt_warning" not in result

    def test_no_warning_for_observation_only_session(self, db):
        from neurostack.memories import end_session, save_memory, start_session

        sid = start_session(db)["session_id"]
        save_memory(db, content="Just an observation", session_id=sid,
                    dedup=False)
        result = end_session(db, sid)
        assert "promotion_debt_warning" not in result
