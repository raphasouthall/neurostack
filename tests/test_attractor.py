"""Tests for neurostack.attractor — Hopfield-style attractor basin community detection."""

from unittest.mock import patch

import numpy as np
import pytest

from neurostack.attractor import (
    ALPHA_SEMANTIC,
    GAMMA_WIKILINKS,
    TOP_K_NEIGHBORS,
    _adaptive_max_iter,
    _assign_communities,
    _attractor_convergence,
    _build_similarity_matrix,
    _sparsify_top_k,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _insert_note(conn, path, title="test"):
    """Insert a note row."""
    conn.execute(
        "INSERT INTO notes (path, title, content_hash, updated_at) "
        "VALUES (?, ?, ?, ?) ON CONFLICT(path) DO NOTHING",
        (path, title, "hash", "2026-01-01"),
    )


def _insert_chunk_with_embedding(conn, note_path, embedding, position=0):
    """Insert a chunk with a fake embedding blob."""
    blob = np.asarray(embedding, dtype=np.float32).tobytes()
    conn.execute(
        "INSERT INTO chunks (note_path, heading_path, content, content_hash, "
        "position, embedding) VALUES (?, ?, ?, ?, ?, ?)",
        (note_path, "", "chunk text", "hash", position, blob),
    )


def _insert_triple(conn, note_path, subject, obj):
    """Insert a triple."""
    conn.execute(
        "INSERT INTO triples (note_path, subject, predicate, object, triple_text) "
        "VALUES (?, ?, ?, ?, ?)",
        (note_path, subject, "relates_to", obj, f"{subject} relates_to {obj}"),
    )


def _insert_graph_edge(conn, source, target):
    """Insert a wiki-link graph edge."""
    conn.execute(
        "INSERT INTO graph_edges (source_path, target_path, link_text) "
        "VALUES (?, ?, ?)",
        (source, target, ""),
    )


# ---------------------------------------------------------------------------
# _sparsify_top_k
# ---------------------------------------------------------------------------

class TestSparsifyTopK:
    def test_preserves_top_k_values(self):
        """Top-k entries per row are preserved; others are zeroed."""
        np.random.seed(42)
        S = np.random.rand(5, 5).astype(np.float32)
        k = 2
        result = _sparsify_top_k(S, k)

        for row_idx in range(5):
            # Exactly k non-zero entries per row
            nonzero = np.count_nonzero(result[row_idx])
            assert nonzero == k

            # The non-zero values match the originals
            top_k_idx = np.argsort(S[row_idx])[-k:]
            for idx in top_k_idx:
                assert result[row_idx, idx] == S[row_idx, idx]

    def test_zeros_non_top_k(self):
        """Entries outside top-k are zero — each row has exactly k nonzeros.

        Note: _sparsify_top_k uses S.shape[0] (rows) as n, so the matrix
        must be square (or at least have more rows than k) to trigger sparsification.
        """
        S = np.array([
            [0.1, 0.5, 0.3, 0.9],
            [0.8, 0.2, 0.6, 0.4],
            [0.4, 0.7, 0.1, 0.3],
            [0.2, 0.6, 0.9, 0.5],
        ], dtype=np.float32)
        result = _sparsify_top_k(S, k=2)

        # Each row should have exactly k non-zero entries
        for row_idx in range(4):
            assert np.count_nonzero(result[row_idx]) == 2

        # The top-2 values per row should be preserved
        for row_idx in range(4):
            top2 = np.sort(S[row_idx])[-2:]
            kept = np.sort(result[row_idx][result[row_idx] > 0])
            np.testing.assert_allclose(kept, top2)

    def test_k_ge_n_returns_unchanged(self):
        """When k >= n, the matrix is returned unchanged."""
        S = np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float32)
        result = _sparsify_top_k(S, k=2)
        np.testing.assert_array_equal(result, S)

        result_larger = _sparsify_top_k(S, k=10)
        np.testing.assert_array_equal(result_larger, S)

    def test_k_one_keeps_single_max(self):
        """With k=1, only the maximum entry per row survives."""
        S = np.array([
            [0.1, 0.9, 0.5],
            [0.7, 0.3, 0.8],
        ], dtype=np.float32)
        result = _sparsify_top_k(S, k=1)
        assert np.count_nonzero(result[0]) == 1
        assert result[0, 1] == pytest.approx(0.9)
        assert np.count_nonzero(result[1]) == 1
        assert result[1, 2] == pytest.approx(0.8)


