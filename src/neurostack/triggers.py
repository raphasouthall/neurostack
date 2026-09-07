# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Trigger tags (issue #131): memories that surface when they apply.

A trigger is an ordinary tag with one of three prefixes. It says WHEN a memory
should be shown, not what it is about:

- ``when-editing:<glob>``     matched against the path of an Edit/Write
- ``when-calling:<tool>``     matched against a tool name (case-insensitive)
- ``when-error:<substring>``  matched against tool error text (case-insensitive)

No schema change for the tags themselves: triggers live in ``memories.tags``.
Matching is a pure read. Per-session "fire once" suppression belongs to the
client (the harness hook), because the server has no notion of a harness
session per tool call.

Issue #136 adds the feedback half. Every hit is logged to ``trigger_log``, and
the client reports whether the agent followed the memory. An ignored trigger
becomes a ``prediction_errors`` row of type ``trigger_ignored`` that the
promotion queue's drift bucket surfaces; after ``RETIRE_AFTER_IGNORES`` the
queue suggests retiring the trigger. Nothing is deleted or decayed here.
"""

from __future__ import annotations

import fnmatch
import json
import sqlite3

TRIGGER_EVENTS = ("editing", "calling", "error")
_PREFIX = "when-"
IGNORED_ERROR_TYPE = "trigger_ignored"
RETIRE_AFTER_IGNORES = 3


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


def record_fired(
    conn: sqlite3.Connection,
    hits: list[dict],
    event: str,
    value: str,
    session_hint: str | None = None,
) -> int:
    """Log one ``trigger_log`` row per hit. Returns the row count written."""
    if not hits:
        return 0
    conn.executemany(
        "INSERT INTO trigger_log (memory_id, event, value, session_hint)"
        " VALUES (?, ?, ?, ?)",
        [(h["memory_id"], event, value, session_hint) for h in hits],
    )
    conn.commit()
    return len(hits)


def _trigger_tags(tags_raw) -> list[str]:
    try:
        tags = json.loads(tags_raw) if isinstance(tags_raw, str) else (tags_raw or [])
    except (json.JSONDecodeError, TypeError):
        return []
    return [t for t in tags if parse_trigger(t)]


def ignored_count(conn: sqlite3.Connection, memory_id: int) -> int:
    """Unresolved ``trigger_ignored`` rows for one memory."""
    return conn.execute(
        "SELECT COUNT(*) FROM prediction_errors"
        " WHERE memory_id = ? AND error_type = ? AND resolved_at IS NULL",
        (memory_id, IGNORED_ERROR_TYPE),
    ).fetchone()[0]


def record_outcome(
    conn: sqlite3.Connection,
    memory_id: int,
    followed: bool,
    note: str | None = None,
) -> dict:
    """Record whether the agent followed a fired trigger.

    ``followed=True`` writes nothing. ``followed=False`` inserts one
    ``prediction_errors`` row (``error_type='trigger_ignored'``, ``context`` =
    the trigger tag that fired, ``query`` = the caller's note). The reply
    carries the running ignore count and ``suggest: "retire"`` once it reaches
    ``RETIRE_AFTER_IGNORES``; the memory row itself is never touched.
    """
    row = conn.execute(
        "SELECT tags FROM memories WHERE memory_id = ?", (memory_id,)
    ).fetchone()
    if row is None:
        return {"error": f"Memory {memory_id} not found", "memory_id": memory_id}
    if not followed:
        fired = conn.execute(
            "SELECT event, value FROM trigger_log WHERE memory_id = ?"
            " ORDER BY fired_at DESC, log_id DESC LIMIT 1",
            (memory_id,),
        ).fetchone()
        tags = _trigger_tags(row["tags"])
        if fired is not None:
            # Prefer the tag that actually matched the logged firing.
            matched = [
                t for t in tags
                if (p := parse_trigger(t)) and p[0] == fired["event"]
                and _match(p[0], p[1], fired["value"])
            ]
            tags = matched or tags
        context = tags[0] if tags else None
        conn.execute(
            "INSERT INTO prediction_errors"
            " (note_path, memory_id, query, cosine_distance, error_type, context)"
            " VALUES ('', ?, ?, 0.0, ?, ?)",
            (memory_id, note or "", IGNORED_ERROR_TYPE, context),
        )
        conn.commit()
    count = ignored_count(conn, memory_id)
    out = {"memory_id": memory_id, "followed": followed, "ignored_count": count}
    if count >= RETIRE_AFTER_IGNORES:
        out["suggest"] = "retire"
    return out
