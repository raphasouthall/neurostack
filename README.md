<a href="https://neurostack.sh"><img src="docs/logo.svg" alt="NeuroStack" height="48"></a>

[![PyPI](https://img.shields.io/pypi/v/neurostack)](https://pypi.org/project/neurostack/)
[![CI](https://github.com/raphasouthall/neurostack/actions/workflows/ci.yml/badge.svg)](https://github.com/raphasouthall/neurostack/actions/workflows/ci.yml)

**Long-term memory for AI agents.** NeuroStack indexes your Markdown vault into a knowledge graph your AI can search -- structured facts, summaries, or full content, automatically tiered by query complexity. It persists agent memories, detects stale notes, and recovers context across sessions. Your vault files are never modified.

Works with Claude Code, Cursor, Windsurf, Codex, and Gemini CLI via MCP.

## Get started

```bash
npm install -g neurostack
neurostack install
neurostack init
```

| | Cloud | Local |
|--|-------|-------|
| **Best for** | Zero friction, any machine | Privacy-first, offline, power users |
| **Indexing** | Gemini API (server-side) | Ollama on your machine |
| **Search** | Local SQLite | Local SQLite (same DB) |
| **GPU required** | No | Recommended for Full mode |
| **Multi-device** | Push once, pull anywhere | Manual DB sync |
| **Setup time** | One command | Install Ollama + models |
| **Cost** | Free tier / [Pro plans](https://neurostack.sh) | Free (your hardware) |

### Cloud (recommended)

No GPU, no Ollama, no ML dependencies. Gemini indexes your vault server-side and returns a ready-to-use SQLite database. All search runs locally against that DB.

```bash
neurostack install            # choose "Cloud"
neurostack init               # point at your vault
neurostack cloud push         # upload + index via Gemini
neurostack cloud pull         # download indexed DB
```

Free tier: 500 queries/month, 200 notes. Dashboard: [app.neurostack.sh](https://app.neurostack.sh) -- vault stats, API keys, usage, billing, query playground.

> Files are uploaded for indexing via HTTPS, processed by Gemini, and not retained after indexing completes.

### Local (self-hosted)

Run everything on your machine with Ollama. Choose a tier during `neurostack install`:

- **Lite** (~130 MB) -- FTS5 search, wiki-link graph, stale detection, MCP server. No GPU or Ollama required.
- **Full** (~560 MB) -- adds semantic search, AI summaries, and cross-encoder reranking via local [Ollama](https://ollama.ai). GPU or 6+ core CPU recommended.
- **Community** (~575 MB) -- adds GraphRAG topic clustering via Leiden algorithm.

<details>
<summary><strong>Alternative install methods</strong></summary>

```bash
# PyPI
pipx install neurostack
pip install neurostack                # inside a venv
uv tool install neurostack

# One-line script
curl -fsSL https://raw.githubusercontent.com/raphasouthall/neurostack/main/install.sh | bash

# Lite mode (no ML deps)
curl -fsSL https://raw.githubusercontent.com/raphasouthall/neurostack/main/install.sh | NEUROSTACK_MODE=lite bash
```

> On Ubuntu 23.04+, Debian 12+, Fedora 38+, bare `pip install` outside a venv is blocked by [PEP 668](https://peps.python.org/pep-0668/). Use `npm`, `pipx`, or `uv tool install`.

</details>

To uninstall: `neurostack uninstall`

## MCP configuration

Add to your MCP client config (Claude Code, Codex, Gemini CLI, Cursor, Windsurf):

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

After install, all commands work the same in both Cloud and Local modes.

Setup guides: [Claude Code](https://docs.anthropic.com/en/docs/claude-code/cli-usage) | [Codex](https://developers.openai.com/codex/mcp/) | [Gemini CLI](https://geminicli.com/docs/tools/mcp-server/)

## Search

Retrieval is tiered. Most queries resolve at the cheapest tier:

| Tier | Tokens | What your AI gets | Example |
|------|--------|-------------------|---------|
| **Triples** | ~15 | Structured facts: `Alpha API -> uses -> PostgreSQL 16` | Quick lookups, factual questions |
| **Summaries** | ~75 | AI-generated note summary | "What is this project about?" |
| **Full content** | ~300 | Actual Markdown content | Deep dives, editing context |
| **Auto** | Varies | Starts at triples, escalates only if coverage is low | Default for most queries |

Full mode adds hybrid semantic + keyword search with cross-encoder reranking. Workspace scoping restricts queries to a vault subdirectory.

```bash
neurostack search "deployment checklist"
neurostack tiered "auth flow" --top-k 3
neurostack search -w "work/" "query"       # workspace scoping
neurostack --json search "query" | jq      # machine-readable output
```

## Maintain

**Stale note detection.** When a note keeps appearing in search contexts where it doesn't belong, NeuroStack flags it as a prediction error. Old decisions, superseded specs, reversed conclusions -- without detection, your AI cites these confidently.

**Excitability decay.** Recently accessed notes score higher in search results. Unused notes fade over time. Modeled on CREB-regulated neuronal excitability (Han et al. 2007).

**Co-occurrence learning.** Notes retrieved together frequently get their connection weights strengthened automatically. The search graph learns your actual workflow, not just your file structure.

**Topic clusters.** Leiden community detection groups notes into thematic clusters for broad "what do I know about X?" queries. Optional -- requires the `community` install extra (GPL).

```bash
neurostack prediction-errors             # stale note detection
neurostack decay                         # excitability report
neurostack communities build             # run Leiden clustering
neurostack watch                         # auto-index on vault changes
```

## Agent memories

AI assistants can write typed memories back to NeuroStack: `observation`, `decision`, `convention`, `learning`, `context`, `bug`. Memories are stored in SQLite and surfaced automatically in `vault_search` results.

- Near-duplicate detection with merge support
- Optional TTL for ephemeral memories
- Tag suggestions on save
- Update in place or merge two memories with audit trail

```bash
neurostack memories add "postgres 16 requires --wal-level=replica" --type decision --tags "db,postgres"
neurostack memories search "postgres"
neurostack memories merge <target> <source>
neurostack memories prune --expired
```

## Session harvest

Scans Claude Code JSONL session transcripts, extracts insights (observations, decisions, conventions, bugs), and deduplicates against existing memories before saving.

```bash
neurostack harvest --sessions 5          # extract from last 5 sessions
neurostack hooks install                 # install systemd timer for hourly harvest
neurostack sessions search "query"       # search raw transcripts
```

## Context recovery

Two modes for rebuilding working context after `/clear` or starting a new session:

- **`vault_context`** -- task-anchored. Assembles relevant notes, memories, and triples for a specific task within a token budget.
- **`session_brief`** -- time-anchored. Compact briefing of recent activity, hot notes, and alerts.

```bash
neurostack context "migrate auth to OAuth2" --budget 2000
neurostack brief
```

## Build

NeuroStack scaffolds new vaults or onboards existing Markdown directories. Six profession packs provide domain-specific templates, seed notes, and workflow guidance.

```bash
neurostack init                        # interactive setup, offers profession packs
neurostack onboard ~/my-notes          # import existing notes with frontmatter generation
neurostack scaffold devops             # apply a pack to an existing vault
neurostack scaffold --list             # researcher, developer, writer, student, devops, data-scientist
```

```
~/your-vault/                           # your Markdown files (never modified)
~/.config/neurostack/config.toml        # configuration
~/.local/share/neurostack/
    neurostack.db                       # SQLite + FTS5 knowledge graph
    sessions.db                         # session transcript index
```

<details>
<summary><strong>MCP tools (21 tools)</strong></summary>

| Tool | Description |
|------|-------------|
| `vault_search` | Hybrid search with tiered depth (`triples`, `summaries`, `full`, `auto`) |
| `vault_ask` | RAG Q&A with inline citations |
| `vault_summary` | Pre-computed note summary |
| `vault_graph` | Wiki-link neighborhood with PageRank scores |
| `vault_related` | Semantically similar notes by embedding distance |
| `vault_triples` | Knowledge graph facts (subject-predicate-object) |
| `vault_communities` | GraphRAG queries across topic clusters |
| `vault_context` | Task-scoped context assembly within token budget |
| `session_brief` | Compact session briefing |
| `vault_stats` | Index health, excitability breakdown, memory stats |
| `vault_record_usage` | Track note hotness |
| `vault_prediction_errors` | Surface stale notes |
| `vault_remember` | Store a memory (returns duplicate warnings + tag suggestions) |
| `vault_update_memory` | Update a memory in place |
| `vault_merge` | Merge two memories (unions tags, audit trail) |
| `vault_forget` | Delete a memory |
| `vault_memories` | List or search memories |
| `vault_harvest` | Extract insights from session transcripts |
| `vault_capture` | Quick-capture to vault inbox |
| `vault_session_start` | Begin a memory session |
| `vault_session_end` | End session with optional summary and auto-harvest |

</details>

<details>
<summary><strong>CLI reference</strong></summary>

```
# Setup
neurostack install                       # install/upgrade mode and Ollama models
neurostack init [path] -p researcher     # interactive setup wizard
neurostack onboard ~/my-notes            # import existing Markdown notes
neurostack scaffold researcher           # apply a profession pack
neurostack update                        # pull latest source + re-sync deps
neurostack uninstall                     # complete removal

# Search & retrieval
neurostack search "query"                # hybrid search
neurostack ask "question"                # RAG Q&A with citations
neurostack tiered "query"                # tiered: triples -> summaries -> full
neurostack triples "query"               # knowledge graph triples
neurostack summary "note.md"             # AI-generated note summary
neurostack related "note.md"             # semantically similar notes
neurostack graph "note.md"               # wiki-link neighborhood
neurostack communities query "topic"     # GraphRAG across topic clusters
neurostack context "task" --budget 2000  # task-scoped context recovery
neurostack brief                         # session briefing

# Maintenance
neurostack index                         # build/rebuild knowledge graph
neurostack watch                         # auto-index on vault changes
neurostack decay                         # excitability report
neurostack prediction-errors             # stale note detection
neurostack backfill [summaries|triples|all]  # fill gaps in AI data
neurostack reembed-chunks                # re-embed all chunks

# Memories
neurostack memories add "text" --type observation  # store (--ttl 7d)
neurostack memories search "query"       # search memories
neurostack memories list                 # list all
neurostack memories update <id> --content "revised"
neurostack memories merge <target> <source>
neurostack memories forget <id>          # remove
neurostack memories prune --expired      # clean up

# Sessions
neurostack harvest --sessions 5          # extract session insights
neurostack sessions search "query"       # search transcripts
neurostack hooks install                 # hourly harvest timer

# Cloud
neurostack cloud login                   # browser OAuth login
neurostack cloud status                  # auth + vault info
neurostack cloud push                    # upload + index vault
neurostack cloud pull                    # download indexed DB
neurostack cloud query "query"           # search via cloud API

# Diagnostics
neurostack stats                         # index health
neurostack doctor                        # validate all subsystems
neurostack demo                          # interactive demo with sample vault
```

</details>

## FAQ

**Does it modify my vault files?** No. All data lives in NeuroStack's own SQLite databases. Your Markdown files are strictly read-only.

**Do I need a GPU?** No. Use NeuroStack Cloud for zero-GPU setup. For local mode, Lite has zero ML dependencies. Full mode runs on CPU but summarization is slow without a GPU.

**How large a vault can it handle?** Tested with ~5,000 notes. FTS5 search stays fast at any size. Cloud indexing handles 500+ notes in minutes.

**Can I use it without MCP?** Yes. The CLI works standalone. Pipe output into any LLM.

**Is my vault private?** In local mode, nothing leaves your machine. In cloud mode, your Markdown files are uploaded for indexing via HTTPS, processed by Gemini, and the indexed DB is returned. Files are not stored after indexing completes.

## Requirements

- Linux or macOS
- **Cloud mode**: just Node.js. No GPU, no Ollama, no Python ML deps.
- **Local Full mode**: [Ollama](https://ollama.ai) with `nomic-embed-text` and a summary model. GPU or 6+ core CPU recommended.

<details>
<summary><strong>Neuroscience basis</strong></summary>

Each maintenance feature is modeled on a specific mechanism from memory neuroscience:

| Feature | Mechanism | Citation |
|---------|-----------|----------|
| Stale detection | Prediction error signals trigger reconsolidation | Sinclair & Bhatt 2022 |
| Excitability decay | CREB-elevated neurons preferentially join new memories | Han et al. 2007 |
| Co-occurrence learning | Hebbian "fire together, wire together" plasticity | Hebb 1949 |
| Topic clusters | Neural ensemble formation | Cai et al. 2016 |
| Tiered retrieval | Complementary learning systems | McClelland et al. 1995 |

Full citations: [docs/neuroscience-appendix.md](docs/neuroscience-appendix.md)

</details>

## Get involved

- **Website**: [neurostack.sh](https://neurostack.sh)
- **Contributing**: [CONTRIBUTING.md](CONTRIBUTING.md)
- **Contact**: [hello@neurostack.sh](mailto:hello@neurostack.sh)
- **Sponsor**: [GitHub Sponsors](https://github.com/sponsors/raphasouthall) | [Buy me a coffee](https://buymeacoffee.com/raphasouthall)

## License

Apache-2.0 -- see [LICENSE](LICENSE).

The optional `neurostack[community]` extra installs [leidenalg](https://github.com/vtraag/leidenalg) (GPL-3.0) and [python-igraph](https://github.com/igraph/python-igraph) (GPL-2.0+). These are isolated behind a runtime import guard and not installed by default.
