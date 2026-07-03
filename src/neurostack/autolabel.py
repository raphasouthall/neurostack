# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Vault-agnostic label generation for the eval / tuning harness (issue #66).

The eval harness scores ranking against a set of ``(query, target-note)`` labels.
Hand-writing those labels ties the benchmark to one person's vault — the paths
leak in a public repo, and nobody else's vault matches them. This module removes
the hand step: a note is its own answer key, so we manufacture queries *from the
vault under test* and take the source note as the target. Any Markdown vault
produces its own benchmark, with nobody labelling anything.

Two tiers, cheapest first:

* **heuristic** (no LLM, offline) — the note's pre-computed summary is a
  paraphrase of its content, so searching the summary and expecting the note
  back genuinely exercises the semantic + convergence signals, not just a title
  keyword match. Falls back to the title when a note has no summary.
* **llm** — ask the configured model for natural questions the note answers,
  which stress retrieval the way real queries do. Cached by note content hash, so
  it regenerates only for notes that changed.

``generate_labels(mode="auto")`` prefers the LLM and falls back to the heuristic
when no model is reachable — the "works everywhere, better when a model exists"
default.

Usage signals (hotness) must NOT be tuned against these labels: a synthetic
known-item query reflects content, not what a user actually opens, which is the
exact confound that made hotness look bad on hand labels. Tune usage signals from
real click feedback instead (a later strategy); keep them frozen here.
"""
from __future__ import annotations

import json
import random
import re
from pathlib import Path

import httpx

from .config import _auth_headers, get_config
from .eval import EvalQuery


def _target_for(path: str) -> str:
    """Label target for a note path — drop the ``.md`` so eval's substring match
    (``matches``) still fires against the ``.md`` result path."""
    return path[:-3] if path.endswith(".md") else path


def _sample_paths(conn, n: int, seed: int) -> list[str]:
    """Deterministically sample up to ``n`` note paths across the vault.

    Seeded so a run is reproducible and diffable; sorted so the label order does
    not depend on the sample draw.
    """
    rows = conn.execute("SELECT path FROM notes ORDER BY path").fetchall()
    paths = [r[0] for r in rows]
    if n and len(paths) > n:
        paths = random.Random(seed).sample(paths, n)
    return sorted(paths)


def _first_sentence(text: str) -> str:
    """First sentence of a summary, capped — enough to be a query, not the whole blurb."""
    text = text.strip()
    m = re.search(r"(.+?[.!?])(\s|$)", text)
    sentence = m.group(1) if m else text
    return sentence[:200].strip()


# ── heuristic tier (no LLM) ────────────────────────────────────────────────


def heuristic_labels(conn, *, n: int = 150, seed: int = 0) -> list[EvalQuery]:
    """Summary-derived queries (title fallback), one per sampled note.

    The summary is a model-written paraphrase already sitting in the DB, so this
    is a semantic label with zero generation cost. Notes with neither a summary
    nor a title are skipped.
    """
    labels: list[EvalQuery] = []
    for path in _sample_paths(conn, n, seed):
        row = conn.execute(
            "SELECT n.title, s.summary_text FROM notes n "
            "LEFT JOIN summaries s ON s.note_path = n.path WHERE n.path = ?",
            (path,),
        ).fetchone()
        if row is None:
            continue
        title, summary = row[0], row[1]
        if summary and summary.strip():
            query, category = _first_sentence(summary), "autolabel-summary"
        elif title and title.strip():
            query, category = title.strip(), "autolabel-title"
        else:
            continue
        labels.append(EvalQuery(query=query, targets=[_target_for(path)], category=category))
    return labels


# ── LLM tier ───────────────────────────────────────────────────────────────

QUERYGEN_PROMPT = """You are writing retrieval test queries for a knowledge vault.
Read the note and write {k} short, natural search queries a user would type to \
find THIS note. One query per line. No numbering, no quotes. Do not copy the \
title verbatim. Make each specific enough that this note is clearly the answer.

