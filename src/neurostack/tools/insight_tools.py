# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Context and insight tools — registered against the singleton registry."""

from __future__ import annotations

from .registry import ToolAnnotationHints as Hints, registry

_READ_ONLY = Hints(read_only=True, open_world=False)


def _cfg():
    from ..config import get_config
    cfg = get_config()
    return cfg.vault_root, cfg.embed_url


@registry.tool(tags=["context", "retrieval"], annotations=_READ_ONLY)
def session_brief(workspace: str = None) -> dict:
    """Get a compact ~500 token session brief.

    Includes: recent vault changes with summaries, git commits,
    recent memories, top connected notes, time-of-day context.

    Args:
        workspace: Optional vault subdirectory prefix to restrict
            results (e.g. "work/acme-cloud")
    """
    import json

    from ..brief import generate_brief

    vault_root, _ = _cfg()
    # generate_brief returns a JSON string — parse to dict
    raw = generate_brief(vault_root=vault_root, workspace=workspace)
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {"brief": raw}


@registry.tool(tags=["context", "retrieval"], annotations=_READ_ONLY)
def vault_context(
    task: str,
    token_budget: int = 2000,
    workspace: str = None,
    include_memories: bool = True,
    include_triples: bool = True,
) -> dict:
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
    from ..context import build_vault_context
    from ..schema import DB_PATH, get_db

    _, embed_url = _cfg()
    conn = get_db(DB_PATH)
    return build_vault_context(
        conn, task=task, token_budget=token_budget,
        workspace=workspace, include_memories=include_memories,
        include_triples=include_triples, embed_url=embed_url,
    )
