# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""RAG-based vault Q&A with inline citations."""

from __future__ import annotations

import re

import httpx

from .config import _auth_headers, get_config
from .search import hybrid_search

# Upper bound on per-source excerpt text passed to synthesis. A chunk is at most
# MAX_CHUNK_CHARS (2000); this passes the whole matched chunk rather than the
# 300-char display snippet, so a fact further down the chunk is still visible (#40).
MAX_SOURCE_CHARS = 2000

ASK_PROMPT = """You are a knowledge assistant answering questions \
using the provided vault notes.
Each source gives a note's summary and the most relevant excerpt from it.

Answer using ONLY the information in the sources below:
- If a source contains the answer, give it and cite the note with [[note-title]], \
quoting the relevant line.
- If the sources discuss the topic but none contains the specific detail asked for, \
say the retrieved notes did not include that detail. Do NOT assert that the fact is \
false or does not exist — you are only seeing excerpts, not the whole vault.

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
        workspace=workspace,
    )

    if not results:
        return {"answer": "No relevant notes found in the vault.", "sources": []}

    # Build source context. Pass the note summary plus the full matched chunk
    # (not the 300-char display snippet) so a fact below char 300 — or in the
    # note's summary rather than the top-scoring chunk — is still seen (#40).
    source_blocks = []
    seen_notes = {}
    source_excerpts = {}
    for r in results:
        if r.note_path not in seen_notes:
            seen_notes[r.note_path] = r.title
        excerpt = (r.chunk_content or r.snippet)[:MAX_SOURCE_CHARS]
        source_excerpts.setdefault(r.note_path, excerpt)
        block = f"[{r.title}] ({r.note_path}):"
        if r.summary:
            block += f"\nSummary: {r.summary}"
        block += f"\nExcerpt: {excerpt}"
        source_blocks.append(block)

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

    # Build sources list. Return the excerpt actually passed to synthesis so a
    # caller can see what the answer was grounded in (issue #40).
    sources = [
        {"path": path, "title": title, "excerpt": source_excerpts.get(path, "")}
        for path, title in seen_notes.items()
    ]

    return {"answer": answer, "sources": sources}
