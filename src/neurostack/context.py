# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Context recovery: assemble task-scoped context for session recovery."""

from __future__ import annotations

import logging
import sqlite3

from .budget import estimate_tokens

log = logging.getLogger("neurostack")


def build_vault_context(
    conn: sqlite3.Connection,
    task: str,
    token_budget: int = 2000,
    workspace: str | None = None,
    include_memories: bool = True,
    include_triples: bool = True,
    embed_url: str | None = None,
    context: str | None = None,
) -> dict:
    """Assemble a context window for a specific task.

    Combines memories, triples, summaries, and session history
    relevant to the given task description. Respects token budget.

    ``context`` applies the same soft attention boost as vault_search
    (1.4x/1.2x convergence, re-ranking not filtering) to the memories,
    triples, and summaries sub-retrievals (issue #94).

    Returns structured dict with sections and approximate token count.
    """
    from .config import get_config

    cfg = get_config()
    url = embed_url or cfg.embed_url

    sections: dict = {}
    tokens_used = 0
    # Token cost is estimated via budget.estimate_tokens (~4 chars/token) so this
    # allocator and vault_search agree on how big a result is (issue #62).

    # 1. Relevant memories (budget: ~40% of total)
    if include_memories:
        mem_budget = int(token_budget * 0.4)
        try:
            from .memories import search_memories

            memories = search_memories(
                conn, query=task, workspace=workspace,
                limit=10, embed_url=url, context=context,
            )
            # Memory drift detection (issue #38), non-blocking.
            from .memory_drift import check_memory_drift
            check_memory_drift(conn, memories)
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
                entry_tokens = estimate_tokens(entry)
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
                embed_url=url, workspace=workspace, context=context,
                record=False,
            )
            triple_entries = []
            for t in triples:
                entry = {
                    "s": t.subject,
                    "p": t.predicate,
                    "o": t.object,
                    "note": t.note_path,
                }
                entry_tokens = estimate_tokens(entry)
                if tokens_used + entry_tokens > token_budget:
                    break
                triple_entries.append(entry)
                tokens_used += entry_tokens
                if sum(estimate_tokens(e) for e in triple_entries) >= triple_budget:
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
            embed_url=url, workspace=workspace, context=context,
            record=False,
        )
        summary_entries = []
        for r in results:
            entry = {
                "path": r.note_path,
                "title": r.title,
                "summary": r.summary or r.snippet[:200],
                "score": round(r.score, 4),
            }
            entry_tokens = estimate_tokens(entry)
            if tokens_used + entry_tokens > token_budget:
                break
            summary_entries.append(entry)
            tokens_used += entry_tokens
            if sum(estimate_tokens(e) for e in summary_entries) >= summary_budget:
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
            entry_tokens = estimate_tokens(session_entries)
            if tokens_used + entry_tokens <= token_budget:
                sections["session_history"] = session_entries
                tokens_used += entry_tokens
    except Exception as exc:
        log.debug("Could not fetch session history: %s", exc)

    # Two-tier activation signal (issue #95): every note path this call RETURNS
    # is a 'primed' event — the auto-RAG hooks inject it, the model may never
    # act on it. Sub-retrievals above ran with record=False so nothing here was
    # double-logged as a strong 'used' event; the deliberate tier stays
    # vault_record_usage / reads. With feedback enabled, the surfacing is also
    # search-logged so a later deliberate use attributes back to this task
    # (tag-and-capture through the #66 loop).
    primed_paths = [t["note"] for t in sections.get("triples", [])]
    primed_paths += [s["path"] for s in sections.get("summaries", [])]
    if primed_paths:
        from .search import _record_note_usage

        _record_note_usage(conn, primed_paths, tier="primed")
        if cfg.feedback_enabled:
            from .feedback import log_search

            log_search(conn, task, list(dict.fromkeys(primed_paths)),
                       cfg.feedback_log_retention)

    return {
        "task": task,
        "tokens_used": tokens_used,
        "workspace": workspace,
        "context": sections,
    }
