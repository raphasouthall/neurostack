# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""The server-owned checkpoint and harvest queue (issues #229, #232)."""

import base64
import gzip
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from neurostack.cli.hook import Verdict, _checkpoint_window, load_state
from neurostack.cli.queue import enqueue
from neurostack.client import ClientConfig
from neurostack.jobs import JOBS, JobFailed, blocked
from neurostack.queue import add, claim, finish, listing
from neurostack.schema import get_db
from neurostack.tools import queue_tools

OMP_LINE = '{"type":"message","message":{"role":"user","content":[{"type":"text","text":"m%d"}]}}\n'


def _iso(moment):
    return moment.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _gz(text):
    return base64.b64encode(gzip.compress(text.encode())).decode()


@pytest.fixture
def client(monkeypatch):
    """The client.toml the jobs see; tests change its fields."""
    cfg = ClientConfig(checkpoint_command="true")
    monkeypatch.setattr("neurostack.client.load_client_config", lambda *a, **k: cfg)
    return cfg


@pytest.fixture
def queue_db(tmp_path, monkeypatch):
    """A server DB the queue tools write to, from any thread."""
    path = tmp_path / "server.db"
    monkeypatch.setattr(queue_tools, "_conn", lambda: get_db(path))
    return get_db(path)


@pytest.fixture
def queue_server(server, queue_db, client):
    """The fake MCP endpoint answering queue_add with the real tool."""
    server.replies["queue_add"] = lambda args: queue_tools.queue_add(**args)
    client.url = server.url
    return server


@pytest.fixture
def runs(monkeypatch):
    """Replace the checkpoint runner; it records the payload and the file it was handed."""
    state = SimpleNamespace(reply=Verdict(data={"ok": True, "saved": 2, "found": 3}),
                            calls=[], seen=[], cfgs=[])

    def fake(payload, harness="cli", cfg=None):
        state.calls.append((payload, harness))
        state.cfgs.append(cfg)
        path = payload.get("transcript_path")
        state.seen.append(Path(path).read_text() if path else None)
        return state.reply

    monkeypatch.setattr("neurostack.cli.hook.run_checkpoint", fake)
    return state


def _server(tmp_path, command="true", vault_save=False):
    """The server's Config, as far as the workers read it."""
    return SimpleNamespace(db_dir=tmp_path, checkpoint_command=command,
                           checkpoint_timeout_s=300.0, checkpoint_max_messages=40,
                           vault_save_on_checkpoint=vault_save)


@pytest.fixture
def saves(monkeypatch):
    """Replace the vault-save agent; it records the transcript it read and returns `code`."""
    state = SimpleNamespace(code=0, seen=[])

    def fake(cfg, transcript, fmt, **kw):
        state.seen.append((transcript.read_text(), fmt))
        return state.code

    monkeypatch.setattr("neurostack.cli.agent.vault_save", fake)
    return state


def _row(conn, job_id):
    return conn.execute("SELECT * FROM job_queue WHERE job_id = ?", (job_id,)).fetchone()


# -- the store and the tools --------------------------------------------------

def test_queue_add_stores_the_decompressed_transcript_and_claim_returns_it(queue_db):
    first = queue_tools.queue_add("checkpoint", "s1", {"session": "s1"}, _gz("line one\n"))
    again = queue_tools.queue_add("checkpoint", "s1", {"session": "s1"}, _gz("line two\n"))

    assert first["ok"] and not first["duplicate"]
    assert again["duplicate"] is True
    assert listing(queue_db, "checkpoint")["jobs"][0]["transcript_chars"] == len("line one\n")
    job = queue_tools.queue_claim("checkpoint")["job"]
    assert job["transcript"] == "line one\n"
    done = queue_tools.queue_finish(job["job_id"], True, saved=1, output="saved 1 of 1")
    assert done["status"] == "done" and done["transcript_chars"] == 0


