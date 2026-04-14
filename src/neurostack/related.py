# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Find semantically related notes using embedding similarity."""

from __future__ import annotations

import logging

try:
    import numpy as np

    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

log = logging.getLogger("neurostack")


def find_related(
    note_path: str,
    top_k: int = 10,
    workspace: str = None,
) -> list[dict]:
    """Find semantically related notes using embedding similarity.

    Computes a mean embedding across all chunks of the given note, then
    compares against mean embeddings of all other notes using cosine
    similarity.

    Args:
        note_path: Path of the source note (e.g. "research/predictive-coding.md")
        top_k: Number of related notes to return (default 10)
        workspace: Optional vault subdirectory prefix to restrict results

    Returns:
        List of dicts with keys: path, title, score, summary
    """
    if not HAS_NUMPY:
        raise ImportError(
            "Related notes requires numpy. "
            "Install with: pip install neurostack[full]"
        )

    from .embedder import blob_to_embedding, cosine_similarity
    from .schema import DB_PATH, get_db
    from .search import _normalize_workspace, _record_note_usage

    conn = get_db(DB_PATH)
    workspace = _normalize_workspace(workspace)

    # Load all chunk embeddings for the source note
    source_rows = conn.execute(
        "SELECT embedding FROM chunks "
        "WHERE note_path = ? AND embedding IS NOT NULL",
        (note_path,),
    ).fetchall()

    if not source_rows:
        log.warning("No embeddings found for note: %s", note_path)
        return []

    # Compute mean embedding for the source note
    source_embeddings = [blob_to_embedding(r["embedding"]) for r in source_rows]
    source_mean = np.mean(np.stack(source_embeddings), axis=0)

    # Load all chunk embeddings for other notes, grouped by note_path
    if workspace:
        all_rows = conn.execute(
            "SELECT note_path, embedding FROM chunks "
            "WHERE embedding IS NOT NULL "
            "  AND note_path != ? "
            "  AND note_path LIKE ? || '%'",
            (note_path, workspace + "/"),
        ).fetchall()
    else:
        all_rows = conn.execute(
            "SELECT note_path, embedding FROM chunks "
            "WHERE embedding IS NOT NULL AND note_path != ?",
            (note_path,),
        ).fetchall()

    if not all_rows:
        return []

    # Group embeddings by note_path and compute mean per note
    note_embeddings: dict[str, list[np.ndarray]] = {}
    for r in all_rows:
        np_ = r["note_path"]
        if np_ not in note_embeddings:
            note_embeddings[np_] = []
        note_embeddings[np_].append(blob_to_embedding(r["embedding"]))

    # Compute mean embedding and cosine similarity for each note
    scored: list[tuple[str, float]] = []
    for np_, embs in note_embeddings.items():
        note_mean = np.mean(np.stack(embs), axis=0)
        sim = cosine_similarity(source_mean, note_mean)
        scored.append((np_, sim))

    # Sort by similarity descending, take top_k
    scored.sort(key=lambda x: x[1], reverse=True)
    top = scored[:top_k]

    # Fetch metadata for results
    results = []
    for np_, sim in top:
        note_row = conn.execute(
            "SELECT title FROM notes WHERE path = ?", (np_,)
        ).fetchone()
        title = note_row["title"] if note_row else np_

        summary_row = conn.execute(
            "SELECT summary_text FROM summaries WHERE note_path = ?", (np_,)
        ).fetchone()
        summary = summary_row["summary_text"] if summary_row else None

        results.append({
            "path": np_,
            "title": title,
            "score": round(sim, 4),
            "summary": summary,
        })

    _record_note_usage(conn, [r["path"] for r in results])
    return results
