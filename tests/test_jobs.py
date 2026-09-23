# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Scheduled jobs and `neurostack run-due` (issue #225)."""

import json
import sys
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from neurostack import jobs
from neurostack.jobs import Daily, Every, Job, Weekly, doctor_checks, run_due
from neurostack.locks import file_lock

T = datetime(2026, 9, 23, 12, 0)  # a Wednesday


def _at(day, hh, mm, ss=0):
    return datetime(2026, 9, day, hh, mm, ss)


class TestDueRule:
    def test_daily_never_run_is_due(self):
        assert Daily("03:00").next_due(None, _at(23, 2, 59)) <= _at(23, 2, 59)

    def test_daily_waits_for_the_instant_after_a_run(self):
        s, last = Daily("03:00"), _at(22, 3, 0, 5)
        assert s.next_due(last, _at(23, 2, 59)) > _at(23, 2, 59)
        assert s.next_due(last, _at(23, 3, 0)) <= _at(23, 3, 0)

    def test_daily_run_after_todays_instant_is_not_due_again(self):
        assert Daily("03:00").next_due(_at(23, 3, 1), _at(23, 23, 59)) == _at(24, 3, 0)

    def test_weekly_is_due_from_its_weekday_instant(self):
        s, last = Weekly(weekday=0, at="07:20"), _at(21, 7, 20, 3)  # Monday's run
        assert s.next_due(last, _at(28, 7, 19)) > _at(28, 7, 19)
        assert s.next_due(last, _at(28, 7, 20)) == _at(28, 7, 20)
        assert s.next_due(_at(14, 7, 20), _at(23, 12, 0)) <= _at(23, 12, 0)  # missed Monday

    def test_every_counts_on_the_minute_grid(self):
        s, last = Every(5), _at(23, 10, 0, 20)
        assert s.next_due(last, _at(23, 10, 4, 59)) > _at(23, 10, 4, 59)
        assert s.next_due(last, _at(23, 10, 5)) <= _at(23, 10, 5)
        assert s.next_due(None, _at(23, 10, 0)) <= _at(23, 10, 0)


def _job(name, body, requires=lambda cfg: None,
         schedule: Daily | Every = Daily("03:00")):
    return Job(name, schedule, body, requires, name)


def _boom(cfg, conn):
    raise RuntimeError("disk on fire")


@pytest.fixture
def cfg(tmp_path):
    return SimpleNamespace(db_dir=tmp_path, db_path=tmp_path / "neurostack.db",
                           jobs=None, notify_command="")


@pytest.fixture
def registry(monkeypatch):
    table = {}
    monkeypatch.setattr(jobs, "JOBS", table)
    return table


def _rows(cfg):
    import sqlite3
    conn = sqlite3.connect(cfg.db_path)
    return conn.execute("SELECT job, status, error FROM job_runs ORDER BY id").fetchall()


def test_records_each_outcome_and_continues_past_a_failure(cfg, registry):
    registry.update({
        "boom": _job("boom", _boom),
        "fine": _job("fine", lambda cfg, conn: {"n": 1}),
        "fresh": _job("fresh", lambda cfg, conn: {"skipped": True, "reason": "fresh"}),
    })
    runs = run_due(cfg, now=T)

    assert [(r["job"], r["status"]) for r in runs] == [
        ("boom", "failed"), ("fine", "ok"), ("fresh", "skipped")]
    rows = _rows(cfg)
    assert [(job, status) for job, status, _ in rows] == [
        ("boom", "failed"), ("fine", "ok"), ("fresh", "skipped")]
    assert rows[0][2].startswith("disk on fire")
    assert json.loads(runs[1]["result"]) == {"n": 1}


def test_a_run_is_not_repeated_until_due_but_force_runs_it(cfg, registry):
    registry["fine"] = _job("fine", lambda cfg, conn: {})
    assert len(run_due(cfg, now=T)) == 1
    assert run_due(cfg, now=T + timedelta(minutes=1)) == []
    forced = run_due(cfg, now=T + timedelta(minutes=1), force=True)
    assert [r["status"] for r in forced] == ["ok"]


