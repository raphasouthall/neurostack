"""Global query answering over GraphRAG community summaries.

Implements GraphRAG 'global search':
1. Embed the query
2. Score all community summaries by cosine similarity
3. Map: extract relevant facts from each top community via LLM
4. Reduce: synthesize a final answer from map outputs
"""

import logging

import httpx
try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

from .embedder import blob_to_embedding, cosine_similarity_batch, get_embedding
from .schema import DB_PATH, get_db

log = logging.getLogger("neurostack")

from .config import get_config

_cfg = get_config()
SUMMARIZE_URL = _cfg.llm_url
EMBED_URL = _cfg.embed_url
SUMMARIZE_MODEL = _cfg.llm_model

_MAP_PROMPT = """You are analyzing a knowledge community summary to answer a question.

Community: {title}
Summary: {summary}

Question: {query}

Extract the key points from this community relevant to the question.
If nothing is relevant, return an empty string.
Be concise — 1-3 sentences max.

Relevant points:"""

_REDUCE_PROMPT = """You are synthesizing findings from across a personal knowledge vault to answer a global question.

Question: {query}

Findings from relevant knowledge communities:
{findings}

Provide a comprehensive answer that synthesizes these findings.
Identify themes, patterns, and connections across the vault.
Be direct and insightful."""


def search_communities(
    query: str,
    top_k: int = 8,
    level: int | None = None,
    conn=None,
    embed_url: str = EMBED_URL,
) -> list[dict]:
    """Semantic search over community summaries. Returns ranked list."""
    if conn is None:
        conn = get_db(DB_PATH)

    q = """
        SELECT community_id, level, title, summary, summary_embedding, entity_count, member_notes
        FROM communities
        WHERE summary_embedding IS NOT NULL AND summary IS NOT NULL
    """
    params: list = []
    if level is not None:
        q += " AND level = ?"
        params.append(level)

    rows = conn.execute(q, params).fetchall()
    if not rows:
        return []

    try:
        query_vec = np.array(get_embedding(query, base_url=embed_url), dtype=np.float32)
    except Exception as e:
        log.warning(f"Query embedding failed: {e}")
        return []

    embeddings = [blob_to_embedding(row["summary_embedding"]) for row in rows]
    scores = cosine_similarity_batch(query_vec, embeddings)

    ranked = sorted(zip(scores, rows), key=lambda x: x[0], reverse=True)[:top_k]

    return [
        {
            "community_id": row["community_id"],
            "level": row["level"],
            "title": row["title"],
            "summary": row["summary"],
            "entity_count": row["entity_count"],
            "member_notes": row["member_notes"],
            "score": float(score),
        }
        for score, row in ranked
    ]


def global_query(
    query: str,
    top_k: int = 6,
    level: int = 0,
    use_map_reduce: bool = True,
    conn=None,
    embed_url: str = EMBED_URL,
    summarize_url: str = SUMMARIZE_URL,
    model: str = SUMMARIZE_MODEL,
) -> dict:
    """Answer a global query using community summaries (GraphRAG global search).

    Args:
        query: Natural language question (e.g. "what themes run across my vault?")
        top_k: Number of communities to retrieve
        level: Community hierarchy level (0=coarse, 1=fine)
        use_map_reduce: Use LLM map-reduce synthesis (True) or return raw hits (False)

    Returns dict: {answer, communities_used, community_hits}
    """
    if conn is None:
        conn = get_db(DB_PATH)

    # Try requested level first, fall back to any level
    hits = search_communities(query, top_k=top_k, level=level, conn=conn, embed_url=embed_url)
    if not hits:
        hits = search_communities(query, top_k=top_k, level=None, conn=conn, embed_url=embed_url)

    if not hits:
        return {
            "answer": "No community summaries found. Run `cli.py communities build` first.",
            "communities_used": 0,
            "community_hits": [],
        }

    if not use_map_reduce:
        return {
            "answer": None,
            "communities_used": len(hits),
            "community_hits": hits,
        }

    # Map step
    findings: list[str] = []
    for hit in hits:
        if hit["score"] < 0.15:
            continue
        prompt = _MAP_PROMPT.format(
            title=hit["title"],
            summary=hit["summary"],
            query=query,
        )
        try:
            resp = httpx.post(
                f"{summarize_url}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.1, "num_predict": 256},
                    "think": False,
                },
                timeout=60.0,
            )
            resp.raise_for_status()
            finding = resp.json().get("response", "").strip()
            if finding:
                findings.append(f"[{hit['title']}]\n{finding}")
        except Exception as e:
            log.warning(f"Map step failed for community {hit['community_id']}: {e}")

    if not findings:
        return {
            "answer": "Could not extract relevant findings from communities.",
            "communities_used": len(hits),
            "community_hits": hits,
        }

    # Reduce step
    reduce_prompt = _REDUCE_PROMPT.format(
        query=query,
        findings="\n\n".join(findings),
    )
    try:
        resp = httpx.post(
            f"{summarize_url}/api/generate",
            json={
                "model": model,
                "prompt": reduce_prompt,
                "stream": False,
                "options": {"temperature": 0.3, "num_predict": 1024},
                "think": False,
            },
            timeout=120.0,
        )
        resp.raise_for_status()
        answer = resp.json().get("response", "").strip()
    except Exception as e:
        log.warning(f"Reduce step failed: {e}")
        answer = "\n\n".join(findings)

    return {
        "answer": answer,
        "communities_used": len(findings),
        "community_hits": hits,
    }
