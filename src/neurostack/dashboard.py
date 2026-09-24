# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Read-only data for the `neurostack ui` dashboard (issue #242).

Each function takes a read-only connection with `row_factory = sqlite3.Row`
and returns plain JSON-serialisable data. Nothing here writes, runs a job or
calls a model, so the promotion numbers come from the last `promotion` run and
never from `compute_promotion_queue`.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any

from . import jobs
from .queue import LIMITS

_QUEUE_STATUSES = ("queued", "running", "done", "failed")


def _json(text: str | None) -> Any:
    """Parsed JSON, or None when the text is absent or not JSON."""
    try:
        return json.loads(text) if text else None
    except ValueError:
        return None


def _clamp(value: int, high: int) -> int:
    return max(1, min(value, high))


def overview(conn: sqlite3.Connection) -> dict[str, Any]:
    from .tools.search_tools import index_stats

    stats = index_stats(conn)
    recent = conn.execute(
        "SELECT path, title, updated_at FROM notes ORDER BY updated_at DESC LIMIT 10"
    ).fetchall()
    return {
        "stats": stats,
        "memories": {k: stats["memories"][k] for k in ("total", "by_type")},
        "recent_notes": [dict(r) for r in recent],
    }


def _run(row: sqlite3.Row) -> dict[str, Any]:
    start, end = row["started_at"], row["finished_at"]
    duration = None
    if end:
        seconds = (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()
        duration = round(seconds, 1)
    return {"status": row["status"], "started_at": start, "finished_at": end,
            "duration_s": duration, "error": row["error"], "result": _json(row["result"])}


def _runs(conn: sqlite3.Connection, job: str, limit: int) -> list[sqlite3.Row]:
    # Same order as jobs.last_run, so `last` is the row the scheduler reads.
    return conn.execute(
        "SELECT * FROM job_runs WHERE job = ? ORDER BY started_at DESC, id DESC LIMIT ?",
        (job, limit),
    ).fetchall()


def automations(conn: sqlite3.Connection, cfg, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now()
    out = []
    for job in jobs.JOBS.values():
        reason = jobs.blocked(cfg, job)
        rows = _runs(conn, job.name, 14)
        out.append({
            "name": job.name,
            "schedule": str(job.schedule),
            "description": job.description,
            "blocked": reason,
            "next_due": None if reason else jobs._utc(jobs.next_due(conn, job, now)),
            "last": _run(rows[0]) if rows else None,
            "recent": [r["status"] for r in rows],
        })

    queues = {name: dict.fromkeys(_QUEUE_STATUSES, 0) for name in LIMITS}
    for r in conn.execute(
        "SELECT queue, status, COUNT(*) AS n FROM job_queue GROUP BY queue, status"
    ):
        queues.setdefault(r["queue"], dict.fromkeys(_QUEUE_STATUSES, 0))[r["status"]] = r["n"]
    return {"jobs": out, "queues": queues}


def job_runs(conn: sqlite3.Connection, job: str, limit: int = 50) -> list[dict[str, Any]]:
    if job not in jobs.JOBS:
        raise KeyError(job)
    return [{"id": r["id"], **_run(r)} for r in _runs(conn, job, _clamp(limit, 500))]


def graph(conn: sqlite3.Connection, limit: int = 500,
          community: int | None = None) -> dict[str, Any]:
    where, params = "", ()
    if community is not None:
        where = "WHERE n.path IN (SELECT entity FROM community_members WHERE community_id = ?)"
        params = (community,)
    # Each node reports its community at the finest level that has members,
    # level 1 after a normal build, so colours stay fine under a coarse filter.
    level = conn.execute(
        "SELECT MAX(c.level) FROM communities c"
        " JOIN community_members m ON m.community_id = c.community_id"
    ).fetchone()[0]
    rows = conn.execute(
        "SELECT n.path AS id, n.title, COALESCE(s.pagerank, 0.0) AS pagerank,"
        " COALESCE(s.in_degree, 0) AS in_degree, COALESCE(s.out_degree, 0) AS out_degree,"
        " md.status,"
        " (SELECT m.community_id FROM community_members m"
        "   JOIN communities c ON c.community_id = m.community_id"
        "   WHERE m.entity = n.path AND c.level = ?) AS community"
        " FROM notes n"
        " LEFT JOIN graph_stats s ON s.note_path = n.path"
        " LEFT JOIN note_metadata md ON md.note_path = n.path"
        f" {where} ORDER BY pagerank DESC, n.path LIMIT ?",
        (level, *params, _clamp(limit, 5000)),
    ).fetchall()
    total = conn.execute(f"SELECT COUNT(*) FROM notes n {where}", params).fetchone()[0]

    ids = {r["id"] for r in rows}
    edges = [
        {"source": src, "target": dst}
        for src, dst in conn.execute("SELECT source_path, target_path FROM graph_edges")
        if src in ids and dst in ids
    ]
    return {"nodes": [dict(r) for r in rows], "edges": edges, "total_nodes": total,
            "truncated": total > len(rows)}


def note(conn: sqlite3.Connection, path: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT n.path, n.title, sm.summary_text AS summary,"
        " COALESCE(s.pagerank, 0.0) AS pagerank, md.status, n.updated_at"
        " FROM notes n"
        " LEFT JOIN summaries sm ON sm.note_path = n.path"
        " LEFT JOIN graph_stats s ON s.note_path = n.path"
        " LEFT JOIN note_metadata md ON md.note_path = n.path"
        " WHERE n.path = ?",
        (path,),
    ).fetchone()
    if row is None:
        raise KeyError(path)
    # graph.get_neighborhood is not reused because it fuzzy-matches the path
    # and logs the neighbours as primed usage, which is a write.
    neighbors = conn.execute(
        "SELECT n.path, n.title, 'out' AS direction FROM graph_edges e"
        " JOIN notes n ON n.path = e.target_path WHERE e.source_path = ?"
        " UNION ALL"
        " SELECT n.path, n.title, 'in' FROM graph_edges e"
        " JOIN notes n ON n.path = e.source_path WHERE e.target_path = ?"
        " ORDER BY 2, 1",
        (path, path),
    ).fetchall()
    return {**dict(row), "neighbors": [dict(r) for r in neighbors]}


def communities(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT community_id AS id, level, title, summary, member_notes, updated_at"
        " FROM communities ORDER BY member_notes DESC, community_id"
    ).fetchall()
    return [dict(r) for r in rows]


def memories(conn: sqlite3.Connection, limit: int = 50, entity_type: str | None = None,
             q: str | None = None) -> dict[str, Any]:
    # total and by_type count the whole table; the filters only narrow items.
    by_type = {
        r["entity_type"]: r["n"] for r in conn.execute(
            "SELECT entity_type, COUNT(*) AS n FROM memories GROUP BY entity_type"
        )
    }
    where, params = [], []
    if entity_type:
        where.append("entity_type = ?")
        params.append(entity_type)
    if q:
        where.append("instr(lower(content), lower(?)) > 0")
        params.append(q)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    rows = conn.execute(
        "SELECT memory_id AS id, content, entity_type, tags, workspace, source_agent,"
        f" created_at FROM memories {clause}"
        " ORDER BY created_at DESC, memory_id DESC LIMIT ?",
        (*params, _clamp(limit, 500)),
    ).fetchall()
    items = [{**dict(r), "tags": _json(r["tags"]) or []} for r in rows]
    return {"total": sum(by_type.values()), "by_type": by_type, "items": items}
