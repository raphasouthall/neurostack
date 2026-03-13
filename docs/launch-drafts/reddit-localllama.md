# r/LocalLLaMA Post

## Title

NeuroStack: local MCP knowledge graph that finds stale notes before they poison your RAG. FTS5 + embeddings, Leiden clustering, 96% token reduction.

## Body

Built a local-first MCP server that turns a Markdown vault into long-term memory for Claude Code and Cursor. Everything runs on your machine.

The feature that sets it apart: **stale note detection**. When a note keeps getting retrieved in contexts where it doesn't belong (cosine distance > 0.62 between embedding and query), that's logged as a retrieval anomaly. Over time you build a ranked list of notes that keep "surprising" the retrieval pipeline — usually because they're outdated or miscategorised. Neuroscience analog: prediction error-driven memory reconsolidation (Sinclair & Bhatt, PNAS 2022).

In practice this catches the silent RAG failure mode: your retriever faithfully returns a note that was accurate when written but is now wrong. The AI doesn't hallucinate — it gives you a confident, well-sourced, *stale* answer.

Architecture:

- **Lite mode**: FTS5 full-text + wiki-link graph + PageRank. SQLite only, no GPU, ~50MB. Good baseline.
- **Full mode**: adds Ollama embeddings (nomic-embed-text) for hybrid FTS5+semantic scoring, cross-encoder reranking, LLM summaries + structured triples (qwen2.5:3b). ~500MB, needs Ollama.
- **Community mode**: adds Leiden clustering for detecting thematic clusters in the wiki-link graph. GPL extra.

Tiered retrieval pipeline:

| Depth | Tokens/result | Use case |
|-------|--------------|----------|
| Triples | ~15 | Quick factual lookups — resolves 80% of queries |
| Summaries | ~75 | More context needed |
| Full | ~300 | Deep dives |

Compared to naive RAG (~750 tok/chunk), that's a **96% reduction** in retrieval tokens. More room for reasoning in the context window.

9 MCP tools, 19 CLI commands, 99 tests.

Install:

    pip install neurostack          # lite
    pip install neurostack[full]    # with ML deps
    pip install "neurostack[full,community]"   # + Leiden

    neurostack init ~/brain
    neurostack index
    neurostack prediction-errors    # find stale notes
    neurostack serve                # start MCP server

Then add to `~/.claude/.mcp.json`:

```json
{
  "mcpServers": {
    "neurostack": {
      "command": "neurostack",
      "args": ["serve"]
    }
  }
}
```

Apache-2.0, read-only vault access.

- GitHub: https://github.com/raphasouthall/neurostack
- Website: https://neurostack.sh