# ---------------------------------------------------------------------------
# _adaptive_max_iter
# ---------------------------------------------------------------------------

class TestAdaptiveMaxIter:
    def test_small_vault(self):
        assert _adaptive_max_iter(1) == 50
        assert _adaptive_max_iter(100) == 50
        assert _adaptive_max_iter(200) == 50

    def test_medium_vault(self):
        assert _adaptive_max_iter(201) == 30
        assert _adaptive_max_iter(500) == 30
        assert _adaptive_max_iter(1000) == 30

    def test_large_vault(self):
        assert _adaptive_max_iter(1001) == 20
        assert _adaptive_max_iter(2000) == 20
        assert _adaptive_max_iter(3000) == 20

    def test_very_large_vault(self):
        assert _adaptive_max_iter(3001) == 15
        assert _adaptive_max_iter(10000) == 15

    def test_boundary_values(self):
        """Exact boundary transitions."""
        assert _adaptive_max_iter(200) == 50
        assert _adaptive_max_iter(201) == 30
        assert _adaptive_max_iter(1000) == 30
        assert _adaptive_max_iter(1001) == 20
        assert _adaptive_max_iter(3000) == 20
        assert _adaptive_max_iter(3001) == 15


# ---------------------------------------------------------------------------
# _attractor_convergence
# ---------------------------------------------------------------------------

class TestAttractorConvergence:
    def test_output_shape(self):
        """State matrix is n x n."""
        n = 10
        S = np.random.rand(n, n).astype(np.float32)
        np.fill_diagonal(S, 0.0)
        S = (S + S.T) / 2
        state = _attractor_convergence(S, beta=1.0, max_iter=5)
        assert state.shape == (n, n)

    def test_rows_are_probability_distributions(self):
        """Each row of the converged state should sum to approximately 1."""
        np.random.seed(42)
        n = 8
        S = np.random.rand(n, n).astype(np.float32)
        np.fill_diagonal(S, 0.0)
        S = (S + S.T) / 2
        state = _attractor_convergence(S, beta=1.0, max_iter=20)

        row_sums = state.sum(axis=1)
        np.testing.assert_allclose(row_sums, 1.0, atol=1e-5)

    def test_all_entries_non_negative(self):
        """Softmax output is always >= 0."""
        np.random.seed(42)
        n = 6
        S = np.random.rand(n, n).astype(np.float32)
        np.fill_diagonal(S, 0.0)
        state = _attractor_convergence(S, beta=2.0, max_iter=10)
        assert np.all(state >= 0.0)

    def test_well_separated_clusters_converge(self):
        """Two well-separated clusters should converge to distinct attractors."""
        n = 6
        S = np.zeros((n, n), dtype=np.float32)
        # Cluster A: notes 0, 1, 2 — high mutual similarity
        for i in range(3):
            for j in range(3):
                if i != j:
                    S[i, j] = 0.9
        # Cluster B: notes 3, 4, 5 — high mutual similarity
        for i in range(3, 6):
            for j in range(3, 6):
                if i != j:
                    S[i, j] = 0.9
        # Zero cross-cluster similarity
        state = _attractor_convergence(S, beta=5.0, max_iter=100)

        # Use _assign_communities which handles the grouping logic
        paths = [f"note{i}.md" for i in range(n)]
        communities = _assign_communities(state, paths)

        # Should produce 2 communities
        assert len(communities) == 2

        # Each community should contain only within-cluster notes
        cluster_a = {"note0.md", "note1.md", "note2.md"}
        cluster_b = {"note3.md", "note4.md", "note5.md"}
        comm_sets = [set(v) for v in communities.values()]
        assert cluster_a in comm_sets
        assert cluster_b in comm_sets

    def test_sparsification_for_large_n(self):
        """When n > TOP_K_NEIGHBORS, sparsification should still produce valid output."""
        n = TOP_K_NEIGHBORS + 10
        np.random.seed(42)
        S = np.random.rand(n, n).astype(np.float32) * 0.1
        np.fill_diagonal(S, 0.0)
        S = (S + S.T) / 2

        state = _attractor_convergence(S, beta=1.0, max_iter=5)
        assert state.shape == (n, n)
        row_sums = state.sum(axis=1)
        np.testing.assert_allclose(row_sums, 1.0, atol=1e-5)

    def test_identity_initial_state(self):
        """With beta=0, softmax should produce uniform distributions."""
        n = 4
        S = np.ones((n, n), dtype=np.float32)
        np.fill_diagonal(S, 0.0)
        state = _attractor_convergence(S, beta=0.0, max_iter=5)
        # beta=0 means logits are all zero, softmax is uniform
        expected = np.full((n, n), 1.0 / n, dtype=np.float32)
        np.testing.assert_allclose(state, expected, atol=1e-5)


