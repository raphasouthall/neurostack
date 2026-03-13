# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Session brief generator: vault DB + external memory sources + git log."""

import os
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path

from .config import get_config
from .schema import DB_PATH, get_db

# Optional external memory DB (e.g. engram) -- configurable via env var
EXTERNAL_MEMORY_DB = Path(os.environ.get(
    "NEUROSTACK_MEMORY_DB",
    str(Path.home() / ".engram" / "engram.db"),
))


def get_recent_vault_changes(conn: sqlite3.Connection, limit: int = 10) -> list[dict]:
    """Get recently modified notes with summaries."""
    rows = conn.execute(
        """
        SELECT n.path, n.title, s.summary_text, n.updated_at
        FROM notes n
        LEFT JOIN summaries s ON s.note_path = n.path
        ORDER BY n.updated_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_git_recent(vault_root: Path, limit: int = 5) -> list[str]:
    """Get recent git commits from the vault."""
    try:
        result = subprocess.run(
            ["git", "log", f"--max-count={limit}", "--oneline", "--no-decorate"],
            cwd=vault_root,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return [line.strip() for line in result.stdout.strip().split("\n") if line.strip()]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return []


def get_external_memories(limit: int = 5) -> list[dict]:
    """Get recent observations from external memory DB (e.g. engram)."""
    if not EXTERNAL_MEMORY_DB.exists():
        return []
    try:
        econn = sqlite3.connect(str(EXTERNAL_MEMORY_DB))
        econn.row_factory = sqlite3.Row
        rows = econn.execute(
            """
            SELECT topic_key, content, timestamp
            FROM memories
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        result = [dict(r) for r in rows]
        econn.close()
        return result
    except Exception:
        return []


def get_top_notes(conn: sqlite3.Connection, limit: int = 5) -> list[dict]:
    """Get top notes by PageRank."""
    rows = conn.execute(
        """
        SELECT gs.note_path, n.title, gs.pagerank, gs.in_degree
        FROM graph_stats gs
        JOIN notes n ON n.path = gs.note_path
        ORDER BY gs.pagerank DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def generate_brief(vault_root: Path = None) -> str:
    """Generate a compact session brief."""
    if vault_root is None:
        vault_root = get_config().vault_root
    conn = get_db(DB_PATH)

    now = datetime.now()
    hour = now.hour
    if 5 <= hour < 12:
        time_ctx = "morning"
    elif 12 <= hour < 17:
        time_ctx = "afternoon"
    elif 17 <= hour < 21:
        time_ctx = "evening"
    else:
        time_ctx = "night"

    parts = [f"## Session Brief ({now.strftime('%Y-%m-%d %H:%M')}, {time_ctx})\n"]

    # Vault stats
    note_count = conn.execute("SELECT COUNT(*) as c FROM notes").fetchone()["c"]
    chunk_count = conn.execute("SELECT COUNT(*) as c FROM chunks").fetchone()["c"]
    summary_count = conn.execute("SELECT COUNT(*) as c FROM summaries").fetchone()["c"]
    embedded_count = conn.execute(
        "SELECT COUNT(*) as c FROM chunks WHERE embedding IS NOT NULL"
    ).fetchone()["c"]
    parts.append(
        f"**Vault:** {note_count} notes, {chunk_count} chunks, "
        f"{embedded_count} embedded, {summary_count} summarized\n"
    )

    # Recent changes
    changes = get_recent_vault_changes(conn, limit=5)
    if changes:
        parts.append("**Recent changes:**")
        for c in changes:
            summary = c.get("summary_text", "") or ""
            if summary:
                parts.append(f"- `{c['path']}`: {summary[:100]}")
            else:
                parts.append(f"- `{c['path']}` ({c['title']})")
        parts.append("")

    # Git history
    commits = get_git_recent(vault_root, limit=3)
    if commits:
        parts.append("**Recent commits:**")
        for c in commits:
            parts.append(f"- {c}")
        parts.append("")

    # External memory observations
    memories = get_external_memories(limit=3)
    if memories:
        parts.append("**Recent memories:**")
        for e in memories:
            content = e.get("content", "")[:100]
            parts.append(f"- [{e.get('topic_key', '?')}] {content}")
        parts.append("")

    # Top connected notes
    top = get_top_notes(conn, limit=5)
    if top:
        parts.append("**Most connected notes:**")
        for t in top:
            parts.append(
                f"- `{t['note_path']}` (PR: {t['pagerank']:.4f}, {t['in_degree']} inlinks)"
            )
        parts.append("")

    return "\n".join(parts)
