"""Tests for neurostack.cooccurrence — entity co-occurrence persistence."""

from neurostack.cooccurrence import (
    MAX_COOCCURRENCE_WEIGHT,
    get_cooccurrence_stats,
    persist_cooccurrence,
    reinforce_cooccurrence,
    upsert_cooccurrence_for_note,
)


def _insert_triple(conn, note_path, subject, obj):
    """Helper: insert a note (if needed) and a triple."""
    conn.execute(
        "INSERT INTO notes (path, title, content_hash, updated_at) "
        "VALUES (?, ?, ?, ?) ON CONFLICT(path) DO NOTHING",
        (note_path, note_path, "hash", "2026-01-01"),
    )
    conn.execute(
        "INSERT INTO triples (note_path, subject, predicate, object, triple_text) "
        "VALUES (?, ?, ?, ?, ?)",
        (note_path, subject, "relates_to", obj, f"{subject} relates_to {obj}"),
    )
    conn.commit()


def test_two_entities_one_note(in_memory_db):
    """Two entities in the same note produce 1 row with weight 1.0."""
    conn = in_memory_db
    _insert_triple(conn, "note1.md", "Alpha", "Beta")

    n = persist_cooccurrence(conn)

    assert n == 1
    row = conn.execute(
        "SELECT entity_a, entity_b, weight FROM entity_cooccurrence"
    ).fetchone()
    assert row["entity_a"] == "Alpha"
    assert row["entity_b"] == "Beta"
    assert row["weight"] == 1.0


# --- upsert_cooccurrence_for_note tests ---


def test_upsert_two_entities_one_note(in_memory_db):
    """upsert for a note with 2 entities creates 1 pair with weight 1.0."""
    conn = in_memory_db
    _insert_triple(conn, "note1.md", "Alpha", "Beta")

    result = upsert_cooccurrence_for_note(conn, "note1.md")

    assert result == 1
    row = conn.execute(
        "SELECT entity_a, entity_b, weight FROM entity_cooccurrence"
    ).fetchone()
    assert row["entity_a"] == "Alpha"
    assert row["entity_b"] == "Beta"
    assert row["weight"] == 1.0


def test_upsert_shared_entities_increments_weight(in_memory_db):
    """upsert for a note sharing entities with another note sets weight to 2.0."""
    conn = in_memory_db
    _insert_triple(conn, "note1.md", "Alpha", "Beta")
    _insert_triple(conn, "note2.md", "Alpha", "Beta")

    # First upsert for note1
    upsert_cooccurrence_for_note(conn, "note1.md")
    # Then upsert for note2 -- weight should now be 2.0
    upsert_cooccurrence_for_note(conn, "note2.md")

    row = conn.execute(
        "SELECT weight FROM entity_cooccurrence "
        "WHERE entity_a = 'Alpha' AND entity_b = 'Beta'"
    ).fetchone()
    assert row["weight"] == 2.0


def test_upsert_re_upsert_same_note_recalculates(in_memory_db):
    """Re-upsert for same note after content change recalculates correctly."""
    conn = in_memory_db
    _insert_triple(conn, "note1.md", "Alpha", "Beta")
    _insert_triple(conn, "note1.md", "Alpha", "Charlie")

    upsert_cooccurrence_for_note(conn, "note1.md")

    # Simulate content change: remove Charlie triple, add Delta
    conn.execute(
        "DELETE FROM triples WHERE note_path = 'note1.md' AND object = 'Charlie'"
    )
    conn.execute(
        "INSERT INTO triples (note_path, subject, predicate, object, triple_text) "
        "VALUES ('note1.md', 'Alpha', 'relates_to', 'Delta', 'Alpha relates_to Delta')"
    )
    conn.commit()

    upsert_cooccurrence_for_note(conn, "note1.md")

    # Should have Alpha-Beta and Alpha-Delta (and Beta-Delta)
    rows = conn.execute(
        "SELECT entity_a, entity_b FROM entity_cooccurrence ORDER BY entity_a, entity_b"
    ).fetchall()
    pairs = [(r["entity_a"], r["entity_b"]) for r in rows]
    assert ("Alpha", "Beta") in pairs
    assert ("Alpha", "Delta") in pairs
    # Alpha-Charlie should no longer exist (no notes have both)
    assert ("Alpha", "Charlie") not in pairs


def test_upsert_no_triples_noop(in_memory_db):
    """upsert for a note with no triples returns 0 and changes nothing."""
    conn = in_memory_db
    # Insert a pair from another note first
    _insert_triple(conn, "note1.md", "Alpha", "Beta")
    upsert_cooccurrence_for_note(conn, "note1.md")

    # upsert for a note that has no triples
    result = upsert_cooccurrence_for_note(conn, "nonexistent.md")
    assert result == 0

    # Existing pair should still be there
    count = conn.execute(
        "SELECT COUNT(*) as c FROM entity_cooccurrence"
    ).fetchone()["c"]
    assert count == 1


