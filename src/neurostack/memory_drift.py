# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Memory drift detection (issue #38).

When an agent-written memory references vault notes via `[[wiki-links]]`, the
note it points at can move on while the memory stays frozen — a memory saying
"X is a blocker in [[project]]" is stale once the project note records X as
done. NeuroStack already models "retrieval diverged from expectation" as a
prediction error; memory drift is the same signal applied to the memory layer.

At memory-retrieval time we compare the memory's stored embedding to the
current chunk embeddings of the notes it links. If the best match is far enough
(cosine distance over threshold), we write a `memory_drift` row to
`prediction_errors` — surfaced by `vault_prediction_errors`, reconciled by the
existing `vault_update_memory` / `vault_forget`. All computation is on stored
embeddings, so no live embedder call and no git/external awareness in core.
"""

from __future__ import annotations

import json
import sqlite3

# Cosine distance over which a memory is considered drifted from a note.
# Calibrated against the production embed model (embeddinggemma:300m) on realistic
# memory/note pairs: an aligned memory sits around 0.25, a memory whose note now
# contradicts it ("blocker" -> "resolved") around 0.50, unrelated content above
# 0.8. 0.40 separates aligned from drifted with margin. The note-centric
# low_overlap distance (~0.62) is tuned for query↔note fit and is too slack here —
# it would miss the resolved-note case, the whole point of drift detection.
# Detection takes the MAX similarity across a note's chunks, so drift only fires
# when the memory is far from every chunk — conservative by design.
DRIFT_THRESHOLD = 0.40
# Skip re-inserting a drift row for the same (memory, note) seen this recently;
# refresh the existing row instead so hot retrievals don't flood the log.
DRIFT_DEBOUNCE_HOURS = 24


def detect_memory_drift(
    conn: sqlite3.Connection,
    memory_id: int,
    content: str,
    embedding,
    threshold: float = DRIFT_THRESHOLD,
    debounce_hours: int = DRIFT_DEBOUNCE_HOURS,
) -> list[dict]:
    """Detect drift of one memory from the notes it wiki-links.

    `embedding` is the memory's stored embedding (numpy array). Returns the list
    of drift records written/refreshed (for observability); empty when the
    memory has no embedding, no resolvable links, or no drift.
    """
    if embedding is None or not content:
        return []

    from .chunker import extract_wiki_links
    from .graph import _build_link_index, resolve_wiki_link

    links = extract_wiki_links(content)
    if not links:
        return []

    all_paths = [r["path"] for r in conn.execute("SELECT path FROM notes")]
    if not all_paths:
        return []
    index = _build_link_index(all_paths)

    resolved: list[tuple[str, str]] = []
    seen: set[str] = set()
    for link in links:
        path = resolve_wiki_link(link, all_paths, _link_index=index)
        if path and path not in seen:
            seen.add(path)
            resolved.append((link, path))
    if not resolved:
        return []

    import numpy as np

    from .embedder import blob_to_embedding, cosine_similarity_batch

    written = []
    for link, note_path in resolved:
        rows = conn.execute(
            "SELECT embedding FROM chunks"
            " WHERE note_path = ? AND embedding IS NOT NULL",
            (note_path,),
        ).fetchall()
        if not rows:
            continue
        matrix = np.vstack([blob_to_embedding(r["embedding"]) for r in rows])
        max_sim = float(cosine_similarity_batch(embedding, matrix).max())
        distance = 1.0 - max_sim
        if distance <= threshold:
            continue
        context = json.dumps({"wiki_link": link, "max_sim": round(max_sim, 4)})
        _write_drift(conn, memory_id, note_path, distance, context, debounce_hours)
        written.append(
            {"memory_id": memory_id, "note_path": note_path,
             "cosine_distance": round(distance, 4)}
        )
    return written


def _write_drift(
    conn: sqlite3.Connection,
    memory_id: int,
    note_path: str,
    distance: float,
    context: str,
    debounce_hours: int,
) -> None:
    """Insert a memory_drift row, or refresh an existing unresolved one for the
    same (memory, note) within the debounce window (keeping the strongest signal)."""
    existing = conn.execute(
        "SELECT error_id, cosine_distance FROM prediction_errors"
        " WHERE memory_id = ? AND note_path = ? AND error_type = 'memory_drift'"
        "   AND resolved_at IS NULL"
        "   AND detected_at > datetime('now', ?)"
        " ORDER BY detected_at DESC LIMIT 1",
        (memory_id, note_path, f"-{int(debounce_hours)} hours"),
    ).fetchone()

    if existing:
        if distance > existing["cosine_distance"]:
            conn.execute(
                "UPDATE prediction_errors SET cosine_distance = ?, context = ?,"
                " detected_at = datetime('now') WHERE error_id = ?",
                (round(distance, 4), context, existing["error_id"]),
            )
            conn.commit()
        return

    conn.execute(
        "INSERT INTO prediction_errors"
        " (note_path, memory_id, query, cosine_distance, error_type, context)"
        " VALUES (?, ?, ?, ?, 'memory_drift', ?)",
        (note_path, memory_id, f"memory:{memory_id}", round(distance, 4), context),
    )
    conn.commit()


def check_memory_drift(conn: sqlite3.Connection, memories) -> None:
    """Run drift detection for a batch of just-retrieved memories. Non-blocking:
    any failure (no numpy in lite mode, embedder blobs absent, etc.) is swallowed
    so retrieval is never disrupted."""
    try:
        ids = [m.memory_id for m in memories]
        if not ids:
            return
        placeholders = ",".join("?" * len(ids))
        rows = conn.execute(
            f"SELECT memory_id, content, embedding FROM memories"
            f" WHERE memory_id IN ({placeholders}) AND embedding IS NOT NULL",
            ids,
        ).fetchall()
        if not rows:
            return
        from .embedder import blob_to_embedding

        for r in rows:
            detect_memory_drift(
                conn, r["memory_id"], r["content"],
                blob_to_embedding(r["embedding"]),
            )
    except Exception:
        pass  # drift detection must never disrupt retrieval


def resolve_memory_drift(conn: sqlite3.Connection, memory_id: int) -> int:
    """Mark all open drift rows for a memory resolved (its content just changed,
    so the frozen-vs-current comparison no longer holds). Returns rows affected."""
    cur = conn.execute(
        "UPDATE prediction_errors SET resolved_at = datetime('now')"
        " WHERE memory_id = ? AND error_type = 'memory_drift' AND resolved_at IS NULL",
        (memory_id,),
    )
    return cur.rowcount
