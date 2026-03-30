# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Session lifecycle and harvest tools — registered against the singleton registry."""

from __future__ import annotations

import logging

from .registry import ToolAnnotationHints as Hints, registry

# Annotation constants
_WRITE_ADDITIVE = Hints(read_only=False, destructive=False, idempotent=False, open_world=False)
_WRITE_IDEMPOTENT = Hints(read_only=False, destructive=False, idempotent=True, open_world=False)

log = logging.getLogger("neurostack.tools.session")


def _embed_url():
    from ..config import get_config
    return get_config().embed_url


# In-memory TTL cache shared with insight_tools (for session_end cache clear)
_tool_cache: dict[str, tuple[float, str]] = {}
_CACHE_TTL = 300.0


def _cache_clear() -> None:
    """Clear all cached tool results."""
    _tool_cache.clear()


@registry.tool(tags=["session"], annotations=_WRITE_ADDITIVE)
def vault_session_start(
    source_agent: str = None,
    workspace: str = None,
) -> dict:
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
    from ..memories import start_session
    from ..schema import DB_PATH, get_db

    conn = get_db(DB_PATH)
    return start_session(
        conn,
        source_agent=source_agent,
        workspace=workspace,
    )


@registry.tool(tags=["session"], annotations=_WRITE_IDEMPOTENT)
def vault_session_end(
    session_id: int,
    summarize: bool = True,
    auto_harvest: bool = True,
) -> dict:
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
    from ..memories import end_session, summarize_session
    from ..schema import DB_PATH, get_db

    _cache_clear()
    log.debug("LLM tool cache cleared on session end")

    conn = get_db(DB_PATH)
    summary = None
    if summarize:
        summary = summarize_session(conn, session_id)
    result = end_session(conn, session_id, summary=summary)

    if auto_harvest:
        try:
            from ..harvest import harvest_sessions
            harvest_report = harvest_sessions(n_sessions=1)
            result["harvest"] = {
                "saved": len(harvest_report.get("saved", [])),
                "skipped": len(harvest_report.get("skipped", [])),
            }
        except Exception as e:
            result["harvest"] = {"error": str(e)}

    return result


@registry.tool(tags=["session", "memory"], annotations=_WRITE_ADDITIVE)
def vault_harvest(sessions: int = 1, dry_run: bool = False, provider: str | None = None) -> dict:
    """Extract insights from recent AI coding sessions and save as memories.

    Scans session transcripts for decisions, bugs, conventions, and learnings.
    Deduplicates against existing memories before saving.
    Supports multiple providers: claude-code, vscode-chat, codex-cli, aider.

    Args:
        sessions: Number of recent sessions to scan (default 1)
        dry_run: If True, show what would be saved without saving
        provider: Restrict to a single provider name, or omit for all
    """
    from ..harvest import harvest_sessions

    return harvest_sessions(
        n_sessions=sessions,
        dry_run=dry_run,
        embed_url=_embed_url(),
        provider=provider,
    )
