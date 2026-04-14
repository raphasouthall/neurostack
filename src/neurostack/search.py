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

from .cooccurrence import reinforce_cooccurrence
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


def _record_note_usage(conn: sqlite3.Connection, note_paths: list[str]) -> None:
    """Record note access for hotness scoring. Non-blocking.

    Deduplicates paths so a single retrieval counts as one usage event per note,
    regardless of how many chunks/triples/edges from that note were returned.
    """
    if not note_paths:
        return
    unique_paths = list(dict.fromkeys(note_paths))
    try:
        conn.executemany(
            "INSERT INTO note_usage (note_path) VALUES (?)",
            [(p,) for p in unique_paths],
        )
        conn.commit()
    except Exception:
        pass  # Never let usage recording disrupt retrieval


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


def _normalize_workspace(workspace: str | None) -> str | None:
    """Normalize workspace path: strip leading/trailing slashes, return None if empty."""
    if not workspace:
        return None
    workspace = workspace.strip("/")
    return workspace if workspace else None


def fts_search(
    conn: sqlite3.Connection,
    query: str,
    limit: int = 50,
    workspace: str | None = None,
) -> list[dict]:
    """Full-text search over chunks, returns chunk_ids and content."""
    # Escape FTS5 special characters and join with OR for better recall.
    # AND (implicit space join) requires ALL tokens in a single chunk,
    # which destroys recall on multi-concept queries.
    safe_query = " OR ".join(
        '"' + word.replace('"', '') + '"'
        for word in query.split()
        if word and not word.startswith("-")
    )
    if not safe_query:
        return []

    workspace = _normalize_workspace(workspace)
    if workspace:
        rows = conn.execute(
            """
            SELECT c.chunk_id, c.note_path, c.heading_path, c.content, c.embedding,
                   rank
            FROM chunks_fts
            JOIN chunks c ON c.chunk_id = chunks_fts.rowid
            WHERE chunks_fts MATCH ?
              AND c.note_path LIKE ? || '%'
            ORDER BY rank
            LIMIT ?
            """,
            (safe_query, workspace + "/", limit),
        ).fetchall()
    else:
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
    workspace: str | None = None,
) -> list[dict]:
    """Pure semantic search over all chunks with embeddings.

    Uses sqlite-vec KNN index when available, falls back to brute-force numpy scan.
    """
    from .vecindex import has_vec_index, vec_knn_chunks

    workspace = _normalize_workspace(workspace)

    # Fast path: sqlite-vec KNN index
    if has_vec_index(conn):
        try:
            return vec_knn_chunks(conn, query_embedding, k=limit, workspace=workspace)
        except Exception as e:
            log.warning("sqlite-vec KNN failed, falling back to brute-force: %s", e)

    # Fallback: brute-force numpy scan
    if workspace:
        rows = conn.execute(
            """
            SELECT chunk_id, note_path, heading_path, content, embedding
            FROM chunks WHERE embedding IS NOT NULL
              AND note_path LIKE ? || '%'
            """,
            (workspace + "/",),
        ).fetchall()
    else:
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


def batch_hotness_scores(
    conn: sqlite3.Connection,
    note_paths: list[str],
    half_life_days: float = 30.0,
) -> dict[str, float]:
    """Compute hotness scores for multiple notes in a single batch query.

    Returns a dict mapping note_path -> hotness score (0-1).
    Notes with no usage history are omitted from the result.
    """
    import math

    if not note_paths:
        return {}

    placeholders = ",".join("?" for _ in note_paths)
    rows = conn.execute(
        f"SELECT note_path, COUNT(*) as usage_count, "
        f"julianday('now') - julianday(MAX(used_at)) as age_days "
        f"FROM note_usage "
        f"WHERE note_path IN ({placeholders}) "
        f"GROUP BY note_path",
        list(note_paths),
    ).fetchall()

    scores: dict[str, float] = {}
    ln2 = math.log(2)
    for row in rows:
        age_days = max(0.0, float(row["age_days"]))
        usage_count = int(row["usage_count"])
        decay = math.exp(-ln2 / half_life_days * age_days)
        freq = 1.0 / (1.0 + math.exp(-math.log1p(usage_count)))
        scores[row["note_path"]] = freq * decay

    return scores


