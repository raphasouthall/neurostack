# Retrieval eval + ablation harness (issue #63)

Measures whether the stacked ranking signals in `hybrid_search` actually rank
better than the base FTS+cosine score — against relevance ground truth, not
wiring assertions. It reports recall@k / MRR / NDCG for the full pipeline, then
re-runs with each signal disabled so every multiplier's marginal contribution is
visible.

## Files

| File | What it is |
|------|-----------|
| `queries.yaml` | Labelled query set: 36 queries → the note(s) each should surface. Seeded from the 2026-04-16 retrieval benchmark and expanded across pinpoint / thematic / crossref / adversarial. |
| `query_embeddings.json` | Cache of query embeddings (created by `--refresh-embeddings`). Lets the harness run offline. Not committed until you generate it against your embedder. |

The code lives in `src/neurostack/eval.py`; the CLI is `neurostack eval`; the
offline unit tests are `tests/test_eval.py`.

## Running it

Against a **copy** of the prod index (eval is read-only — `record=False` — but
point it at a copy anyway), on the box with a live embedder:

```bash
# 1. First run on a new box builds the query-embedding cache, then evaluates
neurostack eval --db /tmp/neurostack-copy.db --refresh-embeddings

# 2. Subsequent runs replay the cache — fully offline, no Ollama needed
neurostack eval --db /tmp/neurostack-copy.db

# JSON for scripting / regression tracking
neurostack --json eval --db /tmp/neurostack-copy.db | jq '.configs'
```

Output is a metric-per-configuration table. Read the delta columns as
`Δ = full − ablated`:

* **Δ > 0** — removing the signal *hurt*; it earns its weight.
* **Δ ≈ 0** — the signal is inert on this query set (candidate for removal, #66).
* **Δ < 0** — removing the signal *helped*; it is actively mis-ranking.

This is the loop that gates #64 (excitability removal must be Δ ≤ 0, i.e.
neutral-or-better) and #66 (weight tuning).

## Offline CI

`tests/test_eval.py` builds a tiny deterministic corpus with hand-assigned
embeddings and an injected query-embedding cache, so the harness — including the
per-signal ablation and the side-effect-free guarantee — runs in CI with no
embedder. It does **not** use `queries.yaml`'s real vault paths (those need the
real index); it only checks that `queries.yaml` ships and parses.

## Maintaining the labels

Paths in `queries.yaml` were verified against the live vault on 2026-07-02. If
the vault is reorganised, re-verify with `vault_list_files` and adjust targets.
Labels are a starting point — after the first real run, inspect misses
(`--json` shows each query's top-k) and correct any target that is genuinely
wrong before trusting the deltas for weight decisions.

## Weight tuning (issue #66)

The ranking scalars the ablation measures are now tunable, not hardcoded:
`convergence_weight`, `hotness_weight`, `inhibition_threshold`,
`inhibition_strength` (config.py / env), plus the existing co-occurrence and
link-penalty weights. `RankingWeights` bundles them; `hybrid_search(weights=...)`
overrides them per call without touching global config.

`neurostack eval --tune` runs coordinate ascent over that vector against the
harness — sweep one scalar, keep the best, iterate to convergence:

```bash
# Tune on a train split, report the held-out (out-of-sample) score
neurostack eval --db /tmp/neurostack-copy.db --tune --tune-metric ndcg

# Tune on the whole set (faster; the gain is in-sample only — do not commit on it)
neurostack eval --db /tmp/neurostack-copy.db --tune --no-holdout
```

**A tuned vector is a candidate, not a shipping decision.** Two gates stand
between the sweep and `config.py`:

* **Label quality.** A signal that scores negative can be a *label* artifact, not
  a ranking defect. Hotness is the standing example: `note_usage` reflects real
  traffic, so hand-picked targets can be cold and the optimiser "wins" by
  zeroing hotness. Decompose the gain — tune with the confounded signal frozen
  (a custom `grids` without it) to isolate the committable part.
* **Out of sample.** 36 queries overfit trivially. The holdout guards against
  memorising specific queries, but not against a bias shared by the whole label
  set (pinpoint-heavy labels under-value the diversity lateral inhibition buys).
  Widen and rebalance the labels before trusting a large delta.

The offline unit tests are `tests/test_tune.py`; the tuner is
`src/neurostack/tune.py`.
