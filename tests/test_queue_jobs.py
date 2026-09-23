# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Queue jobs on the run-due engine and the local checkpoint queue (issue #229)."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from neurostack.cli.hook import Verdict
from neurostack.cli.queue import enqueue
from neurostack.client import ClientConfig
from neurostack.jobs import JOBS, JobFailed, blocked
from neurostack.queue import add, finish


def _iso(moment):
    return moment.replace(microsecond=0).isoformat().replace("+00:00", "Z")


@pytest.fixture
def client(monkeypatch):
    """The client.toml the jobs see; tests change its fields."""
    cfg = ClientConfig(checkpoint_command="true")
    monkeypatch.setattr("neurostack.client.load_client_config", lambda *a, **k: cfg)
    return cfg


@pytest.fixture
def runs(monkeypatch):
    """Replace the checkpoint runner; set `.reply` to the Verdict it returns."""
    state = SimpleNamespace(reply=Verdict(data={"ok": True, "saved": 2, "found": 3}),
                            calls=[])

    def fake(payload, harness="cli", cfg=None):
        state.calls.append((payload, harness))
        return state.reply

    monkeypatch.setattr("neurostack.cli.hook.run_checkpoint", fake)
    return state


def _row(conn, job_id):
    return conn.execute("SELECT * FROM job_queue WHERE job_id = ?", (job_id,)).fetchone()


def test_checkpoint_worker_runs_the_claimed_session_and_finishes_it_done(
        in_memory_db, client, runs):
    job_id = add(in_memory_db, "checkpoint", "s1",
                 {"session": "s1", "harness": "claude"})["job_id"]

    result = JOBS["checkpoint-worker"].run(None, in_memory_db)

    assert result["claimed"] == 1 and result["finished_ok"] == 1
    assert runs.calls == [({"session": "s1", "harness": "claude", "format": "claude-code"},
                           "claude")]
    row = _row(in_memory_db, job_id)
    assert (row["status"], row["saved"], row["output"]) == ("done", 2, "saved 2 of 3")


@pytest.mark.parametrize("reply, output", [
    (Verdict(data={"ok": False, "saved": 0, "found": 0, "error": "command exited 1"}),
     "failed: command exited 1"),
    (Verdict("neurostack: checkpoint already running"),
     "no payload: neurostack: checkpoint already running"),
])
def test_a_failed_or_busy_checkpoint_finishes_failed_and_fails_the_run(
        in_memory_db, client, runs, reply, output):
    runs.reply = reply
    job_id = add(in_memory_db, "checkpoint", "s1", {"session": "s1", "harness": "omp"})["job_id"]

    with pytest.raises(JobFailed, match=output):
        JOBS["checkpoint-worker"].run(None, in_memory_db)

    row = _row(in_memory_db, job_id)
    assert (row["status"], row["output"]) == ("failed", output)


@pytest.mark.parametrize("payload, call", [
    ({"path": "/t/2026-09-23T10-00_abc-123.jsonl", "provider": "omp"},
     ({"session": "abc-123", "harness": "omp", "format": "omp"}, "omp")),
    ({"path": "/t/0f1e-uuid.jsonl", "provider": "claude-code"},
     ({"session": "0f1e-uuid", "harness": "claude", "format": "claude-code"}, "claude")),
])
def test_harvest_worker_derives_the_session_from_the_transcript_path(
        in_memory_db, client, runs, payload, call):
    add(in_memory_db, "harvest", f"{payload['path']}@1", {**payload, "mtime": 1})
    JOBS["harvest-worker"].run(None, in_memory_db)
    assert runs.calls == [call]


def test_worker_reaps_a_stale_run_before_claiming(in_memory_db, client, runs):
    stale = add(in_memory_db, "checkpoint", "old", {"session": "old"})["job_id"]
    in_memory_db.execute(
        "UPDATE job_queue SET status = 'running', started_at = ? WHERE job_id = ?",
        (_iso(datetime.now(timezone.utc) - timedelta(minutes=31)), stale))
    in_memory_db.commit()

    result = JOBS["checkpoint-worker"].run(None, in_memory_db)

    assert result["reaped"] == 1 and result["claimed"] == 0
    assert _row(in_memory_db, stale)["status"] == "failed"


def test_checkpoint_worker_stops_at_fifty_a_day(in_memory_db, client, runs):
    for i in range(50):
        job_id = add(in_memory_db, "checkpoint", f"done-{i}", {})["job_id"]
        finish(in_memory_db, job_id, ok=True)
    # add refuses past the cap too, so the waiting request goes in directly
    in_memory_db.execute("INSERT INTO job_queue (queue, key, payload) VALUES"
                         " ('checkpoint', 'late', '{\"session\": \"late\"}')")
    in_memory_db.commit()

    result = JOBS["checkpoint-worker"].run(None, in_memory_db)
    assert result["claimed"] == 0 and "daily cap 50/50" in result["reason"]
    assert runs.calls == []


def test_harvest_scan_queues_pending_transcripts_once(in_memory_db, client, monkeypatch):
    rows = [{"path": "/t/a.jsonl", "provider": "omp", "mtime": 1},
            {"path": "/t/b.jsonl", "provider": "claude-code", "mtime": 2}]
    monkeypatch.setattr("neurostack.harvest.pending_sessions", lambda n=50, provider=None: rows)

    first = JOBS["harvest-scan"].run(None, in_memory_db)
    again = JOBS["harvest-scan"].run(None, in_memory_db)

    assert first == {"pending": 2, "queued": 2, "duplicates": 0, "errors": 0}
    assert again == {"pending": 2, "queued": 0, "duplicates": 2, "errors": 0}


def test_enqueue_without_queue_url_lands_in_the_local_queue(tmp_path, monkeypatch):
    import sqlite3

    db = tmp_path / "neurostack.db"
    monkeypatch.setattr("neurostack.schema._db_path", lambda: db)

    assert enqueue(ClientConfig(), "sess-1", "omp", "home") == (
        0, "neurostack: checkpoint queued locally (position 1)")
    assert enqueue(ClientConfig(), "sess-1", "omp", "home") == (
        0, "neurostack: checkpoint already queued locally")
    row = sqlite3.connect(db).execute(
        "SELECT queue, key, status, json_extract(payload, '$.harness') FROM job_queue"
    ).fetchall()
    assert row == [("checkpoint", "sess-1", "queued", "omp")]


def test_queue_jobs_need_checkpoint_command(client):
    client.checkpoint_command = None
    for name in ("checkpoint-worker", "harvest-worker", "harvest-scan"):
        assert blocked(SimpleNamespace(jobs=None), JOBS[name]) == \
            "no checkpoint_command in client.toml"


def test_server_jobs_stay_off_a_client_of_a_remote_index(client, tmp_path):
    cfg = SimpleNamespace(jobs=None, db_path=tmp_path / "neurostack.db")
    cfg.db_path.touch()  # a client keeps a local DB for its queue
    client.url = "http://192.168.0.65:8001/mcp"
    assert blocked(cfg, JOBS["decay"]) == "index is served by 192.168.0.65"
    client.url = "http://127.0.0.1:8001/mcp"
    assert blocked(cfg, JOBS["decay"]) is None
