#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""NeuroStack MCP server — tools for pre-computed vault context."""

import json

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("neurostack")

from .config import get_config

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

    Use "triples" for quick factual lookups, "summaries" for overview,
    "full" when you need actual content, "auto" to let the system decide.
    """
    if depth in ("triples", "summaries", "auto"):
        from .search import tiered_search

        result = tiered_search(
            query, top_k=top_k, depth=depth, mode=mode,
            embed_url=EMBED_URL, context=context, rerank=True,
        )
        return json.dumps(result, indent=2)

    # Default: full depth (original behavior)
    from .search import hybrid_search

    results = hybrid_search(
        query, top_k=top_k, mode=mode,
        embed_url=EMBED_URL, context=context, rerank=True,
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

    return json.dumps(output, indent=2)


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
    return json.dumps(result, indent=2)


@mcp.tool()
def vault_graph(note: str, depth: int = 1) -> str:
    """Get wiki-link neighborhood for a note with summaries and PageRank.

    One call replaces manually following links across files.

    Args:
        note: Note path (e.g. "research/predictive-coding.md")
        depth: How many link-hops to traverse (default 1)
    """
    from .graph import get_neighborhood

    result = get_neighborhood(note, depth=depth)
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
    return json.dumps(output, indent=2)


@mcp.tool()
def session_brief() -> str:
    """Get a compact ~500 token session brief.

    Includes: recent vault changes with summaries, git commits,
    recent memories, top connected notes, time-of-day context.
    """
    from .brief import generate_brief

    return generate_brief(vault_root=VAULT_ROOT)


@mcp.tool()
def vault_triples(query: str, top_k: int = 10, mode: str = "hybrid") -> str:
    """Search knowledge graph triples for structured facts.

    Returns compact Subject-Predicate-Object facts (~10-20 tokens each).
    Use this for quick factual lookups instead of reading full notes.

    Args:
        query: Natural language search query
        top_k: Number of triples to return (default 10)
        mode: Search mode - "hybrid" (default), "semantic", or "keyword"
    """
    from .search import search_triples

    results = search_triples(query, top_k=top_k, mode=mode, embed_url=EMBED_URL)

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

    return json.dumps(output, indent=2)


@mcp.tool()
def vault_communities(
    query: str,
    top_k: int = 6,
    level: int = 0,
    map_reduce: bool = True,
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
    """
    from .community_search import global_query

    result = global_query(
        query=query,
        top_k=top_k,
        level=level,
        use_map_reduce=map_reduce,
        embed_url=EMBED_URL,
    )
    return json.dumps(result, indent=2)


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
    }
    return json.dumps(result, indent=2)


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
    """
    from .schema import DB_PATH, get_db

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

    total_unresolved = conn.execute(
        "SELECT COUNT(DISTINCT note_path) FROM prediction_errors WHERE resolved_at IS NULL"
    ).fetchone()[0]

    return json.dumps({
        "total_flagged_notes": total_unresolved,
        "showing": len(results),
        "errors": results,
    }, indent=2)


if __name__ == "__main__":
    mcp.run(transport="stdio")
