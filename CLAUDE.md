# NeuroStack - Claude Code Guide

NeuroStack is a neuroscience-grounded knowledge management system. CLI + MCP server + OpenAI-compatible API. Everything runs locally against a Markdown vault indexed in SQLite + FTS5.

## Quick Reference

### Installation

```bash
npm install -g neurostack    # bootstraps CLI, Python, uv, deps
neurostack install            # interactive mode/model wizard
neurostack init               # vault setup + profession packs
```

### MCP Server (recommended for Claude Code)

Add to `~/.claude/.mcp.json`:
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

### OpenAI-compatible API

```bash
pip install neurostack[api]
neurostack api                          # localhost:8000
neurostack api --host 0.0.0.0 --port 9000
NEUROSTACK_API_KEY=secret neurostack api  # with auth
```

Endpoints: `POST /v1/chat/completions`, `POST /v1/embeddings`, `GET /v1/models`, `GET /health`
Models: `neurostack-ask` (RAG), `neurostack-search` (hybrid), `neurostack-tiered` (auto-depth), `neurostack-triples` (facts)

## CLI Commands

### Search & Retrieval
| Command | Description |
|---------|-------------|
| `neurostack search "query"` | Hybrid FTS5 + semantic search. Flags: `--mode hybrid\|semantic\|keyword`, `--top-k N`, `--rerank`, `--context "domain"`, `--workspace "path/"` |
| `neurostack ask "question"` | RAG Q&A with inline `[[citations]]`. Uses Ollama LLM. Flags: `--top-k N`, `--workspace` |
| `neurostack tiered "query"` | Token-efficient tiered retrieval. `--depth triples\|summaries\|full\|auto` |
| `neurostack triples "query"` | Search knowledge graph triples (subject-predicate-object facts) |
| `neurostack summary "note.md"` | Get pre-computed AI summary of a note |
| `neurostack graph "note.md"` | Wiki-link neighborhood with PageRank scores. `--depth N` |
| `neurostack related "note.md"` | Find semantically similar notes by embedding distance |
| `neurostack communities query "question"` | GraphRAG global queries across topic clusters |
| `neurostack context "task description"` | Assemble task-scoped context for session recovery |
| `neurostack brief` | Compact session briefing (recent activity, hot notes, alerts) |

### Memory Management
| Command | Description |
|---------|-------------|
| `neurostack memories add "content"` | Save a memory. `--tags "a,b"`, `--type observation\|decision\|convention\|learning\|context\|bug`, `--workspace`, `--ttl N` (hours) |
| `neurostack memories search "query"` | Search memories. `--type`, `--workspace`, `--limit N` |
| `neurostack memories list` | List recent memories |
| `neurostack memories update ID` | Update memory. `--content`, `--tags`, `--add-tags`, `--remove-tags`, `--type` |
| `neurostack memories forget ID` | Delete a memory |
| `neurostack memories merge TARGET SOURCE` | Merge two memories (unions tags, audit trail) |
| `neurostack memories prune` | Clean up. `--expired` or `--older-than N` (days) |
| `neurostack memories stats` | Memory statistics |
| `neurostack capture "thought"` | Quick-capture to vault inbox. `--tags "a,b"` |

### Sessions
| Command | Description |
|---------|-------------|
| `neurostack sessions start` | Begin a memory session. `--source "agent-name"`, `--workspace` |
| `neurostack sessions end ID` | End session. `--summarize` for LLM summary |
| `neurostack sessions list` | List recent sessions. `--workspace`, `--limit N` |
| `neurostack sessions show ID` | Session details and memories |
| `neurostack sessions search "query"` | Search session transcripts (delegates to session-index) |

### Indexing & Maintenance
| Command | Description |
|---------|-------------|
| `neurostack index` | Full re-index. `--skip-summary`, `--skip-triples` |
| `neurostack watch` | File watcher - auto-indexes on vault changes |
| `neurostack reembed-chunks` | Re-embed all chunks with contextual text |
| `neurostack backfill` | Backfill missing summaries and/or triples |
| `neurostack folder-summaries` | Build folder-level summaries for context boosting |
| `neurostack communities build` | Run Leiden community detection |
| `neurostack harvest` | Extract insights from recent Claude Code sessions |
| `neurostack record-usage "path1" "path2"` | Record note usage for hotness scoring |
| `neurostack decay` | Report note excitability and dormancy |
| `neurostack prediction-errors` | Show notes flagged as poor retrieval fit |

