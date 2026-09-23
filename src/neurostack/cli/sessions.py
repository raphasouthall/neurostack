# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Session, harvest, and hooks CLI commands."""

import json
import sys
from pathlib import Path
from typing import Any

from .utils import _get_workspace


def cmd_sessions(args):
    """Manage memory sessions and search session transcripts."""
    sessions_cmd = getattr(args, "sessions_command", None)

    if sessions_cmd == "search" or sessions_cmd is None:
        # Delegate to session-index (existing behavior)
        from ..session_index import main as session_main
        extra = getattr(args, "session_args", []) or []
        if args.json and "--json" not in extra:
            extra = ["--json"] + extra
        sys.argv = ["neurostack-sessions"] + extra
        session_main()
        return

    if sessions_cmd == "start":
        from ..memories import start_session
        from ..schema import DB_PATH, get_db
        conn = get_db(DB_PATH)
        result = start_session(
            conn,
            source_agent=getattr(args, "source", None),
            workspace=_get_workspace(args),
        )
        if args.json:
            print(json.dumps(result, indent=2))
            return
        print(
            f"  Session {result['session_id']} started"
            f" at {result['started_at']}"
        )
        return

    if sessions_cmd == "end":
        from ..memories import end_session
        from ..schema import DB_PATH, get_db
        conn = get_db(DB_PATH)
        result = end_session(conn, args.id, summary=getattr(args, "summary", None))
        if "error" in result:
            print(f"  Error: {result['error']}")
            return

        # Auto-harvest unless --no-harvest
        if not getattr(args, "no_harvest", False):
            try:
                from ..harvest import harvest_sessions
                harvest_report = harvest_sessions(n_sessions=1)
                result["harvest"] = {
                    "saved": len(harvest_report.get("saved", [])),
                    "skipped": len(harvest_report.get("skipped", [])),
                }
            except Exception as e:
                result["harvest"] = {"error": str(e)}

        if args.json:
            print(json.dumps(result, indent=2))
            return
        print(
            f"  Session {result['session_id']} ended"
            f" at {result['ended_at']}"
        )
        if result.get("summary"):
            print(f"  Summary: {result['summary']}")
        harvest_info = result.get("harvest", {})
        if "error" not in harvest_info:
            saved = harvest_info.get("saved", 0)
            skipped = harvest_info.get("skipped", 0)
            if saved or skipped:
                print(f"  Harvest: {saved} saved, {skipped} skipped")
        return

    if sessions_cmd == "list":
        from ..memories import list_sessions
        from ..schema import DB_PATH, get_db
        conn = get_db(DB_PATH)
        sessions = list_sessions(
            conn,
            limit=args.limit,
            workspace=_get_workspace(args),
        )
        if args.json:
            print(json.dumps(sessions, indent=2))
            return
        if not sessions:
            print("  No sessions found.")
            return
        for s in sessions:
            status = (
                "active" if not s["ended_at"] else "ended"
            )
            agent = s["source_agent"] or "unknown"
            print(
                f"  #{s['session_id']} [{status}] "
                f"{agent} - {s['started_at']} "
                f"({s['memory_count']} memories)"
            )
            if s.get("summary"):
                print(f"    {s['summary'][:120]}")
        return

    if sessions_cmd == "show":
        from ..memories import get_session
        from ..schema import DB_PATH, get_db
        conn = get_db(DB_PATH)
        session = get_session(conn, args.id)
        if not session:
            print(f"  Session {args.id} not found.")
            return
        if args.json:
            print(json.dumps(session, indent=2))
            return
        sid = session["session_id"]
        status = (
            "active" if not session["ended_at"]
            else "ended"
        )
        print(f"  Session #{sid} [{status}]")
        print(f"  Started: {session['started_at']}")
        if session["ended_at"]:
            print(f"  Ended: {session['ended_at']}")
        if session.get("source_agent"):
            print(
                f"  Agent: {session['source_agent']}"
            )
        if session.get("workspace"):
            print(
                f"  Workspace: {session['workspace']}"
            )
        if session.get("summary"):
            print(
                f"  Summary: {session['summary']}"
            )
        print(
            f"  Memories: {session['memory_count']}"
        )
        for m in session.get("memories", []):
            print(
                f"    [{m['entity_type']}] "
                f"{m['content'][:100]}"
            )
        return


