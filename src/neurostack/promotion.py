# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Promotion queue (issue #92): memories whose knowledge should move into notes.

Agents write rich memories but the note layer lags. This module computes a
worklist in four buckets for a downstream agent (a nightly job, or an
interactive session) to consume. The first three are mechanical reads; the
fourth asks the judgement model and caches its verdicts:

- **debt**: memories explicitly tagged ``promotion-debt`` by a session that
  ended without running its vault-save step.
- **drift**: unresolved ``memory_drift`` prediction errors (issue #38) — the
  memory no longer matches the notes it references — and, since issue #136,
  memories whose trigger fired but was ignored (``trigger_ignored`` rows, one
  entry per memory with the running count; ``suggest: retire`` at three).
- **dead_handoffs**: ``context`` memories that read as handoff/continuation
  state and are older than a grace window. Consumed handoffs stored as if
  live are the single biggest volatile-layer polluter. Memories tagged
  ``open-thread`` are deliberate keeps and excluded.
- **uncovered**: durable memories (decision/learning/bug/convention) that the
  judgement model says no note records yet (issue #215). Embedding similarity
  only picks the evidence, the three nearest notes; it does not decide. A fixed
  similarity floor used to decide, and every embedder change moved the right
  value: after the switch to qwen3-embedding-8b nothing scored below 0.55, so
  the bucket sat empty.
"""

import hashlib
import json
import logging
import sqlite3

log = logging.getLogger("neurostack")

DURABLE_TYPES = ("decision", "learning", "bug", "convention")
HANDOFF_MARKERS = ("handoff", "continuation", "state anchor")
DEFAULT_HANDOFF_AGE_DAYS = 14
DEFAULT_UNCOVERED_LIMIT = 200
_PREVIEW_CHARS = 240

# The coverage rubric runs 0-3. Below the midpoint between "topic there, key
# fact missing" (1) and "mostly covered" (2) the memory holds something the
# vault does not. This is a point on the judge's scale, not the embedder's, so
# it survives an embedder change.
UNCOVERED_BELOW = 1.5
_EVIDENCE_NOTES = 3
_MEMORY_CHARS = 1500
_SUMMARY_CHARS = 500
_PASSAGE_CHARS = 1200
_COVERAGE_QUESTION = {
    "coverage": {
        "type": "score",
        "instructions": (
            "Do these vault notes already record the memory's key fact, so "
            "turning the memory into a note would add nothing new?"
        ),
        "criteria": [
            "not covered: the notes do not mention this at all",
            "topic appears, but the memory's key fact, number or decision is missing",
            "mostly covered, only a minor detail is missing",
            "fully covered: the notes already state this",
        ],
    },
}
_QUESTION_KEY = json.dumps(_COVERAGE_QUESTION, sort_keys=True)


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
    out = [
        _entry(
            dict(r),
            drifted_from=r["note_path"],
            cosine_distance=r["cosine_distance"],
            detected_at=r["detected_at"],
        )
        for r in conn.execute(sql, params).fetchall()
    ]
    out.extend(_ignored_trigger_entries(conn, workspace))
    return out


def _ignored_trigger_entries(
    conn: sqlite3.Connection, workspace: str | None
) -> list[dict]:
    """One entry per memory whose trigger fired and was ignored (issue #136)."""
    from .triggers import IGNORED_ERROR_TYPE, RETIRE_AFTER_IGNORES

    sql = (
        "SELECT m.*, COUNT(*) AS ignored_count, MAX(p.detected_at) AS detected_at,"
        " MAX(p.context) AS ignored_trigger"
        " FROM prediction_errors p JOIN memories m ON m.memory_id = p.memory_id"
        " WHERE p.resolved_at IS NULL AND p.error_type = ?"
    )
    params: list = [IGNORED_ERROR_TYPE]
    if workspace:
        sql += " AND m.workspace = ?"
        params.append(workspace)
    sql += " GROUP BY m.memory_id ORDER BY ignored_count DESC, detected_at DESC"
    out = []
    for r in conn.execute(sql, params).fetchall():
        extra = {
            "ignored_trigger": r["ignored_trigger"],
            "ignored_count": r["ignored_count"],
            "detected_at": r["detected_at"],
        }
        if r["ignored_count"] >= RETIRE_AFTER_IGNORES:
            extra["suggest"] = "retire"
        out.append(_entry(dict(r), **extra))
    return out


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


def _evidence(sims, chunk_paths: list[str]) -> list[int]:
    """Indices of the best chunk in each of the nearest distinct notes."""
    import numpy as np

    picked: list[int] = []
    seen: set[str] = set()
    for i in np.argsort(-sims):
        path = chunk_paths[i]
        if path in seen:
            continue
        seen.add(path)
        picked.append(int(i))
        if len(picked) == _EVIDENCE_NOTES:
            break
    return picked


def _fingerprint(content: str, paths: list[str], note_hashes: dict) -> str:
    h = hashlib.sha256(_QUESTION_KEY.encode())
    h.update(content.encode())
    for path in paths:
        h.update(f"\0{path}\0{note_hashes.get(path) or ''}".encode())
    return h.hexdigest()


def _coverage_state(conn: sqlite3.Connection, content: str, chunk_ids: list[int]) -> str:
    parts = [f"MEMORY:\n{content[:_MEMORY_CHARS]}\n"]
    for n, chunk_id in enumerate(chunk_ids, 1):
        chunk = conn.execute(
            "SELECT note_path, content FROM chunks WHERE chunk_id = ?", (chunk_id,)
        ).fetchone()
        summary = conn.execute(
            "SELECT summary_text FROM summaries WHERE note_path = ?",
            (chunk["note_path"],),
        ).fetchone()
        parts.append(
            f"NOTE {n}: {chunk['note_path']}\n"
            f"summary: {(summary[0] if summary else '')[:_SUMMARY_CHARS]}\n"
            f"closest passage:\n{(chunk['content'] or '')[:_PASSAGE_CHARS]}\n"
        )
    return "\n".join(parts)


def _uncovered_bucket(
    conn: sqlite3.Connection,
    workspace: str | None,
    limit: int,
    exclude_ids: set[int],
) -> tuple[list[dict], int]:
    """Durable memories the judge says no note records, and how many it could
    not judge this time.

    Scans the newest ``limit`` durable memories. A memory whose fingerprint
    matches its cached verdict is not judged again. One the judge fails to
    answer is left out rather than guessed, counted as pending, and asked
    again on the next call.
    """
    import numpy as np

    from .embedder import blob_to_embedding, cosine_similarity_batch

    chunk_rows = conn.execute(
        "SELECT chunk_id, note_path, embedding FROM chunks WHERE embedding IS NOT NULL"
    ).fetchall()
    if not chunk_rows:
        return [], 0
    chunk_matrix = np.vstack([blob_to_embedding(r["embedding"]) for r in chunk_rows])
    chunk_paths = [r["note_path"] for r in chunk_rows]
    chunk_ids = [r["chunk_id"] for r in chunk_rows]

    sql = (
        "SELECT m.*, c.fingerprint AS cached_fingerprint, c.score AS cached_score"
        " FROM memories m LEFT JOIN memory_coverage c ON c.memory_id = m.memory_id"
        " WHERE m.embedding IS NOT NULL"
        f" AND m.entity_type IN ({','.join('?' * len(DURABLE_TYPES))})"
    )
    params: list = list(DURABLE_TYPES)
    if workspace:
        sql += " AND m.workspace = ?"
        params.append(workspace)
    sql += " ORDER BY m.created_at DESC LIMIT ?"
    params.append(limit)

    note_hashes: dict | None = None
    judged: list[tuple[dict, float]] = []
    ask: list[dict] = []
    for r in conn.execute(sql, params).fetchall():
        row = dict(r)
        if row["memory_id"] in exclude_ids:
            continue
        emb = blob_to_embedding(row["embedding"])
        if emb is None:
            continue
        if note_hashes is None:
            note_hashes = dict(conn.execute("SELECT path, content_hash FROM notes"))
        sims = cosine_similarity_batch(emb, chunk_matrix)
        picked = _evidence(sims, chunk_paths)
        row["_evidence"] = [chunk_ids[i] for i in picked]
        row["_nearest"] = (chunk_paths[picked[0]], float(sims[picked[0]]))
        row["_fingerprint"] = _fingerprint(
            row["content"], [chunk_paths[i] for i in picked], note_hashes
        )
        if row["cached_fingerprint"] == row["_fingerprint"]:
            judged.append((row, row["cached_score"]))
        else:
            ask.append(row)

    pending = 0
    if ask:
        from .judge import decide_many

        states = [_coverage_state(conn, r["content"], r["_evidence"]) for r in ask]
        for row, answer in zip(ask, decide_many(states, _COVERAGE_QUESTION)):
            try:
                score = float(answer["coverage"]["score"]) if answer else None
            except (KeyError, TypeError, ValueError):
                score = None
            if score is None:
                pending += 1
                continue
            conn.execute(
                "INSERT OR REPLACE INTO memory_coverage"
                " (memory_id, fingerprint, score, judged_at)"
                " VALUES (?, ?, ?, datetime('now'))",
                (row["memory_id"], row["_fingerprint"], score),
            )
            judged.append((row, score))
        conn.commit()
        if pending:
            log.warning("promotion: %d memories left unjudged, retried next run", pending)

    out = []
    for row, score in judged:
        if score >= UNCOVERED_BELOW:
            continue
        note, sim = row["_nearest"]
        out.append(_entry(
            row,
            coverage=round(score, 2),
            nearest_note=note,
            nearest_similarity=round(sim, 4),
        ))
    out.sort(key=lambda e: (e["coverage"], e["nearest_similarity"]))
    return out, pending


def compute_promotion_queue(
    conn: sqlite3.Connection,
    workspace: str | None = None,
    handoff_age_days: int = DEFAULT_HANDOFF_AGE_DAYS,
    uncovered_limit: int = DEFAULT_UNCOVERED_LIMIT,
) -> dict:
    """Compute the promotion worklist.

    The uncovered bucket calls the judgement model for memories it has not
    judged yet and caches each verdict in ``memory_coverage``; everything else
    is a read. ``uncovered_pending`` counts memories the judge did not answer
    this time; they are left out of ``counts`` so a judge outage empties the
    bucket instead of flooding it.
    """
    workspace = workspace.strip("/") if workspace else None

    debt = _debt_bucket(conn, workspace)
    drift = _drift_bucket(conn, workspace)
    dead = _dead_handoff_bucket(conn, workspace, handoff_age_days)
    claimed = {e["memory_id"] for b in (debt, drift, dead) for e in b}
    uncovered, pending = _uncovered_bucket(conn, workspace, uncovered_limit, claimed)

    return {
        "counts": {
            "debt": len(debt),
            "drift": len(drift),
            "dead_handoffs": len(dead),
            "uncovered": len(uncovered),
        },
        "uncovered_pending": pending,
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
