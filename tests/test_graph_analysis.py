# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Tests for structural graph analysis — gaps and bridges (issue #12)."""

import sqlite3

from neurostack.graph_analysis import (
    analyze_graph,
    betweenness_centrality,
    count_components,
    find_structural_gaps,
)


def _adj(edges):
    """Build an undirected adjacency dict from an (a, b) edge list."""
    adj: dict[str, set[str]] = {}
    for a, b in edges:
        adj.setdefault(a, set()).add(b)
        adj.setdefault(b, set()).add(a)
    return adj


# Two notes X, Y both link the same three hubs A, B, C but not each other.
SHARED_HUB = _adj([
    ("X", "A"), ("X", "B"), ("X", "C"),
    ("Y", "A"), ("Y", "B"), ("Y", "C"),
])

# Two triangles joined by a single connector D (a barbell).
BARBELL = _adj([
    ("A", "B"), ("B", "C"), ("A", "C"),      # triangle 1
    ("C", "D"), ("D", "E"),                   # bridge C–D–E
    ("E", "F"), ("F", "G"), ("E", "G"),      # triangle 2
])


class TestGaps:
    def test_top_gap_is_the_shared_pair(self):
        gaps = find_structural_gaps(SHARED_HUB, top_k=10, min_shared=2)
        top = gaps[0]
        assert (top[0], top[1]) == ("X", "Y")   # keys are stored sorted
        assert top[2] == 3                        # three shared neighbours
        assert set(top[4]) == {"A", "B", "C"}

    def test_already_linked_pairs_excluded(self):
        # X and Y share A,B,C. Add a direct X–Y link → no longer a gap.
        adj = {k: set(v) for k, v in SHARED_HUB.items()}
        adj["X"].add("Y")
        adj["Y"].add("X")
        gaps = find_structural_gaps(adj, top_k=10, min_shared=2)
        assert all({a, b} != {"X", "Y"} for a, b, *_ in gaps)

    def test_min_shared_threshold(self):
        # With min_shared=3 only the X–Y pair (3 shared) qualifies.
        gaps = find_structural_gaps(SHARED_HUB, top_k=10, min_shared=3)
        assert len(gaps) == 1
        assert (gaps[0][0], gaps[0][1]) == ("X", "Y")

    def test_rarer_shared_neighbours_score_higher(self):
        # A shared hub of degree 2 weighs more than one of degree 10.
        niche = find_structural_gaps(_adj([("u", "h"), ("v", "h"),
                                           ("u", "x"), ("v", "x")]),
                                     min_shared=2)
        # u,v share h and x (both degree 2) → one gap with score 2/ln(2).
        assert niche[0][2] == 2


class TestBridgesAndComponents:
    def test_connector_has_highest_betweenness(self):
        betw = betweenness_centrality(BARBELL)
        assert max(betw, key=betw.get) == "D"
        assert betw["D"] > betw["C"]

    def test_component_counting(self):
        assert count_components(BARBELL) == 1
        with_isolate = {**{k: set(v) for k, v in BARBELL.items()}, "Z": set()}
        assert count_components(with_isolate) == 2

    def test_removing_connector_splits_graph(self):
        # D is an articulation point: removing it yields two components.
        assert count_components(BARBELL, exclude="D") == 2
        # A leaf-ish triangle member is not.
        assert count_components(BARBELL, exclude="A") == 1


def _seed_db(notes, edges):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE notes (path TEXT PRIMARY KEY, title TEXT)")
    conn.execute("CREATE TABLE graph_edges (source_path TEXT, target_path TEXT)")
    conn.executemany("INSERT INTO notes VALUES (?, ?)", notes)
    conn.executemany("INSERT INTO graph_edges VALUES (?, ?)", edges)
    conn.commit()
    return conn


class TestAnalyzeGraphEndToEnd:
    def test_shaped_output_over_a_db(self):
        notes = [(p, f"Title {p}") for p in "ABCDEFG"]
        edges = [("A", "B"), ("B", "C"), ("A", "C"), ("C", "D"),
                 ("D", "E"), ("E", "F"), ("F", "G"), ("E", "G")]
        result = analyze_graph(_seed_db(notes, edges), top_k=5)

        assert result["stats"]["notes"] == 7
        assert result["stats"]["edges"] == 8
        assert result["stats"]["components"] == 1
        assert result["stats"]["isolated"] == 0

        top_bridge = result["bridges"][0]
        assert top_bridge["path"] == "D"
        assert top_bridge["title"] == "Title D"
        assert top_bridge["articulation"] is True
        assert top_bridge["fragments_if_removed"] == 2

    def test_empty_graph(self):
        result = analyze_graph(_seed_db([], []), top_k=5)
        assert result["stats"] == {
            "notes": 0, "edges": 0, "isolated": 0, "components": 0
        }
        assert result["gaps"] == []
        assert result["bridges"] == []

    def test_stale_edges_to_missing_notes_ignored(self):
        # An edge to a note that no longer exists must not crash or appear.
        conn = _seed_db([("A", "A"), ("B", "B")], [("A", "B"), ("A", "ghost")])
        result = analyze_graph(conn, top_k=5)
        assert result["stats"]["notes"] == 2
        assert result["stats"]["edges"] == 1
