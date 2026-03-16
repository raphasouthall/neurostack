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

## Decision tree

1. Do you need a specific fact? -> vault_triples or vault_search(depth="triples")
2. Do you need an overview of a topic? -> vault_search(depth="summaries")
3. Do you need actual note content? -> vault_search(depth="full")
4. Is the question broad/thematic? -> vault_communities
5. Need a cited answer? -> vault_ask
6. Want to explore connections from a note? -> vault_graph
7. Want similar notes? -> vault_related
