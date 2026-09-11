"""Job queue for background extraction work (issue #191).

The checkpoint and harvest queues used to live in the orchestrator: n8n held
dedupe, the daily cap, claiming and stale reaping as per-node JavaScript, one
copy per queue. That cost two real bugs — a filter whose conditions were ORed
so a fresh row was failed as stale, and a `lt` comparison that silently never
matched a string column, leaving a crashed worker blocking its queue forever.

Everything a scheduler needs is here instead:

- ``add`` refuses a duplicate while one is live, and refuses past the daily cap.
- ``claim`` hands out at most ``concurrency`` jobs, atomically.
- ``finish`` records the outcome.
- ``reap`` fails jobs whose runner went away.

A scheduler then only calls ``neurostack queue …`` and reads JSON.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

LIVE = ("queued", "running")


@dataclass
class QueueLimits:
    """Per-queue policy. Defaults match what the n8n workflows enforced."""

    cap_per_day: int = 0          # 0 = uncapped
    stale_minutes: int = 30
    concurrency: int = 1
    extra: dict = field(default_factory=dict)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _row(row: sqlite3.Row) -> dict:
    out = dict(row)
    try:
        out["payload"] = json.loads(out.get("payload") or "{}")
    except ValueError:
        out["payload"] = {}
    return out


def _settled_today(conn: sqlite3.Connection, queue: str) -> int:
    """Jobs that finished since local midnight — the cap counts attempts made."""
    midnight = _now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    return conn.execute(
        "SELECT COUNT(*) FROM job_queue WHERE queue = ? AND finished_at >= ?",
        (queue, _iso(midnight.astimezone(timezone.utc))),
    ).fetchone()[0]


def add(conn: sqlite3.Connection, queue: str, key: str,
        payload: dict | None = None, limits: QueueLimits | None = None) -> dict:
    """Queue one job. Idempotent per key while a job for it is still live."""
    limits = limits or QueueLimits()
    if not queue or not key:
        raise ValueError("queue and key are required")

    live = conn.execute(
        f"SELECT job_id FROM job_queue WHERE queue = ? AND key = ?"
        f" AND status IN ({','.join('?' * len(LIVE))})",
        (queue, key, *LIVE),
    ).fetchone()
    if live:
        return {"ok": True, "duplicate": True, "job_id": live["job_id"],
                "position": 0, "queue": queue, "key": key}

    if limits.cap_per_day and _settled_today(conn, queue) >= limits.cap_per_day:
        return {"ok": False, "duplicate": False, "reason": "daily cap reached",
                "cap": limits.cap_per_day, "queue": queue, "key": key}

    cur = conn.execute(
        "INSERT INTO job_queue (queue, key, payload, requested_at)"
        " VALUES (?, ?, ?, ?)",
        (queue, key, json.dumps(payload or {}), _iso(_now())),
    )
    conn.commit()
    waiting = conn.execute(
        "SELECT COUNT(*) FROM job_queue WHERE queue = ? AND status = 'queued'",
        (queue,),
    ).fetchone()[0]
    return {"ok": True, "duplicate": False, "job_id": cur.lastrowid,
            "position": waiting, "queue": queue, "key": key}


def reap(conn: sqlite3.Connection, queue: str,
         limits: QueueLimits | None = None) -> list[dict]:
    """Fail running jobs whose runner went away. Returns what it reaped."""
    limits = limits or QueueLimits()
    cutoff = _iso(_now() - timedelta(minutes=limits.stale_minutes))
    rows = conn.execute(
        "SELECT * FROM job_queue WHERE queue = ? AND status = 'running'",
        (queue,),
    ).fetchall()
    # Compared in Python, not SQL: started_at is text, and a missing stamp has
    # to count as stale rather than sort itself out of the comparison.
    stale = [r for r in rows if not r["started_at"] or r["started_at"] < cutoff]
    for r in stale:
        conn.execute(
            "UPDATE job_queue SET status = 'failed', finished_at = ?, output = ?"
            " WHERE job_id = ?",
            (_iso(_now()), f"runner went stale after {limits.stale_minutes} minutes",
             r["job_id"]),
        )
    if stale:
        conn.commit()
    return [_row(r) for r in stale]


def claim(conn: sqlite3.Connection, queue: str,
          limits: QueueLimits | None = None) -> dict | None:
    """Take the oldest queued job, or return None with the reason it waits.

    Reaps first, so one crashed runner cannot wedge the queue until a human
    notices.
    """
    limits = limits or QueueLimits()
    reaped = reap(conn, queue, limits)

    running = conn.execute(
        "SELECT COUNT(*) FROM job_queue WHERE queue = ? AND status = 'running'",
        (queue,),
    ).fetchone()[0]
    if running >= limits.concurrency:
        return {"claimed": False, "reason": f"{running} already running",
                "reaped": reaped}

    if limits.cap_per_day:
        done_today = _settled_today(conn, queue)
        if done_today >= limits.cap_per_day:
            return {"claimed": False,
                    "reason": f"daily cap {done_today}/{limits.cap_per_day}",
                    "reaped": reaped}

    # One statement, so two workers racing cannot both win the same row.
    started = _iso(_now())
    cur = conn.execute(
        "UPDATE job_queue SET status = 'running', started_at = ?"
        " WHERE job_id = (SELECT job_id FROM job_queue WHERE queue = ?"
        "   AND status = 'queued' ORDER BY job_id LIMIT 1)",
        (started, queue),
    )
    conn.commit()
    if not cur.rowcount:
        return {"claimed": False, "reason": "queue empty", "reaped": reaped}

    row = conn.execute(
        "SELECT * FROM job_queue WHERE queue = ? AND status = 'running'"
        " AND started_at = ? ORDER BY job_id DESC LIMIT 1",
        (queue, started),
    ).fetchone()
    return {"claimed": True, "reaped": reaped, "job": _row(row)}


def finish(conn: sqlite3.Connection, job_id: int, ok: bool,
           saved: int = 0, output: str = "") -> dict:
    """Record how a claimed job ended."""
    row = conn.execute(
        "SELECT * FROM job_queue WHERE job_id = ?", (job_id,)
    ).fetchone()
    if row is None:
        raise ValueError(f"no job {job_id}")
    conn.execute(
        "UPDATE job_queue SET status = ?, saved = ?, output = ?, finished_at = ?"
        " WHERE job_id = ?",
        ("done" if ok else "failed", int(saved), output[:2000],
         _iso(_now()), job_id),
    )
    conn.commit()
    return _row(conn.execute(
        "SELECT * FROM job_queue WHERE job_id = ?", (job_id,)).fetchone())


def listing(conn: sqlite3.Connection, queue: str | None = None,
            status: str | None = None, limit: int = 50) -> dict:
    """Rows plus per-status counts, for a report or a health check."""
    where, params = [], []
    if queue:
        where.append("queue = ?")
        params.append(queue)
    if status:
        where.append("status = ?")
        params.append(status)
    clause = f"WHERE {' AND '.join(where)}" if where else ""

    rows = conn.execute(
        f"SELECT * FROM job_queue {clause} ORDER BY job_id DESC LIMIT ?",
        (*params, limit),
    ).fetchall()
    counts = {
        r["status"]: r["n"] for r in conn.execute(
            f"SELECT status, COUNT(*) AS n FROM job_queue {clause} GROUP BY status",
            params,
        ).fetchall()
    }
    return {"counts": counts, "jobs": [_row(r) for r in rows]}
