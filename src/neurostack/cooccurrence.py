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
