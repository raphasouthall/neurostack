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

Issue #159 makes the other outcome countable. The reported outcome lands on
the firing itself (``trigger_log.followed``, ``outcome_at``), so
``trigger_stats`` can say how often a trigger was obeyed and not only how
often it was ignored.
"""

from __future__ import annotations

import fnmatch
import json
import sqlite3

TRIGGER_EVENTS = ("editing", "calling", "error")
_PREFIX = "when-"
IGNORED_ERROR_TYPE = "trigger_ignored"
RETIRE_AFTER_IGNORES = 3
PREVIEW_CHARS = 120


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


# Tool names that a session calls dozens of times; a trigger on one of these
# fires on nearly every call and only costs a retry (issue #167).
_GENERIC_TOOLS = frozenset({
    "bash", "read", "write", "edit", "glob", "grep", "eval", "task", "todo",
    "ask", "hub", "ls", "cat", "curl", "ssh", "git", "python", "python3", "uv",
    "az", "gh", "docker", "vault_search", "vault_remember", "vault_memories",
    "vault_read_file", "search_code", "web_search",
})
_GENERIC_ERRORS = frozenset({
    "error", "failed", "failure", "exception", "not found", "permission denied",
    "timeout", "timed out", "traceback (most recent call last):", "migration",
    "invalid", "denied", "refused",
})
_MIN_ERROR_CHARS = 8
# MCP servers whose tools a tag may name with the server glued on the front
# (``neurostack_vault_search``). Only these prefixes are stripped, so a tool
# genuinely called ``session_brief`` keeps its own first word.
_MCP_SERVERS = frozenset({
    "neurostack", "claude_context", "claude-context", "codebase_memory",
    "codebase-memory", "n8n",
})


def normalise_tool(value: str) -> str:
    """Bare tool name: lowercased, MCP server prefix dropped.

    The same tool reaches us as ``Bash``, ``mcp__neurostack__vault_search`` or
    ``neurostack_vault_search`` depending on the harness and on how the author
    typed the tag. Triggers compare the bare name so all three agree.
    """
    name = value.strip().lower()
    if name.startswith("mcp__"):
        name = name[len("mcp__"):]
        head, sep, rest = name.partition("__")
        name = rest if sep and rest else name
    head, sep, rest = name.partition("_")
    if sep and rest and head in _MCP_SERVERS:
        name = rest
    return name


def is_broad_trigger(tag: str) -> bool:
    """True when a well-formed trigger would match nearly everything.

    Broad calling triggers name a generic tool; broad error triggers are
    short, numeric, or a stock phrase; broad editing globs carry no literal
    path text. Malformed tags are not triggers and return False.
    """
    parsed = parse_trigger(tag)
    if parsed is None:
        return False
    event, value = parsed
    value = value.strip().lower()
    if event == "calling":
        return normalise_tool(value) in _GENERIC_TOOLS
    if event == "error":
        return (len(value) < _MIN_ERROR_CHARS or value.isdigit()
                or value.rstrip(":") in _GENERIC_ERRORS
                or value in _GENERIC_ERRORS)
    return not any(ch.isalnum() for ch in value)


def _match(event: str, pattern: str, value: str) -> bool:
    if event == "editing":
        # fnmatch's ``*`` spans ``/``, so ``**`` needs no special casing.
        if fnmatch.fnmatch(value, pattern):
            return True
        return not pattern.startswith("/") and fnmatch.fnmatch(value, "*/" + pattern)
    if event == "calling":
        pat = normalise_tool(pattern)
        if pat == normalise_tool(value):
            return True
        # A multi-word pattern names a command line, not a tool: the event
        # carries the command text, so match the prefix the author wrote.
        return " " in pat and pat in value.strip().lower()
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


def _pending_firing(
    conn: sqlite3.Connection,
    memory_id: int,
    session_hint: str | None,
) -> sqlite3.Row | None:
    """The firing an outcome report belongs to: the newest pending row.

    Same session first, because a second harness session can fire the same
    memory while the first has not reported yet. The fallback to the newest
    pending row of any session keeps clients that send no hint working.
    """
    sql = (
        "SELECT log_id, event, value FROM trigger_log"
        " WHERE memory_id = ? AND followed IS NULL"
    )
    order = " ORDER BY fired_at DESC, log_id DESC LIMIT 1"
    if session_hint:
        row = conn.execute(
            f"{sql} AND session_hint = ?{order}", (memory_id, session_hint)
        ).fetchone()
        if row is not None:
            return row
    return conn.execute(sql + order, (memory_id,)).fetchone()


def record_outcome(
    conn: sqlite3.Connection,
    memory_id: int,
    followed: bool,
    note: str | None = None,
    session_hint: str | None = None,
) -> dict:
    """Record whether the agent followed a fired trigger.

    Either way the newest pending ``trigger_log`` row for this memory (and
    session hint, when given) gets ``followed`` and ``outcome_at`` set, so the
    obey count is as measurable as the ignore count (issue #159).
    ``followed=False`` also inserts one ``prediction_errors`` row
    (``error_type='trigger_ignored'``, ``context`` = the trigger tag that
    fired, ``query`` = the caller's note). The reply carries the running
    ignore count and ``suggest: "retire"`` once it reaches
    ``RETIRE_AFTER_IGNORES``; the memory row itself is never touched.
    """
    row = conn.execute(
        "SELECT tags FROM memories WHERE memory_id = ?", (memory_id,)
    ).fetchone()
    if row is None:
        return {"error": f"Memory {memory_id} not found", "memory_id": memory_id}
    fired = _pending_firing(conn, memory_id, session_hint)
    if fired is not None:
        conn.execute(
            "UPDATE trigger_log SET followed = ?, outcome_at = datetime('now')"
            " WHERE log_id = ?",
            (1 if followed else 0, fired["log_id"]),
        )
    if not followed:
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


def _followed_rate(followed: int, ignored: int) -> float | None:
    """Share of settled firings that were followed, None while none settled."""
    settled = followed + ignored
    return followed / settled if settled else None


def trigger_stats(conn: sqlite3.Connection, days: int = 30) -> dict:
    """Fired-versus-followed counts over the last ``days`` (issue #159).

    Totals at the top level, one entry per memory that fired in the window
    under ``memories``. Pending firings count as neither followed nor ignored,
    so ``followed_rate`` is the share of the outcomes actually reported.
    """
    days = max(int(days), 1)
    rows = conn.execute(
        "SELECT l.memory_id AS memory_id, COUNT(*) AS fired,"
        # `followed = 1` is NULL for a pending row, and SUM of only NULLs is
        # NULL, so each branch has to fall through to a zero.
        " SUM(CASE WHEN l.followed = 1 THEN 1 ELSE 0 END) AS followed,"
        " SUM(CASE WHEN l.followed = 0 THEN 1 ELSE 0 END) AS ignored,"
        " SUM(CASE WHEN l.followed IS NULL THEN 1 ELSE 0 END) AS pending,"
        " m.content AS content, m.tags AS tags"
        " FROM trigger_log l LEFT JOIN memories m ON m.memory_id = l.memory_id"
        " WHERE l.fired_at >= datetime('now', ?)"
        " GROUP BY l.memory_id"
        " ORDER BY fired DESC, l.memory_id",
        (f"-{days} days",),
    ).fetchall()

    totals = {"fired": 0, "followed": 0, "ignored": 0, "pending": 0}
    memories = []
    for row in rows:
        tags = _trigger_tags(row["tags"])
        entry = {
            "memory_id": row["memory_id"],
            "trigger": tags[0] if tags else None,
            "content": (row["content"] or "")[:PREVIEW_CHARS],
            "fired": row["fired"],
            "followed": row["followed"],
            "ignored": row["ignored"],
            "pending": row["pending"],
            "followed_rate": _followed_rate(row["followed"], row["ignored"]),
        }
        for key in totals:
            totals[key] += entry[key]
        memories.append(entry)
    return {
        "days": days,
        **totals,
        "followed_rate": _followed_rate(totals["followed"], totals["ignored"]),
        "memories": memories,
    }
