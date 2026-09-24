# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Read-only data behind `neurostack ui` (issue #242)."""

import sqlite3
from datetime import datetime
from types import SimpleNamespace

import pytest

from neurostack import dashboard, jobs
from neurostack.jobs import Daily, Every, Job
from neurostack.schema import get_db

T = datetime(2026, 9, 23, 12, 0)


def _job(name, requires=lambda cfg: None, schedule=Daily("03:00")):
    return Job(name, schedule, lambda cfg, conn: {}, requires, f"{name} job")


@pytest.fixture
def registry(monkeypatch):
    table = {}
    monkeypatch.setattr(jobs, "JOBS", table)
    return table


def _runs(conn, *rows):
    conn.executemany(
        "INSERT INTO job_runs (job, started_at, finished_at, status, result, error)"
        " VALUES (?, ?, ?, ?, ?, ?)", rows)
    conn.commit()


def test_overview_reads_a_read_only_connection(tmp_path):
    db = tmp_path / "neurostack.db"
    conn = get_db(db)
    conn.executemany("INSERT INTO notes (path, title, updated_at) VALUES (?, ?, ?)",
                     [(f"n{i:02d}.md", f"N{i}", f"2026-09-{i:02d}") for i in range(1, 13)])
    conn.executemany("INSERT INTO memories (content, entity_type) VALUES (?, ?)",
                     [("a", "decision"), ("b", "decision"), ("c", "bug")])
    conn.commit()
    conn.close()
    ro = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    ro.row_factory = sqlite3.Row

    out = dashboard.overview(ro)

    assert out["stats"]["notes"] == 12
    assert out["memories"] == {"total": 3, "by_type": {"decision": 2, "bug": 1}}
    assert [n["path"] for n in out["recent_notes"]] == [
        f"n{i:02d}.md" for i in range(12, 2, -1)]


class TestAutomations:
    def test_jobs_in_registry_order_with_last_and_recent(self, in_memory_db, registry):
        registry.update({
            "decay": _job("decay"),
            "worker": _job("worker", requires=lambda cfg: "no checkpoint_command"),
            "scan": _job("scan", schedule=Every(30)),
        })
        _runs(in_memory_db,
              ("decay", "2026-09-22T03:00:00+00:00", "2026-09-22T03:00:05+00:00",
               "ok", '{"demoted": 2}', None),
              ("decay", "2026-09-23T03:00:00+00:00", "2026-09-23T03:01:30+00:00",
               "failed", "not json", "disk on fire"),
              ("scan", "2026-09-23T11:30:00+00:00", None, "running", None, None))

        out = dashboard.automations(in_memory_db, SimpleNamespace(jobs=None), now=T)
        decay, worker, scan = out["jobs"]

        assert [j["name"] for j in out["jobs"]] == ["decay", "worker", "scan"]
        assert decay["schedule"] == "daily 03:00" and scan["schedule"] == "every 30 min"
        assert decay["recent"] == ["failed", "ok"]
        assert decay["last"] == {
            "status": "failed", "started_at": "2026-09-23T03:00:00+00:00",
            "finished_at": "2026-09-23T03:01:30+00:00", "duration_s": 90.0,
            "error": "disk on fire", "result": None}
        assert datetime.fromisoformat(decay["next_due"]).tzinfo is not None
        assert scan["last"]["status"] == "running" and scan["last"]["duration_s"] is None
        assert worker["blocked"] == "no checkpoint_command"
        assert worker["next_due"] is None
        assert worker["last"] is None and worker["recent"] == []

    def test_recent_keeps_the_newest_fourteen(self, in_memory_db, registry):
        registry["decay"] = _job("decay")
        _runs(in_memory_db, *[
            ("decay", f"2026-09-{day:02d}T03:00:00+00:00", f"2026-09-{day:02d}T03:00:01+00:00",
             "failed" if day == 20 else "ok", None, None)
            for day in range(1, 21)])

        (decay,) = dashboard.automations(in_memory_db, SimpleNamespace(jobs=None), now=T)["jobs"]

        assert len(decay["recent"]) == 14
        assert decay["recent"][0] == "failed"

    def test_queue_counts_fill_every_status(self, in_memory_db, registry):
        in_memory_db.executemany(
            "INSERT INTO job_queue (queue, key, status) VALUES (?, ?, ?)",
            [("checkpoint", "a", "queued"), ("checkpoint", "b", "queued"),
             ("harvest", "c", "done"), ("harvest", "d", "failed")])
        in_memory_db.commit()

        queues = dashboard.automations(in_memory_db, SimpleNamespace(jobs=None), now=T)["queues"]

        assert queues == {
            "checkpoint": {"queued": 2, "running": 0, "done": 0, "failed": 0},
            "harvest": {"queued": 0, "running": 0, "done": 1, "failed": 1},
        }


class TestJobRuns:
    def test_newest_first_with_ids(self, in_memory_db, registry):
        registry["decay"] = _job("decay")
        _runs(in_memory_db,
              ("decay", "2026-09-22T03:00:00+00:00", "2026-09-22T03:00:02+00:00",
               "ok", '{"demoted": 1}', None),
              ("decay", "2026-09-23T03:00:00+00:00", "2026-09-23T03:00:04+00:00",
               "skipped", None, None))

        runs = dashboard.job_runs(in_memory_db, "decay")

        assert [(r["id"], r["status"]) for r in runs] == [(2, "skipped"), (1, "ok")]
        assert runs[1]["result"] == {"demoted": 1} and runs[1]["duration_s"] == 2.0

    def test_unknown_job_raises_key_error(self, in_memory_db, registry):
        registry["decay"] = _job("decay")
        with pytest.raises(KeyError):
            dashboard.job_runs(in_memory_db, "nope")


