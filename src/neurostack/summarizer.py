# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Summary client (OpenAI-compatible /v1/ endpoints)."""

import httpx

from .config import _auth_headers, get_config

_cfg = get_config()
DEFAULT_SUMMARIZE_URL = _cfg.llm_url
SUMMARIZE_MODEL = _cfg.llm_model
_LLM_HEADERS = _auth_headers(_cfg.llm_api_key)

SUMMARY_PROMPT = """Summarize this note in 2-3 concise sentences. \
Focus on the key purpose, decisions, and actionable information. \
Do not use filler phrases like "This note discusses". Be direct.

Note title: {title}
---
{content}
---

Summary:"""


def summarize_note(
    title: str,
    content: str,
    base_url: str = DEFAULT_SUMMARIZE_URL,
    model: str = SUMMARIZE_MODEL,
) -> str:
    """Generate a 2-3 sentence summary of a note."""
    # Truncate content to ~3000 chars to keep prompt reasonable
    if len(content) > 3000:
        content = content[:3000] + "\n[... truncated]"

    prompt = SUMMARY_PROMPT.format(title=title, content=content)

    resp = httpx.post(
        f"{base_url}/v1/chat/completions",
        headers=_LLM_HEADERS,
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
    data = resp.json()
    summary = data["choices"][0]["message"]["content"].strip()

    # Strip think tags if model includes them despite reasoning_effort=none
    import re
    summary = re.sub(r"<think>.*?</think>", "", summary, flags=re.DOTALL).strip()

    return summary


FOLDER_SUMMARY_PROMPT = """You are summarizing the contents of a \
folder in a personal knowledge vault.
Below are summaries of the notes it contains. Write 2-3 sentences \
describing what topics, projects, or knowledge this folder covers. \
Be specific and factual — name actual topics, technologies, or \
projects present.

Folder: {folder_path}
Note summaries:
{child_summaries}

Folder summary:"""


def summarize_folder(
    folder_path: str,
    child_summaries: list[dict],
    base_url: str = DEFAULT_SUMMARIZE_URL,
    model: str = SUMMARIZE_MODEL,
) -> str:
    """Generate a 2-3 sentence summary of a vault folder from its child note summaries.

    Args:
        folder_path: Relative folder path (e.g. "work/my-project")
        child_summaries: List of dicts with keys "title" and "summary"
        base_url: Ollama base URL
        model: Ollama model name

    Returns:
        Summary string.
    """
    if not child_summaries:
        return ""

    # Format child summaries, truncate per note to keep prompt reasonable
    lines = []
    for item in child_summaries[:20]:  # cap at 20 notes
        title = item.get("title", "Untitled")
        summary = (item.get("summary") or "").strip()
        if summary:
            lines.append(f"- {title}: {summary[:200]}")

    if not lines:
        return ""

    child_text = "\n".join(lines)
    prompt = FOLDER_SUMMARY_PROMPT.format(folder_path=folder_path, child_summaries=child_text)

    resp = httpx.post(
        f"{base_url}/v1/chat/completions",
        headers=_LLM_HEADERS,
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
    data = resp.json()
    summary = data["choices"][0]["message"]["content"].strip()

    import re
    summary = re.sub(r"<think>.*?</think>", "", summary, flags=re.DOTALL).strip()

    return summary
