# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Context recovery: assemble task-scoped context for session recovery."""

from __future__ import annotations

import json
import logging
import sqlite3

log = logging.getLogger("neurostack")


def build_vault_context(
    conn: sqlite3.Connection,
    task: str,
    token_budget: int = 2000,
    workspace: str | None = None,
    include_memories: bool = True,
    include_triples: bool = True,
    embed_url: str | None = None,
) -> dict:
    """Assemble a context window for a specific task.

    Combines memories, triples, summaries, and session history
    relevant to the given task description. Respects token budget.

    Returns structured dict with sections and approximate token count.
    """
    from .config import get_config

    cfg = get_config()
    url = embed_url or cfg.embed_url

    sections: dict = {}
    tokens_used = 0
    # Rough estimate: 1 token ~ 4 chars

    # 1. Relevant memories (budget: ~40% of total)
    if include_memories:
        mem_budget = int(token_budget * 0.4)
        try:
            from .memories import search_memories

            memories = search_memories(
                conn, query=task, workspace=workspace,
                limit=10, embed_url=url,
            )
            mem_entries = []
            for m in memories:
                if m.score and m.score < 0.3:
                    continue
                entry = {
                    "memory_id": m.memory_id,
                    "content": m.content,
                    "entity_type": m.entity_type,
                    "tags": m.tags,
                    "created_at": m.created_at,
                }
                entry_tokens = len(json.dumps(entry)) // 4
                if tokens_used + entry_tokens > token_budget:
                    break
                mem_entries.append(entry)
                tokens_used += entry_tokens
                if tokens_used >= mem_budget:
                    break
            if mem_entries:
                sections["memories"] = mem_entries
        except Exception as exc:
            log.debug("Could not fetch memories for context: %s", exc)

    # 2. Relevant triples (budget: ~20% of total)
    if include_triples:
        triple_budget = int(token_budget * 0.2)
        try:
            from .search import search_triples

            triples = search_triples(
                task, top_k=15, mode="hybrid",
                embed_url=url, workspace=workspace,
            )
            triple_entries = []
            for t in triples:
                entry = {
                    "s": t.subject,
                    "p": t.predicate,
                    "o": t.object,
                    "note": t.note_path,
                }
                entry_tokens = len(json.dumps(entry)) // 4
                if tokens_used + entry_tokens > token_budget:
                    break
                triple_entries.append(entry)
                tokens_used += entry_tokens
                if sum(len(json.dumps(e)) // 4 for e in triple_entries) >= triple_budget:
                    break
            if triple_entries:
                sections["triples"] = triple_entries
        except Exception as exc:
            log.debug("Could not fetch triples for context: %s", exc)

    # 3. Relevant note summaries (budget: ~30% of total)
    summary_budget = int(token_budget * 0.3)
    try:
        from .search import hybrid_search

        results = hybrid_search(
            task, top_k=5, mode="hybrid",
            embed_url=url, workspace=workspace,
        )
        summary_entries = []
        for r in results:
            entry = {
                "path": r.note_path,
                "title": r.title,
                "summary": r.summary or r.snippet[:200],
                "score": round(r.score, 4),
            }
            entry_tokens = len(json.dumps(entry)) // 4
            if tokens_used + entry_tokens > token_budget:
                break
            summary_entries.append(entry)
            tokens_used += entry_tokens
            if sum(len(json.dumps(e)) // 4 for e in summary_entries) >= summary_budget:
                break
        if summary_entries:
            sections["summaries"] = summary_entries
    except Exception as exc:
        log.debug("Could not fetch summaries for context: %s", exc)

    # 4. Recent session history (budget: ~10% of total)
    try:
        from .memories import list_sessions

        sessions = list_sessions(conn, limit=3, workspace=workspace)
        if sessions:
            session_entries = []
            for s in sessions:
                entry = {
                    "session_id": s["session_id"],
                    "started_at": s["started_at"],
                    "summary": s.get("summary") or f"{s['memory_count']} memories",
                    "memory_count": s["memory_count"],
                }
                session_entries.append(entry)
            entry_tokens = len(json.dumps(session_entries)) // 4
            if tokens_used + entry_tokens <= token_budget:
                sections["session_history"] = session_entries
                tokens_used += entry_tokens
    except Exception as exc:
        log.debug("Could not fetch session history: %s", exc)

    return {
        "task": task,
        "tokens_used": tokens_used,
        "workspace": workspace,
        "context": sections,
    }
