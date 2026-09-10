# Changelog

## Unreleased

### Removed

- **#142 — request-time answering.** NeuroStack returns evidence; the caller reasons over it. Gone: the `vault_ask` MCP tool and `ask.py`, the `neurostack-ask` API model, the `neurostack ask` CLI command (it now prints the replacement and exits 2), the LLM session summary behind `vault_session_end(summarize=True)`, and the model-written eval label tier in `autolabel.py`. `vault_session_end(session_id, summary="…")` stores a summary the caller writes; `neurostack sessions end ID --summary "…"` is the CLI form. `neurostack eval --autolabel` uses stored summaries and titles, so it needs no model — its `--autolabel-mode`, `--autolabel-k`, `--autolabel-cache`, `--llm-url` and `--llm-model` flags are gone. No LLM call now happens while a caller waits on a retrieval tool. Index-time work is untouched: summaries, triples, community labels, harvest classification, synthesize and consolidate all still call a model.

- **#174 — no more automatic transcript posting.** Checkpoints (`neurostack hook checkpoint --run`, wired to the Stop hook by `neurostack hooks install --harness claude|omp`) are now the only automatic learning path. `neurostack init` no longer installs `neurostack-harvest.timer` or a Claude Code `SessionEnd` hook, and reinstalling a harness adapter strips any leftover `SessionEnd` harvest entry from older installs. `neurostack hooks install`/`remove --type` drops the `harvest-timer` choice — `decay-timer` is the only one left. Gone from `src/neurostack/setup.py`: `_session_hook_command`, `claude_session_hook_installed`, `install_claude_session_hook`, `remove_claude_session_hook`. Manual paths are untouched: `neurostack hook session-end` still posts a named transcript on request, `neurostack harvest` and `vault_harvest_transcript` still work when called directly, and `neurostack init`'s `--no-hooks` flag is gone since there is no longer an automatic hook for it to skip.

### Changed
- **#176 — checkpoints become manual.** No harness fires a checkpoint on its own any more: Claude Code's `Stop` hook entry is gone, and the omp adapter dropped its 40-message/30-minute-quiet trigger along with the shutdown flush — `neurostack hooks install --harness claude|omp` and `remove` strip the retired `Stop` entry from older installs. `/save` is the only trigger left, and it no longer runs a checkpoint itself: it hands the request to a server-side queue. New client hook event `enqueue` (`neurostack hook enqueue --harness <claude|omp>`) POSTs `{session, harness, workspace, host, requested_at}` to `client.toml`'s new `queue_url` and prints one line back — `queued (position N)`, already queued (a duplicate), the daily cap reached, or `queue unreachable` — exiting 0 on a landed request, 1 on anything else, all within 2 s. Claude's `/save` slash command and the omp `/save` command both run `hook enqueue` and show that line as-is. `neurostack status` prints a `queue: <url>` line under LEARN when `queue_url` is set. `neurostack hook checkpoint --run` gained `--format {omp,claude-code}`, so a caller with nothing on stdin (a queue worker running it over SSH) can still say which transcript root to search — `harness` alone only labels who ran it.

- **#159 — a re-issued call is no longer counted as an ignore.** The client hook used to report `followed=false` the moment the blocked call came back byte-identical, which is what a model does when it has read the warning and judged that it does not apply, so ignores were over-counted. Nothing about the next call settles a `when-calling` or `when-editing` trigger now: 5 later tool calls with no outcome reported mark it followed, and a re-issue of the same tool spends one of those 5 whether the input changed or not. The `when-error` rule is untouched, so the same error text coming back still reports an ignore.

