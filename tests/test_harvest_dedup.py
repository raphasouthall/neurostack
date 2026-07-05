# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Tests for harvest cosine-similarity dedup with FTS fallback (issue #36)."""

import pytest

from neurostack import config as nsconfig

np = pytest.importorskip("numpy")

from neurostack.harvest import _is_duplicate  # noqa: E402


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROSTACK_DB_DIR", str(tmp_path))
    nsconfig._config = None
    from neurostack.schema import get_db

    conn = get_db()
    yield conn
    conn.close()
    nsconfig._config = None


def _vec(*xs):
    return np.array(xs, dtype=np.float32)


def _save(conn, content, entity_type="learning"):
    from neurostack.memories import save_memory

    return save_memory(conn, content=content, entity_type=entity_type, embed_url="x")


class TestCosineDedup:
    def test_cosine_catches_paraphrase(self, db, monkeypatch):
        # Different wording, overlapping keywords, identical embedding → duplicate.
        # This is the class FTS5's strict all-terms match lets through.
        from neurostack import embedder

        monkeypatch.setattr(embedder, "get_embedding", lambda *a, **k: _vec(1, 0, 0))
        _save(db, "Harrods supply chain integration is complex")
        assert _is_duplicate(
            db, "Harrods supply chain rollout is complicated", "learning", embed_url="x"
        ) is True

    def test_semantically_distinct_not_duplicate(self, db, monkeypatch):
        # Shares keywords but orthogonal embedding → cosine rejects, and the FTS
        # floor's all-terms match also misses (different exact words).
        from neurostack import embedder

        def embed(content, *a, **k):
            return _vec(1, 0, 0) if "integration" in content else _vec(0, 0, 1)

        monkeypatch.setattr(embedder, "get_embedding", embed)
        _save(db, "Harrods supply chain integration is complex")
        assert _is_duplicate(
            db, "Harrods supply chain rollout differs entirely", "learning", embed_url="x"
        ) is False

    def test_fts_fallback_when_embedder_down(self, db, monkeypatch):
        from neurostack import embedder

        monkeypatch.setattr(embedder, "get_embedding", lambda *a, **k: _vec(1, 0, 0))
        _save(db, "The AKS cluster upgrade must leave version 1.33")

        def boom(*a, **k):
            raise RuntimeError("embedder down")

        monkeypatch.setattr(embedder, "get_embedding", boom)
        # No embeddings available, but identical content still dedups via FTS.
        assert _is_duplicate(
            db, "The AKS cluster upgrade must leave version 1.33", "learning", embed_url="x"
        ) is True

    def test_dedup_is_per_entity_type(self, db, monkeypatch):
        from neurostack import embedder

        monkeypatch.setattr(embedder, "get_embedding", lambda *a, **k: _vec(1, 0, 0))
        _save(db, "Harrods supply chain integration is complex", entity_type="learning")
        # Same content, different type → not a duplicate.
        assert _is_duplicate(
            db, "Harrods supply chain integration is complex", "observation", embed_url="x"
        ) is False
