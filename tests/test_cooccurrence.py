"""Tests for neurostack.cooccurrence — entity co-occurrence persistence."""

import sqlite3

import pytest

from neurostack.cooccurrence import persist_cooccurrence


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
