# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""OpenAI-compatible HTTP API server for NeuroStack."""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import AsyncIterator

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from . import __version__

log = logging.getLogger("neurostack")

# -----------------------------------------------------------------------
# Request / response models
# -----------------------------------------------------------------------

MODELS = [
    {
        "id": "neurostack-ask",
        "object": "model",
        "created": 1700000000,
        "owned_by": "neurostack",
    },
    {
        "id": "neurostack-search",
        "object": "model",
        "created": 1700000000,
        "owned_by": "neurostack",
    },
    {
        "id": "neurostack-tiered",
        "object": "model",
        "created": 1700000000,
        "owned_by": "neurostack",
    },
    {
        "id": "neurostack-triples",
        "object": "model",
        "created": 1700000000,
        "owned_by": "neurostack",
    },
]

MODEL_IDS = {m["id"] for m in MODELS}


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str = "neurostack-ask"
    messages: list[ChatMessage]
    temperature: float = 0.3
    max_tokens: int | None = None
    stream: bool = False
    top_k: int = 8
    workspace: str | None = None


class EmbeddingRequest(BaseModel):
    input: str | list[str]
    model: str = "nomic-embed-text"
    encoding_format: str = "float"


# -----------------------------------------------------------------------
# Auth dependency
# -----------------------------------------------------------------------


def _get_api_key() -> str:
    from .config import get_config

    return get_config().api_key


def _verify_auth(request: Request) -> None:
    """Validate Bearer token if api_key is configured."""
    api_key = _get_api_key()
    if not api_key:
        return
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail={
                "error": {
                    "message": "Missing Bearer token.",
                    "type": "invalid_request_error",
                    "code": "invalid_api_key",
                }
            },
        )
    token = auth[len("Bearer "):]
    if token != api_key:
        raise HTTPException(
            status_code=401,
            detail={
                "error": {
                    "message": "Invalid API key.",
                    "type": "invalid_request_error",
                    "code": "invalid_api_key",
                }
            },
        )


# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------


def _extract_query(messages: list[ChatMessage]) -> str:
    """Extract the last user message as the query string."""
    for msg in reversed(messages):
        if msg.role == "user":
            return msg.content
    raise HTTPException(
        status_code=400,
        detail={
            "error": {
                "message": "No user message found in messages.",
                "type": "invalid_request_error",
                "code": "invalid_request",
            }
        },
    )


