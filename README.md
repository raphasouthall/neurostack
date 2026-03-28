<a href="https://neurostack.sh"><img src="docs/logo.svg" alt="NeuroStack" height="48"></a>

[![PyPI](https://img.shields.io/pypi/v/neurostack)](https://pypi.org/project/neurostack/)
[![CI](https://github.com/raphasouthall/neurostack/actions/workflows/ci.yml/badge.svg)](https://github.com/raphasouthall/neurostack/actions/workflows/ci.yml)

**Your notes are lying to you.** That runbook from last quarter? It references an API endpoint you deprecated in February. The architecture decision record your AI just cited? It was reversed two sprints ago. Every knowledge base decays -- and AI agents that search it will confidently repeat whatever they find.<sup>1</sup>

NeuroStack is the memory layer that fights this. It indexes your Markdown vault into a knowledge graph, detects stale notes before your AI cites them, and tiers retrieval so simple queries cost ~15 tokens instead of ~300. It persists agent memories across sessions, tracks what you actually use, and surfaces what's gone stale. Your vault files are never modified.

**Built for anyone whose knowledge goes stale.** Researchers tracking evolving literature. Writers managing world-building bibles. Engineers maintaining runbooks. Students revising across courses. If your notes change faster than you can remember, NeuroStack keeps your AI honest.

Works with Claude Code, Cursor, Windsurf, Codex, and Gemini CLI via MCP.

<sub><sup>1</sup> Prediction error signals -- when retrieved content diverges from query context -- trigger reconsolidation in biological memory (Sinclair & Bhatt 2022). NeuroStack applies the same principle: notes that keep appearing where they don't belong are flagged and demoted.</sub>

## Get started

```bash
npm install -g neurostack
neurostack init
```

The wizard walks you through everything: cloud or local, lite or full, Ollama models, vault path, profession pack, and full indexing -- one command.

| | Cloud | Local |
|--|-------|-------|
| **Best for** | Zero friction, any machine | Privacy-first, offline, power users |
| **Indexing** | Gemini API (server-side) | Ollama on your machine |
| **Search** | Local SQLite | Local SQLite (same DB) |
| **GPU required** | No | Recommended for Full mode |
| **Multi-device** | Push once, pull anywhere | Manual DB sync |
| **Cost** | Free tier / [Pro plans](https://neurostack.sh) | Free (your hardware) |

### Cloud

No GPU, no Ollama, no ML dependencies. Gemini indexes your vault server-side and returns a ready-to-use SQLite database. All search runs locally against that DB.

```bash
neurostack init     # choose "Cloud" → vault setup → login → push
```

Free tier: 500 queries/month, 200 notes. Dashboard: [app.neurostack.sh](https://app.neurostack.sh)

> **Privacy notice:** Cloud mode requires explicit consent before uploading. Your vault files are sent to Google's Gemini API for indexing (embeddings, summaries, knowledge graph triples). Files are processed via HTTPS and not retained after indexing completes. Run `neurostack cloud consent` to review and grant consent. You can exclude sensitive files with a `.neurostackignore` file (gitignore syntax).

### Local

Run everything on your machine with Ollama. Choose a tier during `neurostack init`:

- **Lite** (~130 MB) -- FTS5 search, wiki-link graph, stale detection, MCP server. No GPU or Ollama required.
- **Full** (~560 MB) -- adds semantic search, AI summaries, knowledge graph triples, and attractor basin community detection via local [Ollama](https://ollama.ai). GPU or 6+ core CPU recommended.

Full mode automatically runs the complete indexing pipeline: embeddings, summaries, triples, and community detection.

Non-interactive mode:

```bash
neurostack init --mode full --pull-models ~/brain
neurostack init --cloud ~/brain
```

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

## Connect to your AI

### Claude Code (one command)

```bash
claude mcp add neurostack -- neurostack serve
```

### Claude Desktop

Download the `.mcpb` bundle from [Releases](https://github.com/raphasouthall/neurostack/releases) and double-click to install. Or auto-configure:

```bash
neurostack setup-desktop
```

### Remote MCP (no local install)

Connect Claude to your vault via NeuroStack Cloud -- no Python, no Ollama, nothing to install locally:

```bash
claude mcp add neurostack --transport http https://mcp.neurostack.sh/mcp
```

### Other MCP clients

Auto-configure Cursor, Windsurf, Gemini CLI, VS Code, or Codex:

```bash
neurostack setup-client cursor      # or: windsurf, gemini, vscode, claude-code
neurostack setup-client --list      # show all supported clients
```

<details>
<summary><strong>Manual JSON config</strong></summary>

Add to your client's MCP config file:

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

</details>

After connecting, all 21 MCP tools are available. Search your vault, save memories, detect stale notes -- all from your AI chat.

## Search

Retrieval is tiered. Most queries resolve at the cheapest tier:

| Tier | Tokens | What your AI gets | Example |
|------|--------|-------------------|---------|
| **Triples** | ~15 | Structured facts: `Chapter 3 -> introduces -> Elena's backstory` | Quick lookups, factual questions |
| **Summaries** | ~75 | AI-generated note summary | "What is this project about?" |
| **Full content** | ~300 | Actual Markdown content | Deep dives, editing context |
| **Auto** | Varies | Starts at triples, escalates only if coverage is low | Default for most queries |

Full mode adds hybrid semantic + keyword search with neuroscience-grounded ranking: energy landscape convergence, lateral inhibition, and prediction error feedback. Workspace scoping restricts queries to a vault subdirectory.

```bash
neurostack search "spaced repetition vs interleaving"
neurostack tiered "character motivation in act 2" --top-k 3
neurostack search -w "work/project-x" "API migration plan"
neurostack --json search "query" | jq      # machine-readable output
```

## Maintain

**Stale note detection.** When a note keeps appearing in search contexts where it doesn't belong, NeuroStack flags it as a prediction error. Old decisions, superseded specs, reversed conclusions -- without detection, your AI cites these confidently. Notes with unresolved prediction errors are automatically demoted in future search results.

**Excitability decay.** Recently accessed notes score higher in search results. Unused notes fade over time. Modeled on CREB-regulated neuronal excitability (Han et al. 2007).

**Co-occurrence learning.** Notes retrieved together frequently get their connection weights strengthened automatically. The search graph learns your actual workflow, not just your file structure.

**Topic clusters.** Attractor basin community detection groups notes into thematic clusters for broad "what do I know about X?" queries. Uses Hopfield-style dynamics with a blended similarity matrix (embeddings + co-occurrence + wiki-links). Included in Full mode -- no extra dependencies.

**Lateral inhibition.** Higher-ranked search results suppress semantically similar competitors, promoting diversity. Prevents five near-identical notes from dominating your results.

```bash
neurostack prediction-errors             # stale note detection
neurostack decay                         # excitability report
neurostack communities build             # rebuild topic clusters
neurostack watch                         # auto-index on vault changes
```

## Agent memories

AI assistants can write typed memories back to NeuroStack: `observation`, `decision`, `convention`, `learning`, `context`, `bug`. Memories are stored in SQLite and surfaced automatically in `vault_search` results.

- Near-duplicate detection with merge support
- Optional TTL for ephemeral memories
- Tag suggestions on save
- Update in place or merge two memories with audit trail

```bash
neurostack memories add "revised thesis to focus on complementary learning systems, not just consolidation" --type decision --tags "thesis,neuroscience"
neurostack memories search "thesis direction"
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
neurostack context "migrate auth service to OIDC" --budget 2000
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
neurostack init                          # one-command setup: deps, vault, index
neurostack init --mode full ~/brain      # non-interactive full mode
neurostack init --cloud ~/brain          # non-interactive cloud mode
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
neurostack communities build             # rebuild topic clusters
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
neurostack cloud sync                    # push changes + fetch memories
neurostack cloud query "query"           # search via cloud API
neurostack cloud consent                 # review and grant privacy consent
neurostack cloud install-hooks           # auto-sync on git commit/merge
neurostack cloud auto-sync enable        # periodic sync via systemd timer
neurostack cloud auto-sync disable       # stop periodic sync
neurostack cloud auto-sync status        # check timer status

# Diagnostics
neurostack stats                         # index health
neurostack doctor                        # validate all subsystems
neurostack demo                          # interactive demo with sample vault
```

</details>

## Cloud Sync

Keep your vault indexed across machines without manual push/pull.

**Automatic sync triggers:**

- **Git hooks** -- sync on every commit or merge: `neurostack cloud install-hooks`
- **systemd timer** -- periodic background sync: `neurostack cloud auto-sync enable --interval 15min`
- **Manual** -- push changes and fetch memories in one command: `neurostack cloud sync`

**Upload format:** Vault files are packed into a compressed tar.gz archive with a manifest, replacing the legacy multipart format. Typical compression is 60-80%, breaking the old 32 MB upload limit.

**Concurrent push safety:** A server-side push lock prevents two devices from pushing simultaneously. If another device is mid-push, you'll get a clear conflict message with the lock expiry time.

**`.neurostackignore`:** Place a `.neurostackignore` file in your vault root to exclude sensitive paths from cloud upload. Uses gitignore syntax:

```
# Exclude private notes
private/
journal/*.md
*-draft.md
```

**Progress reporting:** Push and sync operations report file count, compressed size, and compression ratio as they run.

> **Upgrading from v0.10.x:** Cloud mode now requires explicit consent before uploading. On your first push after upgrading, run `neurostack cloud consent` to grant consent. Existing cloud users will be prompted automatically. The upload format has changed from multipart to tar.gz -- servers running v0.10.0+ accept both formats during the transition period. If push fails, add `upload_format = "multipart"` to `[cloud]` in `~/.config/neurostack/config.toml` as a temporary workaround.

## FAQ

**Does it modify my vault files?** No. All data lives in NeuroStack's own SQLite databases. Your Markdown files are strictly read-only.

**Do I need a GPU?** No. Use NeuroStack Cloud for zero-GPU setup. For local mode, Lite has zero ML dependencies. Full mode runs on CPU but summarization is slow without a GPU.

**How large a vault can it handle?** Tested with ~5,000 notes. FTS5 search stays fast at any size. Cloud indexing handles 500+ notes in minutes.

**Can I use it without MCP?** Yes. The CLI works standalone. Pipe output into any LLM.

**Who is this for?** Anyone whose notes go stale. Researchers whose cited papers get retracted or superseded. Writers whose character backstories contradict later chapters. Engineers whose runbooks reference deprecated APIs. Students whose revision notes cover a syllabus that changed. NeuroStack's stale detection catches this before your AI confidently cites something that's no longer true.

**Is my vault private?** In local mode, nothing leaves your machine. In cloud mode, your Markdown files are uploaded for indexing via HTTPS, processed by Gemini, and the indexed DB is returned. Files are not stored after indexing completes.

## Requirements

- Linux or macOS
- **Cloud mode**: just Node.js. No GPU, no Ollama, no Python ML deps.
- **Local Full mode**: [Ollama](https://ollama.ai) with `nomic-embed-text` and a summary model. GPU or 6+ core CPU recommended.

<details>
<summary><strong>Neuroscience basis</strong></summary>

Each feature is modeled on a specific mechanism from memory neuroscience:

| Feature | Mechanism | Citation |
|---------|-----------|----------|
| Stale detection + demotion | Prediction error signals trigger reconsolidation | Sinclair & Bhatt 2022 |
| Excitability decay | CREB-elevated neurons preferentially join new memories | Han et al. 2007 |
| Co-occurrence learning | Hebbian "fire together, wire together" plasticity | Hebb 1949 |
| Topic clusters | Hopfield attractor basin dynamics, inverse temperature | Ramsauer et al. 2020 |
| Convergence confidence | Energy landscape retrieval, basin width = robustness | Krotov & Hopfield 2016 |
| Lateral inhibition | PV+/SOM+ interneuron winner-take-all competition | Rashid et al. 2016 |
| Tiered retrieval | Complementary learning systems | McClelland et al. 1995 |

Full citations: [docs/neuroscience-appendix.md](docs/neuroscience-appendix.md)

</details>

## Get involved

- **Website**: [neurostack.sh](https://neurostack.sh)
- **Contributing**: [CONTRIBUTING.md](CONTRIBUTING.md)
- **Contact**: [hello@neurostack.sh](mailto:hello@neurostack.sh)
- **Sponsor**: [GitHub Sponsors](https://github.com/sponsors/raphasouthall) | [Buy me a coffee](https://buymeacoffee.com/raphasouthall)

## License

Apache-2.0 -- see [LICENSE](LICENSE). No GPL dependencies.
