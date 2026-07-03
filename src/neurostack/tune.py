# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Weight tuning for the ranking signals (issue #66).

Coordinate ascent over :class:`RankingWeights` against the eval harness
(``recall@k`` / ``MRR`` / ``NDCG``). Sweep one signal's scalar while the rest
are held fixed, keep the value that most improves the objective, iterate over
signals until a full round makes no accepted change.

This is deliberately the cheapest, most interpretable optimiser in the strategy
shortlist: it reuses ``evaluate_config`` verbatim, needs only numpy-free stdlib,
and every accepted step is a single scalar move you can read off the history.
It cannot see interactions two signals only exhibit jointly — that is what a
grid / random / Bayesian pass (a later strategy) is for.

**Gate, not a shipping path.** A tuned vector out of here is a *candidate*. Do
not pin it to config until it clears the label-quality pass and an out-of-sample
check — a 36-query set overfits trivially. :func:`interleaved_split` +
:func:`evaluate_weights` give the honest train/test read; the tuner optimises on
train only.
"""
from __future__ import annotations

import contextlib
from dataclasses import dataclass, field, replace

from .config import RankingWeights
from .eval import EvalQuery, cached_query_embeddings, evaluate_config


def _cache_ctx(cache: dict[str, list[float]] | None):
    """Patch in the offline query-embedding cache, or a no-op context in live mode."""
    return cached_query_embeddings(cache) if cache is not None else contextlib.nullcontext()

# Per-parameter candidate grids. Centred on the production defaults so the
# baseline is always reachable (coordinate ascent can decline to move). Kept
# small — coordinate ascent visits |params| × |grid| configs per round.
DEFAULT_GRIDS: dict[str, list[float]] = {
    # Convergence spans the full [0, 1] — the #66 snapshot sweep found its clean
    # optimum well past 0.6, so a grid capped there would silently under-move it.
    "convergence_weight": [0.0, 0.15, 0.3, 0.45, 0.6, 0.75, 0.9, 1.0],
    "hotness_weight": [0.0, 0.1, 0.2, 0.3, 0.4],
    "inhibition_threshold": [0.55, 0.65, 0.75, 0.85, 0.95],
    "inhibition_strength": [0.0, 0.15, 0.3, 0.45],
    "cooccurrence_boost_weight": [0.0, 0.05, 0.1, 0.2],
    "link_section_penalty": [0.3, 0.5, 0.7, 1.0],
}

# Order signals are swept in each round: strongest-known-effect first so an
# early round already captures most of the available lift (ablation memory 1196:
# convergence is the strongest positive, lateral inhibition the cleanest tuning
# target). Order only affects the path, not the reachable set.
DEFAULT_ORDER: tuple[str, ...] = (
    "convergence_weight",
    "inhibition_strength",
    "inhibition_threshold",
    "hotness_weight",
    "cooccurrence_boost_weight",
    "link_section_penalty",
)

METRICS = ("recall", "mrr", "ndcg")


@dataclass
class TuneResult:
    """Outcome of one coordinate-ascent run."""

    metric: str
    baseline_weights: RankingWeights
    baseline_score: float
    best_weights: RankingWeights
    best_score: float
    rounds: int
    n_evals: int
    history: list[dict] = field(default_factory=list)

    @property
    def improved(self) -> bool:
        return self.best_score > self.baseline_score

    @property
    def changed_params(self) -> dict[str, tuple[float, float]]:
        """Params whose tuned value differs from the baseline: name → (from, to)."""
        out: dict[str, tuple[float, float]] = {}
        for f in RankingWeights.__dataclass_fields__:
            a = getattr(self.baseline_weights, f)
            b = getattr(self.best_weights, f)
            if a != b:
                out[f] = (a, b)
        return out


def evaluate_weights(
    queries: list[EvalQuery],
    weights: RankingWeights,
    *,
    db_path,
    k: int = 5,
    metric: str = "ndcg",
    embed_url: str | None = None,
) -> float:
    """Score one weight vector over a query set (full pipeline, no ablation).

    Assumes any offline embedding cache is already patched in by the caller (the
    tuner patches once around the whole ascent rather than per candidate).
    """
    res = evaluate_config(
        queries, set(), db_path=db_path, k=k, embed_url=embed_url, weights=weights
    )
    return _score(res, metric)


def _score(res, metric: str) -> float:
    if metric not in METRICS:
        raise ValueError(f"metric must be one of {METRICS}, got {metric!r}")
    return getattr(res, metric)


def interleaved_split(
    queries: list[EvalQuery],
) -> tuple[list[EvalQuery], list[EvalQuery]]:
    """Deterministic train/test split by even/odd position.

    Index-based (no RNG) so a run is reproducible and diffable. Even indices →
    train (tune on these), odd → test (report out-of-sample). Interleaving keeps
    the four categories balanced across both halves better than a slice would.
    """
    train = [q for i, q in enumerate(queries) if i % 2 == 0]
    test = [q for i, q in enumerate(queries) if i % 2 == 1]
    return train, test


def coordinate_ascent(
    queries: list[EvalQuery],
    *,
    db_path,
    k: int = 5,
    metric: str = "ndcg",
    cache: dict[str, list[float]] | None = None,
    embed_url: str | None = None,
    init: RankingWeights | None = None,
    grids: dict[str, list[float]] | None = None,
    order: tuple[str, ...] | None = None,
    max_rounds: int = 4,
    epsilon: float = 1e-6,
) -> TuneResult:
    """Coordinate ascent over ``RankingWeights``, maximising ``metric``.

    Optimises on ``queries`` — pass the *train* split, not the whole set. Returns
    a :class:`TuneResult`; the caller is responsible for the out-of-sample check
    before trusting the tuned vector.
    """
    if metric not in METRICS:
        raise ValueError(f"metric must be one of {METRICS}, got {metric!r}")

    grids = grids or DEFAULT_GRIDS
    order = order or DEFAULT_ORDER
    baseline = init or RankingWeights()

    # Fail loud on an incomplete cache — the same guarantee run_eval gives, so a
    # sweep never silently degrades to FTS-only for an unseen query.
    if cache is not None:
        missing = [q.query for q in queries if q.query not in cache]
        if missing:
            raise KeyError(
                f"No cached embedding for {len(missing)} quer"
                f"{'y' if len(missing) == 1 else 'ies'} (e.g. {missing[0]!r}). "
                f"Rebuild the cache with `neurostack eval --refresh-embeddings`."
            )

    history: list[dict] = []
    state = {"evals": 0}

    def _eval(w: RankingWeights) -> float:
        state["evals"] += 1
        return evaluate_weights(
            queries, w, db_path=db_path, k=k, metric=metric, embed_url=embed_url
        )

    def _run() -> tuple[RankingWeights, float, int, float]:
        current = baseline
        current_score = _eval(current)
        base_score = current_score
        rounds_done = 0
        for round_i in range(max_rounds):
            improved_this_round = False
            for param in order:
                if param not in grids:
                    continue
                cur_val = getattr(current, param)
                best_val = cur_val
                best_score = current_score
                for val in grids[param]:
                    if val == cur_val:
                        continue
                    cand = replace(current, **{param: val})
                    sc = _eval(cand)
                    history.append(
                        {
                            "round": round_i,
                            "param": param,
                            "value": val,
                            "score": round(sc, 5),
                            "accepted": sc > best_score + epsilon,
                        }
                    )
                    if sc > best_score + epsilon:
                        best_score = sc
                        best_val = val
                if best_val != cur_val:
                    current = replace(current, **{param: best_val})
                    current_score = best_score
                    improved_this_round = True
            rounds_done = round_i + 1
            if not improved_this_round:
                break
        return current, current_score, rounds_done, base_score

    with _cache_ctx(cache):
        best_w, best_s, rounds_done, base_s = _run()

    return TuneResult(
        metric=metric,
        baseline_weights=baseline,
        baseline_score=base_s,
        best_weights=best_w,
        best_score=best_s,
        rounds=rounds_done,
        n_evals=state["evals"],
        history=history,
    )


def holdout_scores(
    result: TuneResult,
    holdout: list[EvalQuery],
    *,
    db_path,
    k: int = 5,
    cache: dict[str, list[float]] | None = None,
    embed_url: str | None = None,
) -> tuple[float, float]:
    """Out-of-sample (baseline, tuned) scores for ``result.metric`` on a held-out
    set. This is the number that gates committing a weight: the tuner optimised on
    the train split, so the honest read is how the tuned vector does on queries it
    never saw."""
    with _cache_ctx(cache):
        base = evaluate_weights(holdout, result.baseline_weights, db_path=db_path,
                                k=k, metric=result.metric, embed_url=embed_url)
        tuned = evaluate_weights(holdout, result.best_weights, db_path=db_path,
                                 k=k, metric=result.metric, embed_url=embed_url)
    return base, tuned


def format_tune_report(
    result: TuneResult,
    *,
    holdout: list[EvalQuery] | None = None,
    db_path=None,
    k: int = 5,
    cache: dict[str, list[float]] | None = None,
    embed_url: str | None = None,
) -> str:
    """Human-readable summary: baseline vs tuned, changed params, and — if a
    holdout set is given — the out-of-sample score for both, which is the number
    that actually decides whether a tuned vector is worth committing."""
    lines: list[str] = []
    lines.append(f"  objective: {result.metric}@{k}  ·  {result.n_evals} evals · "
                 f"{result.rounds} round(s)")
    lines.append("")
    lines.append(f"  train {result.metric}:  baseline {result.baseline_score:.4f}  "
                 f"→  tuned {result.best_score:.4f}  "
                 f"(Δ {result.best_score - result.baseline_score:+.4f})")

    if holdout is not None and db_path is not None:
        base_h, tuned_h = holdout_scores(result, holdout, db_path=db_path, k=k,
                                         cache=cache, embed_url=embed_url)
        lines.append(f"  test  {result.metric}:  baseline {base_h:.4f}  "
                     f"→  tuned {tuned_h:.4f}  (Δ {tuned_h - base_h:+.4f})   ← out-of-sample")

    lines.append("")
    changed = result.changed_params
    if not changed:
        lines.append("  tuned vector == baseline (no scalar move improved the objective).")
    else:
        lines.append("  changed weights:")
        for name, (a, b) in changed.items():
            lines.append(f"    {name:<28} {a:>6} → {b:<6}")
    return "\n".join(lines)
