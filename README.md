# NeuroStack

[![PyPI](https://img.shields.io/pypi/v/neurostack)](https://pypi.org/project/neurostack/)
[![Python](https://img.shields.io/pypi/pyversions/neurostack)](https://pypi.org/project/neurostack/)
[![CI](https://github.com/raphasouthall/neurostack/actions/workflows/ci.yml/badge.svg)](https://github.com/raphasouthall/neurostack/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)

**Your notes are lying to you. NeuroStack finds the ones that went stale.**

You have hundreds of notes. Some of them are outdated, some contradict your recent thinking, and your AI assistant treats them all as equally true. NeuroStack watches your vault and tells you which notes can't be trusted anymore — the same way your brain flags memories that no longer match reality.

## What it does

- **Finds stale notes** — surfaces notes that keep appearing in searches where they don't belong. The signal to review before they mislead you or your AI.
- **Searches by meaning** — finds notes by what they say, not just what they're titled. Ask a question, get an answer.
- **Maps your knowledge** — reveals hidden connections and topic clusters you never planned.
- **Remembers what matters** — recent, active notes get priority. Old, unused notes fade — just like real memory.
- **Works with your AI tools** — gives Claude Code, Cursor, and Windsurf long-term memory from your vault.
- **Stays on your machine** — everything runs locally. Your notes never leave home.

<img src="docs/screenshots/prediction-errors.svg" alt="NeuroStack surfacing stale notes" width="720">

<img src="docs/screenshots/07-search.svg" alt="NeuroStack search" width="720">

<img src="docs/screenshots/brief.svg" alt="NeuroStack daily brief" width="720">

## Quick Start

```bash
pip install neurostack

neurostack init ~/my-vault
neurostack index
neurostack search "what do I know about deployment?"
```

That's it. Works with any Markdown vault — [Obsidian](https://obsidian.md), [Logseq](https://logseq.com), or plain `.md` files.

<details>
<summary><strong>One-line install script</strong></summary>

```bash
# Lite mode — FTS5 search only, ~50MB, no GPU needed
curl -fsSL https://raw.githubusercontent.com/raphasouthall/neurostack/main/install.sh | bash
```

</details>

<details>
<summary><strong>Full mode — local AI (embeddings + summaries)</strong></summary>

```bash
# ~500MB, requires Ollama
NEUROSTACK_MODE=full curl -fsSL https://raw.githubusercontent.com/raphasouthall/neurostack/main/install.sh | bash

# Pull models
ollama pull nomic-embed-text
ollama pull qwen2.5:3b
```

Full mode adds semantic search (find by meaning, not just keywords), AI-generated summaries, and structured knowledge triples — all running locally on your machine.

</details>

## How it works

NeuroStack indexes your vault into a knowledge graph, then uses techniques borrowed from memory neuroscience to help you maintain it:

| What you see | What it does | How your brain does it |
|---|---|---|
| **Stale note detection** | Flags notes that appear in the wrong search contexts | Prediction error signals trigger memory reconsolidation |
| **Hot notes** | Recently active notes get priority in results | CREB-elevated neurons preferentially join new memories |
| **Topic clusters** | Reveals thematic groups across your vault | Neural ensembles form overlapping assemblies |
| **Smart retrieval** | Starts with key facts, escalates only when needed | Hippocampal rapid binding complements slow cortical learning |
| **Meaning-based search** | Finds notes by concept, not just keywords | Associative memory retrieval follows semantic paths |

<details>
<summary><strong>See the neuroscience citations</strong></summary>

| Feature | Key Paper |
|---------|-----------|
| Stale note detection (prediction errors) | Sinclair & Bhatt 2022, *PNAS* 119(31) |
| Hot notes (excitability windows) | Han et al. 2007, *Science* 316(5823) |
| Knowledge graph (engram networks) | Josselyn & Tonegawa 2020, *Science* 367(6473) |
| Community detection (neural ensembles) | Cai et al. 2016, *Nature* 534(7605) |
| Tiered retrieval (complementary learning) | McClelland et al. 1995, *Psychological Review* |

Full citations: [docs/neuroscience-appendix.md](docs/neuroscience-appendix.md)

</details>

## Token economy

NeuroStack's tiered retrieval sends your AI only what it needs:

| Depth | Tokens per result | When it's used |
|-------|-------------------|----------------|
| **Triples** | ~15 tokens | Quick factual lookups — 80% of queries resolve here |
| **Summaries** | ~75 tokens | When you need more context |
| **Full content** | ~300 tokens | Deep dives into specific notes |

Compared to naive RAG (dumping full document chunks at ~750 tokens each), NeuroStack uses **96% fewer tokens** per query. That means lower API costs, faster responses, and more of your AI's attention on actually answering your question instead of processing background noise.

## Features at a glance

| Feature | Lite (no GPU) | Full (local AI) |
|---------|:---:|:---:|
| Full-text search | Yes | Yes |
| Wiki-link graph + PageRank | Yes | Yes |
| Stale note detection | Yes | Yes |
| Session transcript search | Yes | Yes |
| Semantic search (by meaning) | — | Yes |
| AI-generated summaries & triples | — | Yes |
| Cross-encoder reranking | — | Yes |
| Topic clustering (Leiden) | — | +community |

## Works with your AI tools

NeuroStack is an [MCP](https://modelcontextprotocol.io) server — add it to Claude Code, Cursor, or Windsurf and your AI assistant can search your vault in any conversation.

```json
{
  "mcpServers": {
    "neurostack": {
      "command": "neurostack",
      "args": ["serve"],
      "env": {}
    }
  }
}
```

<details>
<summary><strong>All 9 MCP tools</strong></summary>

| Tool | What it does |
|------|-------------|
| `vault_search` | Search your vault by meaning or keywords, with tiered depth |
| `vault_summary` | Get a pre-computed summary of any note |
| `vault_graph` | See a note's neighborhood — what links to it and what it links to |
| `vault_triples` | Get structured facts (who/what/how) extracted from your notes |
| `vault_communities` | Answer big-picture questions across topic clusters |
| `vault_stats` | Check the health of your index |
| `vault_record_usage` | Track which notes are "hot" (recently accessed) |
| `vault_prediction_errors` | Surface notes that need review |
| `session_brief` | Get a compact briefing when starting a new session |

</details>

<details>
<summary><strong>CLI reference</strong></summary>

```
neurostack init [path]          # Set up your vault
neurostack index                # Build the knowledge graph
neurostack search "query"       # Search by meaning or keywords
neurostack graph "note.md"      # See a note's connections
neurostack prediction-errors    # Find stale or misleading notes
neurostack communities "topic"  # Explore topic clusters
neurostack brief                # Morning briefing — what needs attention
neurostack status               # Vault overview
neurostack doctor               # Health check
neurostack serve                # Start the MCP server
```

</details>

<details>
<summary><strong>Configuration</strong></summary>

Config lives at `~/.config/neurostack/config.toml`:

```toml
vault_root = "~/brain"
embed_url = "http://localhost:11435"
llm_url = "http://localhost:11434"
llm_model = "qwen2.5:3b"
```

Every setting has a `NEUROSTACK_*` env var override.

</details>

## Architecture

```
~/your-vault/                        # Your Markdown files (never modified)
~/.config/neurostack/config.toml     # Configuration
~/.local/share/neurostack/
    neurostack.db                    # SQLite + FTS5 knowledge graph
    sessions.db                      # Session transcript index
```

NeuroStack is **read-only** — it indexes your vault but never modifies your files.

## Requirements

- Linux or macOS
- Python 3.11+
- **Full mode**: [Ollama](https://ollama.ai) with `nomic-embed-text` and `qwen2.5:3b`

## Links

- **Website**: [neurostack.sh](https://neurostack.sh)
- **Contact**: [hello@neurostack.sh](mailto:hello@neurostack.sh)

## License

Apache-2.0 — see [LICENSE](LICENSE).

### Community detection extra

The optional `neurostack[community]` extra installs [leidenalg](https://github.com/vtraag/leidenalg) (GPL-3.0) and [python-igraph](https://github.com/igraph/python-igraph) (GPL-2.0+). These are **not** installed by default and are isolated behind a runtime import guard.

If you install `neurostack[community]`, you are responsible for complying with GPL terms when redistributing. The core NeuroStack package remains Apache-2.0 and contains no GPL code.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).
