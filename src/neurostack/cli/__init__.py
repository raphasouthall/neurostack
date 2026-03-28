# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""CLI entry point for neurostack."""

import argparse
import sys
from pathlib import Path

from .. import __version__
from ..config import get_config
from .api import cmd_api, cmd_bundle, cmd_serve
from .cloud import cmd_cloud
from .index import cmd_backfill, cmd_index, cmd_reembed_chunks, cmd_watch
from .memories import cmd_memories
from .search import (
    cmd_ask,
    cmd_brief,
    cmd_capture,
    cmd_communities,
    cmd_context,
    cmd_cooccurrence,
    cmd_decay,
    cmd_folder_summaries,
    cmd_graph,
    cmd_prediction_errors,
    cmd_record_usage,
    cmd_related,
    cmd_search,
    cmd_stats,
    cmd_summary,
    cmd_tiered,
    cmd_triples,
)
from .sessions import cmd_harvest, cmd_hooks, cmd_sessions
from .setup import (
    cmd_demo,
    cmd_doctor,
    cmd_init,
    cmd_install,
    cmd_onboard,
    cmd_scaffold,
    cmd_setup_client,
    cmd_setup_desktop,
    cmd_skills,
    cmd_status,
    cmd_uninstall,
    cmd_update,
)
from .utils import _handle_error


