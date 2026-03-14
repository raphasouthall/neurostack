<a href="https://neurostack.sh"><img src="docs/logo.svg" alt="NeuroStack" height="48"></a>

[![npm](https://img.shields.io/npm/v/neurostack)](https://www.npmjs.com/package/neurostack)
[![PyPI](https://img.shields.io/pypi/v/neurostack)](https://pypi.org/project/neurostack/)
[![Python](https://img.shields.io/pypi/pyversions/neurostack)](https://pypi.org/project/neurostack/)
[![CI](https://github.com/raphasouthall/neurostack/actions/workflows/ci.yml/badge.svg)](https://github.com/raphasouthall/neurostack/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)
[![Sponsor](https://img.shields.io/badge/sponsor-NeuroStack-ea4aaa?logo=githubsponsors)](https://github.com/sponsors/raphasouthall)

> **Looking for sponsors** — NeuroStack is built and maintained by a single developer. If it's useful to you, consider [sponsoring the project](https://github.com/sponsors/raphasouthall) to help fund development, hosting, and new features.

**Your second brain, starting today.** Install one command, answer a few questions, and you have a knowledge vault that gets smarter every day you use it.

NeuroStack helps you start and grow a personal knowledge base — whether you have thousands of notes or none at all. It scaffolds a vault, indexes everything by meaning, surfaces what needs attention, and gives your AI tools long-term memory. It works with **any AI provider** — use it as an [MCP server](https://modelcontextprotocol.io), as a [CLI tool alongside Claude](https://docs.anthropic.com/en/docs/claude-code/cli-usage), or pipe its output into any LLM workflow. Everything runs locally. Your notes never leave your machine.

## Get started

```bash
npm install -g neurostack
neurostack install
neurostack init
```

1. **`npm install -g neurostack`** — bootstraps the CLI (handles Python, uv, and all dependencies automatically).
2. **`neurostack install`** — interactive wizard to choose your installation mode and optionally set up Ollama models.
3. **`neurostack init`** — walks you through vault location, LLM config, and profession packs.

No prior config needed. No Python, git, or curl required.

### Installation modes

| Mode | What you get | Size | GPU needed? |
|------|-------------|------|-------------|
| **lite** (default) | FTS5 search, wiki-link graph, stale note detection, MCP server | ~130 MB | No |
| **full** | + semantic search, AI summaries, cross-encoder reranking | ~560 MB | No (CPU inference) |
| **community** | + GraphRAG topic clustering (Leiden algorithm) | ~575 MB | No |

The `install` command handles everything — dependency syncing via `uv`, Ollama installation, model pulls, and config updates. It detects what's already installed and skips unnecessary work:

```bash
# Interactive — walks you through mode, Ollama, and model selection
neurostack install

# Non-interactive — specify mode directly
neurostack install --mode full

# Full mode + pull Ollama models in one shot
neurostack install --mode full --pull-models

# Custom models
neurostack install --mode full --pull-models --embed-model nomic-embed-text --llm-model qwen3:8b
```

When choosing full or community mode:
- **Ollama not installed?** — offers to install it automatically (Linux) or shows the download link (macOS).
- **Models already pulled?** — skips the download and moves on.

You can re-run `neurostack install` at any time to upgrade between modes (e.g., lite → full).

<details>
<summary><strong>Alternative install methods</strong></summary>

```bash
# PyPI
pipx install neurostack              # isolated environment
pip install neurostack               # inside a venv
uv tool install neurostack           # uv users

# One-line script (lite mode)
curl -fsSL https://raw.githubusercontent.com/raphasouthall/neurostack/main/install.sh | bash

# One-line script (full mode)
curl -fsSL https://raw.githubusercontent.com/raphasouthall/neurostack/main/install.sh | NEUROSTACK_MODE=full bash
```

> **Note:** On Ubuntu 23.04+, Debian 12+, and Fedora 38+, bare `pip install` outside a virtual environment is blocked by [PEP 668](https://peps.python.org/pep-0668/). Use `npm`, `pipx`, `uv tool install`, or create a venv first.

</details>

To uninstall:

```bash
neurostack uninstall
```

## What it does

### Build — start your second brain in minutes
- **Interactive setup** — `neurostack init` walks you through vault location, model selection, and profession packs. No docs to read first.
- **Scaffolds your vault** — profession-ready templates and folder structures so you're not staring at an empty folder.
- **Onboards existing notes** — point it at any folder of Markdown files and it adds frontmatter, generates indexes, and sets up the vault structure. No manual migration.
- **Works with what you have** — connects to any Markdown vault. Use [Obsidian](https://obsidian.md), [Logseq](https://logseq.com), or plain `.md` files.

### Maintain — your vault gets better every day
- **Finds stale notes** — surfaces notes that keep appearing in searches where they don't belong. The signal to review before they mislead you or your AI.
- **Remembers what matters** — recent, active notes get priority. Old, unused notes fade — just like real memory.
- **Maps your knowledge** — reveals hidden connections and topic clusters you never planned.
- **Watches for changes** — auto-indexes new and updated notes so your vault is always current.

### Search — find anything by meaning, not just keywords
- **Searches by meaning** — finds notes by what they say, not just what they're titled. Ask a question, get an answer.
- **Works with any AI tool** — use as an MCP server with [Claude Code](https://docs.anthropic.com/en/docs/claude-code/cli-usage), [Codex](https://developers.openai.com/codex/mcp/), [Gemini CLI](https://geminicli.com/docs/tools/mcp-server/), Cursor, Windsurf, or any MCP-compatible client. Or pipe CLI output into any LLM workflow.
- **Saves tokens** — tiered retrieval sends your AI key facts first, full notes only when needed. 96% fewer tokens per query than naive RAG.

<img src="docs/screenshots/prediction-errors.svg" alt="NeuroStack surfacing stale notes" width="720">

<img src="docs/screenshots/07-search.svg" alt="NeuroStack search" width="720">

<img src="docs/screenshots/brief.svg" alt="NeuroStack daily brief" width="720">

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

## Profession packs

NeuroStack ships with profession-specific starter packs — domain templates, seed notes, and workflow guidance so you're not starting from a blank vault.

```bash
# The interactive setup offers profession packs automatically
neurostack init

# Or apply to an existing vault
neurostack scaffold researcher

# See what's available
neurostack scaffold --list
```

Each pack adds:
- **Templates** — domain-specific note formats (e.g., experiment logs, synthesis notes)
- **Seed research notes** — interconnected examples showing the vault in action
- **Extra directories** — folder structure tailored to the workflow
- **CLAUDE.md guidance** — workflow instructions for your AI assistant

| Pack | Description | Templates | Seed Notes |
|------|-------------|-----------|------------|
| **researcher** | Academic or independent researcher — literature reviews, experiments, thesis work | synthesis-note, experiment-log, method-note, paper-project | 6 |
| **developer** | Software developer or engineer — architecture decisions, code reviews, debugging | architecture-decision, code-review-note, debugging-log, technical-spec | 6 |
| **writer** | Writer or content creator — fiction, articles, worldbuilding, craft notes | article-draft, character-profile, story-outline, world-building-note | 5 |
| **student** | Student or lifelong learner — lectures, study guides, courses, exam prep | assignment-tracker, course-overview, lecture-note, study-guide | 5 |
| **devops** | DevOps engineer or SRE — runbooks, incidents, infrastructure, change management | change-request, incident-report, infrastructure-note, runbook | 6 |
| **data-scientist** | Data scientist or ML engineer — analyses, models, datasets, experiment tracking | analysis-note, dataset-note, model-card, pipeline-note | 6 |

Contributions of new profession packs are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Token economy

NeuroStack's tiered retrieval sends your AI only what it needs:

| Depth | Tokens per result | When it's used |
|-------|-------------------|----------------|
| **Triples** | ~15 tokens | Quick factual lookups — 80% of queries resolve here |
| **Summaries** | ~75 tokens | When you need more context |
| **Full content** | ~300 tokens | Deep dives into specific notes |

Compared to naive RAG (dumping full document chunks at ~750 tokens each), NeuroStack uses **96% fewer tokens** per query. That means lower API costs, faster responses, and more of your AI's attention on actually answering your question instead of processing background noise.

## Agent memories

Your AI can write back short-lived memories — observations, decisions, conventions, bugs — that surface automatically in future `vault_search` results. Unlike vault notes, memories are lightweight and can expire.

**MCP tools:** `vault_remember`, `vault_forget`, `vault_memories`

```bash
# CLI
neurostack memories add "deployment requires VPN" --type convention
neurostack memories add "auth token expires in 1h" --type observation --ttl 7d
neurostack memories search "deployment"
neurostack memories list
neurostack memories forget <id>
neurostack memories prune              # Remove expired memories
neurostack memories stats
```

**Entity types:** `observation`, `decision`, `convention`, `learning`, `context`, `bug`

Memories with a `--ttl` auto-expire after the given duration. Without TTL, they persist until explicitly forgotten or pruned.

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

## What gets installed

`npm install -g neurostack` bootstraps the CLI, then `neurostack install` lets you choose your mode. Here's exactly what ends up on your machine:

### Lite mode (default)

Installed with `neurostack install --mode lite` (or the default interactive selection).

| Component | Location | Size | What it is |
|-----------|----------|------|------------|
| npm wrapper | `$(npm root -g)/neurostack/` | ~20 KB | Node.js bin + install scripts |
| uv | `~/.local/bin/uv` | ~30 MB | Python package manager (auto-installed) |
| Python 3.12 | `~/.local/share/uv/python/` | ~50 MB | Standalone Python managed by uv (not your system Python) |
| NeuroStack source | `~/.local/share/neurostack/repo/` | ~2 MB | Python source + vault templates |
| Python venv + deps | `~/.local/share/neurostack/repo/.venv/` | ~50 MB | pyyaml, watchdog, mcp, httpx |
| Config | `~/.config/neurostack/config.toml` | ~200 B | Vault path, Ollama endpoints, model name |
| Database | `~/.local/share/neurostack/neurostack.db` | Grows with vault | SQLite + FTS5 knowledge graph |

**Total: ~130 MB.** No GPU needed. Keyword search, wiki-link graph, stale note detection, and MCP server all work in lite mode.

### Full mode

Installed with `neurostack install --mode full`. Adds ML dependencies on top of lite.

| Component | Location | Size | What it is |
|-----------|----------|------|------------|
| Everything from lite | (see above) | ~130 MB | |
| numpy | in `.venv/` | ~30 MB | Numerical computing |
| sentence-transformers | in `.venv/` | ~100 MB | Embedding and reranking models |
| PyTorch (CPU) | in `.venv/` | ~300 MB | ML runtime (CPU-only, pulled by sentence-transformers) |
| Ollama (external) | User-installed | ~1 GB+ | Required for embeddings and summaries — [install separately](https://ollama.ai) |

**Total: ~560 MB** + Ollama. Adds semantic search, AI-generated summaries/triples, and cross-encoder reranking.

### Community mode

Installed with `neurostack install --mode community`. Adds community detection on top of full.

| Component | Location | Size | What it is |
|-----------|----------|------|------------|
| Everything from full | (see above) | ~560 MB | |
| leidenalg | in `.venv/` | ~5 MB | Leiden community detection (GPL-3.0) |
| python-igraph | in `.venv/` | ~10 MB | Graph analysis library (GPL-2.0+) |

**Total: ~575 MB** + Ollama. Adds topic cluster detection across your vault.

### Clean removal

```bash
neurostack uninstall    # Removes source, venv, database — preserves config
```

Config at `~/.config/neurostack/` is kept so a reinstall picks up where you left off. To remove everything: `rm -rf ~/.config/neurostack`.

## CLI

NeuroStack is a command-line tool. Every feature is available from your terminal:

```
neurostack install                  # Install/upgrade mode and Ollama models
neurostack install --mode full --pull-models  # Non-interactive install
neurostack init                     # Interactive setup wizard
neurostack init [path] -p researcher  # Non-interactive with profession pack
neurostack onboard ~/my-notes       # Onboard an existing folder of notes
neurostack onboard ~/my-notes -n    # Dry run — preview changes first
neurostack scaffold researcher      # Apply a profession pack to existing vault
neurostack scaffold --list          # List available profession packs
neurostack index                    # Build the knowledge graph
neurostack search "query"           # Search by meaning or keywords
neurostack search -w "work/" "query"  # Search scoped to a workspace path
neurostack memories list              # List agent write-back memories
neurostack graph "note.md"          # See a note's connections
neurostack prediction-errors        # Find stale or misleading notes
neurostack communities query "topic"  # Explore topic clusters
neurostack brief                    # Morning briefing — what needs attention
neurostack record-usage note.md     # Mark notes as used (drives hotness scoring)
neurostack stats                    # Index health overview
neurostack doctor                   # Validate all subsystems
neurostack watch                    # Watch vault for changes, re-index automatically
neurostack serve                    # Start as MCP server for AI tools
neurostack uninstall                # Complete removal — data, deps, and npm package
```

<details>
<summary><strong>More commands</strong></summary>

```
neurostack tiered "query"           # Tiered search: triples → summaries → full
neurostack triples "query"          # Search structured knowledge triples
neurostack summary "note.md"        # Get a note's AI-generated summary
neurostack communities build        # Run Leiden detection + generate summaries
neurostack communities list         # List detected topic clusters
neurostack backfill [summaries|triples|all]  # Fill gaps in AI-generated data
neurostack reembed-chunks           # Re-embed all chunks
neurostack folder-summaries         # Build folder-level context summaries
neurostack sessions search "query"  # Search session transcripts
neurostack memories add "text" --type observation  # Store a memory
neurostack memories search "query"  # Search memories
neurostack memories list            # List all memories
neurostack memories forget <id>     # Remove a memory
neurostack memories prune           # Remove expired memories
neurostack memories stats           # Memory store overview
neurostack demo                     # Interactive demo with sample vault
neurostack status                   # Overview of your vault and config
```

</details>

## Use with any AI provider

NeuroStack is provider-agnostic. Your vault is a local SQLite database with a CLI and MCP interface — use it however fits your workflow.

### MCP server (Claude Code, Codex, Gemini CLI, Cursor, Windsurf, etc.)

Add to your MCP config and your AI assistant gets long-term memory from your vault. Works with any [MCP-compatible client](https://modelcontextprotocol.io):

- [Claude Code MCP setup](https://docs.anthropic.com/en/docs/claude-code/cli-usage)
- [Codex MCP setup](https://developers.openai.com/codex/mcp/)
- [Gemini CLI MCP setup](https://geminicli.com/docs/tools/mcp-server/)

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

### CLI (works with everything)

The CLI outputs plain text — pipe it into any AI tool or workflow:

```bash
# Use with Claude Code as a CLI tool
# See: https://docs.anthropic.com/en/docs/claude-code/cli-usage
neurostack search "deployment checklist"

# JSON output for scripting — all query commands support --json
neurostack --json search "query" | jq '.[] | .title'

# Scope to a workspace path (or set NEUROSTACK_WORKSPACE env var)
neurostack search -w "work/" "deployment"
export NEUROSTACK_WORKSPACE=work/my-project

# Pipe into any LLM
neurostack search "project architecture" | llm "summarize these notes"

# Use in scripts, CI, or automation
CONTEXT=$(neurostack tiered "auth flow" --top-k 3)
echo "$CONTEXT" | your-preferred-ai-tool
```

<details>
<summary><strong>All 12 MCP tools</strong></summary>

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
| `vault_remember` | Store a memory (observation, decision, convention, learning, context, or bug) |
| `vault_forget` | Remove a memory by ID |
| `vault_memories` | List or search stored memories |
| `session_brief` | Get a compact briefing when starting a new session |

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

NeuroStack **never modifies your vault files**. All data (indexes, memories, sessions) lives in its own databases.

## Requirements

- Linux or macOS
- **npm install**: Just Node.js — everything else is installed automatically
- **Full mode**: [Ollama](https://ollama.ai) with `nomic-embed-text` and a summary model (e.g., `phi3.5`)

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
