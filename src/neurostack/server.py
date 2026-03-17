#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""NeuroStack MCP server — tools for pre-computed vault context."""

import json
import logging
import time as _time

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("neurostack")

from .config import get_config

log = logging.getLogger("neurostack")

# -- In-memory TTL cache for expensive LLM-backed tools -----------
_tool_cache: dict[str, tuple[float, str]] = {}
_CACHE_TTL = 300.0  # 5 minutes


def _cache_get(key: str) -> str | None:
    """Return cached result if fresh, else None."""
    entry = _tool_cache.get(key)
    if entry and (_time.time() - entry[0]) < _CACHE_TTL:
        return entry[1]
    if entry:
        del _tool_cache[key]
    return None


def _cache_set(key: str, value: str) -> None:
    """Store result with current timestamp."""
    _tool_cache[key] = (_time.time(), value)


def _cache_clear() -> None:
    """Clear all cached tool results."""
    _tool_cache.clear()


_cfg = get_config()
VAULT_ROOT = _cfg.vault_root
EMBED_URL = _cfg.embed_url



@mcp.tool()
def vault_search(
    query: str,
    top_k: int = 5,
    mode: str = "hybrid",
    depth: str = "auto",
    context: str = None,
    workspace: str = None,
) -> str:
    """Search the vault with tiered retrieval depth.

    Args:
        query: Natural language search query
        top_k: Number of results to return (default 5)
        mode: Search mode - "hybrid" (default), "semantic", or "keyword"
        depth: Retrieval depth controlling token cost:
            - "triples": ~10-20 tokens/fact. Structured SPO facts only. Cheapest.
            - "summaries": ~50-100 tokens/note. Pre-computed note summaries.
            - "full": ~200-500 tokens/result. Snippets + summaries.
            - "auto": Start with triples, escalate to full if coverage is low. Default.
        context: Optional project/domain context for boosting
        workspace: Optional vault subdirectory prefix to restrict
            results (e.g. "work/acme-cloud")

    Use "triples" for quick factual lookups, "summaries" for overview,
    "full" when you need actual content, "auto" to let the system decide.
    """
    if depth in ("triples", "summaries", "auto"):
        from .search import tiered_search

        result = tiered_search(
            query, top_k=top_k, depth=depth, mode=mode,
            embed_url=EMBED_URL, context=context, rerank=True,
            workspace=workspace,
        )

        # Include matching memories in auto/summaries/full modes
        if depth in ("auto", "summaries"):
            memories = _search_memories_for_results(query, workspace, limit=3)
            if memories:
                result["memories"] = memories

        return json.dumps(result)

    # Default: full depth (original behavior)
    from .search import hybrid_search

    results = hybrid_search(
        query, top_k=top_k, mode=mode,
        embed_url=EMBED_URL, context=context, rerank=True,
        workspace=workspace,
    )

    output = []
    for r in results:
        entry = {
            "path": r.note_path,
            "title": r.title,
            "section": r.heading_path,
            "score": round(r.score, 4),
            "snippet": r.snippet,
        }
        if r.summary:
            entry["summary"] = r.summary
        output.append(entry)

    # Include matching memories
    memories = _search_memories_for_results(query, workspace, limit=3)
    if memories:
        output.append({"_memories": memories})

    return json.dumps(output)


@mcp.tool()
def vault_ask(
    question: str,
    top_k: int = 8,
    workspace: str = None,
) -> str:
    """Ask a natural language question and get an answer with citations from vault content.

    Uses RAG (Retrieval-Augmented Generation) to search the vault for relevant
    content, then synthesizes an answer with inline [[note-title]] citations.

    Args:
        question: Natural language question to answer
        top_k: Number of chunks to retrieve for context (default 8)
        workspace: Optional vault subdirectory prefix to restrict
            results (e.g. "work/acme-cloud")
    """
    cache_key = f"ask:{question}:{top_k}:{workspace}"
    cached = _cache_get(cache_key)
    if cached is not None:
        log.debug("Cache hit for %s", cache_key)
        return cached

    from .ask import ask_vault

    result = ask_vault(
        question=question,
        top_k=top_k,
        embed_url=EMBED_URL,
        workspace=workspace,
    )
    out = json.dumps(result)
    _cache_set(cache_key, out)
    return out


