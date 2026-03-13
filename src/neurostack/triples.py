"""Knowledge graph triple extraction using Ollama.

Extracts Subject-Predicate-Object triples from vault notes for
token-efficient structured retrieval (~10-20 tokens per fact vs
~500 tokens per full note chunk).
"""

import json
import logging

import httpx

from .config import get_config

log = logging.getLogger("neurostack")

_cfg = get_config()
DEFAULT_SUMMARIZE_URL = _cfg.llm_url
TRIPLE_MODEL = _cfg.llm_model

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
- Return ONLY valid JSON array, no other text

Note title: {title}
---
{content}
---

Return JSON array of triples:
[{{"s": "subject", "p": "predicate", "o": "object"}}]"""


def extract_triples(
    title: str,
    content: str,
    base_url: str = DEFAULT_SUMMARIZE_URL,
    model: str = TRIPLE_MODEL,
) -> list[dict]:
    """Extract SPO triples from note content via Ollama.

    Returns list of {"s": str, "p": str, "o": str} dicts.
    """
    if len(content) > 4000:
        content = content[:4000] + "\n[... truncated]"

    prompt = TRIPLE_PROMPT.format(title=title, content=content)

    triple_schema = {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "s": {"type": "string"},
                "p": {"type": "string"},
                "o": {"type": "string"},
            },
            "required": ["s", "p", "o"],
        },
    }

    resp = httpx.post(
        f"{base_url}/api/generate",
        json={
            "model": model,
            "prompt": prompt,
            "stream": False,
            "format": triple_schema,
            "options": {
                "temperature": 0.2,
                "num_predict": 2048,
            },
            "think": False,
        },
        timeout=180.0,
    )
    resp.raise_for_status()
    data = resp.json()
    raw = data.get("response", "").strip()

    try:
        triples = json.loads(raw)
    except json.JSONDecodeError as e:
        log.warning(f"JSON parse error for '{title}': {e}")
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


def triple_to_text(t: dict) -> str:
    """Convert a triple dict to searchable text form."""
    return f"{t['s']} | {t['p']} | {t['o']}"