@pytest.fixture
def graph_db(in_memory_db):
    """Five notes a..e ranked by pagerank, one coarse and two fine communities."""
    conn = in_memory_db
    for i, name in enumerate("abcde"):
        conn.execute("INSERT INTO notes (path, title, updated_at) VALUES (?, ?, ?)",
                     (f"{name}.md", name.upper(), f"2026-09-0{i + 1}"))
        conn.execute("INSERT INTO graph_stats (note_path, pagerank) VALUES (?, ?)",
                     (f"{name}.md", 5.0 - i))
    conn.executemany(
        "INSERT INTO graph_edges (source_path, target_path) VALUES (?, ?)",
        [("a.md", "b.md"), ("c.md", "a.md"), ("a.md", "e.md"), ("d.md", "b.md"),
         ("a.md", "missing.md")])
    conn.execute("INSERT INTO note_metadata (note_path, status) VALUES ('a.md', 'dormant')")
    conn.execute("INSERT INTO summaries (note_path, summary_text) VALUES ('a.md', 'About A')")
    conn.executemany(
        "INSERT INTO communities (community_id, level, title, member_notes) VALUES (?, ?, ?, ?)",
        [(1, 0, "all", 5), (2, 1, "even", 2), (3, 1, "odd", 3)])
    conn.executemany(
        "INSERT INTO community_members (community_id, entity) VALUES (?, ?)",
        [(1, f"{n}.md") for n in "abcde"]
        + [(2, "b.md"), (2, "d.md"), (3, "a.md"), (3, "c.md"), (3, "e.md")])
    conn.commit()
    return conn


class TestGraph:
    def test_truncates_to_top_pagerank_and_drops_edges_to_missing_nodes(self, graph_db):
        out = dashboard.graph(graph_db, limit=3)
        ids = [n["id"] for n in out["nodes"]]

        assert ids == ["a.md", "b.md", "c.md"]
        assert out["total_nodes"] == 5 and out["truncated"] is True
        assert sorted((e["source"], e["target"]) for e in out["edges"]) == [
            ("a.md", "b.md"), ("c.md", "a.md")]
        assert out["nodes"][0]["status"] == "dormant"
        assert out["nodes"][0]["community"] == 3  # the fine level, not the coarse one

    def test_community_filter_keeps_only_its_members(self, graph_db):
        out = dashboard.graph(graph_db, community=2)

        assert [n["id"] for n in out["nodes"]] == ["b.md", "d.md"]
        assert out["edges"] == [{"source": "d.md", "target": "b.md"}]
        assert out["total_nodes"] == 2 and out["truncated"] is False

    def test_limit_is_clamped(self, graph_db):
        assert len(dashboard.graph(graph_db, limit=0)["nodes"]) == 1
        assert len(dashboard.graph(graph_db, limit=10**6)["nodes"]) == 5


class TestNote:
    def test_neighbors_carry_their_direction(self, graph_db):
        out = dashboard.note(graph_db, "a.md")

        assert out["summary"] == "About A" and out["pagerank"] == 5.0
        assert out["neighbors"] == [
            {"path": "b.md", "title": "B", "direction": "out"},
            {"path": "c.md", "title": "C", "direction": "in"},
            {"path": "e.md", "title": "E", "direction": "out"},
        ]

    def test_unknown_path_raises_key_error(self, graph_db):
        with pytest.raises(KeyError):
            dashboard.note(graph_db, "a")  # no fuzzy match on a stem


def test_communities_largest_first(graph_db):
    assert [c["id"] for c in dashboard.communities(graph_db)] == [1, 3, 2]


@pytest.fixture
def memory_db(in_memory_db):
    in_memory_db.executemany(
        "INSERT INTO memories (content, tags, entity_type, created_at) VALUES (?, ?, ?, ?)",
        [("Use WAL mode for the index", '["sqlite", "wal"]', "decision", "2026-09-01"),
         ("Checkpoint the wal nightly", None, "observation", "2026-09-02"),
         ("Port 8765 serves the dashboard", '["ui"]', "decision", "2026-09-03"),
         ("Unrelated note", "[]", "observation", "2026-09-04")])
    in_memory_db.commit()
    return in_memory_db


class TestMemories:
    def test_newest_first_with_tags_parsed(self, memory_db):
        out = dashboard.memories(memory_db)

        assert out["total"] == 4 and out["by_type"] == {"decision": 2, "observation": 2}
        assert [m["tags"] for m in out["items"]] == [[], ["ui"], [], ["sqlite", "wal"]]

    def test_type_filter_narrows_items_not_totals(self, memory_db):
        out = dashboard.memories(memory_db, entity_type="decision")

        assert {m["entity_type"] for m in out["items"]} == {"decision"}
        assert len(out["items"]) == 2 and out["total"] == 4

    def test_q_matches_content_case_insensitively(self, memory_db):
        items = dashboard.memories(memory_db, q="WAL")["items"]

        assert [m["content"] for m in items] == [
            "Checkpoint the wal nightly", "Use WAL mode for the index"]

    def test_limit_is_clamped(self, memory_db):
        assert len(dashboard.memories(memory_db, limit=0)["items"]) == 1
        assert len(dashboard.memories(memory_db, limit=10**6)["items"]) == 4