def _search_memories_for_results(query: str, workspace: str = None, limit: int = 3) -> list[dict]:
    """Search memories and return compact results for inclusion in vault_search."""
    try:
        from .memories import search_memories
        from .schema import DB_PATH, get_db

        conn = get_db(DB_PATH)
        memories = search_memories(
            conn, query=query, workspace=workspace,
            limit=limit, embed_url=EMBED_URL,
        )
        return [
            {
                "memory_id": m.memory_id,
                "content": m.content,
                "entity_type": m.entity_type,
                "source": m.source_agent,
                "created_at": m.created_at,
            }
            for m in memories
            if m.score > 0.35  # only include relevant memories
        ]
    except Exception:
        return []


@mcp.tool()
def vault_summary(path_or_query: str) -> str:
    """Get pre-computed summary for a note by path or search query.

    Returns 2-3 sentence summary + frontmatter (~100-200 tokens)
    instead of reading the full file (~500-2000 tokens).

    Args:
        path_or_query: Note path (e.g. "research/predictive-coding.md") or search query
    """
    from .schema import DB_PATH, get_db
    from .search import hybrid_search

    conn = get_db(DB_PATH)

    # Try exact path match
    row = conn.execute(
        """SELECT n.path, n.title, n.frontmatter, s.summary_text
           FROM notes n LEFT JOIN summaries s ON s.note_path = n.path
           WHERE n.path = ?""",
        (path_or_query,),
    ).fetchone()

    if not row:
        # Try search
        results = hybrid_search(path_or_query, top_k=1, embed_url=EMBED_URL)
        if results:
            r = results[0]
            row = conn.execute(
                """SELECT n.path, n.title, n.frontmatter, s.summary_text
                   FROM notes n LEFT JOIN summaries s ON s.note_path = n.path
                   WHERE n.path = ?""",
                (r.note_path,),
            ).fetchone()

    if not row:
        return json.dumps({"error": "Note not found"})

    result = {
        "path": row["path"],
        "title": row["title"],
        "frontmatter": json.loads(row["frontmatter"]) if row["frontmatter"] else {},
        "summary": row["summary_text"] or "(not yet generated)",
    }
    return json.dumps(result)


@mcp.tool()
def vault_graph(note: str, depth: int = 1, workspace: str = None) -> str:
    """Get wiki-link neighborhood for a note with summaries and PageRank.

    One call replaces manually following links across files.

    Args:
        note: Note path (e.g. "research/predictive-coding.md")
        depth: How many link-hops to traverse (default 1)
        workspace: Optional vault subdirectory prefix to restrict
            neighbors (e.g. "work/acme-cloud")
    """
    from .graph import get_neighborhood
    from .search import _normalize_workspace

    result = get_neighborhood(note, depth=depth)
    ws = _normalize_workspace(workspace)
    if result and ws:
        result.neighbors = [
            n for n in result.neighbors
            if n.path.startswith(ws + "/")
        ]
    if not result:
        return json.dumps({"error": f"Note not found: {note}"})

    def node_to_dict(n):
        d = {
            "path": n.path,
            "title": n.title,
            "pagerank": round(n.pagerank, 4),
            "in_degree": n.in_degree,
            "out_degree": n.out_degree,
        }
        if n.summary:
            d["summary"] = n.summary
        return d

    output = {
        "center": node_to_dict(result.center),
        "neighbors": [node_to_dict(n) for n in result.neighbors],
        "neighbor_count": len(result.neighbors),
    }
    return json.dumps(output)


@mcp.tool()
def vault_related(note: str, top_k: int = 10, workspace: str = None) -> str:
    """Find semantically related notes using embedding similarity.

    Unlike vault_graph (which follows explicit wiki-links), this discovers
    connections based on semantic content similarity - notes that discuss
    similar topics even if not explicitly linked.

    Args:
        note: Note path (e.g. "research/predictive-coding.md")
        top_k: Number of related notes to return (default 10)
        workspace: Optional vault subdirectory prefix to restrict
            results (e.g. "work/acme-cloud")
    """
    from .related import find_related

    results = find_related(note_path=note, top_k=top_k, workspace=workspace)
    return json.dumps(results)


