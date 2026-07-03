---
name: vault-audit
description: Audit vault health - stale notes, missing summaries, prediction errors
---

# Vault Audit

## Quick health check
```
vault_stats()
```
Shows note count, chunk count, memory count, embedding coverage.

## Find retrieval issues
```
vault_prediction_errors()
```
Notes that were retrieved but had low semantic relevance - may need updating or re-indexing.

## Check what's stale
```
vault_search(query="<broad topic>", depth="summaries")
```
Review summaries for outdated information. Notes with old summaries may need re-summarizing.

## Record note usage (improves future ranking)
```
vault_record_usage(note_paths=["path/to/note.md"])
```
Call this when a note was genuinely useful. Two signals: **hotness** (boosts it in
future search, always on) and, when `feedback_enabled` is set, the
**implicit-feedback loop** that tunes ranking from real usage (issue #66).

## Measure and tune retrieval quality (issue #66)
```
neurostack feedback                  # accumulated implicit-feedback stats
neurostack eval --autolabel          # benchmark ranking on THIS vault (no hand labels)
neurostack eval --feedback --tune    # tune weights from real usage (hotness included)
```
`--autolabel` builds a benchmark from the vault's own notes (summaries as
queries); `--feedback` learns from recorded `vault_record_usage` events. Ranking
weights are tunable (`convergence_weight`, `hotness_weight`, lateral-inhibition,
etc.) but ship at defaults — a swept weight is a candidate: check the
out-of-sample delta before pinning it in `config.toml`.