def main():
    cfg = get_config()

    parser = argparse.ArgumentParser(description="neurostack: Local AI context engine")
    parser.add_argument("--version", action="version", version=f"neurostack {__version__}")
    parser.add_argument("--vault", default=str(cfg.vault_root), help="Vault root path")
    parser.add_argument("--embed-url", default=cfg.embed_url, help="Ollama embed URL")
    parser.add_argument("--summarize-url", default=cfg.llm_url, help="Ollama summarize URL")
    parser.add_argument("--json", action="store_true", default=False, help="Output results as JSON")

    sub = parser.add_subparsers(dest="command")

    # init
    p = sub.add_parser("init", help="Set up vault, deps, and index (one command)")
    p.add_argument("path", nargs="?", help="Vault path (default: from config)")
    p.add_argument(
        "--profession", "-p",
        help="Apply a profession pack (e.g., developer, writer, "
        "student, devops, data-scientist, researcher). "
        "Use 'scaffold --list' to see all",
    )
    p.add_argument(
        "--mode", "-m", choices=["lite", "full"],
        help="Installation mode (lite=FTS5 only, full=+ML+communities)",
    )
    p.add_argument(
        "--cloud", action="store_true", default=False,
        help="Use cloud mode (Gemini indexing)",
    )
    p.add_argument(
        "--index", action="store_true", default=True,
        help="Index vault after init (default: true)",
    )
    p.add_argument(
        "--no-index", action="store_false", dest="index",
        help="Skip indexing after init",
    )
    p.add_argument("--pull-models", action="store_true", default=False,
                   help="Pull Ollama models (full mode)")
    p.add_argument("--embed-model", help="Embedding model override")
    p.add_argument("--llm-model", help="LLM model override")
    p.add_argument("--embed-url", help="Embedding endpoint override")
    p.add_argument("--summarize-url", help="LLM endpoint override")
    p.set_defaults(func=cmd_init)

    # scaffold
    p = sub.add_parser("scaffold", help="Apply a profession pack to an existing vault")
    p.add_argument(
        "profession", nargs="?",
        help="Profession name (e.g., developer, writer, "
        "student, devops, data-scientist, researcher)",
    )
    p.add_argument("--list", "-l", action="store_true", help="List available profession packs")
    p.set_defaults(func=cmd_scaffold)

    # onboard
    p = sub.add_parser(
        "onboard",
        help="Onboard an existing directory of notes into a NeuroStack vault",
    )
    p.add_argument("path", help="Path to the directory to onboard")
    p.add_argument(
        "--dry-run", "-n", action="store_true",
        help="Show what would be done without making changes",
    )
    p.add_argument(
        "--profession", "-p",
        help="Also apply a profession pack after onboarding",
    )
    p.add_argument(
        "--no-index", action="store_true",
        help="Skip indexing after onboarding",
    )
    p.add_argument(
        "--write-frontmatter", action="store_true",
        help="Write frontmatter into vault files (default: metadata stored in SQLite only)",
    )
    p.set_defaults(func=cmd_onboard)

    # demo
    p = sub.add_parser("demo", help="Run interactive demo with sample vault")
    p.set_defaults(func=cmd_demo)

    # status
    p = sub.add_parser("status", help="Show NeuroStack status")
    p.set_defaults(func=cmd_status)

    # cloud
    p = sub.add_parser("cloud", help="Manage NeuroStack Cloud authentication")
    cloud_sub = p.add_subparsers(dest="cloud_command")

    cp = cloud_sub.add_parser("login", help="Authenticate with an API key")
    cp.add_argument("--key", "-k", help="API key (or prompted interactively)")

    cloud_sub.add_parser("logout", help="Clear stored cloud credentials")

    cp = cloud_sub.add_parser("status", help="Show cloud auth state and usage")
    cp.add_argument("--json", action="store_true", default=False, help="Output as JSON")

    cloud_sub.add_parser("setup", help="Interactive cloud endpoint and key configuration")

    cloud_sub.add_parser("consent", help="Grant privacy consent for cloud features")

    cp = cloud_sub.add_parser("push", help="Upload vault files for cloud indexing")
    cp.add_argument("--json", action="store_true", default=False, help="Output as JSON")

    cp = cloud_sub.add_parser("pull", help="Download indexed database from cloud")
    cp.add_argument("--json", action="store_true", default=False, help="Output as JSON")

    cp = cloud_sub.add_parser("query", help="Search vault via cloud API")
    cp.add_argument("query", help="Search text")
    cp.add_argument("--top-k", type=int, default=10, help="Number of results")
    cp.add_argument(
        "--depth", default="auto",
        choices=["triples", "summaries", "full", "auto"],
        help="Result depth (default: auto)",
    )
    cp.add_argument(
        "--mode", default="hybrid",
        choices=["hybrid", "semantic", "keyword"],
        help="Search mode (default: hybrid)",
    )
    cp.add_argument("--workspace", "-w", help="Scope to vault subdirectory")
    cp.add_argument("--json", action="store_true", default=False, help="Output as JSON")

    cp = cloud_sub.add_parser("triples", help="Search knowledge graph triples via cloud")
    cp.add_argument("query", help="Search text")
    cp.add_argument("--top-k", type=int, default=10, help="Number of results")
    cp.add_argument("--workspace", "-w", help="Scope to vault subdirectory")
    cp.add_argument("--json", action="store_true", default=False, help="Output as JSON")

    cp = cloud_sub.add_parser("summary", help="Get note summary from cloud")
    cp.add_argument("note_path", help="Note path (e.g. research/my-note.md)")
    cp.add_argument("--json", action="store_true", default=False, help="Output as JSON")

    cp = cloud_sub.add_parser("sync", help="Push vault changes and fetch new memories")
    cp.add_argument("--json", action="store_true", default=False, help="Output as JSON")
    cp.add_argument("--quiet", "-q", action="store_true", default=False, help="Suppress output")

    cloud_sub.add_parser("install-hooks", help="Install git hooks for automatic cloud sync")
    cloud_sub.add_parser("uninstall-hooks", help="Remove git hooks for cloud sync")
    cloud_sub.add_parser("hooks-status", help="Check git hook installation status")

    cp = cloud_sub.add_parser("auto-sync", help="Manage automatic periodic sync")
    auto_sub = cp.add_subparsers(dest="auto_sync_command")
    ap = auto_sub.add_parser("enable", help="Enable periodic sync via systemd timer")
    ap.add_argument("--interval", default="15min", help="Sync interval (default: 15min)")
    auto_sub.add_parser("disable", help="Disable periodic sync")
    auto_sub.add_parser("status", help="Show auto-sync status")

    p.set_defaults(func=cmd_cloud)

    # memories
    p = sub.add_parser("memories", help="Manage agent-written memories")
    mem_sub = p.add_subparsers(dest="memories_command")

    mp = mem_sub.add_parser("add", help="Save a new memory")
    mp.add_argument("content", help="Memory content")
    mp.add_argument("--tags", "-t", help="Comma-separated tags")
    mp.add_argument(
        "--type", default="observation",
        choices=["observation", "decision", "convention", "learning", "context", "bug"],
        help="Memory type (default: observation)",
    )
    mp.add_argument("--source", help="Source agent name")
    mp.add_argument("--workspace", "-w", help="Workspace scope")
    mp.add_argument("--ttl", type=float, help="Time-to-live in hours")

    mp = mem_sub.add_parser("search", help="Search memories")
    mp.add_argument("query", help="Search query")
    mp.add_argument("--type", help="Filter by entity type")
    mp.add_argument("--workspace", "-w", help="Workspace scope")
    mp.add_argument("--limit", type=int, default=20)

    mp = mem_sub.add_parser("list", help="List recent memories")
    mp.add_argument("--type", help="Filter by entity type")
    mp.add_argument("--workspace", "-w", help="Workspace scope")
    mp.add_argument("--limit", type=int, default=20)

    mp = mem_sub.add_parser("forget", help="Delete a memory by ID")
    mp.add_argument("id", type=int, help="Memory ID")

    mp = mem_sub.add_parser("prune", help="Delete expired or old memories")
    mp.add_argument("--older-than", type=int, help="Delete memories older than N days")
    mp.add_argument("--expired", action="store_true", help="Delete only expired memories")

    mp = mem_sub.add_parser("stats", help="Show memory statistics")

    mp = mem_sub.add_parser("update", help="Update an existing memory")
    mp.add_argument("id", type=int, help="Memory ID to update")
    mp.add_argument("--content", "-c", help="New content")
    mp.add_argument("--tags", "-t", help="Replace tags (comma-separated)")
    mp.add_argument("--add-tags", help="Add tags (comma-separated)")
    mp.add_argument("--remove-tags", help="Remove tags (comma-separated)")
    mp.add_argument("--type", help="New entity type")
    mp.add_argument("--workspace", "-w", help="New workspace scope")
    mp.add_argument("--ttl", type=float, help="New TTL in hours (0 = permanent)")

    mp = mem_sub.add_parser("merge", help="Merge source memory into target")
    mp.add_argument("target", type=int, help="Target memory ID (kept)")
    mp.add_argument("source", type=int, help="Source memory ID (deleted after merge)")

    p.set_defaults(func=cmd_memories)

    # install
    p = sub.add_parser("install", help="Install or upgrade dependencies and Ollama models")
    p.add_argument(
        "--mode", "-m", choices=["lite", "full"],
        help="Installation mode (lite=FTS5 only, full=+ML+communities)",
    )
    p.add_argument(
        "--pull-models", action="store_true", default=False,
        help="Pull Ollama models after syncing deps",
    )
    p.add_argument("--embed-model", help="Embedding model (default: nomic-embed-text)")
    p.add_argument("--llm-model", help="LLM model (default: phi3.5)")
    p.set_defaults(func=cmd_install)

    # uninstall
    p = sub.add_parser("uninstall", help="Remove NeuroStack data, database, and CLI wrapper")
    p.add_argument(
        "--keep-config", action="store_true", default=False,
        help="Preserve ~/.config/neurostack/ (default: keep config)",
    )
    p.add_argument(
        "--keep-db", action="store_true", default=False,
        help="Preserve database files",
    )
    p.add_argument(
        "-y", "--yes", action="store_true", default=False,
        help="Skip confirmation prompt",
    )
    p.set_defaults(func=cmd_uninstall)

    # skills
    p = sub.add_parser(
        "skills",
        help="Manage agent skill files (.md slash commands)",
    )
    skills_sub = p.add_subparsers(dest="skills_command")
    install_p = skills_sub.add_parser(
        "install", help="Install skills for an AI provider",
    )
    install_p.add_argument(
        "provider", nargs="?", default="claude",
        choices=["claude", "codex", "gemini"],
        help="Target provider (default: claude)",
    )
    skills_sub.add_parser("list", help="List available skills")
    p.set_defaults(func=cmd_skills)

    # update
    p = sub.add_parser(
        "update",
        help="Pull latest source and re-sync dependencies",
    )
    p.set_defaults(func=cmd_update)

    # doctor
    p = sub.add_parser("doctor", help="Validate all subsystems")
    p.add_argument(
        "--strict", action="store_true",
        help="Exit 1 on missing vault/database",
    )
    p.set_defaults(func=cmd_doctor)

    # serve
    p = sub.add_parser("serve", help="Start MCP server")
    p.add_argument(
        "--transport", choices=["stdio", "sse", "http"], default="stdio",
        help="Transport protocol (stdio, sse, or http for Streamable HTTP)",
    )
    p.add_argument(
        "--host", default="127.0.0.1",
        help="Bind host for HTTP transport (default: 127.0.0.1)",
    )
    p.add_argument(
        "--port", type=int, default=8001,
        help="Bind port for HTTP transport (default: 8001)",
    )
    p.set_defaults(func=cmd_serve)

    # setup-desktop
    p = sub.add_parser(
        "setup-desktop",
        help="Auto-configure Claude Desktop to use NeuroStack MCP server",
    )
    p.add_argument(
        "--dry-run", "-n", action="store_true",
        help="Show what would be written without making changes",
    )
    p.set_defaults(func=cmd_setup_desktop)

    # setup-client
    p = sub.add_parser(
        "setup-client",
        help="Auto-configure an AI client to use NeuroStack MCP server",
    )
    p.add_argument(
        "client", nargs="?",
        help="Client name: cursor, windsurf, gemini, vscode, claude-code",
    )
    p.add_argument(
        "--list", "-l", action="store_true",
        help="List supported clients and their config paths",
    )
    p.add_argument(
        "--dry-run", "-n", action="store_true",
        help="Show what would be written without making changes",
    )
    p.set_defaults(func=cmd_setup_client)

    # bundle
    p = sub.add_parser("bundle", help="Build .mcpb bundle for Claude Desktop")
    p.add_argument("--output", "-o", default="dist", help="Output directory (default: dist/)")
    p.set_defaults(func=cmd_bundle)

    # api
    p = sub.add_parser("api", help="Start OpenAI-compatible HTTP API server")
    p.add_argument("--host", default=cfg.api_host, help="Bind host (default: 127.0.0.1)")
    p.add_argument("--port", type=int, default=cfg.api_port, help="Bind port (default: 8000)")
    p.set_defaults(func=cmd_api)

    # sessions
    p = sub.add_parser(
        "sessions",
        help="Memory sessions and transcript search",
    )
    sess_sub = p.add_subparsers(dest="sessions_command")

    # sessions search (delegates to session-index)
    sp = sess_sub.add_parser(
        "search", help="Search session transcripts",
    )
    sp.add_argument(
        "session_args", nargs=argparse.REMAINDER,
        help="Arguments passed to session-index",
    )

    # sessions start
    sp = sess_sub.add_parser(
        "start", help="Start a new memory session",
    )
    sp.add_argument(
        "--source", help="Source agent name",
    )
    sp.add_argument(
        "--workspace", "-w", default=None,
        help="Workspace scope",
    )

    # sessions end
    sp = sess_sub.add_parser(
        "end", help="End a memory session",
    )
    sp.add_argument("id", type=int, help="Session ID")
    sp.add_argument(
        "--summarize", action="store_true",
        help="Generate LLM summary of session memories",
    )
    sp.add_argument(
        "--no-harvest", action="store_true",
        help="Skip auto-harvest of session insights",
    )

    # sessions list
    sp = sess_sub.add_parser(
        "list", help="List recent memory sessions",
    )
    sp.add_argument(
        "--limit", type=int, default=20,
    )
    sp.add_argument(
        "--workspace", "-w", default=None,
        help="Filter by workspace",
    )

    # sessions show
    sp = sess_sub.add_parser(
        "show",
        help="Show session details and memories",
    )
    sp.add_argument("id", type=int, help="Session ID")

    p.set_defaults(func=cmd_sessions)

    # index
    p = sub.add_parser("index", help="Full re-index of vault")
    p.add_argument("--skip-summary", action="store_true", help="Skip LLM summarization")
    p.add_argument("--skip-triples", action="store_true", help="Skip triple extraction")
    p.add_argument(
        "--workers", "-w", type=int, default=2,
        help="Number of parallel workers for LLM calls (default: 2)",
    )
    p.set_defaults(func=cmd_index)

    # search
    p = sub.add_parser("search", help="Search the vault")
    p.add_argument("query", help="Search query")
    p.add_argument("--top-k", type=int, default=5)
    p.add_argument("--mode", choices=["hybrid", "semantic", "keyword"], default="hybrid")
    p.add_argument(
        "--context", "-c", default=None,
        help="Project/domain context for result boosting",
    )
    p.add_argument(
        "--workspace", "-w", default=None,
        help="Restrict results to vault subdirectory "
        "(e.g. 'work/acme-cloud'). "
        "Also reads NEUROSTACK_WORKSPACE env var",
    )
    p.set_defaults(func=cmd_search)

    # ask
    p = sub.add_parser("ask", help="Ask a question using vault content (RAG)")
    p.add_argument("question", help="Natural language question")
    p.add_argument("--top-k", type=int, default=8, help="Number of chunks to retrieve for context")
    p.add_argument(
        "--workspace", "-w", default=None,
        help="Restrict results to vault subdirectory "
        "(e.g. 'work/acme-cloud'). "
        "Also reads NEUROSTACK_WORKSPACE env var",
    )
    p.set_defaults(func=cmd_ask)

    # summary
    p = sub.add_parser("summary", help="Get note summary")
    p.add_argument("path_or_query", help="Note path or search query")
    p.set_defaults(func=cmd_summary)

    # graph
    p = sub.add_parser("graph", help="Get note neighborhood")
    p.add_argument("note", help="Note path")
    p.add_argument("--depth", type=int, default=1)
    p.add_argument(
        "--workspace", "-w", default=None,
        help="Restrict neighbors to vault subdirectory "
        "(e.g. 'work/acme-cloud'). "
        "Also reads NEUROSTACK_WORKSPACE env var",
    )
    p.set_defaults(func=cmd_graph)

    # related
    p = sub.add_parser("related", help="Find semantically related notes")
    p.add_argument("note", help="Note path to find related notes for")
    p.add_argument("--top-k", type=int, default=10)
    p.add_argument(
        "--workspace", "-w", default=None,
        help="Restrict results to vault subdirectory "
        "(e.g. 'work/acme-cloud'). "
        "Also reads NEUROSTACK_WORKSPACE env var",
    )
    p.set_defaults(func=cmd_related)

    # triples
    p = sub.add_parser("triples", help="Search knowledge graph triples")
    p.add_argument("query", help="Search query")
    p.add_argument("--top-k", type=int, default=10)
    p.add_argument("--mode", choices=["hybrid", "semantic", "keyword"], default="hybrid")
    p.add_argument(
        "--workspace", "-w", default=None,
        help="Restrict results to vault subdirectory "
        "(e.g. 'work/acme-cloud'). "
        "Also reads NEUROSTACK_WORKSPACE env var",
    )
    p.set_defaults(func=cmd_triples)

    # tiered
    p = sub.add_parser("tiered", help="Tiered search (triples \u2192 summaries \u2192 full)")
    p.add_argument("query", help="Search query")
    p.add_argument("--top-k", type=int, default=5)
    p.add_argument("--depth", choices=["triples", "summaries", "full", "auto"], default="auto")
    p.add_argument("--mode", choices=["hybrid", "semantic", "keyword"], default="hybrid")
    p.add_argument(
        "--context", "-c", default=None,
        help="Project/domain context for result boosting",
    )
    p.add_argument(
        "--workspace", "-w", default=None,
        help="Restrict results to vault subdirectory "
        "(e.g. 'work/acme-cloud'). "
        "Also reads NEUROSTACK_WORKSPACE env var",
    )
    p.set_defaults(func=cmd_tiered)

    # reembed-chunks
    p = sub.add_parser(
        "reembed-chunks",
        help="Re-embed all chunks with contextual text"
        " (title+tags+summary+chunk)",
    )
    p.set_defaults(func=cmd_reembed_chunks)

    # backfill
    p = sub.add_parser("backfill", help="Backfill missing summaries and/or triples")
    p.add_argument(
        "target", choices=["summaries", "triples", "cooccurrence", "all"],
        default="all", nargs="?",
    )
    p.set_defaults(func=cmd_backfill)

    # communities
    p = sub.add_parser("communities", help="GraphRAG community detection and global queries")
    comm_sub = p.add_subparsers(dest="communities_cmd")

    # communities build
    comm_sub.add_parser(
        "build", help="Run attractor basin detection + LLM summaries",
    )

    # communities query
    p_q = comm_sub.add_parser("query", help="Global query over community summaries (GraphRAG)")
    p_q.add_argument("query", help="Natural language question")
    p_q.add_argument("--top-k", type=int, default=6)
    p_q.add_argument("--level", type=int, default=0, help="Community level (0=coarse, 1=fine)")
    p_q.add_argument(
        "--no-map-reduce", action="store_true",
        help="Return raw community hits without LLM synthesis",
    )
    p_q.add_argument(
        "--workspace", "-w", default=None,
        help="Restrict results to vault subdirectory "
        "(e.g. 'work/acme-cloud'). "
        "Also reads NEUROSTACK_WORKSPACE env var",
    )

    # communities list
    p_l = comm_sub.add_parser("list", help="List detected communities")
    p_l.add_argument("--level", type=int, default=None, help="Filter by level (0 or 1)")

    p.set_defaults(func=cmd_communities)

    # brief
    p = sub.add_parser("brief", help="Generate session brief")
    p.add_argument(
        "--workspace", "-w", default=None,
        help="Restrict brief to vault subdirectory "
        "(e.g. 'work/acme-cloud'). "
        "Also reads NEUROSTACK_WORKSPACE env var",
    )
    p.set_defaults(func=cmd_brief)

    # capture
    p = sub.add_parser("capture", help="Quick-capture a thought into the vault inbox")
    p.add_argument("content", help="The thought to capture")
    p.add_argument("--tags", "-t", help="Comma-separated tags")
    p.set_defaults(func=cmd_capture)

    # folder-summaries
    p = sub.add_parser(
        "folder-summaries",
        help="Build folder-level summaries for semantic"
        " context boosting",
    )
    p.add_argument("--force", action="store_true", help="Regenerate all even if up-to-date")
    p.set_defaults(func=cmd_folder_summaries)

    # prediction-errors
    p = sub.add_parser(
        "prediction-errors",
        help="Show notes flagged as prediction errors"
        " (poor retrieval fit)",
    )
    p.add_argument("--type", choices=["low_overlap", "contextual_mismatch"], default=None,
                   help="Filter by error type")
    p.add_argument("--limit", type=int, default=30, help="Max results to show")
    p.add_argument("--resolve", nargs="+", metavar="NOTE_PATH",
                   help="Mark note(s) as resolved")
    p.add_argument(
        "--workspace", "-w", default=None,
        help="Restrict results to vault subdirectory "
        "(e.g. 'work/acme-cloud'). "
        "Also reads NEUROSTACK_WORKSPACE env var",
    )
    p.set_defaults(func=cmd_prediction_errors)

    # stats
    p = sub.add_parser("stats", help="Show index stats")
    p.set_defaults(func=cmd_stats)

    # record-usage
    p = sub.add_parser(
        "record-usage", help="Record note usage for hotness scoring"
    )
    p.add_argument(
        "note_paths", nargs="+", help="Note paths to mark as used"
    )
    p.set_defaults(func=cmd_record_usage)

    # hooks
    p = sub.add_parser("hooks", help="Manage automation hooks (harvest timer)")
    hooks_sub = p.add_subparsers(dest="hooks_command")
    hp = hooks_sub.add_parser("install", help="Install automation hooks")
    hp.add_argument("--type", default="harvest-timer",
                    help="Hook type (default: harvest-timer)")
    hooks_sub.add_parser("status", help="Show hook status")
    hooks_sub.add_parser("remove", help="Remove automation hooks")
    p.set_defaults(func=cmd_hooks)

    # context
    p = sub.add_parser("context", help="Assemble task-scoped context for session recovery")
    p.add_argument("task", help="Description of the current task or goal")
    p.add_argument("--budget", type=int, default=2000,
                   help="Token budget (default: 2000)")
    p.add_argument("--workspace", "-w", help="Workspace scope")
    p.add_argument("--no-memories", action="store_true",
                   help="Exclude memories from context")
    p.add_argument("--no-triples", action="store_true",
                   help="Exclude triples from context")
    p.set_defaults(func=cmd_context)

    # decay
    p = sub.add_parser("decay", help="Report note excitability and dormancy")
    p.add_argument("--threshold", type=float, default=0.05,
                   help="Hotness threshold below which notes are dormant (default: 0.05)")
    p.add_argument("--half-life", type=float, default=30.0,
                   help="Half-life in days for hotness decay (default: 30)")
    p.add_argument("--limit", type=int, default=50,
                   help="Max notes to show per category (default: 50)")
    p.add_argument("--demote", action="store_true",
                   help="Demote dormant notes to status=dormant in note_metadata")
    p.set_defaults(func=cmd_decay)

    # cooccurrence
    p = sub.add_parser("cooccurrence", help="Inspect entity co-occurrence pairs")
    p.add_argument("--limit", type=int, default=20,
                   help="Number of top pairs to show (default: 20)")
    p.add_argument("--json", action="store_true", help="Output as JSON")
    p.set_defaults(func=cmd_cooccurrence)

    # harvest
    p = sub.add_parser("harvest", help="Extract insights from recent AI coding sessions")
    p.add_argument(
        "--sessions", type=int, default=1,
        help="Number of recent sessions to harvest (default: 1)",
    )
    p.add_argument(
        "--provider", type=str, default=None,
        help="Restrict to a single provider (e.g. claude-code, vscode-chat, codex-cli, aider)",
    )
    p.add_argument(
        "--list-providers", action="store_true",
        help="List available session providers and exit",
    )
    p.add_argument(
        "--dry-run", "-n", action="store_true",
        help="Show what would be saved without saving",
    )
    p.add_argument("--json", action="store_true", help="Output as JSON")
    p.set_defaults(func=cmd_harvest)

    # watch
    p = sub.add_parser("watch", help="Watch vault for changes")
    p.add_argument(
        "--cloud", action="store_true", default=False,
        help="Enable automatic cloud push after idle period (60s)",
    )
    p.set_defaults(func=cmd_watch)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Preflight: nudge user to run init if vault doesn't exist yet
    _skip_preflight = {
        "init", "install", "uninstall", "doctor", "status", "demo", "update", "cloud",
        "setup-desktop", "setup-client", "bundle",
    }
    vault_path = Path(args.vault)
    if args.command not in _skip_preflight and not vault_path.exists():
        print(f"\n  \033[33m!\033[0m Vault not found at {vault_path}")
        print("  Run \033[1mneurostack init\033[0m to set up your vault.\n")
        sys.exit(1)

    try:
        args.func(args)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
    except Exception as exc:
        _handle_error(exc, args.command)
        sys.exit(1)


if __name__ == "__main__":
    main()