@mcp.tool()
def session_brief(workspace: str = None) -> str:
    """Get a compact ~500 token session brief.

    Includes: recent vault changes with summaries, git commits,
    recent memories, top connected notes, time-of-day context.

    Args:
        workspace: Optional vault subdirectory prefix to restrict
            results (e.g. "work/acme-cloud")
    """
    from .brief import generate_brief

    return generate_brief(vault_root=VAULT_ROOT, workspace=workspace)


@mcp.tool()
def vault_context(
    task: str,
    token_budget: int = 2000,
    workspace: str = None,
    include_memories: bool = True,
    include_triples: bool = True,
) -> str:
    """Assemble task-scoped context for session recovery after /clear or new conversation.

    Unlike session_brief (time-anchored status snapshot), this is task-anchored:
    it retrieves memories, triples, summaries, and session history relevant to
    a specific task description, respecting a token budget.

    Args:
        task: Description of the current task or goal
        token_budget: Maximum approximate tokens in response (default 2000)
        workspace: Optional vault subdirectory to scope
        include_memories: Include relevant memories (default True)
        include_triples: Include relevant triples (default True)
    """
    from .context import build_vault_context
    from .schema import DB_PATH, get_db

    conn = get_db(DB_PATH)
    result = build_vault_context(
        conn, task=task, token_budget=token_budget,
        workspace=workspace, include_memories=include_memories,
        include_triples=include_triples, embed_url=EMBED_URL,
    )
    return json.dumps(result)


@mcp.tool()
def vault_triples(query: str, top_k: int = 10, mode: str = "hybrid", workspace: str = None) -> str:
    """Search knowledge graph triples for structured facts.

    Returns compact Subject-Predicate-Object facts (~10-20 tokens each).
    Use this for quick factual lookups instead of reading full notes.

    Args:
        query: Natural language search query
        top_k: Number of triples to return (default 10)
        mode: Search mode - "hybrid" (default), "semantic", or "keyword"
        workspace: Optional vault subdirectory prefix to restrict
            results (e.g. "work/acme-cloud")
    """
    from .search import search_triples

    results = search_triples(
        query, top_k=top_k, mode=mode,
        embed_url=EMBED_URL, workspace=workspace,
    )

    output = []
    for t in results:
        output.append({
            "note": t.note_path,
            "title": t.title,
            "s": t.subject,
            "p": t.predicate,
            "o": t.object,
            "score": round(t.score, 4),
        })

    return json.dumps(output)


@mcp.tool()
def vault_communities(
    query: str,
    top_k: int = 6,
    level: int = 0,
    map_reduce: bool = True,
    workspace: str = None,
) -> str:
    """Answer global queries using GraphRAG community summaries.

    Unlike vault_search (which retrieves specific chunks), this answers
    thematic questions like "what topics dominate my vault?" or
    "what are the main research areas I've been exploring?" by running
    Leiden community detection summaries through a map-reduce synthesis.

    Args:
        query: Natural language question about vault themes/topics
        top_k: Number of communities to retrieve (default 6)
        level: Community hierarchy level — 0=coarse themes (default), 1=fine sub-themes
        map_reduce: Use LLM map-reduce synthesis (True) or raw hits (False)
        workspace: Optional vault subdirectory prefix to restrict
            results (e.g. "work/acme-cloud")
    """
    cache_key = (
        f"communities:{query}:{top_k}:{level}"
        f":{map_reduce}:{workspace}"
    )
    cached = _cache_get(cache_key)
    if cached is not None:
        log.debug("Cache hit for %s", cache_key)
        return cached

    from .community_search import global_query

    result = global_query(
        query=query,
        top_k=top_k,
        level=level,
        use_map_reduce=map_reduce,
        embed_url=EMBED_URL,
        workspace=workspace,
    )
    out = json.dumps(result)
    _cache_set(cache_key, out)
    return out


