# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Hybrid FTS5 + cosine similarity search with tiered retrieval."""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

from .config import get_config

log = logging.getLogger("neurostack")

from .embedder import (
    blob_to_embedding,
    cosine_similarity_batch,
    get_embedding,
)
from .schema import get_db

# Cosine similarity below this threshold signals a prediction error (poor retrieval fit).
# distance = 1 - cosine_sim; values above 0.62 (sim < 0.38) indicate high prediction error.
PREDICTION_ERROR_SIM_THRESHOLD = 0.38


def log_prediction_error(
    conn: sqlite3.Connection,
    note_path: str,
    query: str,
    cosine_sim: float,
    error_type: str,
    context: str | None = None,
) -> None:
    """Record a prediction error — note poorly fit the query at retrieval time.

    Non-blocking: errors during insert are silently ignored so search is never disrupted.
    Rate-limited: skips insert if the same (note_path, error_type) was logged in the last hour.
    """
    try:
        recent = conn.execute(
            """
            SELECT 1 FROM prediction_errors
            WHERE note_path = ? AND error_type = ?
              AND detected_at > datetime('now', '-1 hour')
              AND resolved_at IS NULL
            LIMIT 1
            """,
            (note_path, error_type),
        ).fetchone()
        if recent:
            return
        conn.execute(
            """
            INSERT INTO prediction_errors (note_path, query, cosine_distance, error_type, context)
            VALUES (?, ?, ?, ?, ?)
            """,
            (note_path, query[:500], round(1.0 - cosine_sim, 4), error_type, context),
        )
        conn.commit()
    except Exception:
        pass  # Never let error logging disrupt search


@dataclass
class SearchResult:
    note_path: str
    heading_path: str
    snippet: str
    score: float
    summary: str = ""
    title: str = ""


@dataclass
class TripleResult:
    note_path: str
    subject: str
    predicate: str
    object: str
    score: float
    title: str = ""


def fts_search(conn: sqlite3.Connection, query: str, limit: int = 50) -> list[dict]:
    """Full-text search over chunks, returns chunk_ids and content."""
    # Escape FTS5 special characters (quote each token to prevent hyphen/dot/operator injection)
    safe_query = " ".join(
        '"' + word.replace('"', '') + '"'
        for word in query.split()
        if word and not word.startswith("-")
    )
    if not safe_query:
        return []

    rows = conn.execute(
        """
        SELECT c.chunk_id, c.note_path, c.heading_path, c.content, c.embedding,
               rank
        FROM chunks_fts
        JOIN chunks c ON c.chunk_id = chunks_fts.rowid
        WHERE chunks_fts MATCH ?
        ORDER BY rank
        LIMIT ?
        """,
        (safe_query, limit),
    ).fetchall()

    return [dict(r) for r in rows]


def semantic_search(
    conn: sqlite3.Connection,
    query_embedding: np.ndarray,
    limit: int = 50,
) -> list[dict]:
    """Pure semantic search over all chunks with embeddings."""
    rows = conn.execute(
        """
        SELECT chunk_id, note_path, heading_path, content, embedding
        FROM chunks WHERE embedding IS NOT NULL
        """
    ).fetchall()

    if not rows:
        return []

    chunk_ids = []
    note_paths = []
    heading_paths = []
    contents = []
    embeddings = []

    for r in rows:
        chunk_ids.append(r["chunk_id"])
        note_paths.append(r["note_path"])
        heading_paths.append(r["heading_path"])
        contents.append(r["content"])
        embeddings.append(blob_to_embedding(r["embedding"]))

    matrix = np.stack(embeddings)
    scores = cosine_similarity_batch(query_embedding, matrix)
    top_indices = np.argsort(scores)[::-1][:limit]

    results = []
    for idx in top_indices:
        results.append({
            "chunk_id": chunk_ids[idx],
            "note_path": note_paths[idx],
            "heading_path": heading_paths[idx],
            "content": contents[idx],
            "score": float(scores[idx]),
        })

    return results