def test_upsert_only_touches_affected_pairs(in_memory_db):
    """upsert for note1 does not affect pairs from note2 entities."""
    conn = in_memory_db
    _insert_triple(conn, "note1.md", "Alpha", "Beta")
    _insert_triple(conn, "note2.md", "Gamma", "Delta")

    # Populate both via upsert
    upsert_cooccurrence_for_note(conn, "note1.md")
    upsert_cooccurrence_for_note(conn, "note2.md")

    # Check both pairs exist
    count = conn.execute(
        "SELECT COUNT(*) as c FROM entity_cooccurrence"
    ).fetchone()["c"]
    assert count == 2

    # Now re-upsert note1 -- should not affect Gamma-Delta
    upsert_cooccurrence_for_note(conn, "note1.md")

    gamma_delta = conn.execute(
        "SELECT weight FROM entity_cooccurrence "
        "WHERE entity_a = 'Delta' AND entity_b = 'Gamma'"
    ).fetchone()
    assert gamma_delta is not None
    assert gamma_delta["weight"] == 1.0


def test_three_entities_one_note(in_memory_db):
    """Three entities (A, B, C) in same note produce 3 pairs each weight 1.0."""
    conn = in_memory_db
    _insert_triple(conn, "note1.md", "Alpha", "Beta")
    _insert_triple(conn, "note1.md", "Beta", "Charlie")

    n = persist_cooccurrence(conn)

    assert n == 3
    rows = conn.execute(
        "SELECT entity_a, entity_b, weight FROM entity_cooccurrence "
        "ORDER BY entity_a, entity_b"
    ).fetchall()
    pairs = [(r["entity_a"], r["entity_b"], r["weight"]) for r in rows]
    assert ("Alpha", "Beta", 1.0) in pairs
    assert ("Alpha", "Charlie", 1.0) in pairs
    assert ("Beta", "Charlie", 1.0) in pairs


def test_two_notes_shared_entities_weight_2(in_memory_db):
    """Two notes sharing entities A and B produce weight 2.0."""
    conn = in_memory_db
    _insert_triple(conn, "note1.md", "Alpha", "Beta")
    _insert_triple(conn, "note2.md", "Alpha", "Beta")

    n = persist_cooccurrence(conn)

    assert n == 1
    row = conn.execute(
        "SELECT weight FROM entity_cooccurrence "
        "WHERE entity_a = 'Alpha' AND entity_b = 'Beta'"
    ).fetchone()
    assert row["weight"] == 2.0


def test_canonical_ordering(in_memory_db):
    """Entity pairs stored with entity_a < entity_b regardless of insert order."""
    conn = in_memory_db
    # Insert with Zebra as subject, Alpha as object
    _insert_triple(conn, "note1.md", "Zebra", "Alpha")

    persist_cooccurrence(conn)

    row = conn.execute(
        "SELECT entity_a, entity_b FROM entity_cooccurrence"
    ).fetchone()
    assert row["entity_a"] == "Alpha"
    assert row["entity_b"] == "Zebra"


def test_no_triples_no_rows(in_memory_db):
    """No triples in the DB means no co-occurrence rows."""
    conn = in_memory_db

    n = persist_cooccurrence(conn)

    assert n == 0
    count = conn.execute(
        "SELECT COUNT(*) as c FROM entity_cooccurrence"
    ).fetchone()["c"]
    assert count == 0


def test_last_seen_populated(in_memory_db):
    """last_seen column has a datetime string after persistence."""
    conn = in_memory_db
    _insert_triple(conn, "note1.md", "Alpha", "Beta")

    persist_cooccurrence(conn)

    row = conn.execute(
        "SELECT last_seen FROM entity_cooccurrence"
    ).fetchone()
    assert row["last_seen"] is not None
    assert len(row["last_seen"]) > 10  # ISO datetime string


def test_idempotent_replaces_not_duplicates(in_memory_db):
    """Running persist_cooccurrence twice replaces weights, not duplicates."""
    conn = in_memory_db
    _insert_triple(conn, "note1.md", "Alpha", "Beta")

    persist_cooccurrence(conn)
    persist_cooccurrence(conn)

    count = conn.execute(
        "SELECT COUNT(*) as c FROM entity_cooccurrence"
    ).fetchone()["c"]
    assert count == 1
    row = conn.execute(
        "SELECT weight FROM entity_cooccurrence"
    ).fetchone()
    assert row["weight"] == 1.0


# --- get_cooccurrence_stats tests ---


def test_cooccurrence_stats_empty(in_memory_db):
    """With no data, get_cooccurrence_stats returns zeros."""
    conn = in_memory_db

    stats = get_cooccurrence_stats(conn)

    assert stats["pairs"] == 0
    assert stats["total_weight"] == 0.0