@mcp.tool()
def vault_stats() -> str:
    """Get index health: note count, embedding coverage, graph stats, triple stats."""
    from .schema import DB_PATH, get_db

    conn = get_db(DB_PATH)

    notes = conn.execute("SELECT COUNT(*) as c FROM notes").fetchone()["c"]
    chunks = conn.execute("SELECT COUNT(*) as c FROM chunks").fetchone()["c"]
    embedded = conn.execute(
        "SELECT COUNT(*) as c FROM chunks WHERE embedding IS NOT NULL"
    ).fetchone()["c"]
    summaries = conn.execute("SELECT COUNT(*) as c FROM summaries").fetchone()["c"]
    edges = conn.execute("SELECT COUNT(*) as c FROM graph_edges").fetchone()["c"]

    # Staleness check
    stale_summaries = conn.execute(
        """SELECT COUNT(*) as c FROM notes n
           LEFT JOIN summaries s ON s.note_path = n.path
           WHERE s.content_hash IS NULL OR s.content_hash != n.content_hash"""
    ).fetchone()["c"]

    # Triple stats
    total_triples = conn.execute("SELECT COUNT(*) as c FROM triples").fetchone()["c"]
    notes_with_triples = conn.execute(
        "SELECT COUNT(DISTINCT note_path) as c FROM triples"
    ).fetchone()["c"]
    embedded_triples = conn.execute(
        "SELECT COUNT(*) as c FROM triples WHERE embedding IS NOT NULL"
    ).fetchone()["c"]

    # Excitability stats
    from .search import get_dormancy_report
    dormancy = get_dormancy_report(conn, threshold=0.05, limit=0)

    # Memory stats
    from .memories import get_memory_stats
    mem_stats = get_memory_stats(conn)

    result = {
        "notes": notes,
        "chunks": chunks,
        "embedded": embedded,
        "embedding_coverage": f"{embedded * 100 // max(chunks, 1)}%",
        "summaries": summaries,
        "summary_coverage": f"{summaries * 100 // max(notes, 1)}%",
        "stale_summaries": stale_summaries,
        "graph_edges": edges,
        "triples": total_triples,
        "notes_with_triples": notes_with_triples,
        "triple_coverage": f"{notes_with_triples * 100 // max(notes, 1)}%",
        "triple_embedding_coverage": f"{embedded_triples * 100 // max(total_triples, 1)}%",
        "communities_coarse": conn.execute(
            "SELECT COUNT(*) as c FROM communities"
            " WHERE level = 0"
        ).fetchone()["c"],
        "communities_fine": conn.execute(
            "SELECT COUNT(*) as c FROM communities"
            " WHERE level = 1"
        ).fetchone()["c"],
        "communities_summarized": conn.execute(
            "SELECT COUNT(*) as c FROM communities"
            " WHERE summary IS NOT NULL"
        ).fetchone()["c"],
        "excitability": {
            "active": dormancy["active_count"],
            "dormant": dormancy["dormant_count"],
            "never_used": dormancy["never_used_count"],
        },
        "memories": mem_stats,
    }
    return json.dumps(result)


@mcp.tool()
def vault_record_usage(note_paths: list[str]) -> str:
    """Record that specific notes were retrieved and used in this session.

    Call this after vault_search when you actually consumed the returned notes.
    Drives hotness scoring — frequently used notes score higher in future searches.

    Args:
        note_paths: List of note paths that were used (e.g. ["research/foo.md", "work/bar.md"])
    """
    from .schema import DB_PATH, get_db

    conn = get_db(DB_PATH)
    conn.executemany(
        "INSERT INTO note_usage (note_path) VALUES (?)",
        [(p,) for p in note_paths],
    )
    conn.commit()
    return json.dumps({"recorded": len(note_paths), "paths": note_paths})


