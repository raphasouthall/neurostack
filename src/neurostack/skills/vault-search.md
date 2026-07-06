---
name: vault-search
description: Search the knowledge vault with the right retrieval strategy
---

# Vault Search Guide

NeuroStack has multiple retrieval tools. Pick the right one:

| Tool | Use when | Token cost |
|------|----------|-----------|
| vault_search(depth="triples") | Quick factual lookup | ~10-20 tokens/fact |
| vault_search(depth="summaries") | Overview of a topic | ~50-100 tokens/note |
| vault_search(depth="full") | Need actual content/snippets | ~200-500 tokens/result |
| vault_search(depth="auto") | Unsure - let the system decide | Variable |
| vault_triples | Structured SPO facts only | Cheapest |
| vault_communities | Global/thematic questions across the vault | Expensive (LLM) |
| vault_ask | RAG Q&A with citations | Expensive (LLM) |
| vault_graph | Wiki-link neighborhood of a specific note | Cheap |
| vault_related | Semantically similar notes | Moderate |
| vault_memories | Search agent-written memories | Cheap |
| vault_search(reference_only=True) | Broad scan — {path, score, snippet} only, no bodies | Very cheap |
| vault_read_file(path, offset, limit) | Read a bounded slice of one note | Sized to `limit` |
| vault_graph_analysis(top_k) | Structural gaps (unlinked but related) + bridge notes | Moderate |
| vault_diff(since, baseline) / vault_checkpoint | What changed since a baseline or date | Cheap |

## Decision tree

1. Do you need a specific fact? -> vault_triples or vault_search(depth="triples")
2. Do you need an overview of a topic? -> vault_search(depth="summaries")
3. Do you need actual note content? -> vault_search(depth="full")
4. Is the question broad/thematic? -> vault_communities
5. Need a cited answer? -> vault_ask
6. Want to explore connections from a note? -> vault_graph
7. Want similar notes? -> vault_related
8. Many likely hits but you'll open only 1-2? -> vault_search(reference_only=True), then read the winner
9. Context budget tight? -> add max_tokens=N to vault_search
10. Curating the graph (what should be linked, what's a fragile hub)? -> vault_graph_analysis
11. Orienting at session start / resuming a loop (what changed)? -> vault_diff since your last vault_checkpoint

## Lean retrieval (cut context footprint)

Every result lands in the caller's context window, so pull only what you need:

- **Scan then fetch.** `vault_search(query, reference_only=True)` returns just `{path, score, snippet}` — no summaries or bodies — plus a fetch hint. Pick the 1-2 relevant paths, then `vault_summary(path)` for the gist or `vault_read_file(path, offset, limit)` for exact text.
- **Budget a search.** `vault_search(query, max_tokens=N)` stops accumulating once ~N tokens (4 chars/token) are used, always keeps at least one result, and sets `truncated: true` when it clips. Applies across every depth. Use it in tight contexts (session bootstrap, autonomous loops).
- **Page large notes.** `vault_read_file(path, offset, limit)` reads a slice and reports `size_chars`/`offset`/`truncated`. Read the first `limit` chars, then advance `offset` — don't dump a whole 50 KB note. The no-arg call still returns the full file.

## After retrieval: record what you used

When retrieved notes genuinely informed your answer, record them:
```
vault_record_usage(note_paths=["path/a.md", "path/b.md"])
```
This is how the vault learns to rank better for you. It drives two signals:
**hotness** (frequently-used notes rank higher, always on) and the
**implicit-feedback loop** (which result answered which query, used to tune
ranking; opt-in via `feedback_enabled`). Record the notes that actually helped,
not incidental or irrelevant hits. Skipping it isn't wrong, but the ranking only
improves from the uses you record.
