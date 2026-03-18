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
        updates: list[tuple[str, str, float, str]] = []

        for a, b in canonical:
            row = conn.execute(
                "SELECT weight FROM entity_cooccurrence "
                "WHERE entity_a = ? AND entity_b = ?",
                (a, b),
            ).fetchone()
            if row:
                new_weight = min(row["weight"] * 1.1, MAX_COOCCURRENCE_WEIGHT)
            else:
                new_weight = 1.0
            updates.append((a, b, new_weight, now))

        conn.executemany(
            "INSERT OR REPLACE INTO entity_cooccurrence "
            "(entity_a, entity_b, weight, last_seen) VALUES (?, ?, ?, ?)",
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
    updated = 0

    for i in range(len(entity_list)):
        for j in range(i + 1, len(entity_list)):
            a, b = entity_list[i], entity_list[j]
            # Count distinct notes where BOTH a and b appear as entity
            weight_row = conn.execute(
                """SELECT COUNT(*) AS w FROM (
                       SELECT DISTINCT note_path FROM triples
                       WHERE subject = ? OR object = ?
                   ) n1
                   WHERE n1.note_path IN (
                       SELECT DISTINCT note_path FROM triples
                       WHERE subject = ? OR object = ?
                   )""",
                (a, a, b, b),
            ).fetchone()
            weight = float(weight_row["w"])
            if weight > 0:
                conn.execute(
                    "INSERT OR REPLACE INTO entity_cooccurrence "
                    "(entity_a, entity_b, weight, last_seen) VALUES (?, ?, ?, ?)",
                    (a, b, weight, now),
                )
                updated += 1
            else:
                # Pair no longer co-occurs in any note — remove it
                conn.execute(
                    "DELETE FROM entity_cooccurrence "
                    "WHERE entity_a = ? AND entity_b = ?",
                    (a, b),
                )

    conn.commit()
    return updated


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
