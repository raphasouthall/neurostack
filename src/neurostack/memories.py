# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Agent write-back memory layer.

Allows AI agents to persist observations, decisions, conventions, and learnings
into the vault's database. Memories are searchable alongside vault notes via
FTS5 and semantic search, tagged with [memory] to distinguish origin.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

log = logging.getLogger("neurostack")

VALID_ENTITY_TYPES = frozenset({
    "observation",
    "decision",
    "convention",
    "learning",
    "context",
    "bug",
})


@dataclass
class Memory:
    memory_id: int
    content: str
    tags: list[str]
    entity_type: str
    source_agent: str | None
    workspace: str | None
    created_at: str
    expires_at: str | None
    session_id: int | None = None
    score: float = 0.0


def save_memory(
    conn: sqlite3.Connection,
    content: str,
    tags: list[str] | None = None,
    entity_type: str = "observation",
    source_agent: str | None = None,
    workspace: str | None = None,
    ttl_hours: float | None = None,
    embed_url: str | None = None,
    session_id: int | None = None,
) -> Memory:
    """Save a new memory and return it.

    Optionally embeds the content for semantic search.
    """
    if entity_type not in VALID_ENTITY_TYPES:
        raise ValueError(
            f"Invalid entity_type: {entity_type}. "
            f"Must be one of: {', '.join(sorted(VALID_ENTITY_TYPES))}"
        )

    # Normalize workspace
    if workspace:
        workspace = workspace.strip("/") or None

    # Compute expiry
    expires_at = None
    if ttl_hours is not None and ttl_hours > 0:
        from datetime import timezone
        expires_at = (
            datetime.now(timezone.utc) + timedelta(hours=ttl_hours)
        ).strftime("%Y-%m-%d %H:%M:%S")

    # Try to embed
    embedding_blob = None
    try:
        from .config import get_config
        from .embedder import embedding_to_blob, get_embedding

        url = embed_url or get_config().embed_url
        emb = get_embedding(content, base_url=url)
        embedding_blob = embedding_to_blob(emb)
    except Exception as exc:
        log.debug("Could not embed memory (non-fatal): %s", exc)

    tags_json = json.dumps(tags or [])

    cursor = conn.execute(
        """
        INSERT INTO memories (content, tags, entity_type, source_agent,
                              workspace, embedding, expires_at,
                              session_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (content, tags_json, entity_type, source_agent,
         workspace, embedding_blob, expires_at, session_id),
    )
    conn.commit()

    memory_id = cursor.lastrowid
    created_at = conn.execute(
        "SELECT created_at FROM memories WHERE memory_id = ?",
        (memory_id,),
    ).fetchone()["created_at"]

    return Memory(
        memory_id=memory_id,
        content=content,
        tags=tags or [],
        entity_type=entity_type,
        source_agent=source_agent,
        workspace=workspace,
        created_at=created_at,
        expires_at=expires_at,
        session_id=session_id,
    )


def forget_memory(conn: sqlite3.Connection, memory_id: int) -> bool:
    """Delete a specific memory. Returns True if deleted."""
    cursor = conn.execute(
        "DELETE FROM memories WHERE memory_id = ?", (memory_id,)
    )
    conn.commit()
    return cursor.rowcount > 0


def search_memories(
    conn: sqlite3.Connection,
    query: str | None = None,
    entity_type: str | None = None,
    workspace: str | None = None,
    limit: int = 20,
    embed_url: str | None = None,
    include_expired: bool = False,
) -> list[Memory]:
    """Search memories by text, type, and/or workspace.

    Uses FTS5 for keyword search, with optional semantic reranking.
    """
    # Purge expired memories first
    if not include_expired:
        conn.execute(
            "DELETE FROM memories WHERE expires_at IS NOT NULL AND expires_at < datetime('now')"
        )
        conn.commit()

    if query:
        return _hybrid_memory_search(
            conn, query, entity_type=entity_type, workspace=workspace,
            limit=limit, embed_url=embed_url,
        )

    # No query — list memories with filters
    where_parts = []
    params: list = []

    if not include_expired:
        where_parts.append(
            "(expires_at IS NULL OR expires_at > datetime('now'))"
        )
    if entity_type:
        where_parts.append("entity_type = ?")
        params.append(entity_type)
    if workspace:
        ws = workspace.strip("/")
        where_parts.append("(workspace = ? OR workspace LIKE ? || '/%')")
        params.extend([ws, ws])

    where = "WHERE " + " AND ".join(where_parts) if where_parts else ""

    rows = conn.execute(
        f"""
        SELECT memory_id, content, tags, entity_type, source_agent,
               workspace, created_at, expires_at
        FROM memories
        {where}
        ORDER BY created_at DESC
        LIMIT ?
        """,
        params + [limit],
    ).fetchall()

    return [_row_to_memory(r) for r in rows]


def _hybrid_memory_search(
    conn: sqlite3.Connection,
    query: str,
    entity_type: str | None = None,
    workspace: str | None = None,
    limit: int = 20,
    embed_url: str | None = None,
) -> list[Memory]:
    """FTS5 + semantic search over memories."""
    # FTS5 search
    safe_query = " ".join(
        '"' + word.replace('"', '') + '"'
        for word in query.split()
        if word and not word.startswith("-")
    )

    fts_results = []
    if safe_query:
        where_extra = ""
        params: list = [safe_query]

        if entity_type:
            where_extra += " AND m.entity_type = ?"
            params.append(entity_type)
        if workspace:
            ws = workspace.strip("/")
            where_extra += " AND (m.workspace = ? OR m.workspace LIKE ? || '/%')"
            params.extend([ws, ws])

        where_extra += " AND (m.expires_at IS NULL OR m.expires_at > datetime('now'))"

        rows = conn.execute(
            f"""
            SELECT m.memory_id, m.content, m.tags, m.entity_type,
                   m.source_agent, m.workspace, m.created_at, m.expires_at,
                   m.embedding, rank
            FROM memories_fts
            JOIN memories m ON m.memory_id = memories_fts.rowid
            WHERE memories_fts MATCH ?{where_extra}
            ORDER BY rank
            LIMIT ?
            """,
            params + [limit * 3],
        ).fetchall()
        fts_results = [dict(r) for r in rows]

    # Try semantic reranking
    try:
        import numpy as np

        from .config import get_config
        from .embedder import (
            blob_to_embedding,
            cosine_similarity_batch,
            get_embedding,
        )

        url = embed_url or get_config().embed_url
        query_emb = get_embedding(query, base_url=url)

        if fts_results:
            # Rerank FTS results by cosine similarity
            embeddings = []
            valid = []
            for r in fts_results:
                if r.get("embedding"):
                    embeddings.append(blob_to_embedding(r["embedding"]))
                    valid.append(r)

            if valid:
                matrix = np.stack(embeddings)
                scores = cosine_similarity_batch(query_emb, matrix)
                for i, r in enumerate(valid):
                    fts_score = 1.0 / (1.0 + abs(r.get("rank", 0)))
                    r["score"] = 0.3 * fts_score + 0.7 * float(scores[i])
                valid.sort(key=lambda x: x["score"], reverse=True)
                return [_row_to_memory(r, score=r["score"]) for r in valid[:limit]]

        # Fallback: pure semantic search if FTS returned nothing
        if not fts_results:
            where_parts = [
                "embedding IS NOT NULL",
                "(expires_at IS NULL OR expires_at > datetime('now'))",
            ]
            sem_params: list = []
            if entity_type:
                where_parts.append("entity_type = ?")
                sem_params.append(entity_type)
            if workspace:
                ws = workspace.strip("/")
                where_parts.append("(workspace = ? OR workspace LIKE ? || '/%')")
                sem_params.extend([ws, ws])

            rows = conn.execute(
                f"""
                SELECT memory_id, content, tags, entity_type, source_agent,
                       workspace, created_at, expires_at, embedding
                FROM memories
                WHERE {' AND '.join(where_parts)}
                """,
                sem_params,
            ).fetchall()

            if rows:
                embeddings = []
                data = []
                for r in rows:
                    embeddings.append(blob_to_embedding(r["embedding"]))
                    data.append(dict(r))

                matrix = np.stack(embeddings)
                scores = cosine_similarity_batch(query_emb, matrix)
                top_indices = np.argsort(scores)[::-1][:limit]

                return [
                    _row_to_memory(data[idx], score=float(scores[idx]))
                    for idx in top_indices
                ]

    except Exception as exc:
        log.debug("Semantic memory search unavailable: %s", exc)

    # Fallback: return FTS results without reranking
    return [_row_to_memory(r) for r in fts_results[:limit]]


def prune_memories(
    conn: sqlite3.Connection,
    older_than_days: int | None = None,
    expired_only: bool = False,
) -> int:
    """Delete expired or old memories. Returns count deleted."""
    if expired_only:
        cursor = conn.execute(
            "DELETE FROM memories WHERE expires_at IS NOT NULL AND expires_at < datetime('now')"
        )
    elif older_than_days is not None:
        cursor = conn.execute(
            "DELETE FROM memories WHERE created_at < datetime('now', ?)",
            (f"-{older_than_days} days",),
        )
    else:
        return 0

    conn.commit()
    return cursor.rowcount


def get_memory_stats(conn: sqlite3.Connection) -> dict:
    """Get memory counts by type."""
    total = conn.execute("SELECT COUNT(*) as c FROM memories").fetchone()["c"]
    expired = conn.execute(
        "SELECT COUNT(*) as c FROM memories "
        "WHERE expires_at IS NOT NULL AND expires_at < datetime('now')"
    ).fetchone()["c"]
    embedded = conn.execute(
        "SELECT COUNT(*) as c FROM memories WHERE embedding IS NOT NULL"
    ).fetchone()["c"]

    by_type = {}
    rows = conn.execute(
        "SELECT entity_type, COUNT(*) as c FROM memories GROUP BY entity_type"
    ).fetchall()
    for r in rows:
        by_type[r["entity_type"]] = r["c"]

    return {
        "total": total,
        "expired": expired,
        "embedded": embedded,
        "by_type": by_type,
    }


def start_session(
    conn: sqlite3.Connection,
    source_agent: str | None = None,
    workspace: str | None = None,
) -> dict:
    """Start a new memory session. Returns session_id and started_at."""
    if workspace:
        workspace = workspace.strip("/") or None

    cursor = conn.execute(
        """
        INSERT INTO memory_sessions (source_agent, workspace)
        VALUES (?, ?)
        """,
        (source_agent, workspace),
    )
    conn.commit()
    session_id = cursor.lastrowid
    row = conn.execute(
        "SELECT started_at FROM memory_sessions WHERE session_id = ?",
        (session_id,),
    ).fetchone()

    return {
        "session_id": session_id,
        "started_at": row["started_at"],
        "source_agent": source_agent,
        "workspace": workspace,
    }


def end_session(
    conn: sqlite3.Connection,
    session_id: int,
    summary: str | None = None,
) -> dict:
    """End a memory session. Optionally stores a summary."""
    # Verify session exists and is not already ended
    row = conn.execute(
        "SELECT * FROM memory_sessions WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    if not row:
        return {"error": f"Session {session_id} not found"}
    if row["ended_at"]:
        return {"error": f"Session {session_id} already ended"}

    conn.execute(
        """
        UPDATE memory_sessions
        SET ended_at = datetime('now'), summary = ?
        WHERE session_id = ?
        """,
        (summary, session_id),
    )
    conn.commit()

    updated = conn.execute(
        "SELECT * FROM memory_sessions WHERE session_id = ?",
        (session_id,),
    ).fetchone()

    return {
        "session_id": session_id,
        "started_at": updated["started_at"],
        "ended_at": updated["ended_at"],
        "summary": updated["summary"],
        "source_agent": updated["source_agent"],
        "workspace": updated["workspace"],
    }


def get_session(
    conn: sqlite3.Connection,
    session_id: int,
) -> dict | None:
    """Get session details with its memories."""
    row = conn.execute(
        "SELECT * FROM memory_sessions WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    if not row:
        return None

    memories = conn.execute(
        """
        SELECT memory_id, content, tags, entity_type,
               source_agent, workspace, created_at, expires_at,
               session_id
        FROM memories
        WHERE session_id = ?
        ORDER BY created_at ASC
        """,
        (session_id,),
    ).fetchall()

    return {
        "session_id": row["session_id"],
        "started_at": row["started_at"],
        "ended_at": row["ended_at"],
        "source_agent": row["source_agent"],
        "workspace": row["workspace"],
        "summary": row["summary"],
        "memory_count": len(memories),
        "memories": [
            {
                "memory_id": m["memory_id"],
                "content": m["content"],
                "entity_type": m["entity_type"],
                "tags": json.loads(m["tags"])
                if isinstance(m["tags"], str)
                else (m["tags"] or []),
                "created_at": m["created_at"],
            }
            for m in memories
        ],
    }


def list_sessions(
    conn: sqlite3.Connection,
    limit: int = 20,
    workspace: str | None = None,
) -> list[dict]:
    """List recent sessions with memory counts."""
    where_parts = []
    params: list = []

    if workspace:
        ws = workspace.strip("/")
        where_parts.append(
            "(ms.workspace = ? OR ms.workspace LIKE ? || '/%')"
        )
        params.extend([ws, ws])

    where = (
        "WHERE " + " AND ".join(where_parts) if where_parts else ""
    )

    rows = conn.execute(
        f"""
        SELECT ms.session_id, ms.started_at, ms.ended_at,
               ms.source_agent, ms.workspace, ms.summary,
               COUNT(m.memory_id) as memory_count
        FROM memory_sessions ms
        LEFT JOIN memories m ON m.session_id = ms.session_id
        {where}
        GROUP BY ms.session_id
        ORDER BY ms.started_at DESC
        LIMIT ?
        """,
        params + [limit],
    ).fetchall()

    return [
        {
            "session_id": r["session_id"],
            "started_at": r["started_at"],
            "ended_at": r["ended_at"],
            "source_agent": r["source_agent"],
            "workspace": r["workspace"],
            "summary": r["summary"],
            "memory_count": r["memory_count"],
        }
        for r in rows
    ]


def summarize_session(
    conn: sqlite3.Connection,
    session_id: int,
    llm_url: str | None = None,
    llm_model: str | None = None,
) -> str:
    """Generate an LLM summary of a session's memories.

    Gathers all memories from the session and sends them to
    Ollama to produce a 2-3 sentence summary.
    """
    import re

    import httpx

    from .config import get_config

    cfg = get_config()
    llm_url = llm_url or cfg.llm_url
    llm_model = llm_model or cfg.llm_model

    session = get_session(conn, session_id)
    if not session:
        return ""
    memories = session.get("memories", [])
    if not memories:
        return "No memories recorded in this session."

    memory_lines = []
    for m in memories:
        memory_lines.append(
            f"- [{m['entity_type']}] {m['content']}"
        )
    memory_text = "\n".join(memory_lines)

    prompt = (
        "Summarize this AI coding session in 2-3 concise "
        "sentences. Focus on what was accomplished, key "
        "decisions made, and any problems encountered. "
        "Be direct.\n\n"
        f"Session memories:\n{memory_text}\n\n"
        "Summary:"
    )

    resp = httpx.post(
        f"{llm_url}/api/generate",
        json={
            "model": llm_model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.3,
                "num_predict": 200,
            },
            "think": False,
        },
        timeout=120.0,
    )
    resp.raise_for_status()
    summary = resp.json().get("response", "").strip()

    # Strip think tags if model includes them
    summary = re.sub(
        r"<think>.*?</think>", "", summary, flags=re.DOTALL
    ).strip()

    return summary


def _row_to_memory(row: dict | sqlite3.Row, score: float = 0.0) -> Memory:
    """Convert a database row to a Memory object."""
    # sqlite3.Row doesn't have .get(), so use dict conversion
    if not isinstance(row, dict):
        row = dict(row)

    tags_raw = row.get("tags")
    if isinstance(tags_raw, str):
        try:
            tags = json.loads(tags_raw)
        except (json.JSONDecodeError, TypeError):
            tags = []
    else:
        tags = tags_raw or []

    return Memory(
        memory_id=row["memory_id"],
        content=row["content"],
        tags=tags,
        entity_type=row["entity_type"],
        source_agent=row.get("source_agent"),
        workspace=row.get("workspace"),
        created_at=row["created_at"],
        expires_at=row.get("expires_at"),
        session_id=row.get("session_id"),
        score=score,
    )
