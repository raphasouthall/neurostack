# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Wiki-link graph: parsing, PageRank, neighborhood retrieval."""

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .schema import get_db


@dataclass
class GraphNode:
    path: str
    title: str
    summary: str
    pagerank: float
    in_degree: int
    out_degree: int


@dataclass
class GraphResult:
    center: GraphNode
    neighbors: list[GraphNode]


def resolve_wiki_link(link_target: str, all_paths: list[str]) -> str | None:
    """Resolve a wiki-link target to a note path.

    Wiki-links in Obsidian can be:
    - Just a filename: [[my-note]] -> matches any path ending in my-note.md
    - A path: [[folder/my-note]] -> matches exactly
    """
    # Try exact match first
    target_lower = link_target.lower().strip()
    for p in all_paths:
        if p.lower() == target_lower or p.lower() == target_lower + ".md":
            return p

    # Try filename-only match
    for p in all_paths:
        stem = Path(p).stem.lower()
        if stem == target_lower:
            return p

    return None


def build_graph(conn: sqlite3.Connection, vault_root: Path):
    """Build graph edges from all notes' wiki-links."""
    from .chunker import extract_wiki_links

    # Get all note paths
    all_paths = [r["path"] for r in conn.execute("SELECT path FROM notes").fetchall()]

    # Clear existing edges
    conn.execute("DELETE FROM graph_edges")

    for note_path in all_paths:
        full_path = vault_root / note_path
        if not full_path.exists():
            continue

        text = full_path.read_text(encoding="utf-8", errors="replace")
        links = extract_wiki_links(text)

        for link in links:
            target = resolve_wiki_link(link, all_paths)
            if target and target != note_path:
                conn.execute(
                    "INSERT OR IGNORE INTO graph_edges"
                    " (source_path, target_path, link_text)"
                    " VALUES (?, ?, ?)",
                    (note_path, target, link),
                )

    conn.commit()


def compute_pagerank(conn: sqlite3.Connection, damping: float = 0.85, iterations: int = 20):
    """Compute PageRank for all notes."""
    # Get all notes
    notes = [r["path"] for r in conn.execute("SELECT path FROM notes").fetchall()]
    if not notes:
        return

    n = len(notes)
    path_to_idx = {p: i for i, p in enumerate(notes)}

    # Build adjacency
    edges = conn.execute("SELECT source_path, target_path FROM graph_edges").fetchall()

    # Count out-degrees
    out_degree = [0] * n
    in_links: dict[int, list[int]] = {i: [] for i in range(n)}

    for e in edges:
        src_idx = path_to_idx.get(e["source_path"])
        tgt_idx = path_to_idx.get(e["target_path"])
        if src_idx is not None and tgt_idx is not None:
            out_degree[src_idx] += 1
            in_links[tgt_idx].append(src_idx)

    # Iterative PageRank
    pr = [1.0 / n] * n
    for _ in range(iterations):
        new_pr = [(1.0 - damping) / n] * n
        for i in range(n):
            for j in in_links[i]:
                if out_degree[j] > 0:
                    new_pr[i] += damping * pr[j] / out_degree[j]
        pr = new_pr

    # Compute in-degrees
    in_degree = [0] * n
    for e in edges:
        tgt_idx = path_to_idx.get(e["target_path"])
        if tgt_idx is not None:
            in_degree[tgt_idx] += 1

    # Write to DB
    conn.execute("DELETE FROM graph_stats")
    for i, path in enumerate(notes):
        conn.execute(
            "INSERT INTO graph_stats"
            " (note_path, in_degree, out_degree, pagerank)"
            " VALUES (?, ?, ?, ?)",
            (path, in_degree[i], out_degree[i], pr[i]),
        )
    conn.commit()


def get_neighborhood(
    note_path: str,
    depth: int = 1,
    conn: sqlite3.Connection | None = None,
) -> GraphResult | None:
    """Get a note and its neighborhood in the graph."""
    from .schema import DB_PATH

    if conn is None:
        conn = get_db(DB_PATH)

    # Get center node — try exact match first, then fuzzy (stem, suffix, LIKE)
    note = conn.execute("SELECT path, title FROM notes WHERE path = ?", (note_path,)).fetchone()
    if not note:
        # Try with .md suffix
        note = conn.execute(
            "SELECT path, title FROM notes WHERE path = ?", (note_path + ".md",)
        ).fetchone()
    if not note:
        # Try matching just the filename stem anywhere in the path
        stem = note_path.rsplit("/", 1)[-1].removesuffix(".md")
        note = conn.execute(
            "SELECT path, title FROM notes WHERE path LIKE ? LIMIT 1",
            (f"%{stem}%",),
        ).fetchone()
    if not note:
        return None
    # Use the resolved path from DB
    note_path = note["path"]

    stats = conn.execute(
        "SELECT in_degree, out_degree, pagerank FROM graph_stats WHERE note_path = ?",
        (note_path,),
    ).fetchone()

    summary_row = conn.execute(
        "SELECT summary_text FROM summaries WHERE note_path = ?", (note_path,)
    ).fetchone()

    center = GraphNode(
        path=note_path,
        title=note["title"],
        summary=summary_row["summary_text"] if summary_row else "",
        pagerank=stats["pagerank"] if stats else 0.0,
        in_degree=stats["in_degree"] if stats else 0,
        out_degree=stats["out_degree"] if stats else 0,
    )

    # BFS for neighbors
    visited = {note_path}
    frontier = {note_path}
    neighbor_paths = set()

    for _ in range(depth):
        next_frontier = set()
        for p in frontier:
            # Outgoing links
            for r in conn.execute(
                "SELECT target_path FROM graph_edges WHERE source_path = ?", (p,)
            ).fetchall():
                if r["target_path"] not in visited:
                    next_frontier.add(r["target_path"])
            # Incoming links
            for r in conn.execute(
                "SELECT source_path FROM graph_edges WHERE target_path = ?", (p,)
            ).fetchall():
                if r["source_path"] not in visited:
                    next_frontier.add(r["source_path"])

        visited |= next_frontier
        neighbor_paths |= next_frontier
        frontier = next_frontier

    # Build neighbor nodes
    neighbors = []
    for np_ in neighbor_paths:
        n = conn.execute("SELECT title FROM notes WHERE path = ?", (np_,)).fetchone()
        if not n:
            continue
        s = conn.execute(
            "SELECT in_degree, out_degree, pagerank FROM graph_stats WHERE note_path = ?",
            (np_,),
        ).fetchone()
        sm = conn.execute(
            "SELECT summary_text FROM summaries WHERE note_path = ?", (np_,)
        ).fetchone()
        neighbors.append(GraphNode(
            path=np_,
            title=n["title"],
            summary=sm["summary_text"] if sm else "",
            pagerank=s["pagerank"] if s else 0.0,
            in_degree=s["in_degree"] if s else 0,
            out_degree=s["out_degree"] if s else 0,
        ))

    # Sort by PageRank descending
    neighbors.sort(key=lambda x: x.pagerank, reverse=True)

    return GraphResult(center=center, neighbors=neighbors)
