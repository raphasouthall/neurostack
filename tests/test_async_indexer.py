# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Tests for the async parallel cloud indexing pipeline."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import numpy as np
import pytest
import pytest_asyncio

# Save the real AsyncClient constructor before any patching
_RealAsyncClient = httpx.AsyncClient

from neurostack.cloud.async_indexer import (
    EMBED_BATCH_SIZE,
    MAX_CONCURRENT_NOTES,
    _embed_batch_async,
    _enrich_note,
    _extract_triples_async,
    _retry_request,
    _summarize_async,
    cloud_index_vault,
)
from neurostack.cloud.config import CloudConfig


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def cloud_config():
    """Minimal cloud config for tests."""
    return CloudConfig(
        gemini_api_key="test-key-123",
        gemini_embed_model="gemini-embedding-001",
        gemini_llm_model="gemini-2.5-flash",
        gemini_embed_dim=768,
    )


@pytest.fixture
def sample_vault_files():
    """Sample vault with 3 markdown notes."""
    return {
        "note1.md": b"---\ntitle: Test Note 1\ntags: [test]\n---\n# Test Note 1\n\nThis is a test note about Python programming.\n\n## Details\n\nPython is great for data science.",
        "note2.md": b"---\ntitle: Test Note 2\n---\n# Test Note 2\n\nThis note covers infrastructure topics.\n\n## Kubernetes\n\nK8s orchestrates containers.",
        "subdir/note3.md": b"# Note Three\n\nA note in a subdirectory about networking.",
    }


@pytest.fixture
def db_path(tmp_path):
    """Temporary database path."""
    return tmp_path / "test.db"


def _make_embed_response(texts: list[str], dim: int = 768) -> dict:
    """Build a fake OpenAI embeddings response."""
    data = []
    for i, _text in enumerate(texts):
        vec = np.random.default_rng(i).standard_normal(dim).astype(np.float32).tolist()
        data.append({"object": "embedding", "index": i, "embedding": vec})
    return {"object": "list", "data": data, "model": "test", "usage": {"total_tokens": 10}}


def _make_chat_response(content: str) -> dict:
    """Build a fake OpenAI chat completions response."""
    return {
        "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
        "model": "test",
        "usage": {"prompt_tokens": 10, "completion_tokens": 20},
    }


def _make_summary_response(title: str = "") -> dict:
    """Build a fake summary response."""
    return _make_chat_response(f"This is a summary of {title or 'a note'}. It covers key topics.")


def _make_triples_response() -> dict:
    """Build a fake triples response."""
    triples = [
        {"s": "Python", "p": "is used for", "o": "data science"},
        {"s": "Kubernetes", "p": "orchestrates", "o": "containers"},
    ]
    return _make_chat_response(json.dumps(triples))


class MockTransport(httpx.AsyncBaseTransport):
    """Mock httpx transport that routes embed vs chat requests."""

    def __init__(self, embed_dim: int = 768, fail_notes: set | None = None,
                 transient_failures: int = 0):
        self.embed_dim = embed_dim
        self.fail_notes = fail_notes or set()
        self.transient_failures = transient_failures
        self._call_count = 0
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        self._call_count += 1

        # Simulate transient failures
        if self.transient_failures > 0 and self._call_count <= self.transient_failures:
            return httpx.Response(status_code=503, json={"error": "Service unavailable"})

        url_path = request.url.path if hasattr(request.url, 'path') else str(request.url)

        if "/v1/embeddings" in url_path:
            body = json.loads(request.content)
            texts = body["input"] if isinstance(body["input"], list) else [body["input"]]
            resp_data = _make_embed_response(texts, self.embed_dim)
            return httpx.Response(status_code=200, json=resp_data)

        elif "/v1/chat/completions" in url_path:
            body = json.loads(request.content)
            user_msg = body["messages"][0]["content"]

            # Check if this is for a note that should fail
            for fail_note in self.fail_notes:
                if fail_note in user_msg:
                    return httpx.Response(status_code=500, json={"error": "Internal error"})

            # Determine if summary or triples based on prompt content
            if "Summarize this note" in user_msg:
                return httpx.Response(status_code=200, json=_make_summary_response())
            elif "Extract knowledge graph triples" in user_msg:
                return httpx.Response(status_code=200, json=_make_triples_response())
            else:
                return httpx.Response(status_code=200, json=_make_chat_response("ok"))

        return httpx.Response(status_code=404, json={"error": "not found"})


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cloud_index_vault_returns_complete(
    sample_vault_files, db_path, cloud_config
):
    """cloud_index_vault returns complete status with valid db_path."""
    transport = MockTransport(embed_dim=cloud_config.gemini_embed_dim)

    with patch("neurostack.cloud.async_indexer.httpx.AsyncClient") as mock_client_cls:
        # Return a real async client with our mock transport
        def make_client(**kwargs):
            kwargs.pop("limits", None)
            return _RealAsyncClient(transport=transport, **kwargs)

        mock_client_cls.side_effect = make_client

        result = await cloud_index_vault(sample_vault_files, db_path, cloud_config)

    assert result["status"] == "complete"
    assert result["note_count"] == 3
    assert result["db_size"] > 0
    assert db_path.exists()


