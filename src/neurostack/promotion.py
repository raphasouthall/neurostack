# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Promotion queue (issue #92): memories whose knowledge should move into notes.

Agents write rich memories but the note layer lags. Detection is mechanical;
only the note-writing needs judgment. This module computes a deterministic
worklist in four buckets — no LLM calls, no writes — for a downstream agent
(a weekly cron, or an interactive session) to consume:

- **debt**: memories explicitly tagged ``promotion-debt`` by a session that
  ended without running its vault-save step.
- **drift**: unresolved ``memory_drift`` prediction errors (issue #38) — the
  memory no longer matches the notes it references.
- **dead_handoffs**: ``context`` memories that read as handoff/continuation
  state and are older than a grace window. Consumed handoffs stored as if
  live are the single biggest volatile-layer polluter. Memories tagged
  ``open-thread`` are deliberate keeps and excluded.
- **uncovered**: durable memories (decision/learning/bug/convention) whose
  nearest note chunk falls below a similarity floor — knowledge with no
  covering note anywhere in the vault.
"""

import json
import sqlite3

DURABLE_TYPES = ("decision", "learning", "bug", "convention")
HANDOFF_MARKERS = ("handoff", "continuation", "state anchor")
DEFAULT_HANDOFF_AGE_DAYS = 14
DEFAULT_UNCOVERED_SIM_FLOOR = 0.55
DEFAULT_UNCOVERED_LIMIT = 200
_PREVIEW_CHARS = 240


def _entry(row: dict, **extra) -> dict:
    tags_raw = row.get("tags")
    if isinstance(tags_raw, str):
        try:
            tags = json.loads(tags_raw)
        except (json.JSONDecodeError, TypeError):
            tags = []
    else:
        tags = tags_raw or []
    return {
        "memory_id": row["memory_id"],
        "entity_type": row["entity_type"],
        "workspace": row.get("workspace"),
        "tags": tags,
        "created_at": row.get("created_at"),
        "preview": (row.get("content") or "")[:_PREVIEW_CHARS],
        **extra,
    }


def _debt_bucket(conn: sqlite3.Connection, workspace: str | None) -> list[dict]:
    sql = (
        "SELECT DISTINCT m.* FROM memories m, json_each(m.tags) t"
        " WHERE t.value = 'promotion-debt'"
    )
    params: list = []
    if workspace:
        sql += " AND m.workspace = ?"
        params.append(workspace)
    sql += " ORDER BY m.created_at DESC"
    return [_entry(dict(r)) for r in conn.execute(sql, params).fetchall()]


def _drift_bucket(conn: sqlite3.Connection, workspace: str | None) -> list[dict]:
    sql = (
        "SELECT m.*, p.note_path, p.cosine_distance, p.detected_at"
        " FROM prediction_errors p JOIN memories m ON m.memory_id = p.memory_id"
        " WHERE p.memory_id IS NOT NULL AND p.resolved_at IS NULL"
        " AND p.error_type = 'memory_drift'"
    )
    params: list = []
    if workspace:
        sql += " AND m.workspace = ?"
        params.append(workspace)
    sql += " ORDER BY p.cosine_distance DESC"
    return [
        _entry(
            dict(r),
            drifted_from=r["note_path"],
            cosine_distance=r["cosine_distance"],
            detected_at=r["detected_at"],
        )
        for r in conn.execute(sql, params).fetchall()
    ]


def _dead_handoff_bucket(
    conn: sqlite3.Connection, workspace: str | None, age_days: int
) -> list[dict]:
    sql = (
        "SELECT * FROM memories WHERE entity_type = 'context'"
        " AND created_at < datetime('now', ?)"
    )
    params: list = [f"-{age_days} days"]
    if workspace:
        sql += " AND workspace = ?"
        params.append(workspace)
    sql += " ORDER BY created_at ASC"

    out = []
    for r in conn.execute(sql, params).fetchall():
        row = dict(r)
        head = (row.get("content") or "")[:120].lower()
        if not any(m in head for m in HANDOFF_MARKERS):
            continue
        tags_raw = row.get("tags") or "[]"
        if "open-thread" in tags_raw:
            continue
        out.append(_entry(row, age_days_over=age_days))
    return out


def _uncovered_bucket(
    conn: sqlite3.Connection,
    workspace: str | None,
    sim_floor: float,
    limit: int,
    exclude_ids: set[int],
) -> list[dict]:
    import numpy as np

    from .embedder import blob_to_embedding, cosine_similarity_batch

    chunk_rows = conn.execute(
        "SELECT note_path, embedding FROM chunks WHERE embedding IS NOT NULL"
    ).fetchall()
    if not chunk_rows:
        return []
    chunk_matrix = np.vstack([blob_to_embedding(r["embedding"]) for r in chunk_rows])
    chunk_paths = [r["note_path"] for r in chunk_rows]

    sql = (
        "SELECT * FROM memories WHERE embedding IS NOT NULL"
        f" AND entity_type IN ({','.join('?' * len(DURABLE_TYPES))})"
    )
    params: list = list(DURABLE_TYPES)
    if workspace:
        sql += " AND workspace = ?"
        params.append(workspace)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)

    out = []
    for r in conn.execute(sql, params).fetchall():
        row = dict(r)
        if row["memory_id"] in exclude_ids:
            continue
        emb = blob_to_embedding(row["embedding"])
        if emb is None:
            continue
        sims = cosine_similarity_batch(emb, chunk_matrix)
        best = int(sims.argmax())
        best_sim = float(sims[best])
        if best_sim >= sim_floor:
            continue
        out.append(_entry(
            row,
            nearest_note=chunk_paths[best],
            nearest_similarity=round(best_sim, 4),
        ))
    out.sort(key=lambda e: e["nearest_similarity"])
    return out


def compute_promotion_queue(
    conn: sqlite3.Connection,
    workspace: str | None = None,
    handoff_age_days: int = DEFAULT_HANDOFF_AGE_DAYS,
    uncovered_sim_floor: float = DEFAULT_UNCOVERED_SIM_FLOOR,
    uncovered_limit: int = DEFAULT_UNCOVERED_LIMIT,
) -> dict:
    """Compute the promotion worklist. Pure read — no LLM, no writes."""
    workspace = workspace.strip("/") if workspace else None

    debt = _debt_bucket(conn, workspace)
    drift = _drift_bucket(conn, workspace)
    dead = _dead_handoff_bucket(conn, workspace, handoff_age_days)
    claimed = {e["memory_id"] for b in (debt, drift, dead) for e in b}
    uncovered = _uncovered_bucket(
        conn, workspace, uncovered_sim_floor, uncovered_limit, claimed
    )

    return {
        "counts": {
            "debt": len(debt),
            "drift": len(drift),
            "dead_handoffs": len(dead),
            "uncovered": len(uncovered),
        },
        "debt": debt,
        "drift": drift,
        "dead_handoffs": dead,
        "uncovered": uncovered,
        "hint": (
            "Per entry: promote durable content into a note (folder pattern,"
            " update index.md), then vault_update_memory to slim + wiki-link,"
            " or vault_forget a consumed handoff (archived, restorable)."
            " 'open-thread' tagged memories are deliberate keeps."
        ),
    }
