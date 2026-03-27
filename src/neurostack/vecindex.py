# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""sqlite-vec vector index for KNN search over chunk and triple embeddings."""

import logging
import sqlite3

log = logging.getLogger("neurostack")

try:
    import sqlite_vec

    HAS_SQLITE_VEC = True
except ImportError:
    HAS_SQLITE_VEC = False


def load_vec_extension(conn: sqlite3.Connection) -> bool:
    """Load the sqlite-vec extension into a connection. Returns True on success."""
    if not HAS_SQLITE_VEC:
        return False
    try:
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        return True
    except Exception as e:
        log.debug("Failed to load sqlite-vec extension: %s", e)
        return False


def ensure_vec_tables(conn: sqlite3.Connection, embed_dim: int = 768) -> bool:
    """Create vec0 virtual tables if sqlite-vec is loaded. Returns True if created."""
    # Check if sqlite-vec is available on this connection
    try:
        conn.execute("SELECT vec_version()")
    except sqlite3.OperationalError:
        return False

    # Create chunk vector index
    conn.execute(
        f"CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING vec0("
        f"  chunk_id INTEGER PRIMARY KEY,"
        f"  embedding float[{embed_dim}] distance_metric=cosine"
        f")"
    )

    # Create triple vector index
    conn.execute(
        f"CREATE VIRTUAL TABLE IF NOT EXISTS vec_triples USING vec0("
        f"  triple_id INTEGER PRIMARY KEY,"
        f"  embedding float[{embed_dim}] distance_metric=cosine"
        f")"
    )

    conn.commit()
    return True


def populate_vec_chunks(conn: sqlite3.Connection) -> int:
    """Backfill vec_chunks from existing chunk embeddings. Returns count inserted."""
    # Clear existing entries
    conn.execute("DELETE FROM vec_chunks")

    rows = conn.execute(
        "SELECT chunk_id, embedding FROM chunks WHERE embedding IS NOT NULL"
    ).fetchall()

    if not rows:
        conn.commit()
        return 0

    conn.executemany(
        "INSERT INTO vec_chunks(chunk_id, embedding) VALUES (?, ?)",
        [(r["chunk_id"], r["embedding"]) for r in rows],
    )
    conn.commit()
    return len(rows)


def populate_vec_triples(conn: sqlite3.Connection) -> int:
    """Backfill vec_triples from existing triple embeddings. Returns count inserted."""
    conn.execute("DELETE FROM vec_triples")

    rows = conn.execute(
        "SELECT triple_id, embedding FROM triples WHERE embedding IS NOT NULL"
    ).fetchall()

    if not rows:
        conn.commit()
        return 0

    conn.executemany(
        "INSERT INTO vec_triples(triple_id, embedding) VALUES (?, ?)",
        [(r["triple_id"], r["embedding"]) for r in rows],
    )
    conn.commit()
    return len(rows)


def upsert_chunk_vec(conn: sqlite3.Connection, chunk_id: int, embedding_blob: bytes) -> None:
    """Insert or replace a single chunk embedding in the vector index."""
    conn.execute(
        "INSERT OR REPLACE INTO vec_chunks(chunk_id, embedding) VALUES (?, ?)",
        (chunk_id, embedding_blob),
    )


def delete_chunk_vecs(conn: sqlite3.Connection, note_path: str) -> None:
    """Remove vector index entries for all chunks of a note."""
    conn.execute(
        "DELETE FROM vec_chunks WHERE chunk_id IN "
        "(SELECT chunk_id FROM chunks WHERE note_path = ?)",
        (note_path,),
    )


def upsert_triple_vec(conn: sqlite3.Connection, triple_id: int, embedding_blob: bytes) -> None:
    """Insert or replace a single triple embedding in the vector index."""
    conn.execute(
        "INSERT OR REPLACE INTO vec_triples(triple_id, embedding) VALUES (?, ?)",
        (triple_id, embedding_blob),
    )


