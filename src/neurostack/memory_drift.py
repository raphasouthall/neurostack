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

# Promotion moves a memory's prose into a note and leaves the memory holding
# identifiers plus a `[[wiki-link]]` to it, tagging it `promoted`. Comparing the
# two then measures that split, not staleness: on 2026-09-15, 56 of 64 open rows
# were a promoted memory flagged against the very note it links to, and every
# row read by hand over two runs was a false positive.
PROMOTED_TAG = "promoted"


def is_promotion_pointer(tags) -> bool:
    """True when a memory is a promoted pointer, whose distance from its note is
    the intended outcome rather than drift. `tags` is the stored JSON blob or a
    sequence of tags."""
    if isinstance(tags, str):
        try:
            tags = json.loads(tags)
        except ValueError:
            return False
    if not isinstance(tags, (list, tuple, set)):
        return False
    return PROMOTED_TAG in {str(t).strip() for t in tags}


def _tags_of(conn: sqlite3.Connection, memory_id: int):
    row = conn.execute(
        "SELECT tags FROM memories WHERE memory_id = ?", (memory_id,)
    ).fetchone()
    return row["tags"] if row else None


def detect_memory_drift(
    conn: sqlite3.Connection,
    memory_id: int,
    content: str,
    embedding,
    threshold: float = DRIFT_THRESHOLD,
    link_index=None,
    tags=None,
) -> list[dict]:
    """Detect drift of one memory from the notes it wiki-links.

    `embedding` is the memory's stored embedding (numpy array). Pass `link_index`
    (from graph._build_link_index) to reuse one index across a batch of memories.
    Returns the drift records written/refreshed; empty when the memory has no
    embedding, no resolvable links, no drift, or is a promoted pointer. Pass
    `tags` to save a lookup when the caller already has them.
    """
    if embedding is None or not content:
        return []
    if is_promotion_pointer(tags if tags is not None else _tags_of(conn, memory_id)):
        # Clear anything written before this was understood, so the promotion
        # queue stops re-reporting a backlog that is not work.
        resolve_memory_drift(conn, memory_id)
        conn.commit()
        return []

    from .chunker import extract_wiki_links
    from .graph import _build_link_index, resolve_wiki_link

    links = extract_wiki_links(content)
    if not links:
        return []

    all_paths: list = []
    if link_index is None:
        all_paths = [r["path"] for r in conn.execute("SELECT path FROM notes")]
        if not all_paths:
            return []
        link_index = _build_link_index(all_paths)

    resolved: list[tuple[str, str]] = []
    seen: set[str] = set()
    for link in links:
        path = resolve_wiki_link(link, all_paths, _link_index=link_index)
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
        _write_drift(conn, memory_id, note_path, distance, context)
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
) -> None:
    """Keep exactly one open drift row per (memory, note): refresh the existing
    unresolved row with the stronger signal, or insert the first one. A new open
    row is only created after the prior one is resolved (a genuinely new drift)."""
    existing = conn.execute(
        "SELECT error_id, cosine_distance FROM prediction_errors"
        " WHERE memory_id = ? AND note_path = ? AND error_type = 'memory_drift'"
        "   AND resolved_at IS NULL"
        " ORDER BY detected_at DESC LIMIT 1",
        (memory_id, note_path),
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
    so retrieval is never disrupted. The wiki-link index is built once and reused
    across the batch."""
    try:
        ids = [m.memory_id for m in memories]
        if not ids:
            return
        placeholders = ",".join("?" * len(ids))
        rows = conn.execute(
            f"SELECT memory_id, content, embedding, tags FROM memories"
            f" WHERE memory_id IN ({placeholders}) AND embedding IS NOT NULL",
            ids,
        ).fetchall()
        if not rows:
            return

        from .embedder import blob_to_embedding
        from .graph import _build_link_index

        all_paths = [r["path"] for r in conn.execute("SELECT path FROM notes")]
        if not all_paths:
            return
        link_index = _build_link_index(all_paths)

        for r in rows:
            detect_memory_drift(
                conn, r["memory_id"], r["content"],
                blob_to_embedding(r["embedding"]), link_index=link_index,
                tags=r["tags"],
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