def get_dormancy_report(
    conn: sqlite3.Connection,
    threshold: float = 0.05,
    half_life_days: float = 30.0,
    limit: int = 50,
) -> dict:
    """Report notes by excitability status.

    Returns dormant (hotness < threshold), active, and never-used notes
    with their hotness scores. Uses existing hotness_score() as the
    single source of truth - no separate status column needed.
    """
    all_notes = conn.execute(
        "SELECT path, title FROM notes ORDER BY path"
    ).fetchall()

    dormant = []
    active = []
    never_used = []

    for note in all_notes:
        path = note["path"]
        title = note["title"] or path
        score = hotness_score(conn, path, half_life_days=half_life_days)

        entry = {"path": path, "title": title, "hotness": round(score, 4)}

        if score == 0.0:
            # Check if it was ever used
            usage = conn.execute(
                "SELECT COUNT(*) as c FROM note_usage WHERE note_path = ?",
                (path,),
            ).fetchone()["c"]
            if usage == 0:
                never_used.append(entry)
            else:
                dormant.append(entry)
        elif score < threshold:
            dormant.append(entry)
        else:
            active.append(entry)

    dormant.sort(key=lambda x: x["hotness"])
    active.sort(key=lambda x: x["hotness"], reverse=True)

    return {
        "threshold": threshold,
        "half_life_days": half_life_days,
        "total_notes": len(all_notes),
        "active_count": len(active),
        "dormant_count": len(dormant),
        "never_used_count": len(never_used),
        "dormant": dormant[:limit],
        "active": active[:limit],
        "never_used": never_used[:limit],
    }


def run_excitability_demotion(
    conn: sqlite3.Connection,
    threshold: float = 0.05,
    half_life_days: float = 30.0,
) -> dict:
    """Demote notes with decayed hotness below threshold from active to dormant.

    Updates note_metadata.status — vault files are NEVER modified.
    Also demotes never-used notes older than 90 days.

    Returns {"demoted": N, "paths": [...]}.
    """
    demoted_paths = []

    # Get dormancy report for notes below threshold (large limit to get all)
    report = get_dormancy_report(
        conn, threshold=threshold, half_life_days=half_life_days, limit=999999,
    )

    # Demote dormant notes (used but decayed below threshold)
    for entry in report["dormant"]:
        path = entry["path"]
        changed = conn.execute(
            "UPDATE note_metadata SET status = 'dormant'"
            " WHERE note_path = ? AND status = 'active'",
            (path,),
        ).rowcount
        if changed:
            demoted_paths.append(path)

    # Demote never-used notes older than 90 days
    for entry in report["never_used"]:
        path = entry["path"]
        row = conn.execute(
            "SELECT updated_at FROM notes WHERE path = ?", (path,)
        ).fetchone()
        if not row:
            continue
        age = conn.execute(
            "SELECT (julianday('now') - julianday(?)) as age",
            (row["updated_at"],),
        ).fetchone()
        if age and float(age["age"]) > 90:
            changed = conn.execute(
                "UPDATE note_metadata SET status = 'dormant'"
                " WHERE note_path = ? AND status = 'active'",
                (path,),
            ).rowcount
            if changed:
                demoted_paths.append(path)

    if demoted_paths:
        conn.commit()

    return {"demoted": len(demoted_paths), "paths": demoted_paths}


