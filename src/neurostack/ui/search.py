# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Search endpoints for the dashboard's Search page (issue #282).

`dashboard.py` only reads the database. Search has to embed the query and,
with rerank on, ask the judge model, so it lives here and runs the same
`hybrid_search` / `tiered_search` / `search_memories` code the MCP tools do.
Note searches pass `record=False`: browsing the dashboard must not prime notes
or feed the hotness signal. A memory search still archives expired memories,
as every memory search does.
"""

from __future__ import annotations

from typing import Any

MODES = ("hybrid", "semantic", "keyword")
DEPTHS = ("auto", "triples", "summaries", "full")
MAX_TOP_K = 50
MAX_MEMORIES = 200


def notes(cfg, query: str, *, top_k: int = 10, mode: str = "hybrid", depth: str = "full",
          workspace: str | None = None, context: str | None = None, rerank: bool = False,
          reference_only: bool = False, max_tokens: int | None = None) -> dict[str, Any]:
    """One note search with every `vault_search` option. Raises ValueError on a bad one."""
    from ..budget import trim_to_budget
    from ..search import hybrid_search, tiered_search

    if mode not in MODES:
        raise ValueError(f"mode must be one of {', '.join(MODES)}")
    if depth not in DEPTHS:
        raise ValueError(f"depth must be one of {', '.join(DEPTHS)}")
    if rerank and not (reference_only or depth == "full"):
        raise ValueError("rerank needs whole notes: use depth=full or reference_only")
    top_k = max(1, min(top_k, MAX_TOP_K))

    if reference_only or depth == "full":
        results = hybrid_search(query, top_k=top_k, mode=mode, embed_url=cfg.embed_url,
                                db_path=cfg.db_path, context=context, workspace=workspace,
                                record=False)
        if rerank:
            from ..rerank import rerank_results

            results = rerank_results(query, results)
        rows = [{"path": r.note_path, "title": r.title, "section": r.heading_path,
                 "score": round(r.score, 4), "snippet": r.snippet,
                 "summary": None if reference_only else r.summary}
                for r in results]
        kept, _, truncated = trim_to_budget(rows, max_tokens)
        return {"depth_used": "reference" if reference_only else "full", "results": kept,
                "reranked": rerank, "truncated": truncated}

    out = tiered_search(query, top_k=top_k, depth=depth, mode=mode, embed_url=cfg.embed_url,
                        db_path=cfg.db_path, context=context, workspace=workspace,
                        record=False)
    truncated = False
    if max_tokens is not None:
        remaining = max_tokens
        for key in ("triples", "summaries", "chunks"):
            kept, used, cut = trim_to_budget(out.get(key) or [], remaining)
            out[key] = kept
            remaining = max(0, remaining - used)
            truncated = truncated or cut
    return {**out, "reranked": False, "truncated": truncated}


def memories(cfg, query: str | None, *, entity_type: str | None = None,
             workspace: str | None = None, limit: int = 20) -> dict[str, Any]:
    """One memory search with every `vault_memories` option; no query lists the newest."""
    from ..memories import search_memories
    from ..schema import get_db

    conn = get_db(cfg.db_path)
    try:
        found = search_memories(conn, query=query or None, entity_type=entity_type or None,
                                workspace=workspace or None,
                                limit=max(1, min(limit, MAX_MEMORIES)),
                                embed_url=cfg.embed_url)
    finally:
        conn.close()
    return {"items": [{
        "id": m.memory_id, "content": m.content, "entity_type": m.entity_type,
        "tags": m.tags or [], "workspace": m.workspace, "source_agent": m.source_agent,
        "created_at": m.created_at, "expires_at": m.expires_at,
        "score": round(m.score, 4) if m.score else None,
    } for m in found]}


def workspaces(conn) -> list[dict[str, Any]]:
    """Every folder that holds notes, up to three levels deep, with its note count."""
    counts: dict[str, int] = {}
    for (path,) in conn.execute("SELECT path FROM notes"):
        parts = path.split("/")[:-1]
        for depth in range(1, min(len(parts), 3) + 1):
            key = "/".join(parts[:depth])
            counts[key] = counts.get(key, 0) + 1
    return [{"path": k, "notes": v} for k, v in sorted(counts.items())]
