# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Vault diff / change feed: what changed since a baseline or a date (issue #11).

The notes table carries no created_at and deletions are hard deletes, so
additions and deletions can only be recovered by comparing the current index
against a stored baseline. ``diff_snapshots`` holds named baselines of
``{path -> content_hash}``: ``save_checkpoint`` records one, ``compute_diff``
reports the delta. A date mode (``since``) needs no baseline but can only
surface added-or-modified notes via ``updated_at``, not deletions.
"""

from __future__ import annotations

import sqlite3

DEFAULT_BASELINE = "default"


def _titles(conn: sqlite3.Connection, paths) -> dict[str, str]:
    """Map note paths to titles (falling back to the path) in one query."""
    paths = list(paths)
    if not paths:
        return {}
    placeholders = ",".join("?" * len(paths))
    rows = conn.execute(
        f"SELECT path, title FROM notes WHERE path IN ({placeholders})", paths
    ).fetchall()
    return {r["path"]: (r["title"] or r["path"]) for r in rows}


def compute_diff(
    conn: sqlite3.Connection, since: str | None = None, baseline: str = DEFAULT_BASELINE
) -> dict:
    """Report vault changes. Read-only — never writes a baseline.

    Date mode (``since`` given): notes with ``updated_at > since`` (additions and
    modifications combined; deletions aren't detectable this way). Baseline mode
    (default): added / modified / deleted vs the named stored baseline.
    """
    if since:
        rows = conn.execute(
            "SELECT path, title, updated_at FROM notes"
            " WHERE updated_at > ? ORDER BY updated_at DESC",
            (since,),
        ).fetchall()
        changed = [
            {
                "path": r["path"],
                "title": r["title"] or r["path"],
                "updated_at": r["updated_at"],
            }
            for r in rows
        ]
        return {
            "mode": "since_date",
            "since": since,
            "changed": changed,
            "changed_count": len(changed),
            "note": "Date mode combines additions and modifications (updated_at);"
                    " deletions need baseline mode.",
        }

    current = {
        r["path"]: r["content_hash"]
        for r in conn.execute("SELECT path, content_hash FROM notes")
    }
    snap_rows = conn.execute(
        "SELECT path, content_hash, saved_at FROM diff_snapshots WHERE baseline = ?",
        (baseline,),
    ).fetchall()
    snapshot = {r["path"]: r["content_hash"] for r in snap_rows}

    added = sorted(p for p in current if p not in snapshot)
    deleted = sorted(p for p in snapshot if p not in current)
    modified = sorted(
        p for p in current if p in snapshot and current[p] != snapshot[p]
    )
    titles = _titles(conn, added + modified)

    return {
        "mode": "baseline",
        "baseline": baseline,
        "baseline_saved_at": snap_rows[0]["saved_at"] if snap_rows else None,
        "has_baseline": bool(snap_rows),
        "added": [{"path": p, "title": titles.get(p, p)} for p in added],
        "modified": [{"path": p, "title": titles.get(p, p)} for p in modified],
        "deleted": [{"path": p} for p in deleted],
        "added_count": len(added),
        "modified_count": len(modified),
        "deleted_count": len(deleted),
    }


def save_checkpoint(
    conn: sqlite3.Connection, baseline: str = DEFAULT_BASELINE
) -> dict:
    """Save the current index state as the named baseline.

    Overwrites any prior snapshot for that name. A later ``compute_diff`` against
    this baseline reports what changed since. Returns the note count and the
    save timestamp.
    """
    current = conn.execute("SELECT path, content_hash FROM notes").fetchall()
    now = conn.execute("SELECT datetime('now') AS t").fetchone()["t"]
    conn.execute("DELETE FROM diff_snapshots WHERE baseline = ?", (baseline,))
    conn.executemany(
        "INSERT INTO diff_snapshots (baseline, path, content_hash, saved_at)"
        " VALUES (?, ?, ?, ?)",
        [(baseline, r["path"], r["content_hash"], now) for r in current],
    )
    conn.commit()
    return {"baseline": baseline, "saved_at": now, "notes": len(current)}
