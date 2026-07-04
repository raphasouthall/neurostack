"""Tests for neurostack.feedback — the implicit-feedback loop (issue #66).

Offline: capture (log/attribute), harvest (labels/stats), and the v18 schema
migration, all against a real on-disk SQLite DB.
"""

import json

import pytest

from neurostack import feedback as fb
from neurostack.schema import SCHEMA_VERSION, get_db


def _table_exists(conn, name):
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def _event(conn, query, shown, chosen):
    """Log a search and attribute a chosen result — one feedback event."""
    fb.log_search(conn, query, shown)
    fb.attribute_use(conn, [chosen], 1800)


@pytest.fixture
def fb_db(tmp_path):
    return get_db(tmp_path / "fb.db")


# ── schema / migration ──────────────────────────────────────────────────────


def test_fresh_db_has_feedback_tables(fb_db):
    assert _table_exists(fb_db, "search_log")
    assert _table_exists(fb_db, "search_feedback")
    v = fb_db.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
    assert v == SCHEMA_VERSION


def test_migration_recreates_tables(tmp_path):
    db = tmp_path / "m.db"
    conn = get_db(db)
    conn.execute("DROP TABLE search_log")
    conn.execute("DROP TABLE search_feedback")
    # _run_migrations reads MAX(version) — clear it so the DB reads as v17.
    conn.execute("DELETE FROM schema_version")
    conn.execute("INSERT INTO schema_version VALUES (17)")
    conn.commit()
    conn.close()
    conn2 = get_db(db)  # reopening runs migrations
    assert _table_exists(conn2, "search_log")
    assert _table_exists(conn2, "search_feedback")
    assert conn2.execute(
        "SELECT MAX(version) FROM schema_version"
    ).fetchone()[0] == SCHEMA_VERSION


# ── log_search ──────────────────────────────────────────────────────────────


def test_log_search_inserts(fb_db):
    fb.log_search(fb_db, "how to configure retries", ["a.md", "b.md", "c.md"])
    row = fb_db.execute("SELECT query, shown_paths FROM search_log").fetchone()
    assert row[0] == "how to configure retries"
    assert json.loads(row[1]) == ["a.md", "b.md", "c.md"]


def test_log_search_ignores_empty(fb_db):
    fb.log_search(fb_db, "", ["a.md"])
    fb.log_search(fb_db, "q", [])
    assert fb_db.execute("SELECT COUNT(*) FROM search_log").fetchone()[0] == 0


# ── attribute_use ───────────────────────────────────────────────────────────


def test_attribute_links_to_search_with_rank(fb_db):
    fb.log_search(fb_db, "retry config", ["guides/a.md", "guides/b.md", "guides/c.md"])
    assert fb.attribute_use(fb_db, ["guides/b.md"], window_seconds=1800) == 1
    row = fb_db.execute(
        "SELECT query, chosen_path, rank FROM search_feedback"
    ).fetchone()
    assert (row[0], row[1], row[2]) == ("retry config", "guides/b.md", 2)


def test_attribute_ignores_unsurfaced_path(fb_db):
    fb.log_search(fb_db, "q", ["a.md", "b.md"])
    assert fb.attribute_use(fb_db, ["z.md"], 1800) == 0
    assert fb_db.execute("SELECT COUNT(*) FROM search_feedback").fetchone()[0] == 0


def test_attribute_respects_window(fb_db):
    fb_db.execute(
        "INSERT INTO search_log (query, shown_paths, searched_at) "
        "VALUES (?, ?, datetime('now', '-2 hours'))",
        ("old q", json.dumps(["a.md"])),
    )
    fb_db.commit()
    assert fb.attribute_use(fb_db, ["a.md"], window_seconds=1800) == 0


def test_attribute_dedups_same_use_within_window(fb_db):
    # A read + a record-usage for the same note (a normal pairing) must be one
    # event, not two.
    fb.log_search(fb_db, "q", ["a.md", "b.md"])
    assert fb.attribute_use(fb_db, ["a.md"], 1800) == 1
    assert fb.attribute_use(fb_db, ["a.md"], 1800) == 0  # deduped
    assert fb_db.execute("SELECT COUNT(*) FROM search_feedback").fetchone()[0] == 1


def test_attribute_picks_most_recent_search(fb_db):
    fb.log_search(fb_db, "old query", ["x.md", "a.md"])
    fb.log_search(fb_db, "new query", ["a.md", "y.md"])
    fb.attribute_use(fb_db, ["a.md"], 1800)
    row = fb_db.execute("SELECT query, rank FROM search_feedback").fetchone()
    assert row[0] == "new query"  # tiebreak by search_id
    assert row[1] == 1


# ── harvest ─────────────────────────────────────────────────────────────────


def test_feedback_labels_aggregate(fb_db):
    _event(fb_db, "q1", ["a.md", "b.md"], "a.md")
    _event(fb_db, "q1", ["a.md", "c.md"], "a.md")
    _event(fb_db, "q2", ["d.md"], "d.md")
    labels = fb.feedback_labels(fb_db, min_count=1)
    by_q = {label.query: label for label in labels}
    assert set(by_q) == {"q1", "q2"}
    assert by_q["q1"].targets == ["a.md"]
    assert by_q["q1"].category == "feedback"


def test_feedback_labels_min_count(fb_db):
    _event(fb_db, "q", ["a.md", "b.md"], "a.md")
    assert fb.feedback_labels(fb_db, min_count=2) == []  # chosen only once


def test_feedback_stats(fb_db):
    fb.log_search(fb_db, "q", ["a.md", "b.md", "c.md"])
    fb.attribute_use(fb_db, ["c.md"], 1800)  # rank 3
    s = fb.feedback_stats(fb_db)
    assert s["searches_logged"] == 1
    assert s["feedback_events"] == 1
    assert s["distinct_queries"] == 1
    assert s["distinct_chosen_notes"] == 1
    assert s["avg_chosen_rank"] == 3.0
    assert s["informative_events"] == 1  # rank 3 > 1


def test_stats_empty_db(fb_db):
    s = fb.feedback_stats(fb_db)
    assert s["searches_logged"] == 0
    assert s["feedback_events"] == 0
    assert s["avg_chosen_rank"] is None