@mcp.tool()
def vault_prediction_errors(
    error_type: str = None,
    limit: int = 20,
    resolve: list[str] = None,
    workspace: str = None,
) -> str:
    """Return notes flagged as prediction errors — high semantic distance at retrieval time.

    These are notes that "surprised" during retrieval (poor fit for the query that retrieved them),
    signalling they may be outdated, miscategorised, or poorly linked.

    Error types:
    - low_overlap: cosine distance > 0.62 — note is semantically distant from what retrieved it
    - contextual_mismatch: note surfaced outside its expected domain context

    Args:
        error_type: Filter by type — "low_overlap" or "contextual_mismatch". None = all.
        limit: Max errors to return (default 20).
        resolve: List of note paths to mark as resolved (clears their unresolved flags).
        workspace: Optional vault subdirectory prefix to restrict
            results (e.g. "work/acme-cloud")
    """
    from .schema import DB_PATH, get_db
    from .search import _normalize_workspace

    conn = get_db(DB_PATH)

    if resolve:
        conn.execute(
            """
            UPDATE prediction_errors SET resolved_at = datetime('now')
            WHERE note_path IN ({}) AND resolved_at IS NULL
            """.format(",".join("?" * len(resolve))),
            resolve,
        )
        conn.commit()
        return json.dumps({"resolved": len(resolve), "paths": resolve})

    where = "WHERE resolved_at IS NULL"
    params: list = []
    if error_type:
        where += " AND error_type = ?"
        params.append(error_type)

    ws = _normalize_workspace(workspace)
    if ws:
        where += " AND note_path LIKE ? || '%'"
        params.append(ws + "/")

    rows = conn.execute(
        f"""
        SELECT note_path, error_type, context,
               AVG(cosine_distance) as avg_distance,
               COUNT(*) as occurrences,
               MAX(detected_at) as last_seen,
               MIN(query) as sample_query
        FROM prediction_errors
        {where}
        GROUP BY note_path, error_type
        ORDER BY occurrences DESC, avg_distance DESC
        LIMIT ?
        """,
        params + [limit],
    ).fetchall()

    results = [
        {
            "note_path": r["note_path"],
            "error_type": r["error_type"],
            "context": r["context"],
            "avg_cosine_distance": round(r["avg_distance"], 3),
            "occurrences": r["occurrences"],
            "last_seen": r["last_seen"],
            "sample_query": r["sample_query"],
        }
        for r in rows
    ]

    total_where = "WHERE resolved_at IS NULL"
    total_params: list = []
    if ws:
        total_where += " AND note_path LIKE ? || '%'"
        total_params.append(ws + "/")

    total_unresolved = conn.execute(
        f"SELECT COUNT(DISTINCT note_path) FROM prediction_errors {total_where}",
        total_params,
    ).fetchone()[0]

    return json.dumps({
        "total_flagged_notes": total_unresolved,
        "showing": len(results),
        "errors": results,
    })


@mcp.tool()
def vault_remember(
    content: str,
    tags: list[str] = None,
    entity_type: str = "observation",
    source_agent: str = None,
    workspace: str = None,
    ttl_hours: float = None,
    session_id: int = None,
) -> str:
    """Save a memory - persist an observation, decision, or learning for future retrieval.

    Memories are searchable alongside vault notes. Use this to record:
    - Architecture decisions made during a session
    - Bug root causes discovered
    - Conventions or patterns established
    - Context that should survive across sessions

    Args:
        content: The memory content to save (1-2 sentences recommended)
        tags: Optional tags for filtering (e.g. ["auth", "refactor"])
        entity_type: Type of memory - "observation", "decision",
            "convention", "learning", "context", or "bug"
        source_agent: Name of the agent writing this
            (e.g. "claude-code", "cursor")
        workspace: Optional vault subdirectory scope
            (e.g. "work/acme-cloud")
        ttl_hours: Optional time-to-live in hours. Memory auto-expires
            after this. None = permanent.
        session_id: Optional session ID from vault_session_start to
            group this memory with a session
    """
    from .memories import save_memory
    from .schema import DB_PATH, get_db

    conn = get_db(DB_PATH)
    memory = save_memory(
        conn, content=content, tags=tags, entity_type=entity_type,
        source_agent=source_agent, workspace=workspace,
        ttl_hours=ttl_hours, embed_url=EMBED_URL,
        session_id=session_id,
    )

    result = {
        "saved": True,
        "memory_id": memory.memory_id,
        "entity_type": memory.entity_type,
        "expires_at": memory.expires_at,
    }
    if memory.near_duplicates:
        result["near_duplicates"] = memory.near_duplicates
    if memory.suggested_tags:
        result["suggested_tags"] = memory.suggested_tags
    return json.dumps(result)