def _get_context_notes(
    conn: sqlite3.Connection,
    context: str,
    embed_url: str = None,
) -> tuple[set[str], set[str]]:
    """Get direct context matches and their 1-hop neighbors.

    Returns (direct_matches, neighbor_matches) as sets of note_path strings.
    """
    embed_url = embed_url or get_config().embed_url
    direct = set()

    # Match by path substring
    rows = conn.execute(
        "SELECT path FROM notes WHERE path LIKE ?",
        (f"%{context}%",),
    ).fetchall()
    direct.update(r["path"] for r in rows)

    # Match by frontmatter tags
    rows = conn.execute(
        "SELECT path, frontmatter FROM notes WHERE frontmatter IS NOT NULL"
    ).fetchall()
    for r in rows:
        try:
            fm = json.loads(r["frontmatter"])
            tags = fm.get("tags", [])
            if isinstance(tags, list) and any(context.lower() in str(t).lower() for t in tags):
                direct.add(r["path"])
        except (json.JSONDecodeError, TypeError):
            pass

    # Semantic folder matching: embed the context string, cosine-match against folder summaries
    try:
        folder_rows = conn.execute(
            "SELECT folder_path, embedding FROM folder_summaries WHERE embedding IS NOT NULL"
        ).fetchall()

        if folder_rows:
            from .embedder import blob_to_embedding, cosine_similarity_batch, get_embedding
            ctx_emb = get_embedding(context, base_url=embed_url)
            folder_embeddings = []
            folder_paths = []
            for fr in folder_rows:
                folder_embeddings.append(blob_to_embedding(fr["embedding"]))
                folder_paths.append(fr["folder_path"])

            scores = cosine_similarity_batch(ctx_emb, np.stack(folder_embeddings))
            for i, score in enumerate(scores):
                if score > 0.55:  # semantic relevance threshold
                    matched_folder = folder_paths[i]
                    # Add all notes under this folder to direct set
                    note_rows = conn.execute(
                        "SELECT path FROM notes WHERE path LIKE ?",
                        (f"{matched_folder}/%",),
                    ).fetchall()
                    direct.update(r["path"] for r in note_rows)
    except Exception:
        pass  # Gracefully degrade if embedder unavailable

    # Get 1-hop neighbors
    neighbors = set()
    if direct:
        placeholders = ",".join("?" * len(direct))
        # Outgoing edges
        rows = conn.execute(
            f"SELECT target_path FROM graph_edges WHERE source_path IN ({placeholders})",
            list(direct),
        ).fetchall()
        neighbors.update(r["target_path"] for r in rows)
        # Incoming edges
        rows = conn.execute(
            f"SELECT source_path FROM graph_edges WHERE target_path IN ({placeholders})",
            list(direct),
        ).fetchall()
        neighbors.update(r["source_path"] for r in rows)
        neighbors -= direct  # Don't double-boost

    return direct, neighbors


def hotness_score(conn: sqlite3.Connection, note_path: str, half_life_days: float = 30.0) -> float:
    """Compute hotness score blending usage frequency and recency.

    Blends frequency and recency using sigmoid-compressed usage count
    with exponential half-life decay:
        hotness = sigmoid(log1p(active_count)) * exp(-ln2/half_life * age_days)

    Returns a value in [0, 1]. Returns 0.0 if never used.
    """
    import math

    rows = conn.execute(
        "SELECT used_at FROM note_usage WHERE note_path = ? ORDER BY used_at DESC",
        (note_path,),
    ).fetchall()

    if not rows:
        return 0.0

    active_count = len(rows)

    # Age in days since most recent usage
    most_recent = rows[0]["used_at"]
    age_row = conn.execute(
        "SELECT (julianday('now') - julianday(?)) as age_days", (most_recent,)
    ).fetchone()
    age_days = max(0.0, float(age_row["age_days"]))

    decay = math.exp(-math.log(2) / half_life_days * age_days)
    freq = 1.0 / (1.0 + math.exp(-math.log1p(active_count)))  # sigmoid(log1p(count))

    return freq * decay