def test_cooccurrence_stats_with_data(in_memory_db):
    """After inserting 3 pairs with weights 1.0, 2.5, 3.0, returns correct counts."""
    conn = in_memory_db
    now = "2026-01-01T00:00:00"
    conn.execute(
        "INSERT INTO entity_cooccurrence (entity_a, entity_b, weight, last_seen) "
        "VALUES (?, ?, ?, ?)",
        ("A", "B", 1.0, now),
    )
    conn.execute(
        "INSERT INTO entity_cooccurrence (entity_a, entity_b, weight, last_seen) "
        "VALUES (?, ?, ?, ?)",
        ("C", "D", 2.5, now),
    )
    conn.execute(
        "INSERT INTO entity_cooccurrence (entity_a, entity_b, weight, last_seen) "
        "VALUES (?, ?, ?, ?)",
        ("E", "F", 3.0, now),
    )
    conn.commit()

    stats = get_cooccurrence_stats(conn)

    assert stats["pairs"] == 3
    assert stats["total_weight"] == 6.5


# --- reinforce_cooccurrence tests ---


def test_reinforce_basic(in_memory_db):
    """Reinforcing an existing pair with weight 2.0 increases it via multiplicative formula."""
    conn = in_memory_db
    conn.execute(
        "INSERT INTO entity_cooccurrence (entity_a, entity_b, weight, last_seen) "
        "VALUES (?, ?, ?, ?)",
        ("Alpha", "Beta", 2.0, "2026-01-01"),
    )
    conn.commit()

    n = reinforce_cooccurrence(conn, [("Alpha", "Beta")])

    assert n == 1
    row = conn.execute(
        "SELECT weight FROM entity_cooccurrence "
        "WHERE entity_a = 'Alpha' AND entity_b = 'Beta'"
    ).fetchone()
    expected = min(2.0 * 1.1, MAX_COOCCURRENCE_WEIGHT)
    assert abs(row["weight"] - expected) < 1e-9


def test_reinforce_creates_new_pair(in_memory_db):
    """Reinforcing a non-existent pair creates it with seed weight 1.0."""
    conn = in_memory_db

    n = reinforce_cooccurrence(conn, [("X", "Y")])

    assert n == 1
    row = conn.execute(
        "SELECT weight FROM entity_cooccurrence "
        "WHERE entity_a = 'X' AND entity_b = 'Y'"
    ).fetchone()
    assert row is not None
    assert row["weight"] == 1.0


def test_reinforce_bounded(in_memory_db):
    """Reinforcement cannot push weight above MAX_COOCCURRENCE_WEIGHT (100.0)."""
    conn = in_memory_db
    # Insert pair at 99.0
    conn.execute(
        "INSERT INTO entity_cooccurrence (entity_a, entity_b, weight, last_seen) "
        "VALUES (?, ?, ?, ?)",
        ("Alpha", "Beta", 99.0, "2026-01-01"),
    )
    # Insert pair already at 100.0
    conn.execute(
        "INSERT INTO entity_cooccurrence (entity_a, entity_b, weight, last_seen) "
        "VALUES (?, ?, ?, ?)",
        ("Gamma", "Delta", 100.0, "2026-01-01"),
    )
    conn.commit()

    reinforce_cooccurrence(conn, [("Alpha", "Beta"), ("Gamma", "Delta")])

    row_99 = conn.execute(
        "SELECT weight FROM entity_cooccurrence "
        "WHERE entity_a = 'Alpha' AND entity_b = 'Beta'"
    ).fetchone()
    assert row_99["weight"] <= MAX_COOCCURRENCE_WEIGHT
    # 99.0 * 1.1 = 108.9 -> capped to 100.0
    assert row_99["weight"] == MAX_COOCCURRENCE_WEIGHT

    row_100 = conn.execute(
        "SELECT weight FROM entity_cooccurrence "
        "WHERE entity_a = 'Gamma' AND entity_b = 'Delta'"
    ).fetchone()
    # Already at max, should not increase
    assert row_100["weight"] == MAX_COOCCURRENCE_WEIGHT


def test_reinforce_canonical_order(in_memory_db):
    """Reinforcing with (Z, A) stores as (A, Z) -- canonical order."""
    conn = in_memory_db

    reinforce_cooccurrence(conn, [("Z", "A")])

    row = conn.execute(
        "SELECT entity_a, entity_b FROM entity_cooccurrence"
    ).fetchone()
    assert row["entity_a"] == "A"
    assert row["entity_b"] == "Z"


def test_reinforce_noop_no_entities(in_memory_db):
    """Empty pairs list causes no errors and no new rows."""
    conn = in_memory_db

    n = reinforce_cooccurrence(conn, [])

    assert n == 0
    count = conn.execute(
        "SELECT COUNT(*) as c FROM entity_cooccurrence"
    ).fetchone()["c"]
    assert count == 0
