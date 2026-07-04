# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Entity co-occurrence persistence for NeuroStack.

Two separate signals live in the entity_cooccurrence table (issue #60):

- ``weight`` — structural co-occurrence, recomputed from the triples table
  on every full rebuild. Two entities co-occur when they appear as subject
  or object in triples within the same note.
- ``reinforcement`` — Hebbian usage signal, bumped on every search that
  surfaces an entity pair and never touched by rebuilds, so it accumulates
  across reindexes.

Query time blends them as ``weight + reinforcement``. A row survives a
rebuild while either signal is positive.
"""

import logging
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone

log = logging.getLogger("neurostack")

# Caps the reinforcement (usage) signal; structural weights are raw counts
MAX_COOCCURRENCE_WEIGHT = 100.0


def reinforce_cooccurrence(
    conn: sqlite3.Connection, entity_pairs: list[tuple[str, str]]
) -> int:
    """Hebbian reinforcement: increase the usage signal for entity pairs.

    Operates on the ``reinforcement`` column only, so the bump survives
    structural rebuilds (issue #60). For each pair already reinforced:
        new = min(reinforcement * 1.1, MAX_COOCCURRENCE_WEIGHT)
    Pairs not yet reinforced (or not in the table at all) are seeded at
    1.0; usage-only pairs get structural weight 0. All pairs are stored
    in canonical order (entity_a < entity_b).

    Never raises -- wrapped in try/except to avoid disrupting callers.
    Returns the number of pairs reinforced.
    """
    if not entity_pairs:
        return 0

    try:
        # Canonicalize and deduplicate
        canonical: set[tuple[str, str]] = set()
        for a, b in entity_pairs:
            if a == b:
                continue
            canonical.add((min(a, b), max(a, b)))

        if not canonical:
            return 0

        now = datetime.now(timezone.utc).isoformat()

        # Batch-fetch existing reinforcement in a single query
        canonical_list = sorted(canonical)
        existing: dict[tuple[str, str], float] = {}
        # SQLite has a variable limit; process in chunks of 500 pairs
        for chunk_start in range(0, len(canonical_list), 500):
            chunk = canonical_list[chunk_start:chunk_start + 500]
            where_clauses = " OR ".join(
                "(entity_a = ? AND entity_b = ?)" for _ in chunk
            )
            params = [v for pair in chunk for v in pair]
            rows = conn.execute(
                f"SELECT entity_a, entity_b, reinforcement "
                f"FROM entity_cooccurrence WHERE {where_clauses}",
                params,
            ).fetchall()
            for row in rows:
                existing[(row["entity_a"], row["entity_b"])] = row["reinforcement"]

        updates: list[tuple[str, str, float, str]] = []
        for a, b in canonical_list:
            old = existing.get((a, b), 0.0)
            if old > 0:
                new = min(old * 1.1, MAX_COOCCURRENCE_WEIGHT)
            else:
                new = 1.0
            updates.append((a, b, new, now))

        conn.executemany(
            "INSERT INTO entity_cooccurrence "
            "(entity_a, entity_b, weight, reinforcement, last_seen) "
            "VALUES (?, ?, 0.0, ?, ?) "
            "ON CONFLICT(entity_a, entity_b) DO UPDATE SET "
            "reinforcement = excluded.reinforcement, "
            "last_seen = excluded.last_seen",
            updates,
        )
        conn.commit()
        return len(updates)
    except Exception:
        log.debug("reinforce_cooccurrence failed silently", exc_info=True)
        return 0


def persist_cooccurrence(conn: sqlite3.Connection) -> int:
    """Compute and persist structural co-occurrence weights from triples.

    For each note, extracts all entities (subjects and objects from triples).
    For each pair of entities that appear in the same note, increments
    their structural weight by 1.

    Entity pairs are stored in canonical order (entity_a < entity_b).
    Structural weights are fully replaced; the ``reinforcement`` column is
    never touched, so accumulated search reinforcement survives the rebuild
    (issue #60). Rows with neither structural weight nor reinforcement are
    swept away. When the triples table yields no pairs the function returns
    early and the table is left untouched (historical behaviour).

    Returns the number of structural entity pairs persisted.
    """
    rows = conn.execute(
        "SELECT note_path, subject, object FROM triples"
    ).fetchall()

    if not rows:
        log.info("No triples found — skipping co-occurrence persistence.")
        return 0

    # Map each note to the set of entities in it
    note_entities: dict[str, set[str]] = defaultdict(set)
    for r in rows:
        note_entities[r["note_path"]].add(r["subject"])
        note_entities[r["note_path"]].add(r["object"])

    # Compute entity-entity co-occurrence weights
    pair_weights: dict[tuple[str, str], float] = defaultdict(float)
    for _note_path, entities in note_entities.items():
        entity_list = sorted(entities)
        for i in range(len(entity_list)):
            for j in range(i + 1, len(entity_list)):
                # Canonical order: entity_a < entity_b (guaranteed by sorted)
                pair_weights[(entity_list[i], entity_list[j])] += 1.0

    if not pair_weights:
        log.info("No entity co-occurrence pairs found.")
        return 0

    now = datetime.now(timezone.utc).isoformat()

    # Rebuild the structural signal in place: zero it, upsert the fresh
    # counts (leaving reinforcement untouched), then sweep rows that carry
    # neither structural weight nor reinforcement.
    conn.execute("UPDATE entity_cooccurrence SET weight = 0.0")

    conn.executemany(
        "INSERT INTO entity_cooccurrence (entity_a, entity_b, weight, last_seen) "
        "VALUES (?, ?, ?, ?) "
        "ON CONFLICT(entity_a, entity_b) DO UPDATE SET "
        "weight = excluded.weight, last_seen = excluded.last_seen",
        [
            (pair[0], pair[1], weight, now)
            for pair, weight in pair_weights.items()
        ],
    )
    conn.execute(
        "DELETE FROM entity_cooccurrence WHERE weight <= 0 AND reinforcement <= 0"
    )
    conn.commit()

    log.info(
        f"Persisted {len(pair_weights)} entity co-occurrence pairs."
    )
    return len(pair_weights)


def upsert_cooccurrence_for_note(conn: sqlite3.Connection, note_path: str) -> int:
    """Incrementally update co-occurrence for entities found in *note_path*.

    Unlike ``persist_cooccurrence`` (which rebuilds every structural
    weight), this function only touches pairs involving entities from the
    given note. For each affected pair it recomputes the structural weight
    across ALL notes so the result is always globally correct. The
    ``reinforcement`` column is never modified, and pairs that no longer
    co-occur structurally are deleted only when they carry no
    reinforcement (issue #60).

    Returns the number of pairs upserted.
    """
    rows = conn.execute(
        "SELECT subject, object FROM triples WHERE note_path = ?", (note_path,)
    ).fetchall()

    if not rows:
        return 0

    entities: set[str] = set()
    for r in rows:
        entities.add(r["subject"])
        entities.add(r["object"])

    # Also find entities previously paired with any of our entities in
    # co-occurrence (they may need cleanup if an entity was removed from
    # this note).
    if entities:
        placeholders = ",".join("?" for _ in entities)
        prev_rows = conn.execute(
            f"SELECT DISTINCT entity_a, entity_b FROM entity_cooccurrence "
            f"WHERE entity_a IN ({placeholders}) OR entity_b IN ({placeholders})",
            list(entities) + list(entities),
        ).fetchall()
        for pr in prev_rows:
            entities.add(pr["entity_a"])
            entities.add(pr["entity_b"])

    entity_list = sorted(entities)
    now = datetime.now(timezone.utc).isoformat()

    # Build a map of entity -> set of note_paths (single query)
    placeholders = ",".join("?" for _ in entity_list)
    rows = conn.execute(
        f"SELECT DISTINCT subject, object, note_path FROM triples "
        f"WHERE subject IN ({placeholders}) OR object IN ({placeholders})",
        entity_list + entity_list,
    ).fetchall()

    entity_notes: dict[str, set[str]] = defaultdict(set)
    for r in rows:
        if r["subject"] in entities:
            entity_notes[r["subject"]].add(r["note_path"])
        if r["object"] in entities:
            entity_notes[r["object"]].add(r["note_path"])

    # Compute co-occurrence weights as intersection sizes
    upserts: list[tuple[str, str, float, str]] = []
    deletes: list[tuple[str, str]] = []

    for i in range(len(entity_list)):
        for j in range(i + 1, len(entity_list)):
            a, b = entity_list[i], entity_list[j]
            weight = float(len(entity_notes.get(a, set()) & entity_notes.get(b, set())))
            if weight > 0:
                upserts.append((a, b, weight, now))
            else:
                deletes.append((a, b))

    # Batch upsert
    if upserts:
        conn.executemany(
            "INSERT INTO entity_cooccurrence "
            "(entity_a, entity_b, weight, last_seen) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(entity_a, entity_b) DO UPDATE SET "
            "weight = excluded.weight, last_seen = excluded.last_seen",
            upserts,
        )

    # Pairs that no longer co-occur structurally: drop unreinforced rows,
    # keep reinforced ones at weight 0
    if deletes:
        conn.executemany(
            "DELETE FROM entity_cooccurrence "
            "WHERE entity_a = ? AND entity_b = ? AND reinforcement <= 0",
            deletes,
        )
        conn.executemany(
            "UPDATE entity_cooccurrence SET weight = 0.0 "
            "WHERE entity_a = ? AND entity_b = ?",
            deletes,
        )

    conn.commit()
    return len(upserts)


def get_cooccurrence_stats(conn: sqlite3.Connection) -> dict:
    """Return aggregate co-occurrence statistics.

    Returns dict with:
        pairs: int -- number of entity co-occurrence pairs
        total_weight: float -- sum of structural weights, rounded to 1 decimal
        reinforced_pairs: int -- pairs carrying accumulated search reinforcement
        total_reinforcement: float -- sum of reinforcement, rounded to 1 decimal
    """
    row = conn.execute(
        "SELECT COUNT(*) AS pairs, COALESCE(SUM(weight), 0.0) AS total_weight, "
        "COALESCE(SUM(reinforcement > 0), 0) AS reinforced_pairs, "
        "COALESCE(SUM(reinforcement), 0.0) AS total_reinforcement "
        "FROM entity_cooccurrence"
    ).fetchone()
    return {
        "pairs": row["pairs"],
        "total_weight": round(float(row["total_weight"]), 1),
        "reinforced_pairs": row["reinforced_pairs"],
        "total_reinforcement": round(float(row["total_reinforcement"]), 1),
    }


def get_top_pairs(conn: sqlite3.Connection, limit: int = 20) -> list[dict]:
    """Return the top entity pairs sorted by blended weight descending.

    Each element: {"entity_a": str, "entity_b": str, "weight": float,
    "reinforcement": float, "last_seen": str}. ``weight`` is the structural
    signal; ordering uses weight + reinforcement, the same blend as search.
    """
    rows = conn.execute(
        "SELECT entity_a, entity_b, weight, reinforcement, last_seen "
        "FROM entity_cooccurrence "
        "ORDER BY weight + reinforcement DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [
        {
            "entity_a": r["entity_a"],
            "entity_b": r["entity_b"],
            "weight": float(r["weight"]),
            "reinforcement": float(r["reinforcement"]),
            "last_seen": r["last_seen"],
        }
        for r in rows
    ]