def hybrid_search(
    query: str,
    top_k: int = 5,
    mode: str = "hybrid",
    embed_url: str = None,
    db_path=None,
    context: str = None,
    workspace: str | None = None,
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

    workspace = _normalize_workspace(workspace)

    if mode == "keyword":
        fts_results = fts_search(conn, query, limit=top_k, workspace=workspace)
        return _to_search_results(conn, fts_results[:top_k])

    # Get query embedding — fall back to FTS5-only if embedding service unavailable
    try:
        query_embedding = get_embedding(query, base_url=embed_url)
    except (ConnectionError, OSError, Exception) as exc:
        # httpx.ConnectError is a subclass of ConnectionError
        log.warning("Embedding service unavailable, falling back to FTS5-only search: %s", exc)
        fts_results = fts_search(conn, query, limit=top_k, workspace=workspace)
        results = _to_search_results(conn, fts_results[:top_k])
        for r in results:
            r.snippet = "[FTS5-only] " + r.snippet
        return results

    if mode == "semantic":
        sem_results = semantic_search(conn, query_embedding, limit=top_k, workspace=workspace)
        return _to_search_results(conn, sem_results[:top_k])

    # Hybrid: FTS5 pre-filter + semantic rerank
    fts_results = fts_search(conn, query, limit=50, workspace=workspace)

    if not fts_results:
        # Fall back to pure semantic if no FTS matches
        sem_results = semantic_search(conn, query_embedding, limit=top_k, workspace=workspace)
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

    # ── Energy landscape convergence confidence ──
    # Measures how representative the matched chunk is of its note's overall
    # embedding distribution.  Notes where the hit chunk sits near the centroid
    # of all chunk embeddings score higher than notes where we matched an
    # outlier fragment.  Mirrors attractor-network dynamics: deep, narrow
    # energy wells (low chunk variance) converge cleanly; shallow, broad wells
    # (high variance) indicate noisy or heterogeneous notes.
    #
    # convergence = cosine(query, centroid) / (1 + σ)
    # The final score is blended: 0.7 * raw_score + 0.3 * convergence
    # so convergence can lift or dampen but never dominate.
    note_paths_unique = list({r["note_path"] for r in valid_results})
    if note_paths_unique:
        placeholders = ",".join("?" * len(note_paths_unique))
        all_chunks = conn.execute(
            f"SELECT note_path, embedding FROM chunks "
            f"WHERE note_path IN ({placeholders}) AND embedding IS NOT NULL",
            note_paths_unique,
        ).fetchall()

        # Group embeddings by note
        note_chunk_embeddings: dict[str, list] = {}
        for row in all_chunks:
            np_ = row["note_path"]
            if np_ not in note_chunk_embeddings:
                note_chunk_embeddings[np_] = []
            note_chunk_embeddings[np_].append(blob_to_embedding(row["embedding"]))

        for r in valid_results:
            chunks = note_chunk_embeddings.get(r["note_path"])
            if not chunks or len(chunks) < 2:
                # Single-chunk note: convergence = 1.0 (perfectly representative)
                continue
            chunk_matrix = np.stack(chunks)
            centroid = chunk_matrix.mean(axis=0)
            centroid_sim = float(
                np.dot(query_embedding, centroid)
                / (np.linalg.norm(query_embedding) * np.linalg.norm(centroid) + 1e-10)
            )
            # Standard deviation of chunk similarities to query — measures basin width
            chunk_sims = cosine_similarity_batch(query_embedding, chunk_matrix)
            sigma = float(np.std(chunk_sims))
            convergence = centroid_sim / (1.0 + sigma)
            # Blend: keep 70% of existing score, add 30% convergence influence
            r["score"] = 0.7 * r["score"] + 0.3 * convergence

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
    hotness_map = batch_hotness_scores(conn, [r["note_path"] for r in valid_results])
    for r in valid_results:
        h = hotness_map.get(r["note_path"], 0.0)
        if h > 0.0:
            r["score"] = 0.8 * r["score"] + 0.2 * h

    # Extract query-matched entities (used for co-occurrence boost AND reinforcement)
    cfg = get_config()
    query_words = [w.lower() for w in query.split() if len(w) > 2]
    query_entities: set[str] = set()
    if query_words:
        for word in query_words:
            ent_rows = conn.execute(
                "SELECT DISTINCT subject FROM triples WHERE LOWER(subject) LIKE ? "
                "UNION "
                "SELECT DISTINCT object FROM triples WHERE LOWER(object) LIKE ?",
                (f"%{word}%", f"%{word}%"),
            ).fetchall()
            query_entities.update(r[0] for r in ent_rows)

    # Co-occurrence boost: notes containing entities that co-occur with query entities
    # get a bounded multiplicative boost. Slots after hotness, before excitability.
    cooc_weight = cfg.cooccurrence_boost_weight
    if cooc_weight > 0 and query_entities:
                # Step 2: Find co-occurring entities and their weights
                cooc_entities = {}  # entity -> max co-occurrence weight
                for qe in query_entities:
                    rows = conn.execute(
                        "SELECT entity_b, weight FROM entity_cooccurrence WHERE entity_a = ? "
                        "UNION ALL "
                        "SELECT entity_a, weight FROM entity_cooccurrence WHERE entity_b = ?",
                        (qe, qe),
                    ).fetchall()
                    for r in rows:
                        ent = r[0]
                        w = r[1]
                        if ent not in query_entities:  # Don't boost for direct matches
                            cooc_entities[ent] = max(cooc_entities.get(ent, 0), w)

                if cooc_entities:
                    # Step 3: Build note -> entities map from triples for result notes
                    result_paths = [r["note_path"] for r in valid_results]
                    if result_paths:
                        placeholders = ",".join("?" * len(result_paths))
                        note_ent_rows = conn.execute(
                            f"SELECT DISTINCT note_path, subject, object FROM triples "
                            f"WHERE note_path IN ({placeholders})",
                            result_paths,
                        ).fetchall()
                        note_entities = {}
                        for ner in note_ent_rows:
                            path = ner["note_path"]
                            if path not in note_entities:
                                note_entities[path] = set()
                            note_entities[path].add(ner["subject"])
                            note_entities[path].add(ner["object"])

                        # Step 4: Apply bounded boost
                        max_cooc_weight = max(cooc_entities.values()) if cooc_entities else 1.0
                        for r in valid_results:
                            note_ents = note_entities.get(r["note_path"], set())
                            overlap = note_ents & set(cooc_entities.keys())
                            if overlap:
                                raw_boost = sum(cooc_entities[e] for e in overlap)
                                # Normalize and cap: sigmoid-like bounded boost
                                normalized = raw_boost / (raw_boost + max_cooc_weight)
                                boost = 1.0 + (cooc_weight * normalized)
                                r["score"] *= boost

    # Excitability boost: notes with status=active get a 1.15x boost
    # Mirrors CREB-mediated excitability windows where recently active
    # neurons are preferentially recruited into new engrams.
    # Reads from note_metadata (SQLite-owned) with frontmatter fallback.
    meta_paths = [r["note_path"] for r in valid_results]
    if meta_paths:
        placeholders = ",".join("?" * len(meta_paths))
        meta_rows = conn.execute(
            f"SELECT note_path, status FROM note_metadata"
            f" WHERE note_path IN ({placeholders})",
            meta_paths,
        ).fetchall()
        meta_status = {r["note_path"]: r["status"] for r in meta_rows}
    else:
        meta_status = {}

    for r in valid_results:
        status = meta_status.get(r["note_path"])
        if status is None:
            # Fallback: parse from notes.frontmatter
            note_row = conn.execute(
                "SELECT frontmatter FROM notes WHERE path = ?",
                (r["note_path"],),
            ).fetchone()
            if note_row and note_row["frontmatter"]:
                try:
                    fm = json.loads(note_row["frontmatter"])
                    status = fm.get("status")
                except (json.JSONDecodeError, TypeError):
                    pass
        if status == "active":
            r["score"] *= 1.15

    # ── Prediction error demotion ──
    # Notes with unresolved prediction errors have previously "surprised" on
    # retrieval — the system observed poor semantic fit.  Demoting them mirrors
    # predictive-coding error signals: notes that repeatedly violate retrieval
    # expectations are deprioritised until resolved (re-linked, updated, or
    # the error is marked resolved).
    #
    # Demotion is bounded: score *= 1 / (1 + 0.1 * error_count)
    # 1 error → 0.91x, 3 errors → 0.77x, 10 errors → 0.50x
    if meta_paths:
        try:
            placeholders = ",".join("?" * len(meta_paths))
            error_rows = conn.execute(
                f"SELECT note_path, COUNT(*) as cnt FROM prediction_errors "
                f"WHERE note_path IN ({placeholders}) AND resolved_at IS NULL "
                f"GROUP BY note_path",
                meta_paths,
            ).fetchall()
            error_counts = {r["note_path"]: r["cnt"] for r in error_rows}
            for r in valid_results:
                ec = error_counts.get(r["note_path"], 0)
                if ec > 0:
                    r["score"] *= 1.0 / (1.0 + 0.1 * ec)
        except Exception:
            pass  # Never let error demotion disrupt search

    valid_results.sort(key=lambda x: x["score"], reverse=True)

    # Deduplicate by note_path (keep highest scoring chunk per note).
    # Collect a wider candidate pool (3x top_k) so lateral inhibition has
    # room to suppress similar results and promote diverse alternatives.
    candidate_limit = top_k * 3
    seen_notes = set()
    deduped = []
    for r in valid_results:
        if r["note_path"] not in seen_notes:
            seen_notes.add(r["note_path"])
            deduped.append(r)
        if len(deduped) >= candidate_limit:
            break

    # ── Lateral inhibition ──
    # Winner-take-all dynamics: higher-ranked results suppress semantically
    # similar competitors, promoting diversity in the result set.  Mirrors
    # PV+ / SOM+ inhibitory interneuron function during engram allocation:
    # the most excitable neurons fire first, then recruit inhibitory circuits
    # that suppress neighbours, maintaining engram sparsity.
    #
    # For each result (from rank 2 onward), compute max cosine similarity
    # to all higher-ranked results.  If similarity exceeds the threshold,
    # apply a proportional penalty.  The penalty is bounded so that even
    # maximally similar results retain 70% of their score.
    #
    # penalty = 1 - inhibition_strength * max_similarity_to_higher_ranked
    INHIBITION_THRESHOLD = 0.65   # only suppress when note embeddings are >0.65 similar
    INHIBITION_STRENGTH = 0.30    # max 30% score reduction at similarity=1.0
    if len(deduped) > 1:
        # Build embedding lookup for deduped results
        deduped_embeddings = []
        for r in deduped:
            emb = r.get("embedding")
            if emb:
                deduped_embeddings.append(blob_to_embedding(emb) if isinstance(emb, bytes) else emb)
            else:
                deduped_embeddings.append(None)

        for i in range(1, len(deduped)):
            if deduped_embeddings[i] is None:
                continue
            max_sim = 0.0
            for j in range(i):
                if deduped_embeddings[j] is None:
                    continue
                dot = np.dot(deduped_embeddings[i], deduped_embeddings[j])
                norm = (
                    np.linalg.norm(deduped_embeddings[i])
                    * np.linalg.norm(deduped_embeddings[j])
                    + 1e-10
                )
                sim = float(dot / norm)
                if sim > max_sim:
                    max_sim = sim
            if max_sim > INHIBITION_THRESHOLD:
                penalty = 1.0 - INHIBITION_STRENGTH * max_sim
                deduped[i]["score"] *= penalty

        # Re-sort after inhibition — suppressed results may drop below
        # previously lower-ranked diverse results
        deduped.sort(key=lambda x: x["score"], reverse=True)

    # Trim to final top_k after lateral inhibition
    deduped = deduped[:top_k]

    # Auto-record usage for returned results (drives hotness scoring)
    returned_paths = [r["note_path"] for r in deduped[:top_k]]
    _record_note_usage(conn, returned_paths)

    # Hebbian reinforcement: strengthen co-occurrence for entity pairs shared
    # between query-matched entities and result-note entities.
    # Fires regardless of cooccurrence_boost_weight setting.
    if query_entities and returned_paths:
        try:
            placeholders = ",".join("?" * len(returned_paths))
            result_ent_rows = conn.execute(
                f"SELECT DISTINCT subject, object FROM triples "
                f"WHERE note_path IN ({placeholders})",
                returned_paths,
            ).fetchall()
            result_entities: set[str] = set()
            for rer in result_ent_rows:
                result_entities.add(rer["subject"])
                result_entities.add(rer["object"])

            # Build reinforcement pairs: each query entity x each result entity
            reinforce_pairs = [
                (qe, re)
                for qe in query_entities
                for re in result_entities
                if qe != re
            ]
            if reinforce_pairs:
                reinforce_cooccurrence(conn, reinforce_pairs)
        except Exception:
            pass  # Never let reinforcement disrupt search

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


def triple_fts_search(
    conn: sqlite3.Connection,
    query: str,
    limit: int = 30,
    workspace: str | None = None,
) -> list[dict]:
    """Full-text search over triples."""
    safe_query = " OR ".join(
        '"' + word.replace('"', '') + '"'
        for word in query.split()
        if word and not word.startswith("-")
    )
    if not safe_query:
        return []

    workspace = _normalize_workspace(workspace)
    if workspace:
        rows = conn.execute(
            """
            SELECT t.triple_id, t.note_path, t.subject, t.predicate, t.object,
                   t.triple_text, t.embedding, rank
            FROM triples_fts
            JOIN triples t ON t.triple_id = triples_fts.rowid
            WHERE triples_fts MATCH ?
              AND t.note_path LIKE ? || '%'
            ORDER BY rank
            LIMIT ?
            """,
            (safe_query, workspace + "/", limit),
        ).fetchall()
    else:
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
    workspace: str | None = None,
) -> list[dict]:
    """Pure semantic search over triples with embeddings.

    Uses sqlite-vec KNN index when available, falls back to brute-force numpy scan.
    """
    from .vecindex import has_vec_index, vec_knn_triples

    workspace = _normalize_workspace(workspace)

    # Fast path: sqlite-vec KNN index
    if has_vec_index(conn):
        try:
            return vec_knn_triples(conn, query_embedding, k=limit, workspace=workspace)
        except Exception as e:
            log.warning("sqlite-vec triple KNN failed, falling back to brute-force: %s", e)

    # Fallback: brute-force numpy scan
    if workspace:
        rows = conn.execute(
            """SELECT triple_id, note_path, subject, predicate, object,
                      triple_text, embedding
               FROM triples WHERE embedding IS NOT NULL
                 AND note_path LIKE ? || '%'""",
            (workspace + "/",),
        ).fetchall()
    else:
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
    workspace: str | None = None,
) -> list[TripleResult]:
    """Search triples using hybrid FTS5 + semantic similarity.

    Returns compact TripleResult objects (~10-20 tokens each).
    """
    from .schema import DB_PATH

    embed_url = embed_url or get_config().embed_url
    conn = get_db(db_path or DB_PATH)
    workspace = _normalize_workspace(workspace)

    if mode == "keyword":
        fts_results = triple_fts_search(conn, query, limit=top_k, workspace=workspace)
        results = _to_triple_results(conn, fts_results[:top_k])
        _record_note_usage(conn, [r.note_path for r in results])
        return results

    try:
        query_embedding = get_embedding(query, base_url=embed_url)
    except (ConnectionError, OSError, Exception) as exc:
        log.warning(
            "Embedding service unavailable,"
            " falling back to FTS5-only triple search: %s",
            exc,
        )
        fts_results = triple_fts_search(conn, query, limit=top_k, workspace=workspace)
        results = _to_triple_results(conn, fts_results[:top_k])
        _record_note_usage(conn, [r.note_path for r in results])
        return results

    if mode == "semantic":
        sem_results = triple_semantic_search(
            conn, query_embedding, limit=top_k, workspace=workspace,
        )
        results = _to_triple_results(conn, sem_results[:top_k])
        _record_note_usage(conn, [r.note_path for r in results])
        return results

    # Hybrid: FTS5 pre-filter + semantic rerank
    fts_results = triple_fts_search(
        conn, query, limit=30, workspace=workspace,
    )

    if not fts_results:
        sem_results = triple_semantic_search(
            conn, query_embedding, limit=top_k, workspace=workspace,
        )
        results = _to_triple_results(conn, sem_results[:top_k])
        _record_note_usage(conn, [r.note_path for r in results])
        return results

    embeddings = []
    valid_results = []
    for r in fts_results:
        if r["embedding"]:
            embeddings.append(blob_to_embedding(r["embedding"]))
            valid_results.append(r)

    if not valid_results:
        results = _to_triple_results(conn, fts_results[:top_k])
        _record_note_usage(conn, [r.note_path for r in results])
        return results

    matrix = np.stack(embeddings)
    scores = cosine_similarity_batch(query_embedding, matrix)

    for i, r in enumerate(valid_results):
        fts_score = 1.0 / (1.0 + abs(r.get("rank", 0)))
        r["score"] = 0.3 * fts_score + 0.7 * float(scores[i])

    valid_results.sort(key=lambda x: x["score"], reverse=True)

    results = _to_triple_results(conn, valid_results[:top_k])
    _record_note_usage(conn, [r.note_path for r in results])
    return results


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
    workspace: str | None = None,
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
            workspace=workspace,
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
            context=context,
            workspace=workspace,
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
            context=context,
            workspace=workspace,
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
        workspace=workspace,
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
        context=context,
        workspace=workspace,
    )
    result["chunks"] = [
        {"note": r.note_path, "title": r.title, "section": r.heading_path,
         "snippet": r.snippet, "summary": r.summary, "score": round(r.score, 4)}
        for r in chunk_results
    ]
    result["depth_used"] = "auto:full"
    return result