@mcp.tool()
def vault_forget(memory_id: int) -> str:
    """Delete a specific memory by ID.

    Args:
        memory_id: The ID of the memory to delete (from vault_remember or vault_memories)
    """
    from .memories import forget_memory
    from .schema import DB_PATH, get_db

    conn = get_db(DB_PATH)
    deleted = forget_memory(conn, memory_id)
    return json.dumps({"deleted": deleted, "memory_id": memory_id})


@mcp.tool()
def vault_update_memory(
    memory_id: int,
    content: str = None,
    tags: list[str] = None,
    add_tags: list[str] = None,
    remove_tags: list[str] = None,
    entity_type: str = None,
    workspace: str = None,
    ttl_hours: float = None,
) -> str:
    """Update an existing memory. Only provided fields are changed.

    Args:
        memory_id: The memory to update
        content: New content (re-embeds if changed)
        tags: Replace tags entirely (pass [] to clear)
        add_tags: Add these tags to existing set
        remove_tags: Remove these tags from existing set
        entity_type: Change type
        workspace: Change workspace scope
        ttl_hours: Set or change TTL. Pass 0 to make permanent.
    """
    from .memories import update_memory
    from .schema import DB_PATH, get_db

    conn = get_db(DB_PATH)
    try:
        memory = update_memory(
            conn,
            memory_id=memory_id,
            content=content,
            tags=tags,
            add_tags=add_tags,
            remove_tags=remove_tags,
            entity_type=entity_type,
            workspace=workspace,
            ttl_hours=ttl_hours,
            embed_url=EMBED_URL,
        )
    except ValueError as exc:
        return json.dumps({"updated": False, "error": str(exc), "memory_id": memory_id})

    if not memory:
        return json.dumps({
            "updated": False,
            "error": "Memory not found",
            "memory_id": memory_id,
        })

    # Build changed_fields list
    changed = []
    if content is not None:
        changed.append("content")
    if tags is not None or add_tags is not None or remove_tags is not None:
        changed.append("tags")
    if entity_type is not None:
        changed.append("entity_type")
    if workspace is not None:
        changed.append("workspace")
    if ttl_hours is not None:
        changed.append("ttl")

    return json.dumps({
        "updated": True,
        "memory_id": memory.memory_id,
        "changed_fields": changed,
        "content": memory.content,
        "entity_type": memory.entity_type,
        "tags": memory.tags,
        "created_at": memory.created_at,
        "updated_at": memory.updated_at,
        "expires_at": memory.expires_at,
    })


@mcp.tool()
def vault_merge(
    target_id: int,
    source_id: int,
) -> str:
    """Merge two memories. Source is folded into target; source is deleted.

    Use this after vault_remember reports near_duplicates. Keeps the longer
    content, unions tags, keeps the more specific entity type, and tracks
    the merge in an audit trail.

    Args:
        target_id: Memory to keep (receives merged content)
        source_id: Memory to fold in (deleted after merge)
    """
    from .memories import merge_memories
    from .schema import DB_PATH, get_db

    conn = get_db(DB_PATH)
    memory = merge_memories(
        conn, target_id, source_id, embed_url=EMBED_URL,
    )

    if not memory:
        return json.dumps({
            "merged": False,
            "error": "One or both memory IDs not found",
            "target_id": target_id,
            "source_id": source_id,
        })

    return json.dumps({
        "merged": True,
        "memory_id": memory.memory_id,
        "content": memory.content,
        "entity_type": memory.entity_type,
        "tags": memory.tags,
        "merge_count": memory.merge_count,
        "merged_from": memory.merged_from,
    })


