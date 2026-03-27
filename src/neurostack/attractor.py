# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Attractor basin community detection — neuroscience-grounded replacement for Leiden.

Implements Hopfield-style attractor dynamics on the note embedding space:
  1. Build a blended similarity matrix from embeddings, co-occurrence, and wiki-links
  2. Run iterative softmax attractor convergence at two inverse temperatures (β)
  3. Assign communities by grouping notes that converge to the same attractor

Neuroscience basis:
  - Modern Hopfield networks: energy = -lse(β, S·ξ), β controls granularity
  - Memory consolidation: fast hippocampal encoding → slow neocortical clustering
  - Lateral inhibition: enforces community sparsity (prevents giant clusters)
  - CREB excitability: recently active notes preferentially attract neighbours

No external dependencies beyond numpy (already required for embeddings).
"""

from __future__ import annotations

import logging
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

from .cooccurrence import persist_cooccurrence
from .embedder import blob_to_embedding, cosine_similarity_batch
from .schema import DB_PATH, get_db

log = logging.getLogger("neurostack")

# ── Similarity blending weights ──
# α: semantic similarity (embedding cosine) — structural/content overlap
# β_cooc: co-occurrence weight — Hebbian "used together" signal
# γ: wiki-link weight — explicit human connections
ALPHA_SEMANTIC = 0.6
BETA_COOCCURRENCE = 0.25
GAMMA_WIKILINKS = 0.15

# ── Inverse temperature for attractor convergence ──
# Low β → broad themes (coarse), high β → narrow sub-themes (fine)
# Maps to Hopfield: β controls the sharpness of softmax retrieval
BETA_COARSE = 0.5
BETA_FINE = 2.0

# ── Convergence parameters ──
MAX_ITERATIONS = 50          # max attractor update steps (adaptive for large n)
CONVERGENCE_THRESHOLD = 1e-4  # stop when state change < threshold

# ── Sparse approximation ──
# Keep only top-K similar neighbors per note to improve convergence speed
# and reduce effective matrix density.  At n>200 the full n×n multiply
# is the dominant cost; sparsification makes softmax rows peakier so
# convergence happens in fewer iterations.
TOP_K_NEIGHBORS = 50

# Minimum shared entities for a note-note edge (co-occurrence signal)
MIN_SHARED = 2


def _build_similarity_matrix(
    conn: sqlite3.Connection,
    note_paths: list[str],
    note_embeddings: np.ndarray,
) -> np.ndarray:
    """Build blended similarity matrix from three signals.

    S = α·cosine + β·cooccurrence + γ·wikilinks

    All three matrices are normalised to [0, 1] before blending so that
    each signal contributes proportionally regardless of scale.
    """
    n = len(note_paths)
    path_to_idx = {p: i for i, p in enumerate(note_paths)}

    # 1. Semantic similarity (cosine of note embeddings)
    norms = np.linalg.norm(note_embeddings, axis=1, keepdims=True) + 1e-10
    normalised = note_embeddings / norms
    S_semantic = normalised @ normalised.T
    # Clamp to [0, 1] — negative cosine means unrelated, treat as 0
    np.clip(S_semantic, 0.0, 1.0, out=S_semantic)

    # 2. Co-occurrence signal (entity co-occurrence weights → note-note)
    S_cooc = np.zeros((n, n), dtype=np.float32)

    # Map each entity to the set of notes that mention it (via triples)
    rows = conn.execute(
        "SELECT note_path, subject, object FROM triples"
    ).fetchall()
    entity_notes: dict[str, set[str]] = defaultdict(set)
    for r in rows:
        if r["note_path"] in path_to_idx:
            entity_notes[r["subject"]].add(r["note_path"])
            entity_notes[r["object"]].add(r["note_path"])

    # Build note-note shared entity counts
    note_weights: dict[tuple[int, int], int] = defaultdict(int)
    for notes in entity_notes.values():
        note_list = [path_to_idx[p] for p in notes if p in path_to_idx]
        for i_idx in range(len(note_list)):
            for j_idx in range(i_idx + 1, len(note_list)):
                a, b = min(note_list[i_idx], note_list[j_idx]), max(
                    note_list[i_idx], note_list[j_idx]
                )
                note_weights[(a, b)] += 1

    # Also blend in learned co-occurrence weights from entity_cooccurrence
    cooc_rows = conn.execute(
        "SELECT entity_a, entity_b, weight FROM entity_cooccurrence"
    ).fetchall()
    entity_cooc: dict[str, dict[str, float]] = defaultdict(dict)
    for r in cooc_rows:
        entity_cooc[r["entity_a"]][r["entity_b"]] = r["weight"]
        entity_cooc[r["entity_b"]][r["entity_a"]] = r["weight"]

    # For each note pair, add Hebbian co-occurrence signal
    note_entities: dict[int, set[str]] = defaultdict(set)
    for r in rows:
        idx = path_to_idx.get(r["note_path"])
        if idx is not None:
            note_entities[idx].add(r["subject"])
            note_entities[idx].add(r["object"])

    for (a, b), shared_count in note_weights.items():
        if shared_count >= MIN_SHARED:
            # Base: shared entity count
            S_cooc[a, b] = float(shared_count)
            S_cooc[b, a] = float(shared_count)

            # Add Hebbian weights for shared entities
            shared_ents = note_entities[a] & note_entities[b]
            for ent in shared_ents:
                for other_ent in shared_ents:
                    if ent < other_ent and other_ent in entity_cooc.get(ent, {}):
                        w = entity_cooc[ent][other_ent]
                        S_cooc[a, b] += w
                        S_cooc[b, a] += w

    # Normalise co-occurrence to [0, 1]
    cooc_max = S_cooc.max()
    if cooc_max > 0:
        S_cooc /= cooc_max

    # 3. Wiki-link signal (graph_edges)
    S_links = np.zeros((n, n), dtype=np.float32)
    if note_paths:
        placeholders = ",".join("?" * len(note_paths))
        edge_rows = conn.execute(
            f"SELECT source_path, target_path FROM graph_edges "
            f"WHERE source_path IN ({placeholders}) "
            f"AND target_path IN ({placeholders})",
            note_paths + note_paths,
        ).fetchall()
        for r in edge_rows:
            src = path_to_idx.get(r["source_path"])
            tgt = path_to_idx.get(r["target_path"])
            if src is not None and tgt is not None:
                S_links[src, tgt] = 1.0
                S_links[tgt, src] = 1.0  # symmetric

    # Blend all three signals
    S = (
        ALPHA_SEMANTIC * S_semantic
        + BETA_COOCCURRENCE * S_cooc
        + GAMMA_WIKILINKS * S_links
    )

    # Zero out self-similarity (diagonal) — a note shouldn't attract itself
    np.fill_diagonal(S, 0.0)

    return S


def _sparsify_top_k(S: np.ndarray, k: int) -> np.ndarray:
    """Zero out all but the top-k entries per row in S.

    This makes the similarity matrix effectively sparse: each note only
    "sees" its k nearest neighbors.  The softmax rows become peakier,
    convergence happens in fewer iterations, and the practical scaling
    ceiling rises from ~2,000 to ~5,000 notes.
    """
    n = S.shape[0]
    if k >= n:
        return S
    S_sparse = np.zeros_like(S)
    # For each row, find top-k indices and copy only those values
    top_k_indices = np.argpartition(S, -k, axis=1)[:, -k:]
    rows = np.arange(n)[:, None]
    S_sparse[rows, top_k_indices] = S[rows, top_k_indices]
    return S_sparse


def _adaptive_max_iter(n: int) -> int:
    """Scale max iterations based on matrix size.

    Small vaults (≤200 notes) get the full 50 iterations.
    Larger vaults scale down — convergence is faster with sparsified S
    and the marginal benefit of extra iterations is low.
    """
    if n <= 200:
        return MAX_ITERATIONS
    if n <= 1000:
        return 30
    if n <= 3000:
        return 20
    return 15


def _attractor_convergence(
    S: np.ndarray,
    beta: float,
    max_iter: int | None = None,
    threshold: float = CONVERGENCE_THRESHOLD,
) -> np.ndarray:
    """Run Hopfield-style attractor dynamics on the similarity matrix.

    Each note's state is iteratively updated via softmax over its similarity
    row, weighted by inverse temperature β.  At convergence, notes in the
    same basin will have nearly identical state vectors.

    state_i(t+1) = softmax(β · S_i · state(t))

    For large matrices (n > TOP_K_NEIGHBORS), S is sparsified to keep only
    the top-k neighbors per row, and iterations are scaled adaptively.

    Returns the converged state matrix (n × n).
    """
    n = S.shape[0]

    # Sparsify for large matrices — keeps convergence fast
    if n > TOP_K_NEIGHBORS:
        S = _sparsify_top_k(S, TOP_K_NEIGHBORS)

    if max_iter is None:
        max_iter = _adaptive_max_iter(n)

    # Initial state: each note starts as its own one-hot (identity)
    state = np.eye(n, dtype=np.float32)

    for iteration in range(max_iter):
        # Compute logits: β * S @ state
        logits = beta * (S @ state)

        # Softmax per row (numerically stable)
        logits_max = logits.max(axis=1, keepdims=True)
        exp_logits = np.exp(logits - logits_max)
        new_state = exp_logits / (exp_logits.sum(axis=1, keepdims=True) + 1e-10)

        # Check convergence
        delta = np.abs(new_state - state).max()
        state = new_state
        if delta < threshold:
            log.info(
                f"  Attractor converged at iteration {iteration + 1}"
                f" (delta={delta:.6f})"
            )
            break
    else:
        log.info(
            f"  Attractor reached max iterations ({max_iter})"
            f" (delta={delta:.6f})"
        )

    return state


def _assign_communities(
    state: np.ndarray,
    note_paths: list[str],
) -> dict[int, list[str]]:
    """Assign notes to communities based on converged attractor states.

    Notes that converge to similar states belong to the same community.
    We assign each note to the index of its dominant attractor (argmax of
    its state vector), then group by attractor.

    Applies lateral inhibition: singleton communities (only 1 note) are
    merged into the nearest non-singleton community.
    """
    n = len(note_paths)

    # Each note's community = the note index it's most attracted to
    assignments = np.argmax(state, axis=1)

    # Group notes by attractor
    raw_communities: dict[int, list[str]] = defaultdict(list)
    for i in range(n):
        raw_communities[int(assignments[i])].append(note_paths[i])

    # Lateral inhibition: merge singletons into nearest non-singleton
    non_singletons = {
        k: v for k, v in raw_communities.items() if len(v) > 1
    }
    singletons = {
        k: v for k, v in raw_communities.items() if len(v) == 1
    }

    if non_singletons and singletons:
        # For each singleton, find the non-singleton community whose
        # attractor state is most similar
        ns_keys = sorted(non_singletons.keys())
        ns_states = np.stack([state[k] for k in ns_keys])

        for s_key, s_notes in singletons.items():
            s_state = state[s_key].reshape(1, -1)
            sims = cosine_similarity_batch(s_state[0], ns_states)
            best_idx = int(np.argmax(sims))
            best_key = ns_keys[best_idx]
            non_singletons[best_key].extend(s_notes)

        communities = non_singletons
    elif not non_singletons:
        # All singletons — no merging possible, keep as-is
        communities = raw_communities
    else:
        communities = non_singletons

    # Re-index communities from 0
    return {i: notes for i, notes in enumerate(communities.values())}


def _store_communities(
    conn: sqlite3.Connection,
    level: int,
    communities: dict[int, list[str]],
) -> None:
    """Store one level of communities into the DB."""
    now = datetime.now(timezone.utc).isoformat()

    for note_paths in communities.values():
        cursor = conn.execute(
            "INSERT INTO communities"
            " (level, entity_count, member_notes,"
            " updated_at) VALUES (?, ?, ?, ?)",
            (level, len(note_paths), len(note_paths), now),
        )
        db_id = cursor.lastrowid

        conn.executemany(
            "INSERT OR IGNORE INTO community_members"
            " (community_id, entity) VALUES (?, ?)",
            [(db_id, np_) for np_ in note_paths],
        )


def detect_communities(
    conn: sqlite3.Connection | None = None,
    db_path=None,
) -> tuple[int, int]:
    """Full pipeline: build similarity matrix, run attractor convergence, store.

    Replaces Leiden with Hopfield-style attractor basin clustering:
    1. Compute blended similarity from embeddings + co-occurrence + wiki-links
    2. Run attractor dynamics at β=0.5 (coarse) and β=2.0 (fine)
    3. Assign communities from converged basins

    Clears existing communities first (full rebuild).
    Returns (n_coarse, n_fine) community counts.
    """
    if not HAS_NUMPY:
        raise ImportError(
            "Community detection requires numpy. "
            "Install with: pip install neurostack[full]"
        )
    if conn is None:
        conn = get_db(db_path or DB_PATH)

    # Clear existing
    conn.execute("DELETE FROM community_members")
    conn.execute("DELETE FROM communities")
    conn.commit()

    # Persist entity co-occurrence weights from triples
    n_pairs = persist_cooccurrence(conn)
    log.info(f"Co-occurrence: {n_pairs} entity pairs persisted.")

    # Load all note embeddings (averaged across chunks per note)
    chunk_rows = conn.execute(
        "SELECT note_path, embedding FROM chunks WHERE embedding IS NOT NULL"
    ).fetchall()

    if not chunk_rows:
        log.warning("No embedded chunks found — skipping community detection.")
        return 0, 0

    # Average chunk embeddings per note to get note-level embeddings
    note_chunk_map: dict[str, list[np.ndarray]] = defaultdict(list)
    for r in chunk_rows:
        note_chunk_map[r["note_path"]].append(
            blob_to_embedding(r["embedding"])
        )

    note_paths = sorted(note_chunk_map.keys())
    if len(note_paths) < 3:
        log.warning(
            f"Only {len(note_paths)} notes with embeddings"
            " — need ≥3 for community detection."
        )
        return 0, 0

    note_embeddings = np.stack([
        np.mean(note_chunk_map[p], axis=0) for p in note_paths
    ])

    log.info(
        f"Building similarity matrix for {len(note_paths)} notes"
        f" ({len(chunk_rows)} chunks)..."
    )
    S = _build_similarity_matrix(conn, note_paths, note_embeddings)

    # ── Coarse communities (low β → broad basins) ──
    log.info(
        f"Running attractor convergence level 0"
        f" (coarse, β={BETA_COARSE})..."
    )
    state_coarse = _attractor_convergence(S, beta=BETA_COARSE)
    communities_coarse = _assign_communities(state_coarse, note_paths)
    _store_communities(conn, level=0, communities=communities_coarse)
    n_coarse = len(communities_coarse)

    # ── Fine communities (high β → narrow basins) ──
    log.info(
        f"Running attractor convergence level 1"
        f" (fine, β={BETA_FINE})..."
    )
    state_fine = _attractor_convergence(S, beta=BETA_FINE)
    communities_fine = _assign_communities(state_fine, note_paths)
    _store_communities(conn, level=1, communities=communities_fine)
    n_fine = len(communities_fine)

    conn.commit()
    log.info(
        f"Community detection done:"
        f" {n_coarse} coarse, {n_fine} fine communities."
    )
    return n_coarse, n_fine