def test_queue_add_refuses_a_transcript_over_the_cap(queue_db, monkeypatch):
    monkeypatch.setattr("neurostack.queue.TRANSCRIPT_CAP_BYTES", 100)
    with pytest.raises(ValueError, match="cap"):
        queue_tools.queue_add("harvest", "k", {}, _gz("x" * 101))
    assert listing(queue_db)["jobs"] == []


def test_queue_add_honours_the_checkpoint_daily_cap(queue_db):
    for i in range(50):
        finish(queue_db, add(queue_db, "checkpoint", f"done-{i}")["job_id"], ok=True)
    refused = queue_tools.queue_add("checkpoint", "late", {}, _gz("x\n"))
    assert refused["ok"] is False and refused["reason"] == "daily cap reached"


def test_migration_29_to_30_adds_the_transcript_column(tmp_path):
    from neurostack.schema import _run_migrations

    conn = sqlite3.connect(tmp_path / "old.db")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY)")
    conn.execute("INSERT INTO schema_version VALUES (29)")
    conn.execute("CREATE TABLE job_queue (job_id INTEGER PRIMARY KEY, queue TEXT, key TEXT,"
                 " payload TEXT, status TEXT, saved INTEGER, output TEXT,"
                 " requested_at TEXT, started_at TEXT, finished_at TEXT)")
    _run_migrations(conn)
    assert "transcript" in {r[1] for r in conn.execute("PRAGMA table_info(job_queue)")}


# -- client upload ------------------------------------------------------------

def test_enqueue_uploads_the_transcript_and_reports_duplicates(queue_server, queue_db,
                                                               client, tmp_path):
    path = tmp_path / "s1.jsonl"
    path.write_text(OMP_LINE % 1)

    assert enqueue(client, "s1", "omp", "home", path, "omp") == (
        0, "neurostack: checkpoint queued (position 1)")
    assert enqueue(client, "s1", "omp", "home", path, "omp") == (
        0, "neurostack: checkpoint already queued")
    job = claim(queue_db, "checkpoint")["job"]
    assert job["transcript"] == OMP_LINE % 1
    assert job["payload"]["format"] == "omp" and job["payload"]["workspace"] == "home"


def test_enqueue_fails_when_no_server_answers(client, tmp_path):
    client.url = "http://127.0.0.1:9/mcp"
    path = tmp_path / "s1.jsonl"
    path.write_text(OMP_LINE % 1)
    code, line = enqueue(client, "s1", "omp", None, path, "omp")
    assert code == 1 and line.startswith("neurostack: checkpoint queue unreachable:")


def test_an_oversize_transcript_uploads_its_newest_records_with_the_offset(
        queue_server, queue_db, client, tmp_path, monkeypatch):
    tail = "".join(OMP_LINE % i for i in (8, 9, 10))
    monkeypatch.setattr("neurostack.cli.queue.TRANSCRIPT_CAP_BYTES", len(tail))
    path = tmp_path / "big.jsonl"
    path.write_text("".join(OMP_LINE % i for i in range(1, 11)))

    assert enqueue(client, "big", "omp", None, path, "omp")[0] == 0

    job = claim(queue_db, "checkpoint")["job"]
    assert job["transcript"] == tail
    assert job["payload"]["transcript_offset"] == 7


def test_an_offset_keeps_the_saved_index_on_the_same_message(isolated_home, tmp_path):
    path = tmp_path / "tail.jsonl"
    path.write_text("".join(OMP_LINE % i for i in (8, 9, 10)))
    state = load_state("tail")
    state.since_index = 8  # messages 1-8 were saved before the trim dropped 1-7
    start, window = _checkpoint_window(
        {"transcript_path": str(path), "format": "omp", "transcript_offset": 7}, state)
    assert start == 8 and [m["text"] for m in window] == ["m9", "m10"]


# -- server workers -----------------------------------------------------------