Note title: {title}
---
{content}
---
Queries:"""


def _parse_query_lines(text: str, k: int) -> list[str]:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    # An unclosed <think> (a reasoning model that ran past max_tokens) would
    # otherwise leak its reasoning as "queries" — strip from the open tag on.
    text = re.sub(r"<think>.*", "", text, flags=re.DOTALL)
    out: list[str] = []
    for line in text.splitlines():
        line = re.sub(r"^\s*(?:\d+[.)]|[-*])\s*", "", line).strip().strip('"').strip()
        if line:
            out.append(line)
    return out[:k]


def _llm_queries(title: str, content: str, k: int, *, base_url: str, model: str,
                 headers: dict) -> list[str]:
    if len(content) > 3000:
        content = content[:3000] + "\n[... truncated]"
    prompt = QUERYGEN_PROMPT.format(k=k, title=title, content=content)
    resp = httpx.post(
        f"{base_url}/v1/chat/completions",
        headers=headers,
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "reasoning_effort": "none",
            "temperature": 0.4,
            "max_tokens": 200,
        },
        timeout=300.0,
    )
    resp.raise_for_status()
    return _parse_query_lines(resp.json()["choices"][0]["message"]["content"], k)


def llm_labels(
    conn,
    *,
    n: int = 150,
    seed: int = 0,
    k_per_note: int = 2,
    cache_path: str | Path | None = None,
    llm_url: str | None = None,
    llm_model: str | None = None,
) -> list[EvalQuery]:
    """LLM-generated queries per sampled note, cached by note content hash.

    The cache means a re-run only pays for notes whose content changed since last
    time — the vault's stable notes are free on the second run.
    """
    cfg = get_config()
    base_url = llm_url or cfg.llm_url
    model = llm_model or cfg.llm_model
    headers = _auth_headers(cfg.llm_api_key)

    cache: dict[str, list[str]] = {}
    cpath = Path(cache_path) if cache_path else None
    if cpath and cpath.exists():
        cache = json.loads(cpath.read_text(encoding="utf-8"))

    labels: list[EvalQuery] = []
    dirty = False
    for path in _sample_paths(conn, n, seed):
        row = conn.execute(
            "SELECT title, content_hash FROM notes WHERE path = ?", (path,)
        ).fetchone()
        if row is None:
            continue
        title, content_hash = row[0] or "", row[1] or path
        # Key by (content, k): the cached list is already sliced to k, so a run
        # with a different --autolabel-k must regenerate rather than return the
        # old count.
        cache_key = f"{content_hash}:{k_per_note}"
        if cache_key in cache:
            queries = cache[cache_key]
        else:
            chunk_rows = conn.execute(
                "SELECT content FROM chunks WHERE note_path = ? ORDER BY position",
                (path,),
            ).fetchall()
            content = "\n".join(r[0] for r in chunk_rows if r[0])
            if not content.strip():
                continue
            queries = _llm_queries(title, content, k_per_note,
                                   base_url=base_url, model=model, headers=headers)
            cache[cache_key] = queries
            dirty = True
        for q in queries:
            labels.append(EvalQuery(query=q, targets=[_target_for(path)],
                                    category="autolabel-llm"))

    if cpath and dirty:
        cpath.parent.mkdir(parents=True, exist_ok=True)
        cpath.write_text(json.dumps(cache, indent=2, sort_keys=True), encoding="utf-8")
    return labels


# ── dispatcher ─────────────────────────────────────────────────────────────


def _llm_reachable(base_url: str, headers: dict) -> bool:
    try:
        resp = httpx.get(f"{base_url}/v1/models", headers=headers, timeout=5.0)
        return resp.status_code < 500
    except (httpx.HTTPError, OSError):
        return False


def generate_labels(
    conn,
    *,
    mode: str = "auto",
    n: int = 150,
    seed: int = 0,
    k_per_note: int = 2,
    cache_path: str | Path | None = None,
    llm_url: str | None = None,
    llm_model: str | None = None,
) -> list[EvalQuery]:
    """Generate an eval label set from the vault under test.

    ``mode``: ``"heuristic"`` (no LLM), ``"llm"`` (require the model), or
    ``"auto"`` (LLM when a model is reachable, else the heuristic floor).
    """
    if mode not in ("auto", "heuristic", "llm"):
        raise ValueError(f"mode must be auto/heuristic/llm, got {mode!r}")

    if mode == "heuristic":
        return heuristic_labels(conn, n=n, seed=seed)

    if mode == "llm":
        return llm_labels(conn, n=n, seed=seed, k_per_note=k_per_note,
                          cache_path=cache_path, llm_url=llm_url, llm_model=llm_model)

    # auto: prefer the LLM, fall back to the heuristic floor.
    cfg = get_config()
    base_url = llm_url or cfg.llm_url
    if _llm_reachable(base_url, _auth_headers(cfg.llm_api_key)):
        try:
            labels = llm_labels(conn, n=n, seed=seed, k_per_note=k_per_note,
                                cache_path=cache_path, llm_url=llm_url, llm_model=llm_model)
            if labels:
                return labels
        except (httpx.HTTPError, KeyError, IndexError, ValueError):
            # A reachable-but-broken endpoint (junk/non-JSON body, unexpected
            # shape) or a corrupt cache file must not sink the whole run — that
            # is the point of "auto". mode="llm" still surfaces these.
            pass  # fall through to heuristic
    return heuristic_labels(conn, n=n, seed=seed)