def hybrid_search(
    query: str,
    top_k: int = 5,
    mode: str = "hybrid",
    embed_url: str = None,
    db_path=None,
    context: str = None,
    rerank: bool = False,
) -> list[SearchResult]:
    """
    Hybrid search combining FTS5 and semantic similarity.

    Modes:
    - "hybrid": FTS5 pre-filters top 50, then cosine-reranks
    - "semantic": Pure embedding search
    - "keyword": Pure FTS5 search
    """
    from .schema import DB_PATH

    embed_url = embed_url or get_config().embed_url
    conn = get_db(db_path or DB_PATH)

    if mode == "keyword":
        fts_results = fts_search(conn, query, limit=top_k)
        return _to_search_results(conn, fts_results[:top_k])

    # Get query embedding — fall back to FTS5-only if embedding service unavailable
    try:
        query_embedding = get_embedding(query, base_url=embed_url)
    except (ConnectionError, OSError, Exception) as exc:
        # httpx.ConnectError is a subclass of ConnectionError
        log.warning("Embedding service unavailable, falling back to FTS5-only search: %s", exc)
        fts_results = fts_search(conn, query, limit=top_k)
        results = _to_search_results(conn, fts_results[:top_k])
        for r in results:
            r.snippet = "[FTS5-only] " + r.snippet
        return results

    if mode == "semantic":
        sem_results = semantic_search(conn, query_embedding, limit=top_k)
        return _to_search_results(conn, sem_results[:top_k])

    # Hybrid: FTS5 pre-filter + semantic rerank
    fts_results = fts_search(conn, query, limit=50)

    if not fts_results:
        # Fall back to pure semantic if no FTS matches
        sem_results = semantic_search(conn, query_embedding, limit=top_k)
        return _to_search_results(conn, sem_results[:top_k])

    # Rerank FTS results by cosine similarity
    embeddings = []
    valid_results = []
    for r in fts_results:
        if r["embedding"]:
            embeddings.append(blob_to_embedding(r["embedding"]))
            valid_results.append(r)

    if not valid_results:
        return _to_search_results(conn, fts_results[:top_k])

    matrix = np.stack(embeddings)
    scores = cosine_similarity_batch(query_embedding, matrix)

    # Combine FTS rank (normalized) and cosine similarity; preserve raw cosine for error detection
    for i, r in enumerate(valid_results):
        fts_score = 1.0 / (1.0 + abs(r.get("rank", 0)))
        raw_cosine = float(scores[i])
        r["cosine_sim"] = raw_cosine
        r["score"] = 0.3 * fts_score + 0.7 * raw_cosine

    # Apply context boost; track which notes are in-context for mismatch detection
    in_context_notes: set[str] = set()
    if context:
        direct_ctx, neighbor_ctx = _get_context_notes(conn, context, embed_url=embed_url)
        in_context_notes = direct_ctx | neighbor_ctx
        for r in valid_results:
            note_path = r["note_path"]
            if note_path in direct_ctx:
                r["score"] *= 1.4
            elif note_path in neighbor_ctx:
                r["score"] *= 1.2

    # Apply hotness blend: final_score = 0.8 * semantic + 0.2 * hotness
    for r in valid_results:
        h = hotness_score(conn, r["note_path"])
        if h > 0.0:
            r["score"] = 0.8 * r["score"] + 0.2 * h

    # Excitability boost: notes with status=active get a 1.15x boost
    # Mirrors CREB-mediated excitability windows where recently active
    # neurons are preferentially recruited into new engrams.
    for r in valid_results:
        note_row = conn.execute(
            "SELECT frontmatter FROM notes WHERE path = ?",
            (r["note_path"],),
        ).fetchone()
        if note_row and note_row["frontmatter"]:
            try:
                fm = json.loads(note_row["frontmatter"])
                if fm.get("status") == "active":
                    r["score"] *= 1.15
            except (json.JSONDecodeError, TypeError):
                pass

    valid_results.sort(key=lambda x: x["score"], reverse=True)

    # Deduplicate by note_path (keep highest scoring chunk per note).
    # When reranking, collect a larger candidate pool for the cross-encoder.
    candidate_limit = top_k * 4 if rerank else top_k
    seen_notes = set()
    deduped = []
    for r in valid_results:
        if r["note_path"] not in seen_notes:
            seen_notes.add(r["note_path"])
            deduped.append(r)
        if len(deduped) >= candidate_limit:
            break

    if rerank:
        from .reranker import rerank as cross_rerank
        deduped = cross_rerank(query, deduped, text_key="content", top_k=top_k)

    # Prediction error detection — check top result for high semantic distance
    if deduped:
        top = deduped[0]
        top_cosine = top.get("cosine_sim", 1.0)
        if top_cosine < PREDICTION_ERROR_SIM_THRESHOLD:
            log_prediction_error(
                conn, top["note_path"], query, top_cosine, "low_overlap", context
            )
        elif context and in_context_notes and top["note_path"] not in in_context_notes:
            log_prediction_error(
                conn, top["note_path"], query, top_cosine, "contextual_mismatch", context
            )

    return _to_search_results(conn, deduped)


def _to_search_results(conn: sqlite3.Connection, results: list[dict]) -> list[SearchResult]:
    """Convert raw results to SearchResult objects with summaries."""
    search_results = []
    for r in results:
        note_path = r["note_path"]

        # Get note title
        note = conn.execute(
            "SELECT title FROM notes WHERE path = ?", (note_path,)
        ).fetchone()
        title = note["title"] if note else note_path

        # Get summary if available
        summary_row = conn.execute(
            "SELECT summary_text FROM summaries WHERE note_path = ?", (note_path,)
        ).fetchone()
        summary = summary_row["summary_text"] if summary_row else ""

        # Truncate snippet
        snippet = r["content"][:300]
        if len(r["content"]) > 300:
            snippet += "..."

        search_results.append(SearchResult(
            note_path=note_path,
            heading_path=r.get("heading_path", ""),
            snippet=snippet,
            score=r.get("score", 0.0),
            summary=summary,
            title=title,
        ))

    return search_results