def test_worker_runs_the_checkpoint_on_the_uploaded_transcript_then_drops_it(
        in_memory_db, client, runs, tmp_path):
    job_id = add(in_memory_db, "checkpoint", "s1", {"session": "s1", "harness": "claude"},
                 transcript="the uploaded text\n")["job_id"]

    result = JOBS["checkpoint-worker"].run(_server(tmp_path), in_memory_db)

    assert result["claimed"] == 1 and result["finished_ok"] == 1
    (payload, harness), = runs.calls
    assert runs.seen == ["the uploaded text\n"]
    assert (payload["session"], payload["format"], harness) == ("s1", "claude-code", "claude")
    assert Path(payload["transcript_path"]).parent == tmp_path / "tmp"
    assert not Path(payload["transcript_path"]).exists()
    row = _row(in_memory_db, job_id)
    assert (row["status"], row["saved"], row["output"]) == ("done", 2, "saved 2 of 3")
    assert row["transcript"] is None


@pytest.mark.parametrize("reply, output", [
    (Verdict(data={"ok": False, "saved": 0, "found": 0, "error": "command exited 1"}),
     "failed: command exited 1"),
    (Verdict("neurostack: checkpoint already running"),
     "no payload: neurostack: checkpoint already running"),
])
def test_a_failed_or_busy_checkpoint_finishes_failed_and_fails_the_run(
        in_memory_db, client, runs, tmp_path, reply, output):
    runs.reply = reply
    job_id = add(in_memory_db, "checkpoint", "s1", {"session": "s1", "harness": "omp"},
                 transcript="x\n")["job_id"]

    with pytest.raises(JobFailed, match=output):
        JOBS["checkpoint-worker"].run(_server(tmp_path), in_memory_db)

    assert (_row(in_memory_db, job_id)["status"], _row(in_memory_db, job_id)["output"]) == (
        "failed", output)
    assert list((tmp_path / "tmp").iterdir()) == []


def test_vault_save_runs_on_a_saved_checkpoint_only_when_turned_on(
        in_memory_db, client, runs, saves, tmp_path):
    add(in_memory_db, "checkpoint", "s1", {"session": "s1", "harness": "omp"}, transcript="a\n")
    JOBS["checkpoint-worker"].run(_server(tmp_path), in_memory_db)
    assert saves.seen == []

    add(in_memory_db, "checkpoint", "s2", {"session": "s2", "harness": "omp"}, transcript="b\n")
    result = JOBS["checkpoint-worker"].run(_server(tmp_path, vault_save=True), in_memory_db)
    assert saves.seen == [("b\n", "omp")]
    assert result["vault_save"] == "ok"
    assert list((tmp_path / "tmp").iterdir()) == []


def test_vault_save_skips_a_failed_checkpoint_and_the_harvest_queue(
        in_memory_db, client, runs, saves, tmp_path):
    runs.reply = Verdict(data={"ok": False, "saved": 0, "found": 0, "error": "boom"})
    add(in_memory_db, "checkpoint", "s1", {"session": "s1", "harness": "omp"}, transcript="a\n")
    with pytest.raises(JobFailed):
        JOBS["checkpoint-worker"].run(_server(tmp_path, vault_save=True), in_memory_db)

    runs.reply = Verdict(data={"ok": True, "saved": 1, "found": 1})
    add(in_memory_db, "harvest", "/x/2026_s3.jsonl", {"path": "/x/2026_s3.jsonl"},
        transcript="c\n")
    JOBS["harvest-worker"].run(_server(tmp_path, vault_save=True), in_memory_db)
    assert saves.seen == []


def test_a_failed_vault_save_fails_the_run_but_keeps_the_checkpoint_done(
        in_memory_db, client, runs, saves, tmp_path):
    saves.code = 1
    job_id = add(in_memory_db, "checkpoint", "s1", {"session": "s1", "harness": "omp"},
                 transcript="a\n")["job_id"]
    with pytest.raises(JobFailed, match="vault-save agent exited 1"):
        JOBS["checkpoint-worker"].run(_server(tmp_path, vault_save=True), in_memory_db)
    assert _row(in_memory_db, job_id)["status"] == "done"


