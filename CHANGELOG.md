# Changelog

## v0.15.0 — Remove NeuroStack Cloud (2026-06-03)

### Breaking changes

- **Removed NeuroStack Cloud.** The hosted service has been discontinued. All cloud client commands (`neurostack cloud *`), the `--cloud` flag, cloud sync, and the `neurostack.cloud` package have been removed. NeuroStack is now a purely local tool: it indexes a local Markdown vault into local SQLite, uses local Ollama for embeddings and summaries, and runs the MCP server and OpenAI-compatible API on your own machine. No data leaves your machine unless you configure a third-party LLM provider.

  **Migration**: run `neurostack init` (or `--mode lite|full`) for local indexing. Connect AI clients to the local MCP server with `neurostack serve`. There is no hosted endpoint to connect to.

### Added

- **Folder-path signal in community detection.** Embeddings treat "infrastructure" as one topic whether a note lives under `work/` or `home/`, so distinct organisational areas bled into one cluster. `_build_similarity_matrix` now blends a fourth channel — notes sharing a top-level folder prefix get a uniform similarity bump (`PATH_SIGNAL_WEIGHT`, default 0.3; `PATH_PREFIX_DEPTH`, default 1). Measured on a ~490-note vault: folder purity rose 0.68 → 0.85 (coarse) / 0.76 → 0.93 (fine) with modularity held or slightly improved. Degrades gracefully — root-level files form no path edges and a flat single-folder vault yields an all-zero signal; set the weight to 0 to disable.
- `reconcile_deletions(conn, vault_root, exclude_dirs)` in `watcher.py` — prune orphaned notes; returns the count pruned.
- Startup reconcile in `neurostack watch`: the watcher sweeps offline deletions on boot, so it self-heals without a manual re-index.
- `neurostack index --no-prune` to keep orphaned rows (opt out of the new default).

### Fixed

- **Community hierarchy check no longer false-alarms on every healthy build.** The build asserted `Q(fine) > Q(coarse)` and logged "sanity check failed" whenever it didn't. But Newman modularity is resolution-dependent and maximised at a single scale, so a finer partition scores *lower* at the implicit γ=1 by construction — the assertion could never hold for a healthy hierarchy. Verified empirically: the fine partition only overtakes coarse at γ≈`BETA_FINE` (≈2.0). Replaced with `_hierarchy_health_warning()`, which checks what issue #33 is actually about — the fine level collapsing into *fewer* communities than coarse — plus a `MIN_HEALTHY_Q` floor for near-random partitions.

- **Community modularity no longer collapses toward random.** In a single-domain vault most note pairs share a moderate baseline embedding cosine (off-diagonal mean ≈0.36 on a ~490-note vault), so the semantic signal was a dense floor connecting nearly everything — Newman modularity sat at Q≈0.06, barely better than a random partition. `_build_similarity_matrix` now prunes that floor with an adaptive threshold (`SEMANTIC_THRESHOLD_K`, default mean + 0.5·std of the off-diagonal distribution), zeroing weak semantic edges before community detection. Measured: Q 0.06 → ~0.30 (coarse) / ~0.28 (fine) with stable community counts. The threshold is adaptive, not a fixed cosine, so it self-tunes per vault; set `SEMANTIC_THRESHOLD_K = None` to disable. Diagnosis showed the co-occurrence graph was *not* the cause (entity document-frequency is healthy — 90% of entities appear in a single note), so co-occurrence pruning was a dead end.

- **`neurostack index` now prunes notes deleted from disk.** A full index was upsert-only: it added and updated notes but never removed DB rows for files that no longer existed. The only deletion path was the live watcher's per-event handler, so any file removed while the watcher was down orphaned its rows forever — inflating note counts, polluting co-occurrence and community detection with ghost nodes, and dragging modularity down. A full scan sees the whole vault, so it can now reconcile: anything in the DB but not on disk is pruned (FK cascades drop chunks/summaries/triples; sqlite-vec rows are cleared explicitly). An empty scan is treated as a misconfigured/unmounted vault and skips pruning rather than wiping the index.

### Removed

- `neurostack cloud login/push/pull/sync/consent/install-hooks/auto-sync` CLI commands and the `--cloud` init flag
- `cloud` mode from `manifest.json` and the hosted remote endpoint from `server.json`
- `DPA.md` (Data Processing Agreement) and `docs/api-contract-v2.md` (hosted sync API contract)

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
