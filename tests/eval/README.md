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
