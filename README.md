<a href="https://neurostack.sh"><img src="docs/logo.svg" alt="NeuroStack" height="48"></a>

[![PyPI](https://img.shields.io/pypi/v/neurostack)](https://pypi.org/project/neurostack/)
[![npm](https://img.shields.io/npm/v/neurostack)](https://www.npmjs.com/package/neurostack)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue)](LICENSE)
[![CI](https://github.com/raphasouthall/neurostack/actions/workflows/ci.yml/badge.svg)](https://github.com/raphasouthall/neurostack/actions/workflows/ci.yml)
[![MCP](https://img.shields.io/badge/MCP-20%20tools-green)](https://modelcontextprotocol.io)

**Not a note-taking app. A memory layer for the notes you already have.**

Your AI assistant forgets everything when the conversation ends. You ask it about the paper you summarised last week — it has no idea. You ask it to continue the chapter outline you built together — it starts from scratch.

And even when it does find your notes, it might find the wrong version. The thesis argument you reversed, the runbook endpoint you deprecated, the decision you made in April that you overturned in June. It cites these confidently. It has no idea they're wrong.

NeuroStack reads your existing Markdown notes — from Obsidian, Logseq, Notion exports, or any folder of `.md` files — indexes them into a searchable knowledge graph, and connects that graph to your AI. It detects when notes have gone stale before your AI cites them. Your files are never modified.

```bash
npm install -g neurostack && neurostack init
```

Works with Claude, Cursor, Windsurf, Gemini CLI, VS Code, and Codex — anything that supports MCP.

---

## Your notes, untouched

Before anything else: NeuroStack is strictly read-only.

- Your Markdown files are **never modified, moved, or deleted**
- All index data lives in NeuroStack's own separate database
- To remove it completely: `neurostack uninstall` — your notes are untouched
- In local mode: nothing ever leaves your machine
- In cloud mode: you review and approve exactly what gets sent, and can exclude any folder with a `.neurostackignore` file

---

## Who this is for

You do not need to be a developer. If you take notes in Markdown — or can export your notes as Markdown from Obsidian, Notion, Bear, or Roam — NeuroStack works for you.

| If you are... | NeuroStack helps you... |
|--------------|------------------------|
| **A researcher** | Ask your AI "what do my notes say about X?" across hundreds of papers. Get warned when a note references a retracted finding or superseded paper before your AI cites it confidently. |
| **A fiction writer** | Your AI knows your world-building bible, character histories, and chapter decisions. "We agreed in session 4 that Elena's backstory changes in act 2" — it remembers that. |
| **A student** | Ask your AI to explain connections across all your course notes. When a syllabus topic changes, stale revision notes are flagged automatically. |
| **A professional** | Your AI remembers client context, project decisions, and meeting notes session-to-session. No more re-pasting the same background every time. |
| **A developer or DevOps engineer** | Notes that reference deprecated APIs or reversed architecture decisions get flagged before your AI cites them as current. |

---

## Get started in three steps

You will need [Node.js](https://nodejs.org) installed (most computers already have it). That is the only prerequisite for cloud mode — no GPU, no Python knowledge, nothing else.

**Step 1 — Install**

```
npm install -g neurostack
```

**Step 2 — Set up** (takes about two minutes)

```
neurostack init
```

The setup wizard asks: cloud or local, which vault folder, which profession pack. It does everything else automatically.

**Step 3 — Connect to your AI**

For Claude Desktop:
```
neurostack setup-desktop
```

For Claude Code:
```
claude mcp add neurostack -- neurostack serve
```

For Cursor, Windsurf, Gemini CLI, or VS Code:
```
neurostack setup-client cursor      # or: windsurf, gemini, vscode
```

**Zero-install option** — connect Claude to your vault via NeuroStack Cloud with nothing installed locally:
```
claude mcp add neurostack --transport http https://mcp.neurostack.sh/mcp
```

Done. Open a new conversation and ask your AI about something from your notes.

**Free tier:** 500 queries/month, 200 notes. No credit card required. [Start at app.neurostack.sh](https://app.neurostack.sh)

<details>
<summary><strong>Cloud vs Local — what's the difference?</strong></summary>

| | Cloud (recommended) | Local |
|--|--------------------|-|
| **What you need** | Just Node.js | Node.js + Ollama (a local AI engine) |
| **GPU required** | No | Recommended, but not required |
| **Setup time** | About 2 minutes | 10-20 minutes |
| **Works offline** | No | Yes |
| **Syncs across devices** | Yes, automatically | Manual |
| **Cost** | Free tier: 500 queries/month, 200 notes. [Pro plans](https://neurostack.sh) for more. | Free. Your hardware, your cost. |
| **Your files** | Sent for indexing via encrypted connection, not stored after processing | Never leave your machine |

**Privacy notice:** Cloud mode requires explicit consent before uploading. Your vault files are sent to Google's Gemini API for indexing (embeddings, summaries, connections between notes). Files are processed via HTTPS and not retained after indexing completes. Run `neurostack cloud consent` to review and grant consent. Exclude sensitive files with a `.neurostackignore` file (gitignore syntax).

</details>

<details>
<summary><strong>Local mode (Lite and Full)</strong></summary>

Run everything on your machine with Ollama. Choose a tier during `neurostack init`:

- **Lite** (~130 MB) — keyword search, link-based connections between notes, stale detection, MCP server. No GPU or Ollama required.
- **Full** (~560 MB) — adds semantic search (finds notes by meaning, not just keywords), AI-generated summaries, connections between notes, and topic clustering via local [Ollama](https://ollama.ai). GPU or 6+ core CPU recommended.

Non-interactive setup:

```bash
neurostack init --mode full ~/my-notes    # local full mode
neurostack init --cloud ~/my-notes        # cloud mode
```

</details>

<details>
<summary><strong>Alternative install methods (PyPI, pip, curl)</strong></summary>

```bash
# PyPI
pipx install neurostack
pip install neurostack        # inside a venv
uv tool install neurostack

# One-line script
curl -fsSL https://raw.githubusercontent.com/raphasouthall/neurostack/main/install.sh | bash

# Lite mode (no ML deps)
curl -fsSL https://raw.githubusercontent.com/raphasouthall/neurostack/main/install.sh | NEUROSTACK_MODE=lite bash
```

On Ubuntu 23.04+, Debian 12+, and Fedora 38+, bare `pip install` outside a virtual environment is blocked by the operating system. Use `npm`, `pipx`, or `uv tool install` instead.

To uninstall: `neurostack uninstall`

</details>

---

## What it actually feels like

**The researcher.** You ask Claude to help write the methodology section. Instead of starting from scratch, it already knows you've read 50 papers on complementary learning systems, that you settled on a particular framing in January, and that the meta-analysis you were relying on has been flagged as stale — it keeps appearing in searches where it no longer fits. You check it, update the note, and the AI's next answer reflects where your thinking actually is.

**The writer.** You ask Cursor to help with chapter eleven. It knows Elena's backstory from chapter two, the decision you made in your world-building notes to keep magic systems implicit, and that you changed her last name in a revision three weeks ago. No contradictions.

**The DevOps engineer.** You ask about the deployment runbook for the auth service. NeuroStack surfaces it — but also flags it as stale. You check it. The endpoint was renamed six weeks ago. You fix the note. The next time anyone asks, they get the right answer.

**The student.** You're revising three weeks before exams. You ask your AI what's on the syllabus for Module 4. It searches your notes — and stale detection tells you two of the topics were in last year's module structure, which you replaced when the course was restructured. You know what to revise. You don't waste time on dropped content.

**The data scientist.** You ask about the hyperparameters from your best experiment. NeuroStack returns the results from the rerun, not the original — because you updated that note, and the update is reflected in the index.

---

## What makes it different

NeuroStack is not a replacement for Obsidian, Notion, or any note-taking app. It sits on top of what you already use and adds what they don't have.

| Capability | Note apps | Basic RAG | NeuroStack |
|-----------|-----------|-----------|------------|
| Stores your notes | Yes | No | No (read-only layer) |
| AI can search your notes | Some | Yes | Yes |
| Detects stale/outdated notes | No | No | Yes |
| AI memories persist across sessions | No | No | Yes |
| Works with any MCP-compatible AI | No | Varies | Yes |
| Tiered retrieval (saves 80-95% tokens) | No | No | Yes |
| Profession-specific workflows | No | No | Yes |
| Open source, self-hostable | Varies | Varies | Yes (Apache 2.0) |

Stale detection is the feature no other tool offers. When a note keeps appearing in contexts where it no longer fits — a deprecated API, a reversed decision, a superseded paper — NeuroStack flags it and demotes it in future results. Without this, your AI confidently cites information that is no longer true.

---

## Profession packs

When you run `neurostack init`, you choose a profession pack. Each one configures NeuroStack with templates, folder structures, and AI guidance suited to how your profession actually uses notes.

| Pack | Built for |
|------|-----------|
| `researcher` | Literature review, citation tracking, evolving arguments, stale paper detection |
| `writer` | Character sheets, world-building, chapter outlines, continuity tracking |
| `student` | Course notes, spaced repetition, exam prep, syllabus change detection |
| `developer` | Code decisions, architecture notes, runbooks, deprecated API detection |
| `devops` | Infrastructure runbooks, incident notes, change logs |
| `data-scientist` | Experiment tracking, model notes, dataset documentation |

Apply a pack to an existing vault without losing any notes:

```bash
neurostack scaffold researcher ~/my-notes    # or: writer, student, developer, devops, data-scientist
```

You can also import an existing Markdown directory:

```bash
neurostack onboard ~/my-notes
```

---

## How retrieval works

Most memory tools give your AI a wall of text and let it figure out what's relevant. NeuroStack is tiered. It starts with the cheapest retrieval that answers the question and escalates only when it needs to.

| Level | Tokens | What your AI gets |
|-------|--------|-------------------|
| Quick facts | ~15 | Structured facts extracted from your notes: `experiment-3 used learning-rate 0.001` |
| Summaries | ~75 | AI-generated overview of a note |
| Full content | ~300 | Actual Markdown content |
| Auto (default) | Varies | Starts at quick facts, escalates only if the answer isn't there |

Simple factual questions resolve at ~15 tokens. Deep dives get full context. Your AI spends its attention budget where it matters.

---

## Your AI remembers decisions

Across sessions, your AI can save and retrieve typed memories: observations, decisions, conventions, learnings, bugs. When you start a new session, those memories are surfaced automatically.

> "We decided to keep authentication stateless."
> "The thesis framing shifted from consolidation to complementary learning systems."
> "Elena's surname changed from Vasquez to Reyes in the chapter 7 revision."

These aren't just notes. They're things your AI remembers you decided together. They survive `/clear`. They survive closing the terminal. They survive switching machines.

```bash
neurostack memories add "revised thesis framing to CLS, not just consolidation" --type decision --tags "thesis,neuroscience"
neurostack memories search "thesis direction"
```

---

## Learns from your AI sessions

NeuroStack can scan your past AI conversations, extract the key decisions, observations, and learnings, and save them as memories — automatically. No manual work.

```bash
neurostack harvest --sessions 5          # extract insights from last 5 sessions
neurostack hooks install                 # set up hourly auto-harvest
```

Supports Claude Code, VS Code, Codex CLI, Aider, and Gemini CLI session formats.

---

## Keeps itself current

Your vault changes. NeuroStack watches it.

```bash
neurostack watch     # auto-index on vault changes
```

Or sync on every git commit:

```bash
neurostack cloud install-hooks
```

The index updates as you write. Stale detection runs continuously. You don't maintain it — it maintains itself.

---

## What changes day-to-day

| Without NeuroStack | With NeuroStack |
|-------------------|-----------------|
| AI answers from training data | AI answers from your actual notes |
| Cites the runbook you deprecated | Flags it as stale, demotes it automatically |
| No memory of yesterday's session | `session_brief` reconstructs working context |
| Reading 10 notes to find one fact | Tiered retrieval: ~15 tokens for a structured fact |
| Decisions lost after `/clear` | Typed memories persist indefinitely |
| Cross-machine notes out of sync | Cloud sync: push once, pull anywhere |

---

## How your vault is stored

```
~/your-vault/                           # your Markdown files (never modified)
~/.config/neurostack/config.toml        # configuration
~/.local/share/neurostack/
    neurostack.db                       # SQLite + FTS5 knowledge graph
    sessions.db                         # session transcript index
```

NeuroStack reads your vault. It writes nothing back to it. All index data lives in its own SQLite databases.

---

<details>
<summary><strong>All 20 MCP tools</strong></summary>

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
| `vault_session_start` | Begin a memory session |
| `vault_session_end` | End session with optional summary and auto-harvest |

</details>

<details>
<summary><strong>Full CLI reference</strong></summary>

```
# Setup
neurostack init                          # one-command setup: deps, vault, index
neurostack init --mode full ~/brain      # non-interactive full mode
neurostack init --cloud ~/brain          # non-interactive cloud mode
neurostack onboard ~/my-notes            # import existing Markdown notes
neurostack scaffold researcher           # apply a profession pack
neurostack scaffold --list               # see all packs
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
neurostack backfill [summaries|triples|all]
neurostack communities build             # rebuild topic clusters
neurostack reembed-chunks                # re-embed all chunks

# Memories
neurostack memories add "text" --type observation
neurostack memories search "query"
neurostack memories list
neurostack memories update <id> --content "revised"
neurostack memories merge <target> <source>
neurostack memories forget <id>
neurostack memories prune --expired

# Sessions
neurostack harvest --sessions 5          # extract session insights
neurostack sessions search "query"       # search transcripts
neurostack hooks install                 # hourly harvest timer

# Cloud
neurostack cloud login                   # browser OAuth login
neurostack cloud push                    # upload + index vault
neurostack cloud pull                    # download indexed DB
neurostack cloud sync                    # push changes + fetch memories
neurostack cloud install-hooks           # auto-sync on git commit/merge
neurostack cloud auto-sync enable        # periodic sync via systemd timer
neurostack cloud consent                 # review and grant privacy consent

# Client setup
neurostack setup-client cursor           # or: windsurf, gemini, vscode, claude-code
neurostack setup-client --list
neurostack setup-desktop                 # Claude Desktop

# Diagnostics
neurostack stats                         # index health
neurostack doctor                        # validate all subsystems
neurostack demo                          # interactive demo with sample vault
```

</details>

<details>
<summary><strong>Cloud sync details</strong></summary>

Keep your vault indexed across machines without manual steps.

**Automatic sync triggers:**

- **Git hooks** — sync on every commit or merge: `neurostack cloud install-hooks`
- **systemd timer** — periodic background sync: `neurostack cloud auto-sync enable --interval 15min`
- **Manual** — push changes and fetch memories in one command: `neurostack cloud sync`

**Upload format:** Vault files are packed into a compressed tar.gz archive. Typical compression is 60-80%.

**Concurrent push safety:** A server-side push lock prevents two devices from pushing simultaneously.

**`.neurostackignore`:** Place in your vault root to exclude sensitive paths (gitignore syntax):

```
private/
journal/*.md
*-draft.md
```

**Upgrading from v0.10.x:** Cloud mode now requires explicit consent before uploading. Run `neurostack cloud consent` on first push after upgrading.

</details>

<details>
<summary><strong>Neuroscience basis</strong></summary>

Each feature models a specific mechanism from memory neuroscience:

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

---

## FAQ

**Does it modify my vault files?** No. All data lives in NeuroStack's own SQLite databases. Your Markdown files are strictly read-only.

**Do I need a GPU?** No. Cloud mode requires only Node.js. Local Lite mode has zero ML dependencies. Local Full mode runs on CPU but summarization is slow without a GPU.

**Do I need to know Python?** No. The npm package handles everything. You never touch a virtualenv.

**What's the catch with the free tier?** 500 queries/month, 200 notes. No credit card required. Pro plans at [neurostack.sh](https://neurostack.sh) remove those limits.

**How large a vault can it handle?** Tested with ~5,000 notes. FTS5 search stays fast at any size. Cloud indexing handles 500+ notes in minutes.

**Can I use it without an AI client?** Yes. The CLI works standalone and pipes into any LLM.

**Is my vault private in local mode?** Yes. Nothing leaves your machine.

**What if I want to exclude sensitive notes from cloud?** Add a `.neurostackignore` file to your vault root (gitignore syntax). Those files are never uploaded.

**What AI clients does it work with?** Claude Code, Claude Desktop, Cursor, Windsurf, Gemini CLI, VS Code, and Codex — anything that supports MCP.

---

## Requirements

- Linux or macOS
- **Cloud mode:** Node.js only. No GPU, no Ollama, no Python setup.
- **Local Lite mode:** Node.js + Python 3.11+. No GPU or Ollama required.
- **Local Full mode:** [Ollama](https://ollama.ai) with `nomic-embed-text` and a summary model. GPU or 6+ core CPU recommended.

---

## Get started

```bash
npm install -g neurostack
neurostack init
```

Two minutes. One wizard. Your AI stops forgetting.

- **Website:** [neurostack.sh](https://neurostack.sh)
- **Dashboard:** [app.neurostack.sh](https://app.neurostack.sh)
- **Contributing:** [CONTRIBUTING.md](CONTRIBUTING.md)
- **Contact:** [hello@neurostack.sh](mailto:hello@neurostack.sh)
- **Sponsor:** [GitHub Sponsors](https://github.com/sponsors/raphasouthall) | [Buy me a coffee](https://buymeacoffee.com/raphasouthall)

---

Apache-2.0 — see [LICENSE](LICENSE). No GPL dependencies. Built by [SolidPlus LTD](https://neurostack.sh).