def cmd_harvest(args):
    """Extract insights from recent AI coding sessions."""
    from ..harvest import (
        get_provider_names,
        harvest_session_file,
        harvest_sessions,
        pending_sessions,
    )

    if getattr(args, "list_providers", False):
        for name in get_provider_names():
            print(f"  {name}")
        return

    enqueue = getattr(args, "enqueue", False)
    pending = getattr(args, "pending", False)
    if enqueue and not pending:
        print("  --enqueue requires --pending (use --pending --enqueue)")
        sys.exit(1)
    if enqueue and getattr(args, "session", None):
        print("  --enqueue cannot be combined with --session"
              " (use --pending --enqueue)")
        sys.exit(1)

    if pending:
        # A scan window of 1 is the harvest default; listing wants the backlog.
        scan = args.sessions if args.sessions > 1 else 50
        rows = pending_sessions(scan, provider=getattr(args, "provider", None))
        if enqueue:
            _enqueue_pending(rows, args.json)
            return
        if args.json:
            print(json.dumps(rows, indent=2, default=str))
            return
        for row in rows:
            print(f"  {row['provider']:<12} {row['path']}")
        print(f"\n  {len(rows)} transcript(s) pending of {scan} scanned")
        return

    if getattr(args, "session", None):
        result = harvest_session_file(
            args.session, dry_run=args.dry_run, embed_url=args.embed_url,
        )
    else:
        result = harvest_sessions(
            n_sessions=args.sessions,
            dry_run=args.dry_run,
            embed_url=args.embed_url,
            provider=getattr(args, "provider", None),
        )

    if args.json:
        print(json.dumps(result, indent=2, default=str))
        return

    if "error" in result:
        print(f"  Error: {result['error']}")
        return

    mode = "DRY RUN" if result.get("dry_run") else "Harvest"
    providers = ", ".join(result.get("providers", []))
    print(f"\n  {mode} - scanned {result['sessions_scanned']} session(s)"
          + (f" [{providers}]" if providers else "") + "\n")

    if result["counts"]:
        print("  Counts by type:")
        for etype, count in sorted(result["counts"].items()):
            print(f"    {etype}: {count}")
        print()

    for item in result["saved"]:
        mid = item.get("memory_id", "-")
        print(f"  \033[32m+\033[0m [{item['entity_type']}] #{mid} {item['content'][:80]}")
        if item.get("tags"):
            print(f"    tags: {', '.join(item['tags'])}")

    for item in result["skipped"]:
        status = item.get("status", "skipped")
        snip = item["content"][:60]
        print(f"  \033[33m-\033[0m [{item['entity_type']}] {status}: {snip}")

    n_saved = len(result["saved"])
    n_skip = len(result["skipped"])
    total = n_saved + n_skip
    print(f"\n  Total: {n_saved} saved, {n_skip} skipped ({total} found)")


def enqueue_pending(client, rows) -> dict[str, Any]:
    """Upload every pending transcript to the server's harvest queue (#207, #232).

    Goes through the `queue_add` MCP tool, so dedupe and the schema stay in
    `queue.py` on the server. Keyed on ``path@mtime`` so a transcript already
    queued is a no-op duplicate. A transcript's watermark moves only once the
    server holds it, so a failed upload shows as pending on the next scan. One
    bad row is recorded and skipped; a server that does not answer ends the
    scan, since every later upload would wait out the same timeout.
    """
    from ..harvest import record_watermark
    from .queue import upload

    jobs = []
    queued = 0
    duplicates = 0
    errors = 0

    for row in rows:
        key = f"{row['path']}@{row['mtime']}"
        payload = {"path": row["path"], "provider": row["provider"], "mtime": row["mtime"]}
        try:
            result = upload(client, "harvest", key, payload, Path(row["path"]), row["provider"])
        except Exception as e:
            errors += 1
            jobs.append({"key": key, "error": str(e)})
            continue
        if result is None:
            errors += 1
            jobs.append({"key": key, "error": client.errors[-1] if client.errors else "no reply"})
            break
        if result.get("ok") is not True:
            errors += 1
            jobs.append({"key": key, "error": result.get("reason") or "refused"})
            continue
        record_watermark(row["path"], row["mtime"], row["messages"])
        if result.get("duplicate"):
            duplicates += 1
        else:
            queued += 1
        jobs.append({"key": key, "job_id": result.get("job_id"),
                     "duplicate": result.get("duplicate", False)})

    summary = {"queued": queued, "duplicates": duplicates, "total": len(rows), "jobs": jobs}
    if errors:
        summary["errors"] = errors
    return summary


