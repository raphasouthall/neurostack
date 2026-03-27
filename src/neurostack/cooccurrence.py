# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Entity co-occurrence persistence for NeuroStack.

Computes entity-entity co-occurrence from the triples table and persists
weights to the entity_cooccurrence table. Two entities co-occur when they
appear as subject or object in triples within the same note.
"""

import logging
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone

log = logging.getLogger("neurostack")

MAX_COOCCURRENCE_WEIGHT = 100.0


def reinforce_cooccurrence(
    conn: sqlite3.Connection, entity_pairs: list[tuple[str, str]]
) -> int:
    """Hebbian reinforcement: increase co-occurrence weight for entity pairs.

    For each pair, applies a multiplicative increment:
        new_weight = min(existing_weight * 1.1, MAX_COOCCURRENCE_WEIGHT)

    New pairs are seeded with weight 1.0. All pairs are stored in canonical
    order (entity_a < entity_b).

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

        # Batch-fetch existing weights in a single query
        canonical_list = sorted(canonical)
        existing_weights: dict[tuple[str, str], float] = {}
        # SQLite has a variable limit; process in chunks of 500 pairs
        for chunk_start in range(0, len(canonical_list), 500):
            chunk = canonical_list[chunk_start:chunk_start + 500]
            where_clauses = " OR ".join(
                "(entity_a = ? AND entity_b = ?)" for _ in chunk
            )
            params = [v for pair in chunk for v in pair]
            rows = conn.execute(
                f"SELECT entity_a, entity_b, weight FROM entity_cooccurrence "
                f"WHERE {where_clauses}",
                params,
            ).fetchall()
            for row in rows:
                existing_weights[(row["entity_a"], row["entity_b"])] = row["weight"]

        updates: list[tuple[str, str, float, str]] = []
        for a, b in canonical_list:
            old_weight = existing_weights.get((a, b))
            if old_weight is not None:
                new_weight = min(old_weight * 1.1, MAX_COOCCURRENCE_WEIGHT)
            else:
                new_weight = 1.0
            updates.append((a, b, new_weight, now))

        conn.executemany(
            "INSERT INTO entity_cooccurrence "
            "(entity_a, entity_b, weight, last_seen) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(entity_a, entity_b) DO UPDATE SET "
            "weight = excluded.weight, last_seen = excluded.last_seen",
            updates,
        )
        conn.commit()
        return len(updates)
    except Exception:
        log.debug("reinforce_cooccurrence failed silently", exc_info=True)
        return 0


def persist_cooccurrence(conn: sqlite3.Connection) -> int:
    """Compute and persist entity co-occurrence weights from triples.

    For each note, extracts all entities (subjects and objects from triples).
    For each pair of entities that appear in the same note, increments
    their co-occurrence weight by 1.

    Entity pairs are stored in canonical order (entity_a < entity_b).
    Existing weights are fully replaced (not incremented).

    Returns the number of entity pairs persisted.
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

    # Clear existing co-occurrence data and repopulate
    conn.execute("DELETE FROM entity_cooccurrence")

    conn.executemany(
        "INSERT INTO entity_cooccurrence (entity_a, entity_b, weight, last_seen) "
        "VALUES (?, ?, ?, ?)",
        [
            (pair[0], pair[1], weight, now)
            for pair, weight in pair_weights.items()
        ],
    )
    conn.commit()

    log.info(
        f"Persisted {len(pair_weights)} entity co-occurrence pairs."
    )
    return len(pair_weights)


def upsert_cooccurrence_for_note(conn: sqlite3.Connection, note_path: str) -> int:
    """Incrementally update co-occurrence for entities found in *note_path*.

    Unlike ``persist_cooccurrence`` (which does a full DELETE+INSERT), this
    function only touches pairs involving entities from the given note.
    For each affected pair it recomputes the weight across ALL notes so
    the result is always globally correct.

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

    # Batch delete pairs that no longer co-occur
    if deletes:
        conn.executemany(
            "DELETE FROM entity_cooccurrence "
            "WHERE entity_a = ? AND entity_b = ?",
            deletes,
        )

    conn.commit()
    return len(upserts)


def get_cooccurrence_stats(conn: sqlite3.Connection) -> dict:
    """Return aggregate co-occurrence statistics.

    Returns dict with:
        pairs: int -- number of entity co-occurrence pairs
        total_weight: float -- sum of all weights, rounded to 1 decimal
    """
    row = conn.execute(
        "SELECT COUNT(*) AS pairs, COALESCE(SUM(weight), 0.0) AS total_weight "
        "FROM entity_cooccurrence"
    ).fetchone()
    return {
        "pairs": row["pairs"],
        "total_weight": round(float(row["total_weight"]), 1),
    }


def get_top_pairs(conn: sqlite3.Connection, limit: int = 20) -> list[dict]:
    """Return the top co-occurring entity pairs sorted by weight descending.

    Each element: {"entity_a": str, "entity_b": str, "weight": float, "last_seen": str}
    """
    rows = conn.execute(
        "SELECT entity_a, entity_b, weight, last_seen "
        "FROM entity_cooccurrence ORDER BY weight DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [
        {
            "entity_a": r["entity_a"],
            "entity_b": r["entity_b"],
            "weight": float(r["weight"]),
            "last_seen": r["last_seen"],
        }
        for r in rows
    ]
