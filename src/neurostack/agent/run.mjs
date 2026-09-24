// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2024-2026 Raphael Southall
//
// Pi agent runner for NeuroStack jobs that need tools and reasoning (#217).
// `neurostack agent <job>` installs this directory's dependencies once and
// runs it with a job spec in NEUROSTACK_AGENT_JOB. Memory operations are
// custom tools that call the NeuroStack CLI directly, so a run needs neither
// the MCP server nor a harness login. Built-in file tools work in the vault.
import { spawnSync } from "node:child_process";

import { getModel } from "@earendil-works/pi-ai/compat";
import {
	createAgentSession,
	createExtensionRuntime,
	ModelRuntime,
	SessionManager,
	SettingsManager,
} from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

const job = JSON.parse(process.env.NEUROSTACK_AGENT_JOB);
const cli = JSON.parse(process.env.NEUROSTACK_AGENT_CLI);

function neurostack(args) {
	const r = spawnSync(cli[0], [...cli.slice(1), ...args], {
		encoding: "utf8",
		maxBuffer: 64 * 1024 * 1024,
	});
	const text = (r.stdout || "") + (r.status === 0 ? "" : `\n[exit ${r.status}] ${r.stderr || ""}`);
	return { content: [{ type: "text", text: text.trim() || "(no output)" }], details: {} };
}

function tool(name, description, parameters, toArgs) {
	return {
		name,
		label: name,
		description,
		promptSnippet: description,
		parameters,
		executionMode: "sequential",
		execute: async (_id, params) => neurostack(toArgs(params)),
	};
}

const customTools = [
	tool(
		"promotion_queue",
		"The promotion worklist as JSON: debt, drift, dead_handoffs, uncovered buckets.",
		Type.Object({}),
		() => ["--json", "promote"],
	),
	tool(
		"memory_search",
		"Search memories by text. Use it to find newer memories that supersede a handoff.",
		Type.Object({ query: Type.String(), limit: Type.Optional(Type.Integer()) }),
		(p) => ["--json", "memories", "search", p.query, "--limit", String(p.limit ?? 10)],
	),
	tool(
		"vault_search",
		"Hybrid search over the indexed vault notes. Returns ranked note paths and snippets.",
		Type.Object({ query: Type.String(), top_k: Type.Optional(Type.Integer()) }),
		(p) => ["--json", "search", p.query, "--top-k", String(p.top_k ?? 8)],
	),
	tool(
		"memory_update",
		"Rewrite a memory (slim it to identifiers plus a [[wiki-link]]) and add or remove tags.",
		Type.Object({
			memory_id: Type.Integer(),
			content: Type.Optional(Type.String()),
			add_tags: Type.Optional(Type.String({ description: "comma-separated" })),
			remove_tags: Type.Optional(Type.String({ description: "comma-separated" })),
		}),
		(p) => [
			"memories", "update", String(p.memory_id),
			...(p.content ? ["--content", p.content] : []),
			...(p.add_tags ? ["--add-tags", p.add_tags] : []),
			...(p.remove_tags ? ["--remove-tags", p.remove_tags] : []),
		],
	),
	tool(
		"memory_forget",
		"Archive a memory (restorable). Only after the job's rules allow it.",
		Type.Object({ memory_id: Type.Integer() }),
		(p) => ["memories", "forget", String(p.memory_id)],
	),
	tool(
		"memory_add",
		"Save one memory: an identifier or correction a future session will look up.",
		Type.Object({
			content: Type.String(),
			entity_type: Type.Optional(Type.String({ description: "observation, decision, convention, learning, context or bug" })),
			tags: Type.Optional(Type.String({ description: "comma-separated" })),
			workspace: Type.Optional(Type.String()),
		}),
		(p) => [
			"memories", "add", p.content,
			"--type", p.entity_type ?? "observation",
			...(p.tags ? ["--tags", p.tags] : []),
			...(p.workspace ? ["--workspace", p.workspace] : []),
		],
	),
	tool(
		"graph_analysis",
		"Structural gaps (related but unlinked note pairs) and bridge notes in the wiki-link graph, as JSON.",
		Type.Object({ top_k: Type.Optional(Type.Integer()) }),
		(p) => ["--json", "graph-analysis", "--top-k", String(p.top_k ?? 15)],
	),
	tool(
		"note_summary",
		"The stored summary of a note, by vault-relative path.",
		Type.Object({ path: Type.String() }),
		(p) => ["--json", "summary", p.path],
	),
];

const modelRuntime = await ModelRuntime.create({
	authPath: `${job.state_dir}/auth.json`,
	modelsPath: `${job.state_dir}/models.json`,
});
await modelRuntime.setRuntimeApiKey(job.provider, job.api_key);
const known = getModel(job.provider, job.model);
if (!known) throw new Error(`model not found: ${job.provider}/${job.model}`);
// A base URL points the provider's own API at a compatible proxy, for example
// CLIProxyAPI serving the Anthropic Messages API from a subscription login.
const model = job.base_url ? { ...known, baseUrl: job.base_url } : known;

const { session } = await createAgentSession({
	cwd: job.cwd,
	agentDir: job.state_dir,
	model,
	thinkingLevel: job.thinking,
	modelRuntime,
	resourceLoader: {
		getExtensions: () => ({ extensions: [], errors: [], runtime: createExtensionRuntime() }),
		getSkills: () => ({ skills: [], diagnostics: [] }),
		getPrompts: () => ({ prompts: [], diagnostics: [] }),
		getThemes: () => ({ themes: [], diagnostics: [] }),
		getAgentsFiles: () => ({ agentsFiles: [] }),
		getSystemPrompt: () => undefined,
		getSystemPromptSource: () => undefined,
		getAppendSystemPrompt: () => [],
		getAppendSystemPromptSources: () => [],
		extendResources: () => {},
		reload: async () => {},
	},
	tools: ["read", "bash", "edit", "write", "grep", "find", "ls", ...customTools.map((t) => t.name)],
	customTools,
	sessionManager: SessionManager.inMemory(job.cwd),
	settingsManager: SettingsManager.inMemory({
		compaction: { enabled: true },
		retry: { enabled: true, maxRetries: 3 },
	}),
});

// One line per step on stdout: the scheduler captures it as the run log.
const stamp = () => new Date().toISOString().slice(11, 19);
const clip = (s, n) => (s.length > n ? `${s.slice(0, n)}...` : s);
session.subscribe((e) => {
	if (e.type === "tool_execution_start") {
		console.log(`[${stamp()}] tool ${e.toolName} ${clip(JSON.stringify(e.args ?? {}), 200)}`);
	} else if (e.type === "message_end" && e.message?.role === "assistant") {
		const text = (e.message.content || []).filter((c) => c.type === "text").map((c) => c.text).join("").trim();
		if (text) console.log(`[${stamp()}] text ${clip(text.replace(/\s+/g, " "), 400)}`);
	}
});

const timer = setTimeout(() => {
	console.log(`[${stamp()}] timeout after ${job.timeout_s}s, aborting`);
	void session.abort();
}, job.timeout_s * 1000);

let code = 0;
try {
	await session.prompt(job.prompt);
	await session.waitForIdle();
	const last = session.getLastAssistantText() || "";
	console.log(`[${stamp()}] done\n${last}`);
} catch (err) {
	console.error(`agent failed: ${err?.stack || err}`);
	code = 1;
} finally {
	clearTimeout(timer);
	session.dispose();
}
process.exit(code);
