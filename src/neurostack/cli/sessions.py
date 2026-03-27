# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Session, harvest, and hooks CLI commands."""

import json
import sys
from pathlib import Path

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
        from ..memories import end_session, summarize_session
        from ..schema import DB_PATH, get_db
        conn = get_db(DB_PATH)
        summary = None
        if getattr(args, "summarize", False):
            print("  Generating session summary...")
            summary = summarize_session(
                conn, args.id,
                llm_url=args.summarize_url,
            )
        result = end_session(conn, args.id, summary=summary)
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
    from ..harvest import get_provider_names, harvest_sessions

    if getattr(args, "list_providers", False):
        for name in get_provider_names():
            print(f"  {name}")
        return

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


def cmd_hooks(args):
    """Manage neurostack automation hooks."""
    subcmd = getattr(args, "hooks_command", None)

    if subcmd == "install":
        import subprocess

        hook_type = args.type or "harvest-timer"

        if hook_type == "harvest-timer":
            # Create a systemd user timer for periodic harvest
            timer_dir = Path.home() / ".config" / "systemd" / "user"
            timer_dir.mkdir(parents=True, exist_ok=True)

            service_content = (
                "[Unit]\n"
                "Description=NeuroStack harvest - extract session insights\n\n"
                "[Service]\n"
                "Type=oneshot\n"
                "ExecStart=%h/.local/bin/neurostack harvest --sessions 3\n"
                "Environment=PATH=%h/.local/bin:/usr/local/bin:/usr/bin\n"
            )
            timer_content = (
                "[Unit]\n"
                "Description=Run neurostack harvest every hour\n\n"
                "[Timer]\n"
                "OnCalendar=hourly\n"
                "Persistent=true\n\n"
                "[Install]\n"
                "WantedBy=timers.target\n"
            )

            (timer_dir / "neurostack-harvest.service").write_text(service_content)
            (timer_dir / "neurostack-harvest.timer").write_text(timer_content)

            subprocess.run(
                ["systemctl", "--user", "daemon-reload"],
                check=False, capture_output=True,
            )
            subprocess.run(
                ["systemctl", "--user", "enable", "--now", "neurostack-harvest.timer"],
                check=False, capture_output=True,
            )

            if args.json:
                print(json.dumps({"installed": True, "type": hook_type}))
            else:
                print(f"  \033[32m\u2713\033[0m Installed {hook_type}")
                print(f"    Timer: {timer_dir / 'neurostack-harvest.timer'}")
                print("    Check: systemctl --user status neurostack-harvest.timer")
        else:
            print(f"  Unknown hook type: {hook_type}")

    elif subcmd == "status":
        import subprocess

        result = subprocess.run(
            ["systemctl", "--user", "is-active", "neurostack-harvest.timer"],
            capture_output=True, text=True,
        )
        active = result.stdout.strip() == "active"
        if args.json:
            print(json.dumps({"harvest_timer": "active" if active else "inactive"}))
        else:
            status = "\033[32mactive\033[0m" if active else "\033[31minactive\033[0m"
            print(f"  harvest-timer: {status}")

    elif subcmd == "remove":
        import subprocess

        subprocess.run(
            ["systemctl", "--user", "disable", "--now", "neurostack-harvest.timer"],
            check=False, capture_output=True,
        )
        timer_dir = Path.home() / ".config" / "systemd" / "user"
        for f in ("neurostack-harvest.service", "neurostack-harvest.timer"):
            p = timer_dir / f
            if p.exists():
                p.unlink()
        subprocess.run(
            ["systemctl", "--user", "daemon-reload"],
            check=False, capture_output=True,
        )
        if args.json:
            print(json.dumps({"removed": True}))
        else:
            print("  \033[32m\u2713\033[0m Removed harvest timer")

    else:
        print("Usage: neurostack hooks {install,status,remove}")
        print("       neurostack hooks --help")
