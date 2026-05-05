# Changelog

## v0.13.0 — Remove vault_capture (2026-05-05)

### Breaking changes

- **Removed `vault_capture` MCP tool and `neurostack capture` CLI command.** The tool wrote directly to `{vault_root}/inbox/` without git tracking, indexing, or any path back to origin. In runtimes where the vault is a read-replica (e.g. an indexer container pulling from git), captured files were stranded on the replica's filesystem and invisible to every other tool — including NeuroStack's own search and ask. The architectural promise that "your Markdown files are never modified" had a single, surprising exception; this release restores it.

  **Migration**: drop captured thoughts into your vault using your editor, your shell, or any tool that produces Markdown. The `inbox/` folder convention is unchanged — only the built-in writer is removed.

### Removed

- `vault_capture(content, tags)` MCP tool (`src/neurostack/tools/memory_tools.py`)
- `neurostack capture <thought>` CLI subcommand (`src/neurostack/cli/`)
- `capture_thought()` and `_make_slug()` library functions (`src/neurostack/capture.py` deleted)
- `CloudClient.vault_capture()` (`src/neurostack/cloud/client.py`)
- `vault_capture` entry in `cloud/dispatch.py` tool dispatch table
- `vault_capture` tool entry in `manifest.json`
- `tests/test_capture.py`

### Tool count

NeuroStack now exposes **20 MCP tools** (was 21).

## v0.12.0 — Non-blocking MCP tools + DevOps/SRE focus (2026-03-27)

### Breaking changes

None. All MCP tools, CLI commands, and config remain compatible.

### Non-blocking MCP tools

MCP and REST adapter tool calls now run in `asyncio.to_thread()` instead of blocking the event loop. Under concurrent load (multiple MCP clients, parallel tool calls), this prevents request timeouts caused by synchronous SQLite and LLM operations.

### Structural cleanup

- **Split `cli.py` into `cli/` subpackage** — the 4,841-line monolith is now 8 focused modules: `search`, `index`, `cloud`, `setup`, `memories`, `sessions`, `api`, and `utils`. Contributor onboarding and maintenance are significantly easier.
- **Fixed cloud config circular dependency** — `cloud/config.py` no longer imports `CONFIG_PATH` at module level from the parent package. Uses lazy resolution to avoid import ordering issues.
- **Extracted shared JSON Schema utility** — `_param_to_json_schema` moved from `openai_adapter.py` to `tools/schema_utils.py`, imported by both the OpenAI and REST adapters.

### DevOps/SRE positioning

- README rewritten with "Your notes are lying to you" emotional hook and neuroscience footnote.
- Examples updated to use infrastructure-relevant queries (k8s, Terraform, incident response).
- New FAQ entry explaining why operational knowledge benefits most from stale detection.
