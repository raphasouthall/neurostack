# Retrieval eval + ablation harness (issue #63)

Measures whether the stacked ranking signals in `hybrid_search` actually rank
better than the base FTS+cosine score — against relevance ground truth, not
wiring assertions. It reports recall@k / MRR / NDCG for the full pipeline, then
re-runs with each signal disabled so every multiplier's marginal contribution is
visible.

## Files

| File | What it is |
|------|-----------|
| `queries.sample.yaml` | Public format template: a handful of queries pointing at an imaginary vault. Not a benchmark — copy it and repoint the targets, or use `--autolabel`. |
| `queries.yaml` | Your own hand-written labels, if you keep any. **Gitignored** — it encodes your vault's structure, so it never ships. |
| `query_embeddings.json` | Offline cache of query embeddings (created by `--refresh-embeddings`). Gitignored — its keys are the raw query strings. |

The code lives in `src/neurostack/eval.py` (harness) and
`src/neurostack/autolabel.py` (label generation); the CLI is `neurostack eval`;
the offline unit tests are `tests/test_eval.py` and `tests/test_autolabel.py`.

## Labelling any vault automatically (`--autolabel`, issue #66)

A note is its own answer key, so the harness can manufacture labels from whatever
vault is under test — no hand-labelling, nothing vault-specific to commit:

```bash
# Generate labels from the vault, then run the ablation table
neurostack eval --db /tmp/neurostack-copy.db --autolabel

# Generate labels and tune weights against them (out-of-sample split)
neurostack eval --db /tmp/neurostack-copy.db --autolabel --tune
```

Two tiers (`--autolabel-mode`):

* `heuristic` — no LLM. Uses each sampled note's pre-computed summary (a paraphrase)
  as the query, title as fallback. Free, offline, exercises the semantic signals.
* `llm` — asks the configured model for natural questions each note answers.
  Cached by note content hash (`--autolabel-cache`), so a re-run only regenerates
  changed notes.
* `auto` (default) — LLM when a model is reachable, else the heuristic floor.

Under `--autolabel --tune`, the **hotness** weight is frozen: a synthetic
known-item query reflects content, not what a user actually opens, so it can't
judge usage signals (the confound that skewed the hand labels). Tune those from
real click feedback instead. `--tune-usage-signals` overrides.

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
embedder. It uses fictional paths, not any real vault; it only checks that
`queries.sample.yaml` ships and parses.

## Maintaining labels

Prefer `--autolabel`: generated labels track whatever the vault currently
contains, so there is nothing to re-verify when notes move. If you keep a
hand-written `queries.yaml`, it stays local and gitignored — after a real run,
inspect misses (`--json` shows each query's top-k) and correct any target that
is genuinely wrong before trusting the deltas for weight decisions.

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