# ---------------------------------------------------------------------------
# _assign_communities
# ---------------------------------------------------------------------------

class TestAssignCommunities:
    def test_basic_grouping(self):
        """Notes attracted to the same index are grouped together."""
        # State where notes 0,1 are attracted to 0, notes 2,3 attracted to 2
        state = np.array([
            [0.8, 0.1, 0.05, 0.05],
            [0.7, 0.2, 0.05, 0.05],
            [0.05, 0.05, 0.8, 0.1],
            [0.05, 0.05, 0.7, 0.2],
        ], dtype=np.float32)
        paths = ["a.md", "b.md", "c.md", "d.md"]

        communities = _assign_communities(state, paths)

        # Should be 2 communities
        assert len(communities) == 2
        all_notes = []
        for notes in communities.values():
            all_notes.extend(notes)
        assert sorted(all_notes) == sorted(paths)

        # Check grouping: a,b together and c,d together
        for notes in communities.values():
            if "a.md" in notes:
                assert "b.md" in notes
            if "c.md" in notes:
                assert "d.md" in notes

    def test_singleton_merging(self):
        """Singleton communities are merged into nearest non-singleton."""
        # Notes 0,1 form a cluster; note 2 is a singleton closer to cluster 0,1
        state = np.array([
            [0.8, 0.15, 0.05],
            [0.7, 0.25, 0.05],
            [0.1, 0.1, 0.8],  # singleton — attracted to self
        ], dtype=np.float32)
        paths = ["a.md", "b.md", "c.md"]

        # Mock cosine_similarity_batch to return similarity favouring the
        # non-singleton community
        def mock_csb(query, matrix):
            return np.array([0.9])  # high similarity to the only non-singleton

        with patch("neurostack.attractor.cosine_similarity_batch", mock_csb):
            communities = _assign_communities(state, paths)

        # Singleton should have been merged — only 1 community
        assert len(communities) == 1
        assert sorted(communities[0]) == ["a.md", "b.md", "c.md"]

    def test_all_singletons_kept(self):
        """When all communities are singletons, they are kept as-is."""
        # Identity state — each note attracted only to itself
        state = np.eye(3, dtype=np.float32)
        paths = ["a.md", "b.md", "c.md"]

        communities = _assign_communities(state, paths)

        # 3 singleton communities
        assert len(communities) == 3
        all_notes = []
        for notes in communities.values():
            all_notes.extend(notes)
        assert sorted(all_notes) == sorted(paths)

    def test_reindexed_from_zero(self):
        """Community keys are re-indexed from 0."""
        state = np.array([
            [0.8, 0.1, 0.05, 0.05],
            [0.7, 0.2, 0.05, 0.05],
            [0.05, 0.05, 0.8, 0.1],
            [0.05, 0.05, 0.7, 0.2],
        ], dtype=np.float32)
        paths = ["a.md", "b.md", "c.md", "d.md"]

        communities = _assign_communities(state, paths)
        assert list(communities.keys()) == list(range(len(communities)))


# ---------------------------------------------------------------------------
# _build_similarity_matrix
# ---------------------------------------------------------------------------

