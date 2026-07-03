# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Retrieval-quality benchmark + per-signal ablation harness (issue #63).

Runs ``hybrid_search`` over a labelled query set and reports recall@k, MRR and
NDCG, then re-runs with each ranking signal disabled so the marginal
contribution of every stacked multiplier is measured against relevance ground
truth rather than assumed.

Design notes
------------
* **Offline in CI.** Query embeddings are served from a JSON cache
  (``cached_query_embeddings``) so a run needs no live Ollama. Chunk embeddings
  come from whatever DB is under test — the committed test fixture builds a tiny
  deterministic corpus; a real run points ``--db`` at a copy of the prod index.
* **Side-effect-free.** Every ``hybrid_search`` call passes ``record=False`` so
  an ablation sweep (many passes over the same query) never mutates usage,
  hotness, co-occurrence weights, or the prediction-error log between configs.
* **Ablation via the search pipeline itself.** Each config disables one signal
  through ``hybrid_search(ablate=...)`` and re-runs, rather than trying to undo
  a multiplier after the fact — lateral inhibition and dedup reorder results, so
  a signal's effect can only be read by re-ranking without it.
"""
from __future__ import annotations

import contextlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path

from .search import ABLATABLE_SIGNALS


@dataclass
class EvalQuery:
    """One labelled query: text plus the note paths that count as relevant."""

    query: str
    targets: list[str]          # note-path prefixes / substrings that are relevant
    category: str = ""
    context: str | None = None  # optional --context domain to pass through


@dataclass
class ConfigResult:
    """Aggregate + per-query metrics for one pipeline configuration."""

    name: str
    ablated: set[str]
    recall: float
    mrr: float
    ndcg: float
    per_query: list[dict] = field(default_factory=list)


# ── label loading ─────────────────────────────────────────────────────────


def load_queries(path) -> list[EvalQuery]:
    """Load a labelled query set from YAML.

    Schema::

        queries:
          - query: "Home lab network topology"
            category: pinpoint
            targets: [home/resources/infrastructure]
          - query: "HashiCorp Vault SSH CA"
            target: home/resources/hashicorp-vault   # singular shorthand
    """
    import yaml

    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    items = raw.get("queries", raw) if isinstance(raw, dict) else raw
    queries: list[EvalQuery] = []
    for item in items:
        targets = item.get("targets")
        if targets is None:
            single = item.get("target")
            targets = [single] if single else []
        queries.append(
            EvalQuery(
                query=item["query"],
                targets=[str(t) for t in targets],
                category=item.get("category", ""),
                context=item.get("context"),
            )
        )
    return queries


# ── relevance + metrics ───────────────────────────────────────────────────


def matches(path: str, target: str) -> bool:
    """Whether a result path is relevant to a label target.

    Relevant when the target is a path prefix of the result or appears anywhere
    in it — the match rule from the 2026-04-16 benchmark note, tolerant of the
    ``.md`` suffix and section-anchored paths.
    """
    p = path.lower()
    t = target.lower().rstrip("/")
    return p == t or p.startswith(t + "/") or t in p


def _hits(ranked: list[str], targets: list[str]) -> list[bool]:
    return [any(matches(p, t) for t in targets) for p in ranked]


def recall_at_k(ranked: list[str], targets: list[str], k: int) -> float:
    """Fraction of distinct relevant targets that appear in the top-k results."""
    if not targets:
        return 0.0
    topk = ranked[:k]
    found = sum(1 for t in targets if any(matches(p, t) for p in topk))
    return found / len(targets)


def mrr(ranked: list[str], targets: list[str]) -> float:
    """Reciprocal rank of the first relevant result (0 if none)."""
    for i, p in enumerate(ranked, start=1):
        if any(matches(p, t) for t in targets):
            return 1.0 / i
    return 0.0


def ndcg_at_k(ranked: list[str], targets: list[str], k: int) -> float:
    """Binary-relevance NDCG@k. Each labelled target counts as one relevant
    document scored at the rank where it is *first* found — so a target that
    matches several result paths (e.g. a directory prefix hitting sibling notes)
    cannot inflate DCG past IDCG. Ideal DCG places every target at the top."""
    if not targets:
        return 0.0
    topk = ranked[:k]
    dcg = 0.0
    for t in targets:
        for i, p in enumerate(topk):
            if matches(p, t):
                dcg += 1.0 / math.log2(i + 2)
                break
    n_ideal = min(len(targets), k)
    idcg = sum(1.0 / math.log2(i + 2) for i in range(n_ideal))
    return dcg / idcg if idcg > 0 else 0.0


# ── query-embedding cache (offline replay) ────────────────────────────────


def load_embedding_cache(path) -> dict[str, list[float]]:
    p = Path(path)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {}


def save_embedding_cache(path, cache: dict[str, list[float]]) -> None:
    Path(path).write_text(json.dumps(cache, indent=2, sort_keys=True), encoding="utf-8")


def build_embedding_cache(queries: list[EvalQuery], embed_url: str) -> dict[str, list[float]]:
    """Fetch query embeddings from a live embedder and return a JSON-able cache.

    Used by ``--refresh-embeddings``; requires a reachable Ollama/embed service.
    """
    from .embedder import get_embedding

    cache: dict[str, list[float]] = {}
    for q in queries:
        vec = get_embedding(q.query, base_url=embed_url)
        cache[q.query] = [float(x) for x in vec]
    return cache


@contextlib.contextmanager
def cached_query_embeddings(cache: dict[str, list[float]]):
    """Patch ``search.get_embedding`` to serve query vectors from a cache.

    Lets the harness run with no live embedder. A query missing from the cache
    raises a clear error pointing at ``--refresh-embeddings`` rather than
    silently falling back to FTS-only (which would quietly change the metrics).
    """
    import numpy as np

    from . import search as search_mod

    original = search_mod.get_embedding

    def _fake(text, base_url=None, model=None):
        if text in cache:
            return np.array(cache[text], dtype=np.float32)
        raise KeyError(
            f"No cached embedding for query {text!r}. Rebuild the cache with "
            f"`neurostack eval --refresh-embeddings` against a live embedder."
        )

    search_mod.get_embedding = _fake
    try:
        yield
    finally:
        search_mod.get_embedding = original


# ── evaluation ────────────────────────────────────────────────────────────


def configs(signals=ABLATABLE_SIGNALS) -> list[tuple[str, set[str]]]:
    """The baseline plus one single-signal-ablation config per signal."""
    out: list[tuple[str, set[str]]] = [("full", set())]
    out.extend((f"-{s}", {s}) for s in signals)
    return out


def evaluate_config(
    queries: list[EvalQuery],
    ablate: set[str],
    *,
    db_path,
    k: int,
    embed_url: str | None = None,
) -> ConfigResult:
    """Run one configuration (a set of ablated signals) over every query."""
    from .search import hybrid_search

    per_query: list[dict] = []
    for q in queries:
        results = hybrid_search(
            query=q.query,
            top_k=k,
            mode="hybrid",
            db_path=db_path,
            embed_url=embed_url,
            context=q.context,
            ablate=ablate,
            record=False,
        )
        ranked = [r.note_path for r in results]
        per_query.append(
            {
                "query": q.query,
                "category": q.category,
                "recall": recall_at_k(ranked, q.targets, k),
                "mrr": mrr(ranked, q.targets),
                "ndcg": ndcg_at_k(ranked, q.targets, k),
                "hit": any(_hits(ranked[:k], q.targets)),
                "ranked": ranked[:k],
                "targets": q.targets,
            }
        )

    n = len(per_query) or 1
    return ConfigResult(
        name="full" if not ablate else "-" + ",".join(sorted(ablate)),
        ablated=set(ablate),
        recall=sum(x["recall"] for x in per_query) / n,
        mrr=sum(x["mrr"] for x in per_query) / n,
        ndcg=sum(x["ndcg"] for x in per_query) / n,
        per_query=per_query,
    )


def run_eval(
    queries: list[EvalQuery],
    *,
    db_path,
    k: int = 5,
    embed_url: str | None = None,
    cache: dict[str, list[float]] | None = None,
    ablation: bool = True,
) -> list[ConfigResult]:
    """Evaluate the full pipeline, then (optionally) each single-signal ablation.

    ``cache`` supplies query embeddings for offline replay; pass ``None`` to use
    the live embedder configured on ``embed_url``.
    """
    # Fail loud on an incomplete cache. hybrid_search swallows an embedding
    # error into a silent FTS-only fallback, which would quietly change the
    # metrics — so the harness verifies coverage up front rather than trusting
    # the per-query patch to raise.
    if cache is not None:
        missing = [q.query for q in queries if q.query not in cache]
        if missing:
            raise KeyError(
                f"No cached embedding for {len(missing)} quer"
                f"{'y' if len(missing) == 1 else 'ies'} (e.g. {missing[0]!r}). "
                f"Rebuild the cache with `neurostack eval --refresh-embeddings`."
            )

    run_configs = configs() if ablation else [("full", set())]

    def _run() -> list[ConfigResult]:
        rows: list[ConfigResult] = []
        for name, ablate in run_configs:
            res = evaluate_config(
                queries, ablate, db_path=db_path, k=k, embed_url=embed_url
            )
            res.name = name
            rows.append(res)
        return rows

    if cache is not None:
        with cached_query_embeddings(cache):
            return _run()
    return _run()


# ── reporting ─────────────────────────────────────────────────────────────


def format_table(rows: list[ConfigResult], k: int) -> str:
    """A metric-per-configuration table with per-signal deltas vs the full pipeline."""
    full = next((r for r in rows if r.name == "full"), rows[0])
    lines = []
    header = (
        f"{'config':<20} {'recall@' + str(k):>9} {'MRR':>7} {'NDCG':>7} "
        f"{'Δrecall':>9} {'Δmrr':>8} {'Δndcg':>8}"
    )
    lines.append(header)
    lines.append("-" * len(header))
    for r in rows:
        if r.name == "full":
            drecall = dmrr = dndcg = ""
        else:
            # Δ = full − ablated: positive means the removed signal was helping.
            drecall = f"{full.recall - r.recall:+.3f}"
            dmrr = f"{full.mrr - r.mrr:+.3f}"
            dndcg = f"{full.ndcg - r.ndcg:+.3f}"
        lines.append(
            f"{r.name:<20} {r.recall:>9.3f} {r.mrr:>7.3f} {r.ndcg:>7.3f} "
            f"{drecall:>9} {dmrr:>8} {dndcg:>8}"
        )
    lines.append("")
    lines.append(
        "Δ = full − ablated. Positive Δ ⇒ the removed signal earns its weight; "
        "≤0 ⇒ it is inert or harmful (candidate for removal, issue #66)."
    )
    return "\n".join(lines)


def results_to_dict(rows: list[ConfigResult], k: int) -> dict:
    full = next((r for r in rows if r.name == "full"), rows[0])
    return {
        "k": k,
        "n_queries": len(rows[0].per_query) if rows else 0,
        "configs": [
            {
                "name": r.name,
                "ablated": sorted(r.ablated),
                "recall": round(r.recall, 4),
                "mrr": round(r.mrr, 4),
                "ndcg": round(r.ndcg, 4),
                "delta_recall": None if r.name == "full" else round(full.recall - r.recall, 4),
                "delta_mrr": None if r.name == "full" else round(full.mrr - r.mrr, 4),
                "delta_ndcg": None if r.name == "full" else round(full.ndcg - r.ndcg, 4),
            }
            for r in rows
        ],
    }
