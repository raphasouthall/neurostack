# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Leiden community detection on the note-note shared-entity graph.

Builds a note graph where:
  - Nodes = vault notes that have triples
  - Edges = notes sharing >= MIN_SHARED entity mentions (weight = count)

Runs Leiden at two resolutions:
  - level=0: coarse themes (~10-20 communities)
  - level=1: fine sub-themes (~20-30 communities)

community_members.entity stores note_paths (not raw entity strings).
"""

import logging
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone

try:
    import igraph as ig
    import leidenalg
    HAS_LEIDEN = True
except ImportError:
    HAS_LEIDEN = False

from .schema import DB_PATH, get_db

log = logging.getLogger("neurostack")

# Minimum shared entities for a note-note edge
MIN_SHARED = 2

# Resolution parameters (higher = more/smaller communities)
LEVEL_0_RESOLUTION = 0.3   # coarse (~10-20 communities)
LEVEL_1_RESOLUTION = 1.0   # fine   (~20-30 communities)


def build_note_graph(conn: sqlite3.Connection) -> "ig.Graph":
    """Build a note-note graph from shared entity co-occurrence.

    Two notes are connected if they share >= MIN_SHARED entity names
    (as subject or object in their respective triples).
    Edge weight = number of shared entities.
    """
    if not HAS_LEIDEN:
        raise ImportError(
            "Community detection requires leidenalg and python-igraph. "
            "Install with: pip install neurostack[community]"
        )
    rows = conn.execute("SELECT note_path, subject, object FROM triples").fetchall()

    if not rows:
        return ig.Graph()

    # Map each entity to the set of notes that mention it
    entity_notes: dict[str, set[str]] = defaultdict(set)
    for r in rows:
        entity_notes[r["subject"]].add(r["note_path"])
        entity_notes[r["object"]].add(r["note_path"])

    # Build note-note edge weights
    note_weights: dict[tuple[str, str], int] = defaultdict(int)
    for notes in entity_notes.values():
        note_list = list(notes)
        for i in range(len(note_list)):
            for j in range(i + 1, len(note_list)):
                key = (min(note_list[i], note_list[j]), max(note_list[i], note_list[j]))
                note_weights[key] += 1

    # Filter to strong edges only
    strong = {k: v for k, v in note_weights.items() if v >= MIN_SHARED}
    if not strong:
        log.warning(f"No note pairs share >= {MIN_SHARED} entities.")
        return ig.Graph()

    all_notes = sorted({n for pair in strong for n in pair})
    note_to_idx = {n: i for i, n in enumerate(all_notes)}

    edges = [(note_to_idx[k[0]], note_to_idx[k[1]]) for k in strong]
    weights = list(strong.values())

    g = ig.Graph(n=len(all_notes), edges=edges, directed=False)
    g.vs["name"] = all_notes
    g.es["weight"] = weights

    log.info(f"Note graph: {g.vcount()} nodes, {g.ecount()} edges (min_shared={MIN_SHARED})")
    return g


def run_leiden(g: "ig.Graph", resolution: float, seed: int = 42) -> list[int]:
    """Run Leiden community detection. Returns membership list (index = node index)."""
    if not HAS_LEIDEN:
        raise ImportError(
            "Community detection requires leidenalg and python-igraph. "
            "Install with: pip install neurostack[community]"
        )
    if g.vcount() == 0:
        return []

    partition = leidenalg.find_partition(
        g,
        leidenalg.RBConfigurationVertexPartition,
        weights="weight",
        resolution_parameter=resolution,
        seed=seed,
        n_iterations=10,
    )
    return list(partition.membership)


def _store_communities(
    conn: sqlite3.Connection,
    g: ig.Graph,
    level: int,
    membership: list[int],
) -> None:
    """Store one level of communities. community_members.entity holds note_paths."""
    if not membership:
        return

    now = datetime.now(timezone.utc).isoformat()

    community_notes: dict[int, list[str]] = {}
    for node_idx, comm_id in enumerate(membership):
        note_path = g.vs[node_idx]["name"]
        community_notes.setdefault(comm_id, []).append(note_path)

    for note_paths in community_notes.values():
        cursor = conn.execute(
            "INSERT INTO communities"
            " (level, entity_count, member_notes,"
            " updated_at) VALUES (?, ?, ?, ?)",
            (level, len(note_paths), len(note_paths), now),
        )
        db_id = cursor.lastrowid

        conn.executemany(
            "INSERT OR IGNORE INTO community_members (community_id, entity) VALUES (?, ?)",
            [(db_id, np_) for np_ in note_paths],
        )


def detect_communities(
    conn: sqlite3.Connection | None = None,
    db_path=None,
) -> tuple[int, int]:
    """Full pipeline: build note graph, run Leiden at 2 levels, store results.

    Clears existing communities first (full rebuild).
    Returns (n_coarse, n_fine) community counts.
    """
    if not HAS_LEIDEN:
        raise ImportError(
            "Community detection requires leidenalg and python-igraph. "
            "Install with: pip install neurostack[community]"
        )
    if conn is None:
        conn = get_db(db_path or DB_PATH)

    # Clear existing
    conn.execute("DELETE FROM community_members")
    conn.execute("DELETE FROM communities")
    conn.commit()

    g = build_note_graph(conn)
    if g.vcount() == 0:
        log.warning("No connected notes found — skipping community detection.")
        return 0, 0

    log.info(f"Running Leiden level 0 (coarse, resolution={LEVEL_0_RESOLUTION})...")
    m0 = run_leiden(g, resolution=LEVEL_0_RESOLUTION)
    _store_communities(conn, g, level=0, membership=m0)
    n_coarse = len(set(m0))

    log.info(f"Running Leiden level 1 (fine, resolution={LEVEL_1_RESOLUTION})...")
    m1 = run_leiden(g, resolution=LEVEL_1_RESOLUTION)
    _store_communities(conn, g, level=1, membership=m1)
    n_fine = len(set(m1))

    conn.commit()
    log.info(f"Community detection done: {n_coarse} coarse, {n_fine} fine communities.")
    return n_coarse, n_fine