class TestBuildSimilarityMatrix:
    def test_shape_and_diagonal(self, in_memory_db):
        """Matrix is n x n with zero diagonal."""
        conn = in_memory_db
        np.random.seed(42)
        dim = 32
        paths = ["note_a.md", "note_b.md", "note_c.md"]

        for p in paths:
            _insert_note(conn, p)
            emb = np.random.randn(dim).astype(np.float32)
            _insert_chunk_with_embedding(conn, p, emb)
        conn.commit()

        np.random.seed(42)  # re-seed for same embeddings
        embs = np.stack([
            np.random.randn(dim).astype(np.float32) for _ in paths
        ])

        S = _build_similarity_matrix(conn, paths, embs)

        assert S.shape == (3, 3)
        np.testing.assert_array_equal(np.diag(S), 0.0)

    def test_semantic_only(self, in_memory_db):
        """With no triples or edges, only semantic signal contributes."""
        conn = in_memory_db
        np.random.seed(42)
        dim = 16

        paths = ["a.md", "b.md"]
        for p in paths:
            _insert_note(conn, p)
        conn.commit()

        # Two identical embeddings should give high similarity
        emb = np.random.randn(dim).astype(np.float32)
        embs = np.stack([emb, emb])

        S = _build_similarity_matrix(conn, paths, embs)

        # Diagonal is zero
        assert S[0, 0] == 0.0
        # Off-diagonal should be ALPHA_SEMANTIC * 1.0 (cosine=1 for identical)
        assert S[0, 1] == pytest.approx(ALPHA_SEMANTIC, abs=1e-4)

    def test_wikilink_signal(self, in_memory_db):
        """Wiki-link edges add GAMMA_WIKILINKS to similarity."""
        conn = in_memory_db
        dim = 16
        paths = ["a.md", "b.md"]

        for p in paths:
            _insert_note(conn, p)
        _insert_graph_edge(conn, "a.md", "b.md")
        conn.commit()

        # Orthogonal embeddings so semantic ~ 0
        embs = np.eye(2, dim, dtype=np.float32)

        S = _build_similarity_matrix(conn, paths, embs)

        # Should include the wiki-link contribution
        assert S[0, 1] >= GAMMA_WIKILINKS - 0.01

    def test_cooccurrence_signal(self, in_memory_db):
        """Shared entities across notes add co-occurrence signal."""
        conn = in_memory_db
        dim = 16
        paths = ["a.md", "b.md"]

        for p in paths:
            _insert_note(conn, p)

        # Both notes share entities "Alpha" and "Beta" (MIN_SHARED=2)
        _insert_triple(conn, "a.md", "Alpha", "Beta")
        _insert_triple(conn, "b.md", "Alpha", "Beta")
        conn.commit()

        # Orthogonal embeddings
        embs = np.eye(2, dim, dtype=np.float32)

        S = _build_similarity_matrix(conn, paths, embs)

        # Co-occurrence contribution should be present
        assert S[0, 1] > 0.0

    def test_symmetric(self, in_memory_db):
        """Similarity matrix should be symmetric."""
        conn = in_memory_db
        np.random.seed(42)
        dim = 16
        paths = ["a.md", "b.md", "c.md"]

        for p in paths:
            _insert_note(conn, p)
        _insert_graph_edge(conn, "a.md", "b.md")
        _insert_triple(conn, "a.md", "X", "Y")
        _insert_triple(conn, "b.md", "X", "Y")
        conn.commit()

        embs = np.random.randn(3, dim).astype(np.float32)
        S = _build_similarity_matrix(conn, paths, embs)

        np.testing.assert_allclose(S, S.T, atol=1e-6)

    def test_values_bounded(self, in_memory_db):
        """All entries should be non-negative (clamped cosine + normalised signals)."""
        conn = in_memory_db
        np.random.seed(42)
        dim = 16
        paths = ["a.md", "b.md", "c.md"]

        for p in paths:
            _insert_note(conn, p)
        conn.commit()

        embs = np.random.randn(3, dim).astype(np.float32)
        S = _build_similarity_matrix(conn, paths, embs)

        assert np.all(S >= 0.0)
