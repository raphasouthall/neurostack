# Changelog

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
