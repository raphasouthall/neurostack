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
Call this when a note was genuinely useful. Boosts it in future search via hotness scoring.
