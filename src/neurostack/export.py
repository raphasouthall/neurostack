# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Export index data as JSON-serialisable structures (issue #4)."""

import sqlite3


def export_notes(
    conn: sqlite3.Connection, include_triples: bool = False
) -> list[dict]:
    """Export all indexed notes with title, PageRank, and summary.

    Args:
        conn: Database connection
        include_triples: Attach each note's triples as a ``triples`` key

    Returns:
        List of note dicts sorted by path. ``summary`` is None when no
        summary has been computed; ``pagerank`` is 0.0 when the graph
        stats have not been built.
    """
    rows = conn.execute(
        """
        SELECT n.path, n.title, g.pagerank, s.summary_text
        FROM notes n
        LEFT JOIN graph_stats g ON g.note_path = n.path
        LEFT JOIN summaries s ON s.note_path = n.path
        ORDER BY n.path
        """
    ).fetchall()

    notes = [
        {
            "path": row["path"],
            "title": row["title"],
            "pagerank": row["pagerank"] if row["pagerank"] is not None else 0.0,
            "summary": row["summary_text"],
        }
        for row in rows
    ]

    if include_triples:
        triples_by_note: dict[str, list[dict]] = {}
        for t in conn.execute(
            "SELECT note_path, subject, predicate, object"
            " FROM triples ORDER BY triple_id"
        ):
            triples_by_note.setdefault(t["note_path"], []).append(
                {
                    "subject": t["subject"],
                    "predicate": t["predicate"],
                    "object": t["object"],
                }
            )
        for note in notes:
            note["triples"] = triples_by_note.get(note["path"], [])

    return notes
