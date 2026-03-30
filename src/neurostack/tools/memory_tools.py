# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Memory management tools — registered against the singleton registry."""

from __future__ import annotations

from .registry import ToolAnnotationHints as Hints, registry

# Annotation constants
_READ_ONLY = Hints(read_only=True, open_world=False)
_WRITE_ADDITIVE = Hints(read_only=False, destructive=False, idempotent=False, open_world=False)
_WRITE_IDEMPOTENT = Hints(read_only=False, destructive=False, idempotent=True, open_world=False)
_WRITE_DESTRUCTIVE = Hints(read_only=False, destructive=True, idempotent=True, open_world=False)


def _embed_url():
    from ..config import get_config
    return get_config().embed_url


@registry.tool(tags=["memory", "write"], annotations=_WRITE_ADDITIVE)
def vault_remember(
    content: str,
    tags: list[str] = None,
    entity_type: str = "observation",
    source_agent: str = None,
    workspace: str = None,
    ttl_hours: float = None,
    session_id: int = None,
) -> dict:
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
    from ..memories import save_memory
    from ..schema import DB_PATH, get_db

    conn = get_db(DB_PATH)
    memory = save_memory(
        conn, content=content, tags=tags, entity_type=entity_type,
        source_agent=source_agent, workspace=workspace,
        ttl_hours=ttl_hours, embed_url=_embed_url(),
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
    return result


@registry.tool(tags=["memory", "write"], annotations=_WRITE_DESTRUCTIVE)
def vault_forget(memory_id: int) -> dict:
    """Delete a specific memory by ID.

    Args:
        memory_id: The ID of the memory to delete (from vault_remember or vault_memories)
    """
    from ..memories import forget_memory
    from ..schema import DB_PATH, get_db

    conn = get_db(DB_PATH)
    deleted = forget_memory(conn, memory_id)
    return {"deleted": deleted, "memory_id": memory_id}


@registry.tool(tags=["memory", "write"], annotations=_WRITE_IDEMPOTENT)
def vault_update_memory(
    memory_id: int,
    content: str = None,
    tags: list[str] = None,
    add_tags: list[str] = None,
    remove_tags: list[str] = None,
    entity_type: str = None,
    workspace: str = None,
    ttl_hours: float = None,
) -> dict:
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
    from ..memories import update_memory
    from ..schema import DB_PATH, get_db

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
            embed_url=_embed_url(),
        )
    except ValueError as exc:
        return {"updated": False, "error": str(exc), "memory_id": memory_id}

    if not memory:
        return {"updated": False, "error": "Memory not found", "memory_id": memory_id}

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

    return {
        "updated": True,
        "memory_id": memory.memory_id,
        "changed_fields": changed,
        "content": memory.content,
        "entity_type": memory.entity_type,
        "tags": memory.tags,
        "created_at": memory.created_at,
        "updated_at": memory.updated_at,
        "expires_at": memory.expires_at,
    }


@registry.tool(tags=["memory", "write"], annotations=Hints(read_only=False, destructive=True, idempotent=False, open_world=False))
def vault_merge(
    target_id: int,
    source_id: int,
) -> dict:
    """Merge two memories. Source is folded into target; source is deleted.

    Use this after vault_remember reports near_duplicates. Keeps the longer
    content, unions tags, keeps the more specific entity type, and tracks
    the merge in an audit trail.

    Args:
        target_id: Memory to keep (receives merged content)
        source_id: Memory to fold in (deleted after merge)
    """
    from ..memories import merge_memories
    from ..schema import DB_PATH, get_db

    conn = get_db(DB_PATH)
    memory = merge_memories(
        conn, target_id, source_id, embed_url=_embed_url(),
    )

    if not memory:
        return {
            "merged": False,
            "error": "One or both memory IDs not found",
            "target_id": target_id,
            "source_id": source_id,
        }

    return {
        "merged": True,
        "memory_id": memory.memory_id,
        "content": memory.content,
        "entity_type": memory.entity_type,
        "tags": memory.tags,
        "merge_count": memory.merge_count,
        "merged_from": memory.merged_from,
    }


@registry.tool(tags=["memory", "read"], annotations=_READ_ONLY)
def vault_memories(
    query: str = None,
    entity_type: str = None,
    workspace: str = None,
    limit: int = 20,
) -> dict:
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
    from ..memories import search_memories
    from ..schema import DB_PATH, get_db

    conn = get_db(DB_PATH)
    memories = search_memories(
        conn, query=query, entity_type=entity_type,
        workspace=workspace, limit=limit, embed_url=_embed_url(),
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

    return {"memories": output}


@registry.tool(tags=["memory", "write"], annotations=_WRITE_ADDITIVE)
def vault_capture(
    content: str,
    tags: list[str] = None,
) -> dict:
    """Quick-capture a thought into the vault inbox.

    Zero-friction way to dump a thought without creating a full note.
    Creates a timestamped markdown file in the vault's inbox/ folder.

    Args:
        content: The thought or idea to capture
        tags: Optional tags for the capture (e.g. ["idea", "research"])
    """
    from ..capture import capture_thought
    from ..config import get_config

    vault_root = get_config().vault_root
    return capture_thought(
        content=content,
        vault_root=str(vault_root),
        tags=tags,
    )
