# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Knowledge graph triple extraction (OpenAI-compatible /v1/ endpoints).

Extracts Subject-Predicate-Object triples from vault notes for
token-efficient structured retrieval (~10-20 tokens per fact vs
~500 tokens per full note chunk).
"""

import json
import logging
import re

import httpx

from .config import _auth_headers, get_config

log = logging.getLogger("neurostack")

_cfg = get_config()
DEFAULT_SUMMARIZE_URL = _cfg.llm_url
TRIPLE_MODEL = _cfg.llm_model
_LLM_HEADERS = _auth_headers(_cfg.llm_api_key)


class TripleExtractionError(Exception):
    """Raised when triple extraction fails after retry.

    Distinguishes a hard failure (the LLM returned output that could not be
    parsed into triples even after a retry) from the legitimate case of a note
    that simply yields no triples (which returns an empty list). Callers use
    this to schedule a retry instead of silently recording zero triples — see
    issue #28.
    """


TRIPLE_PROMPT = """Extract knowledge graph triples from this note. \
Each triple is a (subject, predicate, object) fact.

Rules:
- Extract 3-15 triples depending on note length and density
- Subject and object should be specific named entities, \
concepts, or tools (not pronouns)
- Predicate should be a short verb phrase \
(e.g. "uses", "runs on", "depends on", "configures")
- Normalize entity names: use canonical names, \
not abbreviations (e.g. "PostgreSQL" not "pg.conf")
- Include relationships about: configurations, dependencies, \
connections, purposes, locations, states
- Skip trivial or redundant triples
- Return ONLY a JSON object, no other text

Note title: {title}
---
{content}
---

Return a JSON object of this exact shape (an empty list if there are no facts):
{{"triples": [{{"s": "subject", "p": "predicate", "o": "object"}}]}}"""

_RETRY_SUFFIX = (
    "\n\nYour previous reply could not be parsed. Reply with ONLY the JSON "
    'object {"triples": [...]} — no prose, no markdown fences.'
)


def _call_triple_llm(prompt: str, base_url: str, model: str, json_mode: bool) -> str:
    """Single LLM call returning the raw assistant message content."""
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "reasoning_effort": "none",
        "temperature": 0.2,
        "max_tokens": 2048,
    }
    if json_mode:
        # Ask the endpoint to constrain output to a JSON object. Supported by
        # Ollama and OpenAI-compatible servers; the retry drops it in case a
        # given backend rejects the field.
        body["response_format"] = {"type": "json_object"}
    resp = httpx.post(
        f"{base_url}/v1/chat/completions",
        headers=_LLM_HEADERS,
        json=body,
        timeout=180.0,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def _extract_json_blob(raw: str) -> str:
    """Best-effort: isolate the first JSON object/array in a noisy response."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```\w*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw).strip()
    starts = [i for i in (raw.find("{"), raw.find("[")) if i != -1]
    if not starts:
        return raw
    start = min(starts)
    end = max(raw.rfind("}"), raw.rfind("]"))
    if end > start:
        return raw[start : end + 1]
    return raw


def _parse_triples(raw: str) -> list:
    """Parse raw LLM output into a list of triple candidates.

    Accepts a bare JSON array, a ``{"triples": [...]}`` object, or those forms
    embedded in surrounding prose / markdown fences. Raises on unparseable input.
    """
    data = json.loads(_extract_json_blob(raw))
    if isinstance(data, dict):
        data = data.get("triples", data.get("facts", []))
    if not isinstance(data, list):
        raise ValueError("expected a JSON array of triples or {'triples': [...]}")
    return data


def _validate(triples: list) -> list[dict]:
    """Keep only well-formed {s, p, o} triples with non-empty values."""
    valid = []
    for t in triples:
        if isinstance(t, dict) and "s" in t and "p" in t and "o" in t:
            s = str(t["s"]).strip()
            p = str(t["p"]).strip()
            o = str(t["o"]).strip()
            if s and p and o:
                valid.append({"s": s, "p": p, "o": o})
    return valid


def extract_triples(
    title: str,
    content: str,
    base_url: str = DEFAULT_SUMMARIZE_URL,
    model: str = TRIPLE_MODEL,
) -> list[dict]:
    """Extract SPO triples from note content via an OpenAI-compatible LLM.

    Returns a list of {"s", "p", "o"} dicts (possibly empty if the note has no
    extractable facts). Raises :class:`TripleExtractionError` if the LLM output
    cannot be parsed even after one retry, so the caller can schedule a retry
    rather than silently recording zero triples (issue #28).
    """
    if len(content) > 4000:
        content = content[:4000] + "\n[... truncated]"

    prompt = TRIPLE_PROMPT.format(title=title, content=content)
    last_err: Exception | None = None

    # Attempt 0: JSON-object mode. Attempt 1: stricter prompt, no response_format.
    for attempt in range(2):
        try:
            raw = _call_triple_llm(
                prompt if attempt == 0 else prompt + _RETRY_SUFFIX,
                base_url, model, json_mode=(attempt == 0),
            )
            return _validate(_parse_triples(raw))
        except (json.JSONDecodeError, ValueError) as e:
            last_err = e
            log.warning(
                "Triple JSON parse failed for '%s' (attempt %d/2): %s",
                title, attempt + 1, e,
            )

    raise TripleExtractionError(
        f"could not parse triples for '{title}' after 2 attempts: {last_err}"
    )


def triple_to_text(t: dict) -> str:
    """Convert a triple dict to searchable text form."""
    return f"{t['s']} | {t['p']} | {t['o']}"
