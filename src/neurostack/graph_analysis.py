# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Structural graph analysis: missing-link gaps and bridge notes (issue #12).

Pure structural computation over the wiki-link graph (``graph_edges``) — no
embeddings, no LLM — answering two questions:

- **Gaps**: pairs of notes that share many neighbours but aren't linked. Ranked
  by Adamic-Adar, the standard common-neighbour link-prediction score, which
  weights a shared neighbour by how rare it is (a link through a hub counts for
  less than one through a niche note). These are candidate links worth adding.
- **Bridges**: notes that hold the graph together. Ranked by betweenness
  centrality (Brandes' algorithm); each is also tested for whether removing it
  fragments the graph (an articulation point) and into how many pieces.

The graph is treated as undirected: a wiki-link is a connection regardless of
which note authored it.
"""

from __future__ import annotations

import collections
import math
import sqlite3


def _undirected_adjacency(conn: sqlite3.Connection) -> dict[str, set[str]]:
    """Build undirected neighbour sets keyed by note path.

    Every current note is seeded (so isolated notes are visible), and edges
    whose endpoints are no longer in ``notes`` are dropped, keeping the
    adjacency consistent with the live vault rather than stale edge rows.
    """
    adj: dict[str, set[str]] = {
        r["path"]: set() for r in conn.execute("SELECT path FROM notes")
    }
    for e in conn.execute("SELECT source_path, target_path FROM graph_edges"):
        s, t = e["source_path"], e["target_path"]
        if s == t or s not in adj or t not in adj:
            continue
        adj[s].add(t)
        adj[t].add(s)
    return adj


def find_structural_gaps(
    adj: dict[str, set[str]], top_k: int = 10, min_shared: int = 2
) -> list[tuple[str, str, int, float, list[str]]]:
    """Unlinked note pairs ranked by Adamic-Adar common-neighbour score.

    Returns ``(a, b, shared_count, score, common_neighbours)`` tuples, best
    first. Accumulated per hub's neighbour pairs — O(sum of degree^2), far
    cheaper than scoring all note pairs on a sparse graph.
    """
    shared: dict[tuple[str, str], list] = {}
    for _hub, nbrs in adj.items():
        deg = len(nbrs)
        if deg < 2:
            continue
        weight = 1.0 / math.log(deg)  # deg >= 2, so log(deg) > 0
        ordered = sorted(nbrs)
        for i in range(deg):
            a = ordered[i]
            for j in range(i + 1, deg):
                b = ordered[j]
                rec = shared.get((a, b))
                if rec is None:
                    rec = [0, 0.0, []]
                    shared[(a, b)] = rec
                rec[0] += 1
                rec[1] += weight
                rec[2].append(_hub)

    gaps: list[tuple[str, str, int, float, list[str]]] = []
    for (a, b), (count, score, commons) in shared.items():
        if count < min_shared:
            continue
        if b in adj.get(a, ()):  # already linked — not a gap
            continue
        gaps.append((a, b, count, score, commons))

    gaps.sort(key=lambda g: (g[3], g[2]), reverse=True)
    return gaps[:top_k]


def betweenness_centrality(adj: dict[str, set[str]]) -> dict[str, float]:
    """Brandes' betweenness centrality on an undirected, unweighted graph."""
    betw = dict.fromkeys(adj, 0.0)
    for s in adj:
        stack: list[str] = []
        pred: dict[str, list[str]] = {v: [] for v in adj}
        sigma = dict.fromkeys(adj, 0.0)
        sigma[s] = 1.0
        dist = dict.fromkeys(adj, -1)
        dist[s] = 0
        queue = collections.deque([s])
        while queue:
            v = queue.popleft()
            stack.append(v)
            for w in adj[v]:
                if dist[w] < 0:
                    dist[w] = dist[v] + 1
                    queue.append(w)
                if dist[w] == dist[v] + 1:
                    sigma[w] += sigma[v]
                    pred[w].append(v)
        delta = dict.fromkeys(adj, 0.0)
        while stack:
            w = stack.pop()
            for v in pred[w]:
                delta[v] += (sigma[v] / sigma[w]) * (1.0 + delta[w])
            if w != s:
                betw[w] += delta[w]
    # Undirected graph: every shortest path is walked from both endpoints.
    for v in betw:
        betw[v] /= 2.0
    return betw


def count_components(adj: dict[str, set[str]], exclude: str | None = None) -> int:
    """Count connected components. If ``exclude`` is given, that node is treated
    as removed (used to test whether a node is an articulation point)."""
    seen: set[str] = set()
    if exclude is not None:
        seen.add(exclude)  # pre-mark so it is never visited or counted
    count = 0
    for start in adj:
        if start in seen:
            continue
        count += 1
        stack = [start]
        seen.add(start)
        while stack:
            v = stack.pop()
            for w in adj[v]:
                if w not in seen:
                    seen.add(w)
                    stack.append(w)
    return count


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


def analyze_graph(
    conn: sqlite3.Connection, top_k: int = 10, min_shared: int = 2
) -> dict:
    """Run the full gaps + bridges analysis and shape it for callers."""
    adj = _undirected_adjacency(conn)

    edge_count = sum(len(v) for v in adj.values()) // 2
    stats = {
        "notes": len(adj),
        "edges": edge_count,
        "isolated": sum(1 for v in adj.values() if not v),
        "components": count_components(adj),
    }

    gap_tuples = find_structural_gaps(adj, top_k=top_k, min_shared=min_shared)

    betw = betweenness_centrality(adj)
    bridge_paths = [p for p, score in
                    sorted(betw.items(), key=lambda kv: kv[1], reverse=True)
                    if score > 0][:top_k]

    referenced: set[str] = set(bridge_paths)
    for a, b, _cnt, _score, commons in gap_tuples:
        referenced.add(a)
        referenced.add(b)
        referenced.update(commons[:5])
    titles = _titles(conn, referenced)

    gaps = [
        {
            "a": a,
            "a_title": titles.get(a, a),
            "b": b,
            "b_title": titles.get(b, b),
            "shared_neighbors": count,
            "score": round(score, 4),
            "via": [titles.get(c, c) for c in commons[:5]],
        }
        for (a, b, count, score, commons) in gap_tuples
    ]

    comp_before = stats["components"]
    bridges = []
    for p in bridge_paths:
        comp_after = count_components(adj, exclude=p)
        articulation = comp_after > comp_before
        bridges.append({
            "path": p,
            "title": titles.get(p, p),
            "betweenness": round(betw[p], 4),
            "degree": len(adj[p]),
            "articulation": articulation,
            # Pieces the graph splits into when this note is removed (1 = no split).
            "fragments_if_removed": (comp_after - comp_before + 1) if articulation else 1,
        })

    return {"stats": stats, "gaps": gaps, "bridges": bridges}