def _estimate_tokens(text: str) -> int:
    """Rough token estimate (1 token per ~4 chars)."""
    return max(1, len(text) // 4)


def _make_completion_id() -> str:
    return f"chatcmpl-{uuid.uuid4().hex[:12]}"


def _format_search_results(results: list) -> str:
    """Format SearchResult objects into readable text."""
    if not results:
        return "No results found."
    lines = []
    for i, r in enumerate(results, 1):
        lines.append(f"## Result {i} (score: {r.score:.4f})")
        lines.append(f"**{r.title}** - `{r.note_path}`")
        if r.heading_path:
            lines.append(f"Section: {r.heading_path}")
        if r.summary:
            lines.append(f"Summary: {r.summary}")
        lines.append(f"\n{r.snippet}\n")
    return "\n".join(lines)


def _format_tiered_results(result: dict) -> str:
    """Format tiered search result dict into readable text."""
    lines = [f"Depth used: {result.get('depth_used', 'unknown')}\n"]

    triples = result.get("triples", [])
    if triples:
        lines.append("## Triples")
        for t in triples:
            score = t.get("score", 0.0)
            lines.append(
                f"- [{t.get('title', '')}] "
                f"{t['s']} -- {t['p']} -> {t['o']} "
                f"(score: {score:.4f})"
            )
        lines.append("")

    summaries = result.get("summaries", [])
    if summaries:
        lines.append("## Summaries")
        for s in summaries:
            score = s.get("score", "")
            score_str = f" (score: {score:.4f})" if score else ""
            lines.append(
                f"### {s.get('title', s.get('note', ''))}"
                f"{score_str}"
            )
            lines.append(s.get("summary", ""))
            lines.append("")

    chunks = result.get("chunks", [])
    if chunks:
        lines.append("## Chunks")
        for c in chunks:
            lines.append(
                f"### {c.get('title', '')} - "
                f"{c.get('section', '')} "
                f"(score: {c.get('score', 0.0):.4f})"
            )
            if c.get("summary"):
                lines.append(f"Summary: {c['summary']}")
            lines.append(c.get("snippet", ""))
            lines.append("")

    if not triples and not summaries and not chunks:
        lines.append("No results found.")

    return "\n".join(lines)


def _split_into_chunks(text: str, chunk_words: int = 20) -> list[str]:
    """Split text into roughly equal word-sized chunks for streaming."""
    words = text.split()
    if not words:
        return [text] if text else []
    chunks = []
    for i in range(0, len(words), chunk_words):
        chunk = " ".join(words[i : i + chunk_words])
        if i > 0:
            chunk = " " + chunk
        chunks.append(chunk)
    return chunks


def _build_completion_response(
    content: str,
    model: str,
    completion_id: str | None = None,
) -> dict:
    """Build a standard ChatCompletion response dict."""
    cid = completion_id or _make_completion_id()
    prompt_tokens = _estimate_tokens(content) // 2
    completion_tokens = _estimate_tokens(content)
    return {
        "id": cid,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": content,
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


# -----------------------------------------------------------------------
# Route handlers
# -----------------------------------------------------------------------


def _handle_ask(query: str, top_k: int, workspace: str | None) -> str:
    from .ask import ask_vault
    from .config import get_config

    cfg = get_config()
    result = ask_vault(
        question=query,
        top_k=top_k,
        embed_url=cfg.embed_url,
        llm_url=cfg.llm_url,
        llm_model=cfg.llm_model,
        workspace=workspace,
    )
    answer = result.get("answer", "")
    sources = result.get("sources", [])
    if sources:
        source_list = ", ".join(
            f"[[{s['title']}]]" for s in sources
        )
        answer += f"\n\nSources: {source_list}"
    return answer


def _handle_search(
    query: str, top_k: int, workspace: str | None,
) -> str:
    from .config import get_config
    from .search import hybrid_search

    cfg = get_config()
    results = hybrid_search(
        query=query,
        top_k=top_k,
        mode="hybrid",
        embed_url=cfg.embed_url,
        workspace=workspace,
    )
    return _format_search_results(results)


def _handle_tiered(
    query: str,
    top_k: int,
    workspace: str | None,
    depth: str = "auto",
) -> str:
    from .config import get_config
    from .search import tiered_search

    cfg = get_config()
    result = tiered_search(
        query=query,
        top_k=top_k,
        depth=depth,
        mode="hybrid",
        embed_url=cfg.embed_url,
        workspace=workspace,
    )
    return _format_tiered_results(result)


# -----------------------------------------------------------------------
# App factory
# -----------------------------------------------------------------------


def create_app() -> FastAPI:
    """Build and return the FastAPI application."""
    app = FastAPI(
        title="NeuroStack API",
        version=__version__,
        description="OpenAI-compatible API for NeuroStack vault search",
    )

    # --- Error handler ---------------------------------------------------

    @app.exception_handler(Exception)
    async def _generic_error(request: Request, exc: Exception):
        log.exception("Unhandled error in API request")
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "message": str(exc),
                    "type": "internal_error",
                    "code": "internal_error",
                }
            },
        )

    # --- Health ----------------------------------------------------------

    @app.get("/health")
    async def health():
        return {"status": "ok", "version": __version__}

    # --- Models ----------------------------------------------------------

    @app.get("/v1/models")
    async def list_models():
        return {"object": "list", "data": MODELS}

    # --- Chat completions ------------------------------------------------

    @app.post("/v1/chat/completions")
    async def chat_completions(
        body: ChatCompletionRequest,
        _: None = Depends(_verify_auth),
    ):
        query = _extract_query(body.messages)
        model = body.model

        if model not in MODEL_IDS:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": {
                        "message": (
                            f"Unknown model '{model}'. "
                            f"Available: {sorted(MODEL_IDS)}"
                        ),
                        "type": "invalid_request_error",
                        "code": "model_not_found",
                    }
                },
            )

        try:
            if model == "neurostack-ask":
                content = _handle_ask(
                    query, body.top_k, body.workspace,
                )
            elif model == "neurostack-search":
                content = _handle_search(
                    query, body.top_k, body.workspace,
                )
            elif model == "neurostack-tiered":
                content = _handle_tiered(
                    query, body.top_k, body.workspace,
                )
            elif model == "neurostack-triples":
                content = _handle_tiered(
                    query, body.top_k, body.workspace,
                    depth="triples",
                )
            else:
                content = _handle_search(
                    query, body.top_k, body.workspace,
                )
        except Exception as exc:
            log.exception("Error handling chat completion")
            raise HTTPException(
                status_code=500,
                detail={
                    "error": {
                        "message": f"Backend error: {exc}",
                        "type": "internal_error",
                        "code": "internal_error",
                    }
                },
            ) from exc

        completion_id = _make_completion_id()

        if not body.stream:
            return _build_completion_response(
                content, model, completion_id,
            )

        # Streaming response - sse-starlette adds "data:" prefix
        from sse_starlette.sse import EventSourceResponse, ServerSentEvent

        async def _stream() -> AsyncIterator[ServerSentEvent]:
            chunks = _split_into_chunks(content)
            # First chunk: include role
            first_data = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"role": "assistant"},
                        "finish_reason": None,
                    }
                ],
            }
            yield ServerSentEvent(data=json.dumps(first_data))

            # Content chunks
            for chunk_text in chunks:
                chunk_data = {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": chunk_text},
                            "finish_reason": None,
                        }
                    ],
                }
                yield ServerSentEvent(data=json.dumps(chunk_data))

            # Final chunk: finish_reason=stop
            stop_data = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "delta": {},
                        "finish_reason": "stop",
                    }
                ],
            }
            yield ServerSentEvent(data=json.dumps(stop_data))
            yield ServerSentEvent(data="[DONE]")

        return EventSourceResponse(
            _stream(),
            media_type="text/event-stream",
        )

    # --- Embeddings ------------------------------------------------------

    @app.post("/v1/embeddings")
    async def embeddings(
        body: EmbeddingRequest,
        _: None = Depends(_verify_auth),
    ):
        from .config import get_config
        from .embedder import get_embedding, get_embeddings_batch

        cfg = get_config()

        try:
            if isinstance(body.input, str):
                texts = [body.input]
            else:
                texts = body.input

            if len(texts) == 1:
                vec = get_embedding(
                    texts[0],
                    base_url=cfg.embed_url,
                    model=body.model,
                )
                data = [
                    {
                        "object": "embedding",
                        "embedding": vec.tolist(),
                        "index": 0,
                    }
                ]
            else:
                vecs = get_embeddings_batch(
                    texts,
                    base_url=cfg.embed_url,
                    model=body.model,
                )
                data = [
                    {
                        "object": "embedding",
                        "embedding": v.tolist(),
                        "index": i,
                    }
                    for i, v in enumerate(vecs)
                ]

            total_tokens = sum(
                _estimate_tokens(t) for t in texts
            )
            return {
                "object": "list",
                "data": data,
                "model": body.model,
                "usage": {
                    "prompt_tokens": total_tokens,
                    "total_tokens": total_tokens,
                },
            }

        except Exception as exc:
            log.exception("Error generating embeddings")
            raise HTTPException(
                status_code=500,
                detail={
                    "error": {
                        "message": f"Embedding error: {exc}",
                        "type": "internal_error",
                        "code": "internal_error",
                    }
                },
            ) from exc

    return app


# -----------------------------------------------------------------------
# Server entry point
# -----------------------------------------------------------------------


def run_server(
    host: str | None = None,
    port: int | None = None,
) -> None:
    """Start the API server with uvicorn."""
    import uvicorn

    from .config import get_config

    cfg = get_config()
    host = host or cfg.api_host
    port = port or cfg.api_port

    log.info("Starting NeuroStack API on %s:%d", host, port)
    app = create_app()
    uvicorn.run(app, host=host, port=port, log_level="info")
