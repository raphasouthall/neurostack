# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Async parallel cloud indexing pipeline for NeuroStack Cloud.

Two-phase pipeline replacing the sequential subprocess-based indexer:
  Phase 1 (embed-only, ~45s): Parse all -> FTS5 insert -> batch embed at 100/call
  Phase 2 (enrichment, ~5min): 20 concurrent notes via asyncio.Semaphore -> summaries + triples

All DB writes happen in the main thread after async gather (SQLite is single-writer).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import httpx
import numpy as np

from neurostack.chunker import parse_note
from neurostack.cooccurrence import persist_cooccurrence, upsert_cooccurrence_for_note
from neurostack.embedder import build_chunk_context, embedding_to_blob
from neurostack.graph import build_graph, compute_pagerank
from neurostack.schema import get_db
from neurostack.summarizer import SUMMARY_PROMPT
from neurostack.triples import TRIPLE_PROMPT, triple_to_text

from .config import GEMINI_BASE_URL, CloudConfig

log = logging.getLogger("neurostack.cloud.async_indexer")

# Concurrency limits
MAX_CONCURRENT_NOTES = 20
EMBED_BATCH_SIZE = 100

# Retry settings
MAX_RETRIES = 3
RETRY_DELAYS = [1.0, 2.0, 4.0]


async def _retry_request(coro_factory, description: str = "API call"):
    """Retry an async HTTP request with exponential backoff.

    Args:
        coro_factory: A callable that returns a new coroutine each call.
        description: Label for log messages.

    Returns:
        The result of the successful coroutine.

    Raises:
        The last exception if all retries are exhausted.
    """
    last_exc = None
    for attempt in range(MAX_RETRIES):
        try:
            return await coro_factory()
        except (httpx.HTTPStatusError, httpx.TransportError, httpx.TimeoutException) as exc:
            last_exc = exc
            if attempt < MAX_RETRIES - 1:
                delay = RETRY_DELAYS[attempt]
                log.warning(
                    "%s failed (attempt %d/%d), retrying in %.1fs: %s",
                    description, attempt + 1, MAX_RETRIES, delay, exc,
                )
                await asyncio.sleep(delay)
            else:
                log.error(
                    "%s failed after %d attempts: %s",
                    description, MAX_RETRIES, exc,
                )
    raise last_exc  # type: ignore[misc]


async def _embed_batch_async(
    texts: list[str],
    client: httpx.AsyncClient,
    model: str,
    dim: int,
) -> list[bytes]:
    """Embed a batch of texts, return as blob bytes for SQLite."""
    payload: dict = {"model": model, "input": texts}
    if dim:
        payload["dimensions"] = dim

    async def _do_request():
        resp = await client.post("/v1/embeddings", json=payload, timeout=120.0)
        resp.raise_for_status()
        return resp

    resp = await _retry_request(_do_request, f"embed batch ({len(texts)} texts)")
    data = resp.json()

    blobs = []
    for item in data["data"]:
        vec = np.array(item["embedding"], dtype=np.float32)
        blobs.append(vec.tobytes())
    return blobs


async def _summarize_async(
    title: str, content: str, client: httpx.AsyncClient, model: str
) -> str:
    """Generate note summary via Gemini API."""
    if len(content) > 3000:
        content = content[:3000] + "\n[... truncated]"

    prompt = SUMMARY_PROMPT.format(title=title, content=content)

    async def _do_request():
        resp = await client.post(
            "/v1/chat/completions",
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "reasoning_effort": "none",
                "temperature": 0.3,
                "max_tokens": 200,
            },
            timeout=120.0,
        )
        resp.raise_for_status()
        return resp

    resp = await _retry_request(_do_request, f"summarize '{title}'")
    data = resp.json()
    summary = data["choices"][0]["message"]["content"].strip()

    # Strip think tags if model includes them despite reasoning_effort=none
    summary = re.sub(r"<think>.*?</think>", "", summary, flags=re.DOTALL).strip()
    return summary