- **#155 — the checkpoint runs in the background and puts nothing in the chat.** The omp adapter no longer injects a prompt with `pi.sendUserMessage` or watches for the model's reply: it writes the window to `~/.cache/neurostack/sessions/<session>.window.json` (`{since_index, messages}`) and spawns `neurostack hook checkpoint --run --harness omp --session <id>` detached, so the summarising happens through `checkpoint_command` with nothing in the transcript. `/save` does the same and prints one line — `NeuroStack: checkpoint started in the background`, or `NeuroStack: nothing to save yet (N messages)` under the 5-message floor, which used to be silence. Claude Code's `Stop` entry and `~/.claude/commands/save.md` run `checkpoint --run --harness claude` under `nohup` instead of blocking the turn with exit 2. `checkpoint --run` reads the window file when stdin is empty, deletes it once the memories are saved, and takes the session from the newest state file when no id is passed; every `--run` failure now goes to stderr and `learn-status.json` instead of stdout, where a harness would inject it. `checkpoint --save` is unchanged for herdr and hand use.

- Checkpoint prompts now carry assistant text in full; only tool output is clipped at 500 chars (#149)

- **#142 — config keys `llm_url` / `llm_model` / `llm_api_key` are now `index_llm_url` / `index_llm_model` / `index_llm_api_key`** (env `NEUROSTACK_INDEX_LLM_URL` / `_MODEL` / `_API_KEY`), naming what the endpoint is for now that nothing calls it on a query. The old TOML keys and `NEUROSTACK_LLM_*` env vars still load into the new fields and log one deprecation line per config load naming every old name seen; setting the new name wins when both appear. `neurostack init` / `install`'s `--llm-model` and `consolidate` / `synthesize`'s `--llm-model` are now `--index-llm-model`; `--summarize-url` keeps its name and feeds `index_llm_url`.

### Added
- **#165 — event webhook.** `client.toml` gained `event_url`: when set, `neurostack hook session-start` and every checkpoint outcome (`saved`, `busy`, `failed`) POST one JSON body — `event`, `result`, `session`, `harness`, `saved`, `error`, `workspace`, `host`, `at` — to that URL, so a workflow board (n8n or otherwise) can show agent activity next to server-side jobs. A webhook that is down, slow, or misconfigured never affects the hook's own verdict: the POST runs best-effort with a 2-second cap and every failure is swallowed. `neurostack status` prints an `events: <url>` line under LEARN when configured.

- **#159 — the WARN obey count.** `trigger_log` gained `followed` and `outcome_at`, so `vault_trigger_outcome` marks the firing it belongs to instead of writing nothing when the agent obeyed — NULL is pending, 1 is followed, 0 is ignored. The tool takes a `session_hint` and puts the outcome on that session's newest pending firing, falling back to the newest pending firing of any session for a client that sends no hint. New `trigger_stats(conn, days=30)` returns fired, followed, ignored and pending counts plus the followed share of the settled firings, per memory and in total. `neurostack triggers stats [--days N]` prints it, `vault_stats` carries the totals under `triggers.last_30d`, and the `neurostack status` LEARN block gained one line: `WARN: N fired, M followed, K ignored (30d)`.
- **#151 — LEARN visibility.** Every checkpoint attempt now writes `~/.cache/neurostack/learn-status.json` (`last_ok_at`, `last_error_at`, `last_error`, `saved_today`, `session`, `harness`), and `neurostack hook session-start` prints one line from it before the brief: `LEARN: ok, N memories today, last HH:MM`, `LEARN: FAILING since <when>: <error>`, `LEARN: stale, no checkpoint since <when>` past 48 hours, or `LEARN: never ran`. The line comes first so it survives a truncated brief, and it prints on its own when the server is unreachable. `neurostack status` shows the same line, a 7-day table of memories by `source_agent`, and how many live sessions have a transcript longer than the window the model was last offered. `vault_stats` gained `memories.by_source_7d` for that table — `vault_memories` takes no date filter, so the count is grouped in SQL on the server instead of shipping a week of memories to the client.

- `neurostack hook checkpoint --run` pipes the checkpoint prompt through `checkpoint_command` from `client.toml` (for example `claude -p --model sonnet`) and saves the reply, for timers and herdr where no harness model is at hand. Runs from `$HOME` so a project's agent instructions cannot shape the extraction (#147)

- **#143 — idle checkpoint.** New hook event `checkpoint`: it prints a prompt for the harness's own model and calls no LLM from Python. The model replies with a JSON array of `{content, entity_type, tags[], trigger?}` and `neurostack hook checkpoint --save` reads that on stdin, redacts each item through `redact.py`, and writes one `vault_remember` per item with `source_agent="checkpoint/<harness>"`. Skip rules: fewer than 5 new messages, or no tool call and no user message over 200 characters. Dedup is by index in the session state file — `since_index` is what has been saved, `offered_index` what the model has already been asked about — so nothing is summarised twice and a Stop hook cannot re-prompt the same window every turn. The prompt carries every user message whole and clips assistant text and tool output to 500 characters. `--session <id>` lets a caller outside the session (herdr marking a session idle, a slash command) name it; without it, `--save` uses the session whose state was written last. The omp adapter counts messages from `context` events and checkpoints at 40 new messages or 30 quiet minutes with at least 5, and registers `/save` for on demand; the Claude Code adapter adds a `Stop` entry and writes `~/.claude/commands/save.md`. `neurostack-harvest-sync.timer` and `vault_harvest_transcript` are untouched — disable the timer once checkpoints have run for a week.

- **#141 — `neurostack hook`, the harness-neutral client.** One JSON event on stdin, context on stdout, exit 2 to block: `session-start`, `prompt`, `tool-call`, `tool-result`, `session-end`. Trigger lookups, once-per-session suppression, outcome reporting (#136) and transcript posting now live in the package instead of once per harness. Client config `~/.config/neurostack/client.toml` (`url`, `fallback_url`, `token`, `timeout_s`, `harvest_timeout_s`, `workspace_map`; `NEUROSTACK_URL` overrides), per-session state in `~/.cache/neurostack/sessions/`. Every server problem fails open: one stderr line, exit 0, inside `timeout_s` across both URLs. `neurostack hooks install --harness claude|omp` generates the adapter — Claude Code settings entries, or a small omp extension — and replaces the hand-written hook scripts it supersedes. `hooks install --type claude-hook` is gone; use `--harness claude`.

- **#136 — fired-but-ignored triggers.** `vault_triggers` logs every hit to a new `trigger_log` table; new tool `vault_trigger_outcome(memory_id, followed, note)` records whether the agent followed it. An ignored trigger becomes a `prediction_errors` row of type `trigger_ignored`; the promotion queue's `drift` bucket lists the memory once with `ignored_trigger` and `ignored_count`, and adds `suggest: retire` at three. Nothing is deleted or decayed automatically.

- **#135 — harvest emits trigger tags.** Providers stamp each transcript message with the tool call, path and failed result that preceded it; the classifier sees that context and may return a `trigger` field, which harvest normalises and saves as a `when-*` tag. A malformed value is dropped with one log line and the memory still saves. Regex fallback emits none.

- **#131 — trigger tags.** A memory tagged `when-editing:<glob>`, `when-calling:<tool>` or `when-error:<substring>` surfaces at the moment it applies. New `triggers.py` and MCP `vault_triggers(event, value)`; no schema change, per-session fire-once lives in the client hook.

- **#92 — promotion queue.** `neurostack promote` + MCP `vault_promotion_queue`: a deterministic worklist of memories whose knowledge should move into vault notes, in four buckets — `debt` (tagged `promotion-debt`), `drift` (unresolved memory-drift rows), `dead_handoffs` (stale context memories that read as handoffs; `open-thread` tag exempts), `uncovered` (durable memories whose nearest note chunk is below a similarity floor). Pure local compute, no LLM, no writes. `vault_session_end` now returns a soft `promotion_debt_warning` when a session wrote durable memories but no note changed while it ran.

- **#90 — archive-on-forget.** Every memory delete path (`vault_forget`/`memories forget`, merge source, TTL expiry, prune) now moves the row to a `memories_archive` table instead of destroying it. Archived rows are outside search/FTS/drift by construction but stay greppable and restorable. New CLI: `neurostack memories archived [-w] [--limit N]` and `neurostack memories restore ID` (restored rows re-embed via `backfill memories`). `memories stats` gains `archived`; MCP `vault_forget` result carries `archived: true`.

### Fixed

- **#163 — checkpoint overlap and retry races.** A nonblocking OS lock now covers checkpoint state, model execution, and saves per conversation, while other conversations remain independent. omp uses its stable harness session ID across resumes. Checkpoint state merges with interactive hook state, settled cursors stay monotonic, and Python persists each frozen payload before model execution. The runner persists the extracted reply and exact acknowledged-item receipts, so partial retries skip confirmed saves without discarding corrected facts. LEARN count updates use a short file lock. A network failure after a remote commit but before its acknowledgement can still duplicate that item because `vault_remember` has no server idempotency key.

  The generated omp adapter now sends each frozen message window to the locked CLI on stdin; Python persists that payload before invoking the model. Reinstall the adapter and restart omp after upgrading. Legacy `.window.json` handovers remain readable for migration, but NeuroStack leaves them in place because an old publisher cannot coordinate a safe pathname deletion.

- **#153 — a checkpoint save no longer drops the reply the model wrote.** `neurostack hook checkpoint --save` now spends the `harvest_timeout_s` budget (600 s by default) on each `vault_remember` instead of the 5 s interactive `timeout_s`, because the server embeds every memory as it stores it. A non-empty reply that parses to zero items records `reply had no items: <first 120 chars>` in `learn-status.json` and puts the window back on offer, so prose can no longer pass for a clean checkpoint of nothing. A literal `[]` still counts as ok with 0 saved and settles the window, and an empty body keeps the window on offer without recording an error. Every `--save` writes its raw stdin to `~/.cache/neurostack/last-capture.txt`, so a capture bug is inspectable after the fact. The omp adapter waits for a JSON-shaped reply and skips up to 3 prose messages before it gives up with an empty save, which stops a model that thinks out loud first from losing its own summary.

### Schema

- v21 → v22: `memories_archive` table (#90).
- v24 → v25: `trigger_log` table (#136).
- v25 → v26: `trigger_log.followed`, `outcome_at` (#159).

## v0.16.0 — Retrieval & extraction fixes (2026-06-11)

### Added

- **`neurostack search --explain` / `hybrid_search(explain=True)`** — per-result score breakdown (base, link-section penalty, convergence, context, hotness, co-occurrence, excitability, prediction-error, lateral inhibition) for diagnosing ranking. Zero behaviour change when off.
- **`neurostack backfill memories`** (and `backfill all`) — re-embeds memories whose embedding is missing or previously failed; rows that still fail stay flagged for the next run.
- **Triple-extraction retry queue** — notes whose extraction fails to parse are recorded with exponential backoff (1h/6h/24h/72h/weekly) and retried by `neurostack backfill triples`, instead of being dropped silently.
- Config knobs `link_section_penalty` / `link_density_threshold` (`NEUROSTACK_LINK_SECTION_PENALTY`, `NEUROSTACK_LINK_DENSITY_THRESHOLD`), default 0.5 / 0.5.

### Fixed

- **#41 — `vault_search` ranked link-list chunks above on-topic notes.** A `## Related` / index block repeats a note's topic terms through link titles, inflating its score. `hybrid_search` now down-weights matched chunks that are navigational link lists (named-heading or high wiki-link density), applied before the per-note dedup so a note's substantive body chunk wins instead.
- **#40 — `vault_ask` answered "no source" when the answer was in the chunk.** Synthesis only saw the 300-char display snippet of the top chunk per note. It now uses the note summary plus the full matched chunk (cap 2000 chars), returns the excerpt in `sources[]`, and the prompt distinguishes "not in the retrieved notes" from asserting the fact is false.
- **#28 — silent JSON-parse failures dropped triples permanently.** `extract_triples` now requests a JSON object, salvages JSON from noisy output, retries once, and raises `TripleExtractionError` on hard failure instead of returning an empty list indistinguishable from a genuinely empty note.
- **#29 — memory embeddings were silently dropped on failure.** Failures now set an `embed_pending` flag and log at WARNING; `backfill_memory_embeddings` heals them and `full_index` self-heals pending rows when embeddings are reachable.

### Schema

- v15 → v16: `triple_extraction_failed` retry-queue table (#28).
- v16 → v17: `memories.embed_pending` column; existing NULL-embedding rows flagged for backfill (#29).

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