# ---------------------------------------------------------------------------
# Triple search (Phase 2: structured retrieval)
# ---------------------------------------------------------------------------


def triple_fts_search(conn: sqlite3.Connection, query: str, limit: int = 30) -> list[dict]:
    """Full-text search over triples."""
    safe_query = " ".join(
        '"' + word.replace('"', '') + '"'
        for word in query.split()
        if word and not word.startswith("-")
    )
    if not safe_query:
        return []

    rows = conn.execute(
        """
        SELECT t.triple_id, t.note_path, t.subject, t.predicate, t.object,
               t.triple_text, t.embedding, rank
        FROM triples_fts
        JOIN triples t ON t.triple_id = triples_fts.rowid
        WHERE triples_fts MATCH ?
        ORDER BY rank
        LIMIT ?
        """,
        (safe_query, limit),
    ).fetchall()

    return [dict(r) for r in rows]


def triple_semantic_search(
    conn: sqlite3.Connection,
    query_embedding: np.ndarray,
    limit: int = 30,
) -> list[dict]:
    """Pure semantic search over triples with embeddings."""
    rows = conn.execute(
        """SELECT triple_id, note_path, subject, predicate, object,
                  triple_text, embedding
           FROM triples WHERE embedding IS NOT NULL"""
    ).fetchall()

    if not rows:
        return []

    data = []
    embeddings = []
    for r in rows:
        data.append(dict(r))
        embeddings.append(blob_to_embedding(r["embedding"]))

    matrix = np.stack(embeddings)
    scores = cosine_similarity_batch(query_embedding, matrix)
    top_indices = np.argsort(scores)[::-1][:limit]

    results = []
    for idx in top_indices:
        d = data[idx]
        d["score"] = float(scores[idx])
        results.append(d)

    return results


def search_triples(
    query: str,
    top_k: int = 10,
    mode: str = "hybrid",
    embed_url: str = None,
    db_path=None,
) -> list[TripleResult]:
    """Search triples using hybrid FTS5 + semantic similarity.

    Returns compact TripleResult objects (~10-20 tokens each).
    """
    from .schema import DB_PATH

    embed_url = embed_url or get_config().embed_url
    conn = get_db(db_path or DB_PATH)

    if mode == "keyword":
        fts_results = triple_fts_search(conn, query, limit=top_k)
        return _to_triple_results(conn, fts_results[:top_k])

    try:
        query_embedding = get_embedding(query, base_url=embed_url)
    except (ConnectionError, OSError, Exception) as exc:
        log.warning(
            "Embedding service unavailable,"
            " falling back to FTS5-only triple search: %s",
            exc,
        )
        fts_results = triple_fts_search(conn, query, limit=top_k)
        return _to_triple_results(conn, fts_results[:top_k])

    if mode == "semantic":
        sem_results = triple_semantic_search(conn, query_embedding, limit=top_k)
        return _to_triple_results(conn, sem_results[:top_k])

    # Hybrid: FTS5 pre-filter + semantic rerank
    fts_results = triple_fts_search(conn, query, limit=30)

    if not fts_results:
        sem_results = triple_semantic_search(conn, query_embedding, limit=top_k)
        return _to_triple_results(conn, sem_results[:top_k])

    embeddings = []
    valid_results = []
    for r in fts_results:
        if r["embedding"]:
            embeddings.append(blob_to_embedding(r["embedding"]))
            valid_results.append(r)

    if not valid_results:
        return _to_triple_results(conn, fts_results[:top_k])

    matrix = np.stack(embeddings)
    scores = cosine_similarity_batch(query_embedding, matrix)

    for i, r in enumerate(valid_results):
        fts_score = 1.0 / (1.0 + abs(r.get("rank", 0)))
        r["score"] = 0.3 * fts_score + 0.7 * float(scores[i])

    valid_results.sort(key=lambda x: x["score"], reverse=True)

    return _to_triple_results(conn, valid_results[:top_k])