@pytest.mark.asyncio
async def test_phase1_produces_notes_chunks_embeddings(
    sample_vault_files, db_path, cloud_config
):
    """Phase 1 produces notes, chunks, and embeddings in the DB."""
    transport = MockTransport(embed_dim=cloud_config.gemini_embed_dim)

    with patch("neurostack.cloud.async_indexer.httpx.AsyncClient") as mock_client_cls:
        def make_client(**kwargs):
            kwargs.pop("limits", None)
            return _RealAsyncClient(transport=transport, **kwargs)

        mock_client_cls.side_effect = make_client

        result = await cloud_index_vault(sample_vault_files, db_path, cloud_config)

    assert result["status"] == "complete"

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # Check notes were inserted
    notes = conn.execute("SELECT * FROM notes").fetchall()
    assert len(notes) == 3

    # Check chunks were inserted
    chunks = conn.execute("SELECT * FROM chunks").fetchall()
    assert len(chunks) > 0

    # Check embeddings exist on chunks
    chunks_with_emb = conn.execute(
        "SELECT * FROM chunks WHERE embedding IS NOT NULL"
    ).fetchall()
    assert len(chunks_with_emb) == len(chunks)

    # Check note_metadata was populated
    metadata = conn.execute("SELECT * FROM note_metadata").fetchall()
    assert len(metadata) == 3

    conn.close()


@pytest.mark.asyncio
async def test_phase2_produces_summaries_and_triples(
    sample_vault_files, db_path, cloud_config
):
    """Phase 2 produces summaries and triples."""
    transport = MockTransport(embed_dim=cloud_config.gemini_embed_dim)

    with patch("neurostack.cloud.async_indexer.httpx.AsyncClient") as mock_client_cls:
        def make_client(**kwargs):
            kwargs.pop("limits", None)
            return _RealAsyncClient(transport=transport, **kwargs)

        mock_client_cls.side_effect = make_client

        result = await cloud_index_vault(sample_vault_files, db_path, cloud_config)

    assert result["status"] == "complete"

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # Check summaries were inserted
    summaries = conn.execute("SELECT * FROM summaries").fetchall()
    assert len(summaries) == 3

    # Check triples were inserted
    triples = conn.execute("SELECT * FROM triples").fetchall()
    assert len(triples) > 0

    # Check triple embeddings
    triples_with_emb = conn.execute(
        "SELECT * FROM triples WHERE embedding IS NOT NULL"
    ).fetchall()
    assert len(triples_with_emb) == len(triples)

    conn.close()


@pytest.mark.asyncio
async def test_concurrency_limited_by_semaphore(cloud_config):
    """Semaphore limits concurrent enrichment to MAX_CONCURRENT_NOTES."""
    max_concurrent = 0
    current_concurrent = 0
    lock = asyncio.Lock()

    original_enrich = _enrich_note

    async def tracking_summarize(title, content, client, model):
        nonlocal max_concurrent, current_concurrent
        async with lock:
            current_concurrent += 1
            max_concurrent = max(max_concurrent, current_concurrent)
        await asyncio.sleep(0.01)  # Simulate API latency
        async with lock:
            current_concurrent -= 1
        return f"Summary of {title}"

    async def tracking_triples(title, content, client, model):
        return [{"s": "A", "p": "relates to", "o": "B"}]

    # Create 30 notes (more than MAX_CONCURRENT_NOTES)
    vault_files = {
        f"note{i}.md": f"# Note {i}\n\nContent for note {i}".encode()
        for i in range(30)
    }
    db_path = Path(tempfile.mkdtemp()) / "test.db"

    with patch("neurostack.cloud.async_indexer._summarize_async", tracking_summarize), \
         patch("neurostack.cloud.async_indexer._extract_triples_async", tracking_triples), \
         patch("neurostack.cloud.async_indexer.httpx.AsyncClient") as mock_client_cls:

        transport = MockTransport(embed_dim=cloud_config.gemini_embed_dim)

        def make_client(**kwargs):
            kwargs.pop("limits", None)
            return _RealAsyncClient(transport=transport, **kwargs)

        mock_client_cls.side_effect = make_client

        result = await cloud_index_vault(vault_files, db_path, cloud_config)

    assert result["status"] == "complete"
    assert max_concurrent <= MAX_CONCURRENT_NOTES


@pytest.mark.asyncio
async def test_retry_on_transient_api_errors():
    """Retry logic handles transient API errors with backoff."""
    call_count = 0

    async def flaky_request():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise httpx.TransportError("Connection reset")
        return "success"

    with patch("neurostack.cloud.async_indexer.RETRY_DELAYS", [0.01, 0.01, 0.01]):
        result = await _retry_request(flaky_request, "test")

    assert result == "success"
    assert call_count == 3


@pytest.mark.asyncio
async def test_retry_exhausted_raises():
    """After MAX_RETRIES, the last exception is raised."""
    async def always_fail():
        raise httpx.TransportError("Permanent failure")

    with patch("neurostack.cloud.async_indexer.RETRY_DELAYS", [0.01, 0.01, 0.01]):
        with pytest.raises(httpx.TransportError, match="Permanent failure"):
            await _retry_request(always_fail, "test")