def test_only_restricts_to_one_job_and_says_why_it_did_not_run(cfg, registry):
    registry.update({
        "a": _job("a", lambda cfg, conn: {}),
        "b": _job("b", lambda cfg, conn: {}),
        "c": _job("c", lambda cfg, conn: {}, requires=lambda cfg: "no widget"),
    })
    assert [r["job"] for r in run_due(cfg, only="b", now=T)] == ["b"]
    assert [job for job, _, _ in _rows(cfg)] == ["b"]
    (skip,) = run_due(cfg, only="c", now=T)
    assert skip["status"] == "not run" and skip["reason"] == "no widget"


def test_config_jobs_list_disables_the_rest(cfg, registry):
    registry.update({"a": _job("a", lambda cfg, conn: {}),
                     "b": _job("b", lambda cfg, conn: {})})
    cfg.jobs = ["b"]
    assert [r["job"] for r in run_due(cfg, now=T)] == ["b"]


def test_busy_lock_prints_busy_and_exits_zero(cfg, registry, monkeypatch, capsys):
    from neurostack.cli.jobs import cmd_run_due

    registry["fine"] = _job("fine", lambda cfg, conn: {})
    monkeypatch.setattr("neurostack.config.get_config", lambda: cfg)
    with file_lock(cfg.db_dir / "run-due.lock") as held:
        assert held
        assert run_due(cfg, now=T) == [{"busy": True}]
        cmd_run_due(SimpleNamespace(job=None, force=False, json=False))  # no SystemExit
    assert capsys.readouterr().out.strip() == "busy"
    assert not cfg.db_path.exists()


def test_notify_command_gets_the_failed_row_on_stdin(cfg, registry, tmp_path):
    out = tmp_path / "notified.json"
    cfg.notify_command = (
        f'"{sys.executable}" -c "import sys, pathlib; '
        f"pathlib.Path(r'{out}').write_text(sys.stdin.read())\""
    )
    registry.update({"fine": _job("fine", lambda cfg, conn: {}),
                     "boom": _job("boom", _boom)})
    run_due(cfg, now=T)

    row = json.loads(out.read_text())
    assert row["job"] == "boom" and row["status"] == "failed"
    assert "disk on fire" in row["error"]


def test_jobs_json_shows_the_requires_reason(cfg, registry, monkeypatch, capsys):
    from neurostack.cli.jobs import cmd_jobs

    registry.update({"a": _job("a", lambda cfg, conn: {}),
                     "c": _job("c", lambda cfg, conn: {}, requires=lambda cfg: "no widget")})
    monkeypatch.setattr("neurostack.config.get_config", lambda: cfg)
    cmd_jobs(SimpleNamespace(json=True))
    rows = {r["job"]: r for r in json.loads(capsys.readouterr().out)}
    assert rows["a"]["enabled"] is True and rows["a"]["reason"] is None
    assert rows["c"]["enabled"] is False and rows["c"]["reason"] == "no widget"


def test_doctor_has_one_row_per_enabled_job(cfg, registry):
    from neurostack.schema import get_db

    registry.update({
        "ran": _job("ran", lambda cfg, conn: {}),
        "boom": _job("boom", _boom),
        "never": _job("never", lambda cfg, conn: {}, schedule=Every(5)),
        "off": _job("off", lambda cfg, conn: {}, requires=lambda cfg: "no widget"),
    })
    run_due(cfg, only="ran", now=T)
    run_due(cfg, only="boom", now=T)
    conn = get_db(cfg.db_path)

    checks = {name: (status, detail) for name, status, detail in
              doctor_checks(cfg, conn, now=T + timedelta(hours=1))}
    assert set(checks) == {"Job ran", "Job boom", "Job never"}
    assert checks["Job ran"][0] == "OK"
    assert checks["Job boom"] == ("WARN", "last run failed: disk on fire")
    assert checks["Job never"][0] == "WARN" and "never run" in checks["Job never"][1]
    stale = doctor_checks(cfg, conn, now=T + timedelta(hours=49))
    assert ("Job ran", "WARN", "stale, last run 49h ago") in stale


def test_migration_28_to_29_creates_job_runs(in_memory_db):
    from neurostack.schema import SCHEMA_VERSION, _run_migrations

    conn = in_memory_db
    conn.execute("DROP TABLE job_runs")
    conn.execute("DELETE FROM schema_version")
    conn.execute("INSERT INTO schema_version VALUES (28)")
    conn.commit()
    _run_migrations(conn)

    assert conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] == SCHEMA_VERSION
    cols = {r[1] for r in conn.execute("PRAGMA table_info(job_runs)")}
    assert cols == {"id", "job", "started_at", "finished_at", "status", "result", "error"}