@mcp.tool()
def vault_memories(
    query: str = None,
    entity_type: str = None,
    workspace: str = None,
    limit: int = 20,
) -> str:
    """Search or list agent-written memories.

    Without a query, lists recent memories. With a query, searches by
    content using FTS5 + semantic similarity.

    Args:
        query: Optional search query (FTS5 + semantic). None = list recent.
        entity_type: Filter by type — "observation", "decision", "convention",
                     "learning", "context", or "bug". None = all.
        workspace: Optional vault subdirectory to scope results
        limit: Max results (default 20)
    """
    from .memories import search_memories
    from .schema import DB_PATH, get_db

    conn = get_db(DB_PATH)
    memories = search_memories(
        conn, query=query, entity_type=entity_type,
        workspace=workspace, limit=limit, embed_url=EMBED_URL,
    )

    output = []
    for m in memories:
        entry = {
            "memory_id": m.memory_id,
            "content": m.content,
            "entity_type": m.entity_type,
            "tags": m.tags,
            "created_at": m.created_at,
        }
        if m.source_agent:
            entry["source_agent"] = m.source_agent
        if m.workspace:
            entry["workspace"] = m.workspace
        if m.expires_at:
            entry["expires_at"] = m.expires_at
        if m.score > 0:
            entry["score"] = round(m.score, 4)
        output.append(entry)

    return json.dumps(output)


@mcp.tool()
def vault_harvest(sessions: int = 1, dry_run: bool = False, provider: str | None = None) -> str:
    """Extract insights from recent AI coding sessions and save as memories.

    Scans session transcripts for decisions, bugs, conventions, and learnings.
    Deduplicates against existing memories before saving.
    Supports multiple providers: claude-code, vscode-chat, codex-cli, aider.

    Args:
        sessions: Number of recent sessions to scan (default 1)
        dry_run: If True, show what would be saved without saving
        provider: Restrict to a single provider name, or omit for all
    """
    from .harvest import harvest_sessions

    result = harvest_sessions(
        n_sessions=sessions,
        dry_run=dry_run,
        embed_url=EMBED_URL,
        provider=provider,
    )
    return json.dumps(result, default=str)


@mcp.tool()
def vault_session_start(
    source_agent: str = None,
    workspace: str = None,
) -> str:
    """Start a new memory session to group related memories.

    Call at the beginning of a work session. All memories saved
    with the returned session_id will be grouped together and
    can be reviewed or summarized as a unit.

    Args:
        source_agent: Name of the agent starting the session
            (e.g. "claude-code", "cursor")
        workspace: Optional vault subdirectory scope
            (e.g. "work/acme-cloud")
    """
    from .memories import start_session
    from .schema import DB_PATH, get_db

    conn = get_db(DB_PATH)
    result = start_session(
        conn,
        source_agent=source_agent,
        workspace=workspace,
    )
    return json.dumps(result)


@mcp.tool()
def vault_session_end(
    session_id: int,
    summarize: bool = True,
    auto_harvest: bool = True,
) -> str:
    """End a memory session and optionally generate a summary.

    Call at the end of a work session. If summarize=True, uses
    the LLM to produce a 2-3 sentence summary of all memories
    recorded during the session. If auto_harvest=True, extracts
    insights from the most recent session transcript and saves
    them as memories.

    Args:
        session_id: The session ID returned by vault_session_start
        summarize: Generate LLM summary of session (default True)
        auto_harvest: Run harvest on the latest session (default True)
    """
    from .memories import end_session, summarize_session
    from .schema import DB_PATH, get_db

    _cache_clear()
    log.debug("LLM tool cache cleared on session end")

    conn = get_db(DB_PATH)
    summary = None
    if summarize:
        summary = summarize_session(conn, session_id)
    result = end_session(conn, session_id, summary=summary)

    if auto_harvest:
        try:
            from .harvest import harvest_sessions
            harvest_report = harvest_sessions(n_sessions=1)
            result["harvest"] = {
                "saved": len(harvest_report.get("saved", [])),
                "skipped": len(harvest_report.get("skipped", [])),
            }
        except Exception as e:
            result["harvest"] = {"error": str(e)}

    return json.dumps(result)


@mcp.tool()
def vault_capture(
    content: str,
    tags: list[str] = None,
) -> str:
    """Quick-capture a thought into the vault inbox.

    Zero-friction way to dump a thought without creating a full note.
    Creates a timestamped markdown file in the vault's inbox/ folder.

    Args:
        content: The thought or idea to capture
        tags: Optional tags for the capture (e.g. ["idea", "research"])
    """
    from .capture import capture_thought

    result = capture_thought(
        content=content,
        vault_root=str(VAULT_ROOT),
        tags=tags,
    )
    return json.dumps(result)


if __name__ == "__main__":
    mcp.run(transport="stdio")