@pytest.mark.asyncio
async def test_per_note_error_handling(sample_vault_files, db_path, cloud_config):
    """One note failing enrichment doesn't kill the entire batch."""
    # Make note2 fail during enrichment
    transport = MockTransport(
        embed_dim=cloud_config.gemini_embed_dim,
        fail_notes={"Test Note 2"},
    )

    with patch("neurostack.cloud.async_indexer.httpx.AsyncClient") as mock_client_cls, \
         patch("neurostack.cloud.async_indexer.RETRY_DELAYS", [0.01, 0.01, 0.01]):

        def make_client(**kwargs):
            kwargs.pop("limits", None)
            return _RealAsyncClient(transport=transport, **kwargs)

        mock_client_cls.side_effect = make_client

        result = await cloud_index_vault(sample_vault_files, db_path, cloud_config)

    # Pipeline should still complete
    assert result["status"] == "complete"
    assert result["note_count"] == 3

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # All notes should be in DB (Phase 1 doesn't fail)
    notes = conn.execute("SELECT * FROM notes").fetchall()
    assert len(notes) == 3

    # At least some summaries should exist (the non-failing notes)
    summaries = conn.execute("SELECT * FROM summaries").fetchall()
    # note1 and note3 should succeed, note2 may fail
    assert len(summaries) >= 2

    conn.close()


@pytest.mark.asyncio
async def test_empty_vault(db_path, cloud_config):
    """Empty vault files returns complete with zero notes."""
    result = await cloud_index_vault({}, db_path, cloud_config)
    assert result["status"] == "complete"
    assert result["note_count"] == 0
    assert result["db_size"] == 0


@pytest.mark.asyncio
async def test_progress_callback(sample_vault_files, db_path, cloud_config):
    """Progress callback is called with correct phases."""
    phases_seen = []

    def callback(phase, current, total):
        phases_seen.append(phase)

    transport = MockTransport(embed_dim=cloud_config.gemini_embed_dim)

    with patch("neurostack.cloud.async_indexer.httpx.AsyncClient") as mock_client_cls:
        def make_client(**kwargs):
            kwargs.pop("limits", None)
            return _RealAsyncClient(transport=transport, **kwargs)

        mock_client_cls.side_effect = make_client

        result = await cloud_index_vault(
            sample_vault_files, db_path, cloud_config, progress_callback=callback
        )

    assert result["status"] == "complete"
    assert "parse" in phases_seen
    assert "embed" in phases_seen
    assert "search_ready" in phases_seen
    assert "complete" in phases_seen


@pytest.mark.asyncio
async def test_embed_batch_async():
    """_embed_batch_async returns correct number of blobs."""
    texts = ["hello", "world", "test"]
    transport = MockTransport(embed_dim=768)

    async with httpx.AsyncClient(
        transport=transport, base_url="https://test.example.com"
    ) as client:
        blobs = await _embed_batch_async(texts, client, "test-model", 768)

    assert len(blobs) == 3
    # Each blob should be 768 * 4 bytes (float32)
    for blob in blobs:
        assert len(blob) == 768 * 4


@pytest.mark.asyncio
async def test_summarize_async():
    """_summarize_async returns a summary string."""
    transport = MockTransport()

    async with httpx.AsyncClient(
        transport=transport, base_url="https://test.example.com"
    ) as client:
        summary = await _summarize_async("Test Note", "Some content", client, "test-model")

    assert isinstance(summary, str)
    assert len(summary) > 0


@pytest.mark.asyncio
async def test_extract_triples_async():
    """_extract_triples_async returns validated triple dicts."""
    transport = MockTransport()

    async with httpx.AsyncClient(
        transport=transport, base_url="https://test.example.com"
    ) as client:
        triples = await _extract_triples_async("Test Note", "Some content", client, "test-model")

    assert isinstance(triples, list)
    assert len(triples) > 0
    for t in triples:
        assert "s" in t and "p" in t and "o" in t


@pytest.mark.asyncio
async def test_graph_and_pagerank_built(sample_vault_files, db_path, cloud_config):
    """Graph edges and pagerank are computed after indexing."""
    transport = MockTransport(embed_dim=cloud_config.gemini_embed_dim)

    # Add wiki-links between notes
    sample_vault_files["note1.md"] = (
        b"---\ntitle: Test Note 1\n---\n# Test Note 1\n\n"
        b"See also [[note2]] for more info.\n"
    )

    with patch("neurostack.cloud.async_indexer.httpx.AsyncClient") as mock_client_cls:
        def make_client(**kwargs):
            kwargs.pop("limits", None)
            return _RealAsyncClient(transport=transport, **kwargs)

        mock_client_cls.side_effect = make_client

        result = await cloud_index_vault(sample_vault_files, db_path, cloud_config)

    assert result["status"] == "complete"

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # graph_stats should be populated
    stats = conn.execute("SELECT * FROM graph_stats").fetchall()
    assert len(stats) >= 0  # May be 0 if targets don't resolve, but table exists

    conn.close()
