# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Scheduled jobs and the engine behind `neurostack run-due` (issue #225).

One OS timer calls `run-due` every minute (`neurostack schedule install`).
`run-due` takes a non-blocking file lock, walks `JOBS` in order, and runs each
job that is due, one at a time, recording every run in the `job_runs` table.
The latest row per job decides when it is next due, so a missed tick or a
crashed run needs no state beyond the database.

Schedules work in naive local time. `job_runs.started_at` is stored in UTC and
converted back to local time before it is compared.
"""

from __future__ import annotations

import contextlib
import json
import logging
import shutil
import subprocess
import sys
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, ClassVar

from .queue import LIMITS

log = logging.getLogger(__name__)


class JobFailed(Exception):
    """A job finished its work but found problems worth a notification."""

    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))


@dataclass(frozen=True)
class Daily:
    at: str = "00:00"
    period: ClassVar[timedelta] = timedelta(days=1)

    def _latest(self, now: datetime) -> datetime:
        """The most recent scheduled instant at or before `now`."""
        hour, minute = map(int, self.at.split(":"))
        inst = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        return inst if inst <= now else inst - self.period

    def next_due(self, last: datetime | None, now: datetime) -> datetime:
        inst = self._latest(now)
        return inst if last is None or last < inst else inst + self.period

    def __str__(self) -> str:
        return f"daily {self.at}"


@dataclass(frozen=True)
class Weekly(Daily):
    weekday: int = 0  # Monday, as in datetime.weekday()
    period: ClassVar[timedelta] = timedelta(days=7)

    def _latest(self, now: datetime) -> datetime:
        hour, minute = map(int, self.at.split(":"))
        inst = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        inst -= timedelta(days=(now.weekday() - self.weekday) % 7)
        return inst if inst <= now else inst - self.period

    def __str__(self) -> str:
        day = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")[self.weekday]
        return f"weekly {day} {self.at}"


@dataclass(frozen=True)
class Every:
    minutes: int

    @property
    def period(self) -> timedelta:
        return timedelta(minutes=self.minutes)

    def next_due(self, last: datetime | None, now: datetime) -> datetime:
        if last is None:
            return now
        # Counted on the minute grid the timer ticks on, so a run that started a
        # few seconds past the minute is due again N ticks later, not N + 1.
        return last.replace(second=0, microsecond=0) + self.period

    def __str__(self) -> str:
        return f"every {self.minutes} min"


@dataclass(frozen=True)
class Job:
    name: str
    schedule: Daily | Every
    run: Callable[..., dict[str, Any]]
    requires: Callable[..., str | None]
    description: str


# ---------------------------------------------------------------------------
# Job bodies. Each takes (cfg, conn), returns a result dict, and raises on
# failure. A result with "skipped": True records the run as skipped.
# ---------------------------------------------------------------------------

def _decay(cfg, conn) -> dict[str, Any]:
    from .search import run_excitability_demotion

    r = run_excitability_demotion(conn, threshold=0.05, half_life_days=30.0)
    return {"demoted": r["demoted"], "promoted": r["promoted"]}


def _synthesize(cfg, conn) -> dict[str, Any]:
    from .synthesize import synthesize_observations

    # threshold matches the `neurostack synthesize` CLI default, which is what
    # the scheduled run used before; the module default is stricter.
    r = synthesize_observations(conn, cap=5, dry_run=False, threshold=0.65)
    return {"clusters_found": r["clusters_found"], "synthesized": len(r["synthesized"]),
            "skipped": len(r.get("skipped", [])), "deferred": len(r.get("deferred", []))}


def _git(vault, *args: str) -> str:
    return subprocess.run(["git", "-C", str(vault), *args], capture_output=True,
                          text=True, check=True).stdout.strip()


def _promotion(cfg, conn) -> dict[str, Any]:
    from .cli.agent import JOBS as AGENT_JOBS
    from .cli.agent import job_prompt, run_agent
    from .memories import get_memory_stats
    from .promotion import compute_promotion_queue

    def queue_size() -> int:
        return sum(compute_promotion_queue(conn)["counts"].values())

    queue_before = queue_size()
    archived_before = get_memory_stats(conn)["archived"]
    head_before = _git(cfg.vault_root, "rev-parse", "HEAD")
    code = run_agent(cfg, job_prompt("promotion"), AGENT_JOBS["promotion"],
                     cwd=str(cfg.vault_root))
    if code:
        raise RuntimeError(f"Pi agent exited {code}")
    head = _git(cfg.vault_root, "rev-parse", "HEAD")
    changes = _git(cfg.vault_root, "diff", "--name-status", head_before, head).splitlines()
    return {
        "wrote": sum(1 for c in changes if c.startswith("A")),
        "patched": sum(1 for c in changes if c[:1] in ("M", "R")),
        "forgot": get_memory_stats(conn)["archived"] - archived_before,
        "commit": head if head != head_before else None,
        "queue_before": queue_before,
        "queue_after": queue_size(),
    }


def _pct(value: str) -> int:
    return int(value.rstrip("%"))


def _health_problems(stats: dict[str, Any]) -> list[str]:
    problems = []
    if _pct(stats["embedding_coverage"]) < 98:
        problems.append(f"embeddings {stats['embedding_coverage']}")
    if _pct(stats["summary_coverage"]) < 90:
        problems.append(f"summaries {stats['summary_coverage']}")
    if stats["stale_summaries"] > 80:
        problems.append(f"{stats['stale_summaries']} stale summaries")
    if _pct(stats["triple_coverage"]) < 90:
        problems.append(f"triples {stats['triple_coverage']}")
    return problems


def _health(cfg, conn) -> dict[str, Any]:
    from types import SimpleNamespace

    from .cli.index import cmd_backfill
    from .tools.search_tools import vault_stats

    stats = vault_stats()
    backfilled = _pct(stats["embedding_coverage"]) < 98
    if backfilled:
        # The same `neurostack backfill` (target all) the n8n health check ran.
        cmd_backfill(SimpleNamespace(target="all", vault=str(cfg.vault_root),
                                     summarize_url=cfg.index_llm_url,
                                     embed_url=cfg.embed_url))
        stats = vault_stats()
    problems = _health_problems(stats)
    if problems:
        raise JobFailed(problems)
    keys = ("notes", "chunks", "embedding_coverage", "summary_coverage",
            "stale_summaries", "triple_coverage")
    return {**{k: stats[k] for k in keys}, "backfilled": backfilled}


def _verify(cfg, conn) -> dict[str, Any]:
    from .cli.search import verify_prediction_errors

    r = verify_prediction_errors(conn)
    return {"checked": r["checked"], "kept": r["kept"],
            "resolved_stale": r["resolved_stale"], "errors": len(r["errors"])}


def _reindex(cfg, conn) -> dict[str, Any]:
    from .watcher import full_index

    pruned = full_index(vault_root=cfg.vault_root, embed_url=cfg.embed_url,
                        summarize_url=cfg.index_llm_url,
                        skip_summary=True, skip_triples=True)
    counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in ("notes", "chunks", "graph_edges")}
    return {**counts, "pruned": pruned}


def _communities(cfg, conn) -> dict[str, Any]:
    from .community import maybe_rebuild_communities

    # Probes community_build_status first and rebuilds (detect + summarize
    # every community) only when the partition is stale.
    r = maybe_rebuild_communities(conn, summarize_url=cfg.index_llm_url,
                                  embed_url=cfg.embed_url)
    if not r["rebuilt"]:
        return {"skipped": True, "reason": "fresh", "detail": r["reason"]}
    return {"coarse": r["coarse"], "fine": r["fine"], "trigger": r["trigger"]}


def _checkpoint_payload(queue: str, job: dict[str, Any]) -> tuple[str, str]:
    """(session, harness) for a claimed job, as the n8n `Read Claim` node built them."""
    p = job["payload"]
    if queue != "harvest":
        return p.get("session", ""), p.get("harness", "")
    # A transcript file is <stamp>_<session-id>.jsonl in omp and <session-id>.jsonl
    # in Claude Code. The runner resolves the file from the id, so pass the id.
    stem = str(p.get("path") or job["key"]).split("/")[-1].removesuffix(".jsonl")
    omp = p.get("provider") == "omp" and "_" in stem
    session = stem[stem.rindex("_") + 1:] if omp else stem
    return session, "claude" if p.get("provider") == "claude-code" else "omp"


def _work_queue(queue: str, limits) -> Callable[..., dict[str, Any]]:
    """A job body that claims one queued checkpoint, runs it, and finishes it.

    One claim per tick, like the n8n workflow. The client uploaded the
    transcript with the job (issue #232), so it is written to a temp file under
    `db_dir/tmp` and handed to `run_checkpoint`, the function `hook checkpoint
    --run` calls, as `transcript_path`. The file goes once the job is finished.
    The model command, its timeout and the window cap come from the server's
    config.toml (issue #233). client.toml, when this host has one, still names
    the MCP endpoint the memories are saved through.
    """
    def body(cfg, conn) -> dict[str, Any]:
        from dataclasses import replace

        from .cli.hook import run_checkpoint
        from .client import load_client_config
        from .queue import claim, finish

        out = claim(conn, queue, limits)
        result = {"claimed": int(out["claimed"]), "finished_ok": 0,
                  "finished_failed": 0, "reaped": len(out["reaped"])}
        if not out["claimed"]:
            return {**result, "reason": out["reason"]}
        job = out["job"]
        session, harness = _checkpoint_payload(queue, job)
        p = job["payload"]
        payload = {"session": session, "harness": harness,
                   "format": p.get("format") or ("claude-code" if harness == "claude" else "omp")}
        if p.get("transcript_offset"):
            payload["transcript_offset"] = p["transcript_offset"]
        tmp = cfg.db_dir / "tmp" / f"{queue}-{job['job_id']}.jsonl"
        try:
            if job["transcript"] is None:
                data, text = None, "no transcript uploaded with the job"
            else:
                tmp.parent.mkdir(parents=True, exist_ok=True)
                tmp.write_text(job["transcript"], encoding="utf-8")
                try:
                    client_cfg = replace(
                        load_client_config(),
                        checkpoint_command=cfg.checkpoint_command,
                        checkpoint_timeout_s=cfg.checkpoint_timeout_s,
                        checkpoint_max_messages=cfg.checkpoint_max_messages,
                    )
                    verdict = run_checkpoint({**payload, "transcript_path": str(tmp)},
                                             harness or "cli", client_cfg)
                    data, text = verdict.data, verdict.text
                except Exception as exc:  # cmd_hook would print this and leave no payload
                    data, text = None, f"{type(exc).__name__}: {exc}"
            # The n8n `Build Finish` mapping: success is the payload's ok field, and
            # a run with no payload (a busy lock, a crash) counts as failed.
            ok = bool(data and data.get("ok"))
            saved = data["saved"] if data else 0
            if data is None:
                output = f"no payload: {text[-200:] or 'no output'}"
            elif ok:
                output = f"saved {saved} of {data['found']}"
            else:
                output = f"failed: {data.get('error') or 'unknown'}"
            finish(conn, job["job_id"], ok, saved=saved, output=output)
        finally:
            tmp.unlink(missing_ok=True)
        if not ok:
            # n8n stopped the execution with an error here, which alerted.
            raise JobFailed([f"{queue} job {job['job_id']} ({job['key']}): {output}"])
        return {**result, "finished_ok": 1, "job_id": job["job_id"], "saved": saved}

    return body


def _harvest_scan(cfg, conn) -> dict[str, Any]:
    from .cli.sessions import enqueue_pending
    from .client import McpClient, load_client_config
    from .harvest import pending_sessions

    rows = pending_sessions(50)
    client = McpClient(load_client_config())
    try:
        summary = enqueue_pending(client, rows)
    finally:
        client.close()
    if rows and not summary["queued"] + summary["duplicates"]:
        # Nothing reached the server: say so instead of recording an ok scan.
        raise JobFailed([f"no transcript queued: {summary['jobs'][-1].get('error')}"])
    return {"pending": len(rows), "queued": summary["queued"],
            "duplicates": summary["duplicates"], "errors": summary.get("errors", 0)}


# ---------------------------------------------------------------------------
# Requirements. None means the job can run on this host.
# ---------------------------------------------------------------------------

def _client_of() -> str | None:
    """The host serving the index when it is not this one, else None."""
    import ipaddress
    import socket
    from urllib.parse import urlsplit

    from .client import load_client_config

    host = urlsplit(load_client_config().url).hostname or "localhost"
    if host in ("localhost", socket.gethostname()):
        return None
    try:
        return None if ipaddress.ip_address(host).is_loopback else host
    except ValueError:
        return host


def _needs_index(cfg) -> str | None:
    # A client keeps a local neurostack.db for its own job_runs, so the file
    # existing does not make this host the server.
    if server := _client_of():
        return f"index is served by {server}"
    if not cfg.db_path.exists():
        return f"no index at {cfg.db_path}"
    return None


def _needs_checkpoint_command(cfg) -> str | None:
    from .client import load_client_config

    if not load_client_config().checkpoint_command:
        return "no checkpoint_command in client.toml"
    return None


def _needs_queue_server(cfg) -> str | None:
    if reason := _needs_index(cfg):
        return reason
    if not cfg.checkpoint_command:
        return "no checkpoint_command in config.toml"
    return None


def _needs_vault(cfg) -> str | None:
    if not cfg.vault_root.is_dir():
        return f"no vault at {cfg.vault_root}"
    return _needs_index(cfg)


def _needs_agent(cfg) -> str | None:
    if not (cfg.agent_api_key or cfg.judge_api_key):
        return "no agent_api_key"
    if not shutil.which("node"):
        return "node not found"
    if not (cfg.vault_root / ".git").exists():
        return f"vault at {cfg.vault_root} is not a git repository"
    return _needs_index(cfg)


JOBS: dict[str, Job] = {}


def register(job: Job) -> None:
    """Append a job. Registry order is run order within one tick."""
    JOBS[job.name] = job


for _job in (
    Job("decay", Daily("03:00"), _decay, _needs_index,
        "Sync note dormancy with hotness"),
    Job("synthesize", Daily("05:30"), _synthesize, _needs_index,
        "Fold aged observation heaps into learnings"),
    Job("promotion", Daily("06:45"), _promotion, _needs_agent,
        "Pi agent writes promotion-queue memories into vault notes"),
    Job("health", Daily("07:15"), _health, _needs_vault,
        "Check index coverage, backfill when embeddings lag"),
    Job("verify", Weekly(weekday=0, at="07:20"), _verify, _needs_index,
        "Resolve prediction-error flags that no longer reproduce"),
    Job("reindex", Daily("07:50"), _reindex, _needs_vault,
        "Full index without summaries or triples"),
    Job("communities", Daily("04:30"), _communities, _needs_index,
        "Rebuild the community partition when it is stale"),
    Job("checkpoint-worker", Every(1), _work_queue("checkpoint", LIMITS["checkpoint"]),
        _needs_queue_server, "Run one uploaded /save checkpoint"),
    Job("harvest-worker", Every(5), _work_queue("harvest", LIMITS["harvest"]),
        _needs_queue_server, "Harvest one uploaded transcript through checkpoint_command"),
    Job("harvest-scan", Every(30), _harvest_scan, _needs_checkpoint_command,
        "Upload transcripts with new messages to the server's harvest queue"),
):
    register(_job)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

def _utc(moment: datetime) -> str:
    """ISO UTC text for a naive local (or aware) datetime."""
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds")


def _local(stamp: str) -> datetime:
    """Naive local datetime for a stored ISO timestamp."""
    return datetime.fromisoformat(stamp).astimezone().replace(tzinfo=None)


def last_run(conn, job: str):
    """Latest `job_runs` row for `job`, or None when it never ran."""
    return conn.execute(
        "SELECT * FROM job_runs WHERE job = ? ORDER BY started_at DESC, id DESC LIMIT 1",
        (job,),
    ).fetchone()


def next_due(conn, job: Job, now: datetime) -> datetime:
    last = last_run(conn, job.name)
    return job.schedule.next_due(_local(last["started_at"]) if last else None, now)


def blocked(cfg, job: Job) -> str | None:
    """Why this host does not run `job`, or None when it does."""
    if cfg.jobs is not None and job.name not in cfg.jobs:
        return "not listed in config jobs"
    return job.requires(cfg)


_SEEDED = "seeded at install"


def seed_runs(cfg, conn, now: datetime | None = None) -> list[str]:
    """Record a skipped run for each daily or weekly job this host runs and that never ran.

    Without it the first tick after install finds every calendar job overdue
    and runs all of them back to back, reindex and promotion included. The
    seeded row makes each one wait for its next scheduled time. Interval jobs
    are left alone, since their first run is cheap and wanted. Jobs that
    already have a row are untouched, so running this twice changes nothing.
    """
    stamp = _utc(now or datetime.now())
    seeded = []
    for job in JOBS.values():
        if not isinstance(job.schedule, Daily) or blocked(cfg, job) or last_run(conn, job.name):
            continue
        conn.execute(
            "INSERT INTO job_runs (job, started_at, finished_at, status, result)"
            " VALUES (?, ?, ?, 'skipped', ?)",
            (job.name, stamp, stamp, json.dumps({"skipped": True, "reason": _SEEDED})),
        )
        seeded.append(job.name)
    conn.commit()
    return seeded


def doctor_checks(cfg, conn, now: datetime | None = None) -> list[tuple[str, str, str]]:
    """`neurostack doctor` rows, one per job this host runs."""
    now = now or datetime.now()
    checks = []
    for job in JOBS.values():
        if blocked(cfg, job):
            continue
        name = f"Job {job.name}"
        last = last_run(conn, job.name)
        if last is None:
            checks.append((name, "WARN", "never run yet; neurostack schedule status shows"
                                         " whether the timer is on"))
            continue
        age = now - _local(last["started_at"])
        hours = age.total_seconds() / 3600
        if last["status"] == "failed":
            head = last["error"].splitlines()[0][:120] if last["error"] else "no error text"
            checks.append((name, "WARN", f"last run failed: {head}"))
        elif age > 2 * job.schedule.period:
            checks.append((name, "WARN", f"stale, last run {hours:.0f}h ago"))
        elif _SEEDED in (last["result"] or ""):
            first = job.schedule.next_due(_local(last["started_at"]), now)
            checks.append((name, "OK", f"waiting for its first run at {first:%Y-%m-%d %H:%M}"))
        else:
            checks.append((name, "OK", f"last run {hours:.1f}h ago"))
    return checks


def _notify(command: str, row: dict[str, Any]) -> None:
    try:
        r = subprocess.run(command, shell=True, input=json.dumps(row), text=True,
                           timeout=60, capture_output=True)
        if r.returncode:
            log.warning("notify_command exited %d: %s", r.returncode, r.stderr.strip()[-500:])
    except Exception as exc:
        log.warning("notify_command failed: %s", exc)


def _run(cfg, conn, job: Job, now: datetime | None) -> dict[str, Any]:
    run_id = conn.execute(
        "INSERT INTO job_runs (job, started_at, status) VALUES (?, ?, 'running')",
        (job.name, _utc(now or datetime.now())),
    ).lastrowid
    conn.commit()
    t0 = time.monotonic()
    status, result, error = "ok", None, None
    try:
        # Job output belongs in the journal; stdout carries the run-due report.
        with contextlib.redirect_stdout(sys.stderr):
            result = job.run(cfg, conn)
        if result.get("skipped"):
            status = "skipped"
    except (Exception, SystemExit) as exc:
        conn.rollback()  # never commit a failed body's half-written transaction
        status = "failed"
        error = f"{exc}\n\n{traceback.format_exc()[-2000:]}"
    conn.execute(
        "UPDATE job_runs SET finished_at = ?, status = ?, result = ?, error = ? WHERE id = ?",
        (_utc(datetime.now()), status, json.dumps(result, default=str) if result else None,
         error, run_id),
    )
    conn.commit()
    row = dict(conn.execute("SELECT * FROM job_runs WHERE id = ?", (run_id,)).fetchone())
    duration = round(time.monotonic() - t0, 1)
    log.info("job %s %s in %.1fs", job.name, status, duration)
    if status == "failed" and cfg.notify_command:
        _notify(cfg.notify_command, row)
    return {**row, "duration_s": duration}


def run_due(cfg, *, only: str | None = None, force: bool = False,
            now: datetime | None = None) -> list[dict[str, Any]]:
    """Run every due job once, in registry order, under one non-blocking lock.

    Returns one dict per run (the `job_runs` row plus `duration_s`), or
    `[{"busy": True}]` when another run-due holds the lock. A job that is
    blocked or not due is skipped without a row; with `only` set, the skip is
    returned so the caller can say why nothing ran.
    """
    from .locks import file_lock
    from .schema import get_db

    with file_lock(cfg.db_dir / "run-due.lock", blocking=False) as held:
        if not held:
            return [{"busy": True}]
        conn = None
        runs = []
        for job in JOBS.values():
            if only and job.name != only:
                continue
            reason = blocked(cfg, job)
            if reason is None:
                # Opened only once a job can run, so a host with no index
                # never gets an empty database created by the timer.
                conn = conn or get_db(cfg.db_path)
                current = now or datetime.now()
                due_at = next_due(conn, job, current)
                if due_at > current and not force:
                    reason = f"not due until {due_at:%Y-%m-%d %H:%M}"
            if reason:
                log.debug("job %s skipped: %s", job.name, reason)
                if only:
                    runs.append({"job": job.name, "status": "not run", "reason": reason})
                continue
            runs.append(_run(cfg, conn, job, now))
        return runs