def test_a_job_without_a_transcript_fails_without_running(in_memory_db, client, runs, tmp_path):
    add(in_memory_db, "checkpoint", "s1", {"session": "s1"})
    with pytest.raises(JobFailed, match="no transcript uploaded"):
        JOBS["checkpoint-worker"].run(_server(tmp_path), in_memory_db)
    assert runs.calls == []


@pytest.mark.parametrize("payload, session, harness", [
    ({"path": "/t/2026-09-23T10-00_abc-123.jsonl", "provider": "omp"}, "abc-123", "omp"),
    ({"path": "/t/0f1e-uuid.jsonl", "provider": "claude-code"}, "0f1e-uuid", "claude"),
])
def test_harvest_worker_derives_the_session_from_the_transcript_path(
        in_memory_db, client, runs, tmp_path, payload, session, harness):
    add(in_memory_db, "harvest", f"{payload['path']}@1", {**payload, "mtime": 1}, transcript="t\n")
    JOBS["harvest-worker"].run(_server(tmp_path), in_memory_db)
    (sent, used), = runs.calls
    assert (sent["session"], used) == (session, harness)


def test_worker_reaps_a_stale_run_before_claiming(in_memory_db, client, runs, tmp_path):
    stale = add(in_memory_db, "checkpoint", "old", {"session": "old"}, transcript="x\n")["job_id"]
    in_memory_db.execute(
        "UPDATE job_queue SET status = 'running', started_at = ? WHERE job_id = ?",
        (_iso(datetime.now(timezone.utc) - timedelta(minutes=31)), stale))
    in_memory_db.commit()

    result = JOBS["checkpoint-worker"].run(_server(tmp_path), in_memory_db)

    assert result["reaped"] == 1 and result["claimed"] == 0
    assert _row(in_memory_db, stale)["status"] == "failed"
    assert _row(in_memory_db, stale)["transcript"] is None


def test_checkpoint_worker_stops_at_fifty_a_day(in_memory_db, client, runs, tmp_path):
    for i in range(50):
        finish(in_memory_db, add(in_memory_db, "checkpoint", f"done-{i}")["job_id"], ok=True)
    # add refuses past the cap too, so the waiting request goes in directly
    in_memory_db.execute("INSERT INTO job_queue (queue, key, payload) VALUES"
                         " ('checkpoint', 'late', '{\"session\": \"late\"}')")
    in_memory_db.commit()

    result = JOBS["checkpoint-worker"].run(_server(tmp_path), in_memory_db)
    assert result["claimed"] == 0 and "daily cap 50/50" in result["reason"]
    assert runs.calls == []


# -- client harvest-scan ------------------------------------------------------

def test_harvest_scan_moves_the_watermark_only_for_uploads_that_landed(
        server, client, tmp_path, monkeypatch):
    rows = []
    for name in ("a", "b"):
        path = tmp_path / f"{name}.jsonl"
        path.write_text(OMP_LINE % 1)
        rows.append({"path": str(path), "provider": "omp", "mtime": 1.0, "messages": 1})
    monkeypatch.setattr("neurostack.harvest.pending_sessions", lambda n=50, provider=None: rows)
    state_file = tmp_path / "harvest_state.json"
    monkeypatch.setattr("neurostack.harvest._harvest_state_path", lambda: state_file)
    server.replies["queue_add"] = lambda args: (
        {"ok": True, "duplicate": False, "job_id": 1, "position": 1}
        if "a.jsonl" in args["key"] else {"ok": False, "reason": "disk full"})
    client.url = server.url

    result = JOBS["harvest-scan"].run(None, None)

    assert result == {"pending": 2, "queued": 1, "duplicates": 0, "errors": 1}
    assert set(json.loads(state_file.read_text())) == {rows[0]["path"]}


