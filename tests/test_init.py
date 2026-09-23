# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""`neurostack init` finishes the install: hooks, checkpoint model, timer (issue #236)."""

import io
import json
import sqlite3
import subprocess
import tomllib
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from neurostack import jobs
from neurostack.cli import schedule
from neurostack.cli.setup import cmd_init
from neurostack.client import client_config_path
from neurostack.config import Config
from neurostack.jobs import Daily, Every, Job, doctor_checks, run_due, seed_runs
from neurostack.schema import get_db

CALENDAR_JOBS = {"decay", "synthesize", "health", "verify", "reindex", "communities"}


@pytest.fixture
def home(isolated_home, tmp_path, monkeypatch, server):
    """A fresh machine: config under the throwaway HOME, the timer's systemctl faked.

    The index LLM URL points at a local HTTP server, so the checkpoint step finds it.
    """
    cfg = Config(vault_root=tmp_path / "unused", db_dir=tmp_path / "data",
                 index_llm_url=server.url)
    monkeypatch.setattr("neurostack.config._config", cfg)
    monkeypatch.setattr("neurostack.config.CONFIG_PATH",
                        isolated_home / ".config" / "neurostack" / "config.toml")
    monkeypatch.setattr("neurostack.cli.setup.cmd_doctor", lambda args: None)
    monkeypatch.setattr(schedule.platform, "system", lambda: "Linux")
    monkeypatch.setattr(schedule.shutil, "which", lambda name: "/opt/ns/bin/neurostack")
    monkeypatch.setattr(schedule.subprocess, "run",
                        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, "", ""))
    get_db(cfg.db_path)  # the index `init` builds; --no-index keeps the test offline
    return SimpleNamespace(path=isolated_home, cfg=cfg, vault=tmp_path / "vault")


def _init(home, **flags):
    args = dict(path=str(home.vault), profession=None, mode="lite", index=False,
                yes=True, no_hooks=False, no_schedule=False, checkpoint=None)
    cmd_init(SimpleNamespace(**{**args, **flags}))


def _closed_port_url():
    """A local URL nothing listens on. Port 0 is not that on Windows, where a
    connect to it did not fail in CI."""
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    return f"http://127.0.0.1:{port}"


def test_no_reachable_llm_turns_checkpoints_off_and_says_why(home, capsys):
    home.cfg.index_llm_url = url = _closed_port_url()
    _init(home, no_schedule=True)

    assert "checkpoint_command" not in _toml(home.path / ".config" / "neurostack" / "config.toml")
    assert f"No LLM reachable at {url}, so checkpoints are off." in capsys.readouterr().out


def _toml(path):
    return tomllib.loads(path.read_text()) if path.exists() else {}


def _runs(home):
    conn = sqlite3.connect(home.cfg.db_path)
    return conn.execute("SELECT job, status FROM job_runs").fetchall()


def test_yes_installs_the_timer_seeds_the_daily_jobs_and_sets_the_checkpoint_model(home):
    _init(home)

    assert (home.path / ".config" / "systemd" / "user" / "neurostack.timer").exists()
    assert {job for job, _ in _runs(home)} == CALENDAR_JOBS
    assert {status for _, status in _runs(home)} == {"skipped"}
    config = _toml(home.path / ".config" / "neurostack" / "config.toml")
    assert config["checkpoint_command"] == "/opt/ns/bin/neurostack checkpoint-llm"
    assert config["checkpoint_max_messages"] == 40
    assert config["vault_root"] == str(home.vault)
    client = _toml(client_config_path())  # AppData on Windows, ~/.config elsewhere
    assert client["checkpoint_command"] == config["checkpoint_command"]


def test_no_schedule_writes_no_timer_and_seeds_nothing(home):
    _init(home, no_schedule=True)

    assert not (home.path / ".config" / "systemd").exists()
    assert _runs(home) == []


def test_checkpoint_none_leaves_the_workers_off(home, capsys):
    from neurostack.cli.jobs import cmd_jobs

    _init(home, checkpoint="none", no_schedule=True)
    assert "checkpoint_command" not in _toml(home.path / ".config" / "neurostack" / "config.toml")
    capsys.readouterr()

    cmd_jobs(SimpleNamespace(json=True))

    rows = {r["job"]: r for r in json.loads(capsys.readouterr().out)}
    assert rows["checkpoint-worker"]["reason"] == "no checkpoint_command in config.toml"
    assert rows["harvest-worker"]["reason"] == "no checkpoint_command in config.toml"


def test_a_command_already_configured_is_kept(home):
    home.cfg.checkpoint_command = "my-model --json"
    _init(home, no_schedule=True)
    assert "checkpoint_command" not in _toml(home.path / ".config" / "neurostack" / "config.toml")
    assert home.cfg.checkpoint_command == "my-model --json"


def test_seeded_daily_jobs_wait_for_their_time_and_interval_jobs_do_not(tmp_path, monkeypatch):
    registry = {
        "nightly": Job("nightly", Daily("03:00"), lambda cfg, conn: {}, lambda cfg: None, ""),
        "often": Job("often", Every(5), lambda cfg, conn: {}, lambda cfg: None, ""),
    }
    monkeypatch.setattr(jobs, "JOBS", registry)
    cfg = SimpleNamespace(jobs=None, db_dir=tmp_path, db_path=tmp_path / "neurostack.db",
                          notify_command="")
    conn = get_db(cfg.db_path)
    now = datetime(2026, 9, 23, 12, 0)

    assert seed_runs(cfg, conn, now) == ["nightly"]
    assert seed_runs(cfg, conn, now) == []

    ran = run_due(cfg, now=now + timedelta(minutes=1))
    assert [r["job"] for r in ran] == ["often"]
    assert ("Job nightly", "OK", "waiting for its first run at 2026-09-24 03:00") in (
        doctor_checks(cfg, conn, now + timedelta(minutes=2)))


def test_checkpoint_llm_sends_the_prompt_and_prints_the_reply(monkeypatch, capsys):
    import httpx

    from neurostack.cli.checkpoint_llm import cmd_checkpoint_llm

    cfg = Config(index_llm_url="http://llm.test", index_llm_model="m1")
    monkeypatch.setattr("neurostack.config._config", cfg)
    monkeypatch.setattr("sys.stdin", io.StringIO("summarise this"))
    sent = {}

    def post(url, json, headers, timeout):
        sent.update(url=url, body=json)
        return httpx.Response(200, request=httpx.Request("POST", url),
                              json={"choices": [{"message": {"content": '[{"content": "x"}]'}}]})

    monkeypatch.setattr(httpx, "post", post)
    cmd_checkpoint_llm(SimpleNamespace())

    assert sent["url"] == "http://llm.test/v1/chat/completions"
    assert sent["body"]["model"] == "m1"
    assert sent["body"]["messages"] == [{"role": "user", "content": "summarise this"}]
    assert capsys.readouterr().out == '[{"content": "x"}]\n'


def test_checkpoint_llm_exits_nonzero_when_the_endpoint_fails(monkeypatch):
    import httpx

    from neurostack.cli.checkpoint_llm import cmd_checkpoint_llm

    monkeypatch.setattr("neurostack.config._config", Config(index_llm_url="http://llm.test"))
    monkeypatch.setattr("sys.stdin", io.StringIO("p"))
    monkeypatch.setattr(httpx, "post", lambda url, **kw: httpx.Response(
        503, request=httpx.Request("POST", url)))

    with pytest.raises(SystemExit) as exc:
        cmd_checkpoint_llm(SimpleNamespace())
    assert "503" in str(exc.value.code)