### Setup & Diagnostics
| Command | Description |
|---------|-------------|
| `neurostack init [path]` | Initialize vault and config. `--profession developer\|writer\|devops\|...` |
| `neurostack scaffold [profession]` | Apply profession pack to existing vault. `--list` to see options |
| `neurostack onboard /path/to/notes` | Onboard existing Markdown notes. `--dry-run`, `--no-index` |
| `neurostack install` | Install/upgrade deps and models. `--mode lite\|full\|community`, `--pull-models` |
| `neurostack update` | Pull latest source and re-sync deps |
| `neurostack doctor` | Validate all subsystems. `--strict` exits 1 on missing vault/db |
| `neurostack status` | Show current status |
| `neurostack stats` | Index health (note count, embedding coverage, excitability breakdown) |
| `neurostack demo` | Run interactive demo with sample vault |

### Client Setup
| Command | Description |
|---------|-------------|
| `neurostack setup-desktop` | Auto-configure Claude Desktop MCP config. `--dry-run` |
| `neurostack setup-client <name>` | Auto-configure AI client: cursor, windsurf, gemini, vscode, claude-code. `--list`, `--dry-run` |

### Servers
| Command | Description |
|---------|-------------|
| `neurostack serve` | Start MCP server. `--transport stdio\|sse\|http`, `--host`, `--port` |
| `neurostack api` | Start OpenAI-compatible HTTP API. `--host`, `--port` |

## MCP Tools (21 tools)

### Search & Retrieval
- `vault_search(query, top_k, mode, depth, context, workspace)` - Hybrid search with tiered depth
- `vault_ask(question, top_k, workspace)` - RAG Q&A with citations
- `vault_summary(path_or_query)` - Pre-computed note summaries
- `vault_graph(note, depth, workspace)` - Wiki-link neighborhood with PageRank
- `vault_related(note, top_k, workspace)` - Semantically similar notes
- `vault_triples(query, top_k, mode, workspace)` - Knowledge graph triples
- `vault_communities(query, top_k, level, map_reduce, workspace)` - GraphRAG global queries

### Context & Insights
- `vault_context(task, token_budget, workspace, include_memories, include_triples)` - Task-scoped context recovery
- `session_brief(workspace)` - Compact session briefing
- `vault_stats()` - Index health
- `vault_record_usage(note_paths)` - Track note hotness
- `vault_prediction_errors(error_type, limit, resolve, workspace)` - Stale note detection

### Memories
- `vault_remember(content, tags, entity_type, source_agent, workspace, ttl_hours, session_id)` - Save memory
- `vault_update_memory(memory_id, content, tags, add_tags, remove_tags, entity_type, workspace, ttl_hours)` - Update memory
- `vault_merge(target_id, source_id)` - Merge two memories
- `vault_forget(memory_id)` - Delete memory
- `vault_memories(query, entity_type, workspace, limit)` - List/search memories
- `vault_harvest(sessions, dry_run)` - Extract session insights
- `vault_capture(content, tags)` - Quick-capture to inbox

### Sessions
- `vault_session_start(source_agent, workspace)` - Begin memory session
- `vault_session_end(session_id, summarize, auto_harvest)` - End session

## Global Flags

All query commands support `--json` for machine-readable output:
```bash
neurostack --json search "query" | jq '.[] | .title'
```

Workspace scoping (filter to vault subdirectory):
```bash
neurostack search -w "work/my-project" "query"
# or
export NEUROSTACK_WORKSPACE=work/my-project
```

## Configuration

File: `~/.config/neurostack/config.toml`

| Key | Default | Env Override |
|-----|---------|-------------|
| `vault_root` | `~/brain` | `NEUROSTACK_VAULT_ROOT` |
| `embed_url` | `http://localhost:11435` | `NEUROSTACK_EMBED_URL` |
| `embed_model` | `nomic-embed-text` | `NEUROSTACK_EMBED_MODEL` |
| `llm_url` | `http://localhost:11434` | `NEUROSTACK_LLM_URL` |
| `llm_model` | `phi3.5` | `NEUROSTACK_LLM_MODEL` |
| `api_host` | `127.0.0.1` | `NEUROSTACK_API_HOST` |
| `api_port` | `8000` | `NEUROSTACK_API_PORT` |
| `api_key` | (none) | `NEUROSTACK_API_KEY` |

## Architecture

```
~/brain/                                 # Markdown vault (never modified)
~/.config/neurostack/config.toml         # Configuration
~/.local/share/neurostack/
    neurostack.db                        # SQLite + FTS5 knowledge graph
    sessions.db                          # Session transcript index
```

## Development

```bash
cd ~/tools/neurostack
uv sync --extra dev --extra full --extra api
uv run pytest                            # run tests
uv run ruff check src/ tests/            # lint
uv run neurostack doctor                 # validate subsystems
```
