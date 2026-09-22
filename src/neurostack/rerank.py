# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Opt-in reranking of search results with a judgement model (Jev).

Issue #142 took every LLM off the retrieval path so no user waits on one. That
rule still holds by default: `vault_search(rerank=True)` is the only way in, it
is off everywhere else, and a failure returns the original ordering untouched.

Measured on 76 real `search_feedback` clicks (2026-09-22): baseline MRR 0.503
to 0.652 with pure reranked order, top-1 34.2% to 48.7%, top-3 56.6% to 75.0%,
paired permutation p=0.004. Blending the model score with the original rank
scored *worse* than the model's own order at every weight tried (0.574 blended
against 0.652 pure), so the order here is the model's, not a blend.

Feeding the model title + summary alone is not enough: it put 485 of 718
candidates in the bottom band and could not separate them. Passing the matched
chunk text alongside roughly doubled the gain.
"""

from __future__ import annotations

import logging

log = logging.getLogger("neurostack.rerank")

# Chunk text sent per candidate. 1600 chars is what the evaluation used; longer
# costs more per search without a measured gain.
DOC_CHARS = 1600

_QUESTION = {
    "relevance": {
        "type": "score",
        "instructions": "How well does this note answer the search query?",
        "criteria": [
            "unrelated",
            "same topic area but does not answer it",
            "partially answers it",
            "directly answers the query",
        ],
    }
}


def _state(query: str, result) -> str:
    """The text the judge sees for one candidate."""
    body = (result.chunk_content or result.snippet or "")[:DOC_CHARS]
    return (
        f"SEARCH QUERY: {query}\n\n"
        f"CANDIDATE NOTE\n"
        f"title: {result.title or result.note_path}\n"
        f"summary: {result.summary}\n\n"
        f"NOTE TEXT: {body}"
    )


def _score_one(client, url: str, model: str, headers: dict, query: str, result) -> float:
    resp = client.post(
        url,
        headers=headers,
        json={"model": model, "state": _state(query, result), "questions": _QUESTION},
        timeout=30.0,
    )
    resp.raise_for_status()
    return float(resp.json()["answers"]["relevance"]["score"])


def rerank_results(query: str, results: list, cfg=None) -> list:
    """Reorder `results` best-first by judged relevance to `query`.

    Fails open. Any transport error, HTTP status, or malformed answer returns
    the input list in its original order, because a search that silently
    degrades beats a search that raises. The OpenRouter free allowance running
    out mid-evaluation returned 402 on every call, which is exactly the shape
    of failure this has to absorb.
    """
    if len(results) < 2:
        return results

    if cfg is None:
        from .config import get_config

        cfg = get_config()

    if not cfg.rerank_model:
        log.warning("rerank requested but rerank_model is unset - returning original order")
        return results

    import concurrent.futures

    import httpx

    headers = {"Content-Type": "application/json"}
    if cfg.rerank_api_key:
        headers["Authorization"] = f"Bearer {cfg.rerank_api_key}"

    url = f"{cfg.rerank_url.rstrip('/')}/alpha/decisions"

    try:
        with httpx.Client() as client, concurrent.futures.ThreadPoolExecutor(
            max_workers=cfg.rerank_concurrency
        ) as pool:
            scores = list(
                pool.map(
                    lambda r: _score_one(client, url, cfg.rerank_model, headers, query, r),
                    results,
                )
            )
    except Exception as exc:
        log.warning("rerank failed (%s) - returning original order", exc)
        return results

    # Stable sort: equal scores keep the incoming hybrid order.
    return [r for _, r in sorted(
        enumerate(results), key=lambda pair: -scores[pair[0]]
    )]
