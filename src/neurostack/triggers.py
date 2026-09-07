# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Trigger tags (issue #131): memories that surface when they apply.

A trigger is an ordinary tag with one of three prefixes. It says WHEN a memory
should be shown, not what it is about:

- ``when-editing:<glob>``     matched against the path of an Edit/Write
- ``when-calling:<tool>``     matched against a tool name (case-insensitive)
- ``when-error:<substring>``  matched against tool error text (case-insensitive)

No schema change: triggers live in ``memories.tags``. Matching is a pure read.
Per-session "fire once" suppression belongs to the client (the harness hook),
because the server has no notion of a harness session per tool call.
"""

from __future__ import annotations

import fnmatch
import json
import sqlite3

TRIGGER_EVENTS = ("editing", "calling", "error")
_PREFIX = "when-"


def parse_trigger(tag: str) -> tuple[str, str] | None:
    """Return ``(event, value)`` for a well-formed trigger tag, else None.

    Malformed prefixes (``when-writing:x``, ``when-editing:``) are plain tags.
    """
    if not isinstance(tag, str) or not tag.startswith(_PREFIX):
        return None
    head, sep, value = tag[len(_PREFIX):].partition(":")
    if not sep or head not in TRIGGER_EVENTS or not value:
        return None
    return head, value


def _match(event: str, pattern: str, value: str) -> bool:
    if event == "editing":
        # fnmatch's ``*`` spans ``/``, so ``**`` needs no special casing.
        if fnmatch.fnmatch(value, pattern):
            return True
        return not pattern.startswith("/") and fnmatch.fnmatch(value, "*/" + pattern)
    if event == "calling":
        return value.lower() == pattern.lower()
    if event == "error":
        return pattern.lower() in value.lower()
    return False


def match_triggers(
    conn: sqlite3.Connection,
    event: str,
    value: str,
    workspace: str | None = None,
    limit: int = 10,
) -> list[dict]:
    """Memories whose ``when-<event>:`` trigger matches ``value``.

    Newest first. Expired memories are excluded; untagged memories are never
    touched (the SQL prefilter only sees rows containing the prefix).
    """
    if event not in TRIGGER_EVENTS or not value:
        return []
    sql = (
        "SELECT memory_id, content, tags, entity_type, workspace, created_at"
        " FROM memories"
        " WHERE COALESCE(tags, '') LIKE ?"
        " AND (expires_at IS NULL OR expires_at > datetime('now'))"
    )
    params: list = [f"%{_PREFIX}{event}:%"]
    if workspace:
        ws = workspace.strip("/")
        sql += " AND (workspace = ? OR workspace LIKE ? || '/%')"
        params.extend([ws, ws])
    sql += " ORDER BY created_at DESC"

    out: list[dict] = []
    for row in conn.execute(sql, params):
        try:
            tags = json.loads(row["tags"]) or []
        except (json.JSONDecodeError, TypeError):
            continue
        hit = None
        for tag in tags:
            parsed = parse_trigger(tag)
            if parsed and parsed[0] == event and _match(event, parsed[1], value):
                hit = tag
                break
        if hit is None:
            continue
        out.append({
            "memory_id": row["memory_id"],
            "content": row["content"],
            "entity_type": row["entity_type"],
            "workspace": row["workspace"],
            "trigger": hit,
            "created_at": row["created_at"],
        })
        if len(out) >= limit:
            break
    return out
