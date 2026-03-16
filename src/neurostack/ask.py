# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""RAG-based vault Q&A with inline citations."""

from __future__ import annotations

import re

import httpx

from .config import _auth_headers, get_config
from .search import hybrid_search

ASK_PROMPT = """You are a knowledge assistant answering questions \
using the provided vault notes.
Use ONLY the information from the sources below to answer. \
If the answer is not in the sources, say so.
Cite sources inline using [[note-title]] format.

Sources:
{sources}

Question: {question}

Answer (cite sources with [[note-title]]):"""


def ask_vault(
    question: str,
    top_k: int = 8,
    embed_url: str = None,
    llm_url: str = None,
    llm_model: str = None,
    workspace: str = None,
) -> dict:
    """Answer a question using vault content with citations.

    Returns dict with 'answer', 'sources' (list of cited notes).
    """
    cfg = get_config()
    embed_url = embed_url or cfg.embed_url
    llm_url = llm_url or cfg.llm_url
    llm_model = llm_model or cfg.llm_model

    # Search for relevant chunks
    results = hybrid_search(
        question,
        top_k=top_k,
        mode="hybrid",
        embed_url=embed_url,
        rerank=True,
        workspace=workspace,
    )

    if not results:
        return {"answer": "No relevant notes found in the vault.", "sources": []}

    # Build source context
    source_blocks = []
    seen_notes = {}
    for r in results:
        if r.note_path not in seen_notes:
            seen_notes[r.note_path] = r.title
        source_blocks.append(
            f"[{r.title}] ({r.note_path}):\n{r.snippet[:500]}"
        )

    sources_text = "\n\n---\n\n".join(source_blocks)
    prompt = ASK_PROMPT.format(sources=sources_text, question=question)

    # Call LLM (OpenAI-compatible endpoint)
    resp = httpx.post(
        f"{llm_url}/v1/chat/completions",
        headers=_auth_headers(cfg.llm_api_key),
        json={
            "model": llm_model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "reasoning_effort": "none",
            "temperature": 0.3,
            "max_tokens": 500,
        },
        timeout=180.0,
    )
    resp.raise_for_status()
    answer = resp.json()["choices"][0]["message"]["content"].strip()

    # Strip think tags if model includes them
    answer = re.sub(r"<think>.*?</think>", "", answer, flags=re.DOTALL).strip()

    # Build sources list
    sources = [
        {"path": path, "title": title}
        for path, title in seen_notes.items()
    ]

    return {"answer": answer, "sources": sources}