async def _extract_triples_async(
    title: str, content: str, client: httpx.AsyncClient, model: str
) -> list[dict]:
    """Extract SPO triples via Gemini API."""
    if len(content) > 4000:
        content = content[:4000] + "\n[... truncated]"

    prompt = TRIPLE_PROMPT.format(title=title, content=content)

    async def _do_request():
        resp = await client.post(
            "/v1/chat/completions",
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "reasoning_effort": "none",
                "temperature": 0.2,
                "max_tokens": 2048,
            },
            timeout=180.0,
        )
        resp.raise_for_status()
        return resp

    resp = await _retry_request(_do_request, f"extract triples '{title}'")
    data = resp.json()
    raw = data["choices"][0]["message"]["content"].strip()

    # Strip markdown fences if present
    if raw.startswith("```"):
        raw = re.sub(r"^```\w*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw).strip()

    try:
        triples = json.loads(raw)
    except json.JSONDecodeError as e:
        log.warning("JSON parse error for '%s': %s", title, e)
        return []

    # Validate structure
    valid = []
    for t in triples:
        if isinstance(t, dict) and "s" in t and "p" in t and "o" in t:
            s = str(t["s"]).strip()
            p = str(t["p"]).strip()
            o = str(t["o"]).strip()
            if s and p and o:
                valid.append({"s": s, "p": p, "o": o})

    return valid


async def _enrich_note(
    note_path: str,
    title: str,
    content: str,
    semaphore: asyncio.Semaphore,
    client: httpx.AsyncClient,
    model: str,
) -> dict:
    """Enrich a single note with summary + triples, respecting concurrency.

    Returns dict with note_path, summary, triples, and error (if any).
    """
    async with semaphore:
        result = {"note_path": note_path, "summary": None, "triples": [], "error": None}
        try:
            summary, triples = await asyncio.gather(
                _summarize_async(title, content, client, model),
                _extract_triples_async(title, content, client, model),
            )
            result["summary"] = summary
            result["triples"] = triples
        except Exception as exc:
            log.warning("Enrichment failed for %s: %s", note_path, exc)
            result["error"] = str(exc)
            # Try individual operations so partial success is possible
            try:
                result["summary"] = await _summarize_async(title, content, client, model)
            except Exception:
                pass
            try:
                result["triples"] = await _extract_triples_async(title, content, client, model)
            except Exception:
                pass
        return result


async def cloud_index_vault(
    vault_files: dict[str, bytes],
    db_path: Path,
    config: CloudConfig,
    progress_callback=None,
) -> dict:
    """Index vault files using async parallel Gemini API calls.

    Two-phase pipeline:
    1. Parse all -> FTS5 + embed (fast, ~45s for 500 notes)
    2. Parallel enrichment: summarize + triples (20 concurrent, ~5min)

    Args:
        vault_files: Mapping of filename -> file content bytes.
        db_path: Path where the SQLite database will be created.
        config: Cloud configuration with Gemini API credentials.
        progress_callback: Optional callable(phase, current, total).

    Returns:
        Dict with status, db_size, note_count on success,
        or status, error on failure.
    """
    total_notes = len(vault_files)
    if total_notes == 0:
        return {"status": "complete", "db_size": 0, "note_count": 0}

    with tempfile.TemporaryDirectory(prefix="ns-async-idx-") as tmpdir:
        vault_dir = Path(tmpdir)

        # Write vault files to temp dir for parsing
        for filename, content in vault_files.items():
            filepath = vault_dir / filename
            filepath.parent.mkdir(parents=True, exist_ok=True)
            filepath.write_bytes(content)

        # Create SQLite DB
        conn = get_db(db_path)
        now = datetime.now(timezone.utc).isoformat()

        # ---------------------------------------------------------------
        # Phase 1: Parse + FTS5 + Embed
        # ---------------------------------------------------------------
        parsed_notes = []
        all_chunk_texts = []  # (note_index, chunk_index, context_text)
        chunk_registry = []  # flat list of (parsed_note, chunk, frontmatter_json)

        for i, (filename, _content_bytes) in enumerate(vault_files.items()):
            filepath = vault_dir / filename
            if not filepath.exists():
                continue

            try:
                parsed = parse_note(filepath, vault_dir)
            except Exception as exc:
                log.warning("Parse failed for %s: %s", filename, exc)
                continue

            parsed_notes.append(parsed)
            frontmatter_json = json.dumps(parsed.frontmatter, default=str)

            # Insert note
            conn.execute(
                """INSERT OR REPLACE INTO notes (path, title, frontmatter, content_hash, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (parsed.path, parsed.title, frontmatter_json, parsed.content_hash, now),
            )

            # Insert note_metadata
            fm = parsed.frontmatter or {}
            conn.execute(
                "INSERT INTO note_metadata"
                " (note_path, status, tags, note_type,"
                "  actionable, compositional, date_added)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(note_path) DO UPDATE SET"
                "  tags = excluded.tags,"
                "  note_type = excluded.note_type,"
                "  actionable = excluded.actionable,"
                "  compositional = excluded.compositional",
                (
                    parsed.path,
                    fm.get("status", "active"),
                    json.dumps(fm.get("tags", [])),
                    fm.get("type", "permanent"),
                    1 if fm.get("actionable") else 0,
                    1 if fm.get("compositional") else 0,
                    fm.get("date", now[:10]),
                ),
            )

            # Delete old chunks for this note
            conn.execute("DELETE FROM chunks WHERE note_path = ?", (parsed.path,))

            # Collect chunk texts for batch embedding (no summary yet in Phase 1)
            for chunk in parsed.chunks:
                context_text = build_chunk_context(
                    parsed.title, frontmatter_json, None, chunk.content
                )
                all_chunk_texts.append(context_text)
                chunk_registry.append((parsed, chunk, frontmatter_json))

            if progress_callback:
                progress_callback("parse", i + 1, total_notes)

        # Batch embed ALL chunks
        auth_headers = {}
        if config.gemini_api_key:
            auth_headers["Authorization"] = f"Bearer {config.gemini_api_key}"

        all_chunk_blobs: list[bytes | None] = [None] * len(all_chunk_texts)

        if all_chunk_texts:
            async with httpx.AsyncClient(
                base_url=GEMINI_BASE_URL, headers=auth_headers
            ) as client:
                for batch_start in range(0, len(all_chunk_texts), EMBED_BATCH_SIZE):
                    batch_end = min(batch_start + EMBED_BATCH_SIZE, len(all_chunk_texts))
                    batch = all_chunk_texts[batch_start:batch_end]
                    try:
                        blobs = await _embed_batch_async(
                            batch, client, config.gemini_embed_model, config.gemini_embed_dim
                        )
                        for j, blob in enumerate(blobs):
                            all_chunk_blobs[batch_start + j] = blob
                    except Exception as exc:
                        log.warning(
                            "Embedding batch %d-%d failed: %s", batch_start, batch_end, exc
                        )

                    if progress_callback:
                        progress_callback("embed", min(batch_end, len(all_chunk_texts)), len(all_chunk_texts))

        # Insert all chunks with embeddings
        for idx, (parsed, chunk, _fm_json) in enumerate(chunk_registry):
            emb_blob = all_chunk_blobs[idx]
            conn.execute(
                "INSERT INTO chunks"
                " (note_path, heading_path, content,"
                " content_hash, position, embedding)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    parsed.path,
                    chunk.heading_path,
                    chunk.content,
                    hashlib.sha256(chunk.content.encode()).hexdigest()[:16],
                    chunk.position,
                    emb_blob,
                ),
            )

        conn.commit()

        # Report search_ready
        if progress_callback:
            progress_callback("search_ready", total_notes, total_notes)

        # ---------------------------------------------------------------
        # Phase 2: Parallel Enrichment (summarize + triples)
        # ---------------------------------------------------------------
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_NOTES)

        # Build note contents for enrichment
        note_contents = {}
        for parsed in parsed_notes:
            full_content = "\n\n".join(c.content for c in parsed.chunks)
            note_contents[parsed.path] = (parsed.title, full_content)

        async with httpx.AsyncClient(
            base_url=GEMINI_BASE_URL,
            headers=auth_headers,
            limits=httpx.Limits(
                max_connections=MAX_CONCURRENT_NOTES + 5,
                max_keepalive_connections=MAX_CONCURRENT_NOTES,
            ),
        ) as client:
            tasks = []
            for note_path, (title, content) in note_contents.items():
                tasks.append(
                    _enrich_note(
                        note_path, title, content,
                        semaphore, client, config.gemini_llm_model,
                    )
                )

            enrichment_results = await asyncio.gather(*tasks)

        # Collect all triple texts for batch embedding
        all_triple_texts = []
        triple_registry = []  # (note_path, triple_dict, triple_text)

        for result in enrichment_results:
            note_path = result["note_path"]
            for t in result.get("triples", []):
                text = triple_to_text(t)
                all_triple_texts.append(text)
                triple_registry.append((note_path, t, text))

        # Batch embed all triples
        all_triple_blobs: list[bytes | None] = [None] * len(all_triple_texts)

        if all_triple_texts:
            async with httpx.AsyncClient(
                base_url=GEMINI_BASE_URL, headers=auth_headers
            ) as client:
                for batch_start in range(0, len(all_triple_texts), EMBED_BATCH_SIZE):
                    batch_end = min(batch_start + EMBED_BATCH_SIZE, len(all_triple_texts))
                    batch = all_triple_texts[batch_start:batch_end]
                    try:
                        blobs = await _embed_batch_async(
                            batch, client, config.gemini_embed_model, config.gemini_embed_dim
                        )
                        for j, blob in enumerate(blobs):
                            all_triple_blobs[batch_start + j] = blob
                    except Exception as exc:
                        log.warning(
                            "Triple embedding batch %d-%d failed: %s",
                            batch_start, batch_end, exc,
                        )

        # Write all summaries + triples to DB (sequential, single writer)
        for result in enrichment_results:
            note_path = result["note_path"]

            # Write summary
            if result.get("summary"):
                parsed_match = next(
                    (p for p in parsed_notes if p.path == note_path), None
                )
                content_hash = parsed_match.content_hash if parsed_match else ""
                conn.execute(
                    "INSERT OR REPLACE INTO summaries"
                    " (note_path, summary_text, content_hash, updated_at)"
                    " VALUES (?, ?, ?, ?)",
                    (note_path, result["summary"], content_hash, now),
                )

            # Delete old triples
            conn.execute("DELETE FROM triples WHERE note_path = ?", (note_path,))

        # Write all triples with embeddings
        triple_idx = 0
        for note_path, t, text in triple_registry:
            parsed_match = next(
                (p for p in parsed_notes if p.path == note_path), None
            )
            content_hash = parsed_match.content_hash if parsed_match else ""
            emb_blob = all_triple_blobs[triple_idx]
            conn.execute(
                "INSERT INTO triples"
                " (note_path, subject, predicate, object,"
                " triple_text, embedding,"
                " content_hash, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    note_path, t["s"], t["p"], t["o"],
                    text, emb_blob, content_hash, now,
                ),
            )
            triple_idx += 1

        # Update co-occurrence for each note
        for result in enrichment_results:
            if result.get("triples"):
                try:
                    upsert_cooccurrence_for_note(conn, result["note_path"])
                except Exception as exc:
                    log.warning(
                        "Co-occurrence update failed for %s: %s",
                        result["note_path"], exc,
                    )

        # Build graph, pagerank, co-occurrence
        try:
            build_graph(conn, vault_dir)
            compute_pagerank(conn)
            persist_cooccurrence(conn)
        except Exception as exc:
            log.warning("Graph/pagerank/cooccurrence build failed: %s", exc)

        conn.commit()
        conn.close()

        if progress_callback:
            progress_callback("complete", total_notes, total_notes)

        db_size = db_path.stat().st_size if db_path.exists() else 0

        return {
            "status": "complete",
            "db_size": db_size,
            "note_count": len(parsed_notes),
        }