def delete_triple_vecs(conn: sqlite3.Connection, note_path: str) -> None:
    """Remove vector index entries for all triples of a note."""
    conn.execute(
        "DELETE FROM vec_triples WHERE triple_id IN "
        "(SELECT triple_id FROM triples WHERE note_path = ?)",
        (note_path,),
    )


def vec_knn_chunks(
    conn: sqlite3.Connection,
    query_embedding,
    k: int = 50,
    workspace: str | None = None,
) -> list[dict]:
    """KNN search over chunk embeddings using sqlite-vec.

    Returns list of dicts with chunk_id, note_path, heading_path, content, embedding, distance.
    """
    if workspace:
        # Over-fetch from KNN, then post-filter by workspace
        rows = conn.execute(
            """
            WITH knn AS (
                SELECT chunk_id, distance
                FROM vec_chunks
                WHERE embedding MATCH ? AND k = ?
            )
            SELECT c.chunk_id, c.note_path, c.heading_path, c.content, c.embedding,
                   knn.distance
            FROM knn
            JOIN chunks c ON c.chunk_id = knn.chunk_id
            WHERE c.note_path LIKE ? || '%'
            ORDER BY knn.distance
            LIMIT ?
            """,
            (query_embedding, k * 3, workspace.strip("/") + "/", k),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            WITH knn AS (
                SELECT chunk_id, distance
                FROM vec_chunks
                WHERE embedding MATCH ? AND k = ?
            )
            SELECT c.chunk_id, c.note_path, c.heading_path, c.content, c.embedding,
                   knn.distance
            FROM knn
            JOIN chunks c ON c.chunk_id = knn.chunk_id
            ORDER BY knn.distance
            LIMIT ?
            """,
            (query_embedding, k, k),
        ).fetchall()

    results = []
    for r in rows:
        results.append({
            "chunk_id": r["chunk_id"],
            "note_path": r["note_path"],
            "heading_path": r["heading_path"],
            "content": r["content"],
            "embedding": r["embedding"],
            # Convert cosine distance to similarity: sim = 1 - distance
            "score": 1.0 - float(r["distance"]),
        })
    return results


def vec_knn_triples(
    conn: sqlite3.Connection,
    query_embedding,
    k: int = 30,
    workspace: str | None = None,
) -> list[dict]:
    """KNN search over triple embeddings using sqlite-vec."""
    if workspace:
        rows = conn.execute(
            """
            WITH knn AS (
                SELECT triple_id, distance
                FROM vec_triples
                WHERE embedding MATCH ? AND k = ?
            )
            SELECT t.triple_id, t.note_path, t.subject, t.predicate, t.object,
                   t.triple_text, t.embedding, knn.distance
            FROM knn
            JOIN triples t ON t.triple_id = knn.triple_id
            WHERE t.note_path LIKE ? || '%'
            ORDER BY knn.distance
            LIMIT ?
            """,
            (query_embedding, k * 3, workspace.strip("/") + "/", k),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            WITH knn AS (
                SELECT triple_id, distance
                FROM vec_triples
                WHERE embedding MATCH ? AND k = ?
            )
            SELECT t.triple_id, t.note_path, t.subject, t.predicate, t.object,
                   t.triple_text, t.embedding, knn.distance
            FROM knn
            JOIN triples t ON t.triple_id = knn.triple_id
            ORDER BY knn.distance
            LIMIT ?
            """,
            (query_embedding, k, k),
        ).fetchall()

    results = []
    for r in rows:
        results.append({
            "triple_id": r["triple_id"],
            "note_path": r["note_path"],
            "subject": r["subject"],
            "predicate": r["predicate"],
            "object": r["object"],
            "triple_text": r["triple_text"],
            "embedding": r["embedding"],
            "score": 1.0 - float(r["distance"]),
        })
    return results


def has_vec_index(conn: sqlite3.Connection) -> bool:
    """Check if vec_chunks virtual table exists and is usable."""
    try:
        conn.execute("SELECT COUNT(*) FROM vec_chunks LIMIT 1")
        return True
    except sqlite3.OperationalError:
        return False