def _enqueue_pending(rows, as_json):
    from ..client import McpClient, load_client_config

    client = McpClient(load_client_config())
    try:
        summary = enqueue_pending(client, rows)
    finally:
        client.close()
    if as_json:
        print(json.dumps(summary))
        return

    jobs, errors = summary["jobs"], summary.get("errors", 0)
    queued, duplicates = summary["queued"], summary["duplicates"]

    for row, job in zip(rows, jobs):
        if "error" in job:
            print(f"  \033[31mERROR\033[0m {row['path']}: {job['error']}")
        elif not job["duplicate"]:
            print(f"  + {row['path']}")
    print(f"\n  Total: {queued} queued, {duplicates} duplicate(s),"
          f" {errors} error(s) ({len(rows)} pending)")


def _mark(flag, yes="installed", no="absent"):
    return f"\033[32m{yes}\033[0m" if flag else f"\033[31m{no}\033[0m"


def _install_harness_adapter(args, harness):
    """Generate the adapter that wires a harness to `neurostack hook`."""
    from ..adapters import install_adapter

    status, path = install_adapter(harness)
    if args.json:
        print(json.dumps({"installed": status == "installed", "harness": harness,
                          "status": status, "path": str(path)}))
        return
    if status == "installed":
        restart = "omp" if harness == "omp" else "Claude Code"
        print(f"  \033[32m\u2713\033[0m Installed the {harness} adapter")
        print(f"    Adapter: {path}")
        print(f"    Restart {restart} to load it")
    elif status == "not-detected":
        print(f"  {harness} not detected — skipped")
    else:
        print("  \033[31m\u2717\033[0m neurostack binary not found on PATH"
              " or in ~/.local/bin — adapter not installed")


def _remove_harness_adapter(args, harness):
    from ..adapters import remove_adapter

    removed = remove_adapter(harness)
    if args.json:
        print(json.dumps({"removed": removed, "harness": harness}))
    elif removed:
        print(f"  \033[32m\u2713\033[0m Removed the {harness} adapter")
    else:
        print(f"  No {harness} adapter found")


def cmd_hooks(args):
    """Manage neurostack automation hooks."""
    subcmd = getattr(args, "hooks_command", None)
    harness = getattr(args, "harness", None)

    if subcmd == "install":
        if harness:
            _install_harness_adapter(args, harness)
            return
        print("  Scheduled jobs now run from one timer. Install it with"
              " 'neurostack schedule install'.")

    elif subcmd == "status":
        from ..adapters import claude_adapter_installed, omp_extension_path

        claude_adapter = claude_adapter_installed()
        omp_adapter = omp_extension_path().exists()
        if args.json:
            print(json.dumps({
                "claude_adapter": "installed" if claude_adapter else "absent",
                "omp_adapter": "installed" if omp_adapter else "absent",
            }))
        else:
            print(f"  claude-adapter: {_mark(claude_adapter)}")
            print(f"  omp-adapter: {_mark(omp_adapter)}")

    elif subcmd == "remove":
        if harness:
            _remove_harness_adapter(args, harness)
            return
        print("  Pass --harness {claude,omp}. Remove the run-due timer with"
              " 'neurostack schedule remove'.")

    else:
        print("Usage: neurostack hooks {install,status,remove}")
        print("       neurostack hooks --harness {claude,omp}")
        print("       neurostack hooks --help")
