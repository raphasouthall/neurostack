# NeuroStack Hyperterse MCP

A [Hyperterse](https://docs.hyperterse.com) MCP server that exposes all 21 NeuroStack vault tools. This is a drop-in replacement for the Python FastMCP server — same tools, same behavior, powered by the Hyperterse framework.

## Architecture

```
Claude / Cursor  ──►  Hyperterse MCP Server (port 8080)
                        │
                        │  fetch() from TypeScript handlers
                        ▼
                      Python Bridge API (port 8100)
                        │
                        │  direct imports
                        ▼
                      neurostack internals
```

- **Hyperterse** is the MCP server that clients connect to. It provides tool discovery, input validation, auth, and the MCP protocol surface.
- **The bridge** is an internal HTTP API (not an MCP server) that Hyperterse handlers call via `fetch()`. It imports NeuroStack's Python modules directly, so there is zero logic duplication.
- **One start command** launches both processes together.

## Prerequisites

- [Hyperterse CLI](https://docs.hyperterse.com/installation) installed
- NeuroStack installed and indexed (`neurostack doctor` passes)
- Python 3.10+ with `fastapi` and `uvicorn` (or `pip install neurostack[api]`)
- Ollama running (for search, ask, and community tools)

## Quick Start

```bash
cd mcp-hyperterse

# Copy and edit environment variables (optional — defaults work if neurostack is configured)
cp .env.example .env

# Start everything
./start.sh
```

The start script launches the Python bridge on port 8100, waits for it to be healthy, then starts Hyperterse on port 8080.

## Connecting to Claude Desktop / Cursor

### Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "neurostack": {
      "url": "http://localhost:8080/mcp"
    }
  }
}
```

### Cursor

Add to your MCP settings:

```json
{
  "mcpServers": {
    "neurostack": {
      "url": "http://localhost:8080/mcp"
    }
  }
}
```

## Tools (21)

### Search & Retrieval
| Tool | Description |
|------|-------------|
| `vault-search` | Hybrid search with tiered depth (triples/summaries/full/auto) |
| `vault-ask` | RAG Q&A with inline `[[citations]]` |
| `vault-summary` | Pre-computed note summary by path or search query |
| `vault-graph` | Wiki-link neighborhood with PageRank |
| `vault-related` | Semantically similar notes by embedding distance |
| `vault-triples` | Search knowledge graph triples (SPO facts) |
| `vault-communities` | GraphRAG global queries across topic clusters |
| `vault-context` | Task-scoped context assembly for session recovery |

### Context & Insights
| Tool | Description |
|------|-------------|
| `session-brief` | Compact session briefing (~500 tokens) |
| `vault-stats` | Index health (notes, embeddings, graph, triples, memories) |
| `vault-record-usage` | Record note usage for hotness scoring |
| `vault-prediction-errors` | Notes flagged as stale or miscategorised |

### Memories
| Tool | Description |
|------|-------------|
| `vault-remember` | Save a memory (observation, decision, convention, etc.) |
| `vault-forget` | Delete a memory by ID |
| `vault-update-memory` | Update an existing memory |
| `vault-merge` | Merge two memories (dedup) |
| `vault-memories` | Search or list memories |

### Sessions
| Tool | Description |
|------|-------------|
| `vault-session-start` | Begin a memory session |
| `vault-session-end` | End session with optional summary and harvest |
| `vault-capture` | Quick-capture a thought to the vault inbox |
| `vault-harvest` | Extract insights from AI session transcripts |

## Environment Variables

Set in `.env` or export before running:

| Variable | Default | Description |
|----------|---------|-------------|
| `BRIDGE_PORT` | `8100` | Port for the internal Python bridge API |

Standard NeuroStack variables (`NEUROSTACK_VAULT_ROOT`, `NEUROSTACK_EMBED_URL`, etc.) are read by the bridge through NeuroStack's own config system.

## Development

Use `--watch` for automatic restarts on file changes:

```bash
# Start bridge manually
BRIDGE_PORT=8100 python3 bridge/api.py &

# Start Hyperterse with hot reload
hyperterse start --watch
```

Validate the project without starting:

```bash
hyperterse validate
```

## Project Structure

```
mcp-hyperterse/
├── .hyperterse              Root config (service name, port, log level)
├── .env.example             Environment variable template
├── start.sh                 Launches bridge + Hyperterse together
├── bridge/
│   ├── api.py               FastAPI bridge — all 21 tool endpoints
│   └── requirements.txt     Python deps (fastapi, uvicorn)
├── app/
│   └── tools/
│       ├── vault-search/    config.terse + handler.ts
│       ├── vault-ask/       ...
│       └── ...              (21 tool directories)
└── README.md
```

Each tool directory contains:
- `config.terse` — Hyperterse tool definition (name, description, inputs, auth)
- `handler.ts` — TypeScript handler that calls the bridge via `fetch()`