def test_harvest_scan_fails_when_nothing_reaches_the_server(client, tmp_path, monkeypatch):
    path = tmp_path / "a.jsonl"
    path.write_text(OMP_LINE % 1)
    monkeypatch.setattr("neurostack.harvest.pending_sessions", lambda n=50, provider=None: [
        {"path": str(path), "provider": "omp", "mtime": 1.0, "messages": 1}])
    client.url = "http://127.0.0.1:9/mcp"
    with pytest.raises(JobFailed, match="no transcript queued"):
        JOBS["harvest-scan"].run(None, None)


# -- which host runs what -----------------------------------------------------

def test_workers_run_on_the_index_host_and_the_scan_on_any_client(client, tmp_path):
    cfg = SimpleNamespace(jobs=None, db_path=tmp_path / "neurostack.db", checkpoint_command="true")
    cfg.db_path.touch()
    client.url = "http://192.168.0.65:8001/mcp"
    for name in ("checkpoint-worker", "harvest-worker"):
        assert blocked(cfg, JOBS[name]) == "index is served by 192.168.0.65"
    assert blocked(cfg, JOBS["harvest-scan"]) is None

    client.url = "http://127.0.0.1:8001/mcp"
    assert blocked(cfg, JOBS["checkpoint-worker"]) is None
    client.checkpoint_command = None
    assert blocked(cfg, JOBS["harvest-scan"]) == "no checkpoint_command in client.toml"
    assert blocked(cfg, JOBS["checkpoint-worker"]) is None  # the server key decides


# -- the server's own checkpoint command (issue #233) --------------------------

def test_worker_runs_the_server_command_with_no_client_toml(isolated_home, in_memory_db,
                                                            runs, tmp_path):
    add(in_memory_db, "checkpoint", "s1", {"session": "s1"}, transcript="x\n")

    JOBS["checkpoint-worker"].run(_server(tmp_path, command="server-model --json"),
                                  in_memory_db)

    (used,) = runs.cfgs
    assert (used.checkpoint_command, used.checkpoint_timeout_s,
            used.checkpoint_max_messages) == ("server-model --json", 300.0, 40)


def test_jobs_json_turns_the_workers_off_without_the_server_key(isolated_home, tmp_path,
                                                                monkeypatch, capsys):
    from neurostack.cli.jobs import cmd_jobs
    from neurostack.config import Config

    cfg = Config(vault_root=tmp_path, db_dir=tmp_path / "data")
    get_db(cfg.db_path)
    monkeypatch.setattr("neurostack.config.get_config", lambda: cfg)

    cmd_jobs(SimpleNamespace(json=True))

    rows = {r["job"]: r for r in json.loads(capsys.readouterr().out)}
    for name in ("checkpoint-worker", "harvest-worker"):
        assert rows[name]["enabled"] is False
        assert rows[name]["reason"] == "no checkpoint_command in config.toml"


def test_the_server_keys_load_from_config_toml_and_env(tmp_path, monkeypatch):
    from neurostack.config import load_config

    config_file = tmp_path / "config.toml"
    config_file.write_text('checkpoint_command = "claude -p"\ncheckpoint_timeout_s = 90\n'
                           "checkpoint_max_messages = 40\n")
    monkeypatch.setattr("neurostack.config.CONFIG_PATH", config_file)
    cfg = load_config()
    assert (cfg.checkpoint_command, cfg.checkpoint_timeout_s,
            cfg.checkpoint_max_messages) == ("claude -p", 90.0, 40)

    monkeypatch.setenv("NEUROSTACK_CHECKPOINT_COMMAND", "proxy-model")
    monkeypatch.setenv("NEUROSTACK_CHECKPOINT_TIMEOUT_S", "30")
    cfg = load_config()
    assert (cfg.checkpoint_command, cfg.checkpoint_timeout_s) == ("proxy-model", 30.0)
