"""Tests for neurostack.embedder — context building, cosine similarity, blob conversion."""

import json

import pytest

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

from neurostack.embedder import build_chunk_context


class TestBuildChunkContext:
    def test_basic_context(self):
        result = build_chunk_context(
            title="Test Note",
            frontmatter_json=json.dumps({"type": "permanent", "tags": ["a", "b"]}),
            summary="A test summary.",
            chunk_text="The actual chunk content.",
        )
        assert "Note: Test Note" in result
        assert "Type: permanent" in result
        assert "Tags: a, b" in result
        assert "Summary: A test summary." in result
        assert "The actual chunk content." in result

    def test_no_summary(self):
        result = build_chunk_context(
            title="Note",
            frontmatter_json=json.dumps({}),
            summary=None,
            chunk_text="Content.",
        )
        assert "Summary:" not in result
        assert "Content." in result

    def test_empty_frontmatter(self):
        result = build_chunk_context(
            title="Note",
            frontmatter_json="",
            summary=None,
            chunk_text="Content.",
        )
        assert "Note: Note" in result

    def test_invalid_frontmatter_json(self):
        result = build_chunk_context(
            title="Note",
            frontmatter_json="not json",
            summary=None,
            chunk_text="Content.",
        )
        assert "Note: Note" in result
        assert "Content." in result


@pytest.mark.skipif(not HAS_NUMPY, reason="numpy required")
class TestCosineSimilarity:
    def test_identical_vectors(self):
        from neurostack.embedder import cosine_similarity
        a = np.array([1.0, 0.0, 0.0])
        assert abs(cosine_similarity(a, a) - 1.0) < 1e-6

    def test_orthogonal_vectors(self):
        from neurostack.embedder import cosine_similarity
        a = np.array([1.0, 0.0])
        b = np.array([0.0, 1.0])
        assert abs(cosine_similarity(a, b)) < 1e-6

    def test_opposite_vectors(self):
        from neurostack.embedder import cosine_similarity
        a = np.array([1.0, 0.0])
        b = np.array([-1.0, 0.0])
        assert abs(cosine_similarity(a, b) + 1.0) < 1e-6

    def test_zero_vector(self):
        from neurostack.embedder import cosine_similarity
        a = np.array([1.0, 0.0])
        b = np.array([0.0, 0.0])
        assert cosine_similarity(a, b) == 0.0

    def test_batch(self):
        from neurostack.embedder import cosine_similarity_batch
        query = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        matrix = np.array([
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.5, 0.5, 0.0],
        ], dtype=np.float32)
        scores = cosine_similarity_batch(query, matrix)
        assert scores[0] > scores[1]  # identical > orthogonal
        assert scores[2] > scores[1]  # partial > orthogonal


@pytest.mark.skipif(not HAS_NUMPY, reason="numpy required")
class TestBlobConversion:
    def test_roundtrip(self):
        from neurostack.embedder import blob_to_embedding, embedding_to_blob
        vec = np.array([0.1, 0.2, 0.3, 0.4], dtype=np.float32)
        blob = embedding_to_blob(vec)
        recovered = blob_to_embedding(blob)
        assert np.allclose(vec, recovered)