def _to_triple_results(conn: sqlite3.Connection, results: list[dict]) -> list[TripleResult]:
    """Convert raw triple results to TripleResult objects."""
    triple_results = []
    for r in results:
        note = conn.execute(
            "SELECT title FROM notes WHERE path = ?", (r["note_path"],)
        ).fetchone()
        title = note["title"] if note else r["note_path"]

        triple_results.append(TripleResult(
            note_path=r["note_path"],
            subject=r["subject"],
            predicate=r["predicate"],
            object=r["object"],
            score=r.get("score", 0.0),
            title=title,
        ))

    return triple_results


# ---------------------------------------------------------------------------
# Tiered search (Phase 3: adaptive compression)
# ---------------------------------------------------------------------------


def tiered_search(
    query: str,
    top_k: int = 5,
    depth: str = "auto",
    mode: str = "hybrid",
    embed_url: str = None,
    db_path=None,
    context: str = None,
    rerank: bool = False,
) -> dict:
    """Tiered search returning results at the appropriate compression level.

    Depth levels:
    - "triples": Return only triples (~10-20 tokens per fact). Cheapest.
    - "summaries": Return note summaries (~50-100 tokens per note). Medium.
    - "full": Return full chunk snippets + summaries (~200-500 tokens). Current behavior.
    - "auto": Start with triples, include summaries for top matches,
              full chunks only if triple coverage is low.

    Returns dict with keys: triples, summaries, chunks (each may be empty
    depending on depth).
    """
    from .schema import DB_PATH

    embed_url = embed_url or get_config().embed_url
    conn = get_db(db_path or DB_PATH)

    result = {"triples": [], "summaries": [], "chunks": [], "depth_used": depth}

    if depth == "triples":
        triples = search_triples(
            query, top_k=top_k * 2, mode=mode,
            embed_url=embed_url, db_path=db_path,
        )
        result["triples"] = [
            {"note": t.note_path, "title": t.title,
             "s": t.subject, "p": t.predicate, "o": t.object,
             "score": round(t.score, 4)}
            for t in triples
        ]
        return result

    if depth == "summaries":
        # Search via chunks but return only summaries (deduplicated by note)
        chunk_results = hybrid_search(
            query, top_k=top_k, mode=mode,
            embed_url=embed_url, db_path=db_path,
            context=context, rerank=rerank,
        )
        seen = set()
        for r in chunk_results:
            if r.note_path not in seen and r.summary:
                seen.add(r.note_path)
                result["summaries"].append({
                    "note": r.note_path, "title": r.title,
                    "summary": r.summary, "score": round(r.score, 4),
                })
        return result

    if depth == "full":
        chunk_results = hybrid_search(
            query, top_k=top_k, mode=mode,
            embed_url=embed_url, db_path=db_path,
            context=context, rerank=rerank,
        )
        result["chunks"] = [
            {"note": r.note_path, "title": r.title, "section": r.heading_path,
             "snippet": r.snippet, "summary": r.summary, "score": round(r.score, 4)}
            for r in chunk_results
        ]
        return result

    # Auto mode: start cheap, escalate if needed
    triples = search_triples(
        query, top_k=top_k * 3, mode=mode,
        embed_url=embed_url, db_path=db_path,
    )
    result["triples"] = [
        {"note": t.note_path, "title": t.title,
         "s": t.subject, "p": t.predicate, "o": t.object,
         "score": round(t.score, 4)}
        for t in triples
    ]

    # Check coverage: how many unique notes do triples cover?
    triple_notes = {t.note_path for t in triples}
    triple_confidence = max((t.score for t in triples), default=0.0)

    # If triples have good coverage and high scores, just add summaries for top notes
    if len(triple_notes) >= 2 and triple_confidence > 0.4:
        # Add summaries for the top-scoring note paths
        top_notes = list(dict.fromkeys(t.note_path for t in triples))[:top_k]
        for np_ in top_notes:
            summary_row = conn.execute(
                "SELECT s.summary_text, n.title FROM summaries s "
                "JOIN notes n ON n.path = s.note_path WHERE s.note_path = ?",
                (np_,),
            ).fetchone()
            if summary_row:
                result["summaries"].append({
                    "note": np_, "title": summary_row["title"],
                    "summary": summary_row["summary_text"],
                })
        result["depth_used"] = "auto:triples+summaries"
        return result

    # Low triple coverage — fall back to full chunk search
    chunk_results = hybrid_search(
        query, top_k=top_k, mode=mode,
        embed_url=embed_url, db_path=db_path,
        context=context, rerank=rerank,
    )
    result["chunks"] = [
        {"note": r.note_path, "title": r.title, "section": r.heading_path,
         "snippet": r.snippet, "summary": r.summary, "score": round(r.score, 4)}
        for r in chunk_results
    ]
    result["depth_used"] = "auto:full"
    return result
