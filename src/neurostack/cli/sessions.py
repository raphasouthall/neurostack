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


_DECAY_TIMER = {
    "unit": "neurostack-decay",
    "service_desc": "NeuroStack excitability decay - sync note hotness status",
    "exec": "%h/.local/bin/neurostack decay --demote",
    "timer_desc": "Run neurostack excitability decay daily",
    "on_calendar": "*-*-* 03:00:00",
}


def _install_user_timer(spec):
    """Write and enable a systemd --user timer/service pair; return the timer path."""
    import subprocess

    timer_dir = Path.home() / ".config" / "systemd" / "user"
    timer_dir.mkdir(parents=True, exist_ok=True)
    (timer_dir / f"{spec['unit']}.service").write_text(
        f"""[Unit]
Description={spec['service_desc']}

[Service]
Type=oneshot
ExecStart={spec['exec']}
Environment=PATH=%h/.local/bin:/usr/local/bin:/usr/bin
"""
    )
    (timer_dir / f"{spec['unit']}.timer").write_text(
        f"""[Unit]
Description={spec['timer_desc']}

[Timer]
OnCalendar={spec['on_calendar']}
Persistent=true

[Install]
WantedBy=timers.target
"""
    )
    subprocess.run(
        ["systemctl", "--user", "daemon-reload"],
        check=False, capture_output=True,
    )
    subprocess.run(
        ["systemctl", "--user", "enable", "--now", f"{spec['unit']}.timer"],
        check=False, capture_output=True,
    )
    return timer_dir / f"{spec['unit']}.timer"


def _remove_user_timer(unit):
    """Disable and delete a systemd --user timer/service pair."""
    import subprocess

    subprocess.run(
        ["systemctl", "--user", "disable", "--now", f"{unit}.timer"],
        check=False, capture_output=True,
    )
    timer_dir = Path.home() / ".config" / "systemd" / "user"
    for fname in (f"{unit}.service", f"{unit}.timer"):
        p = timer_dir / fname
        if p.exists():
            p.unlink()
    subprocess.run(
        ["systemctl", "--user", "daemon-reload"],
        check=False, capture_output=True,
    )


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
        hook_type = args.type or "decay-timer"

        if hook_type == "decay-timer":
            timer_path = _install_user_timer(_DECAY_TIMER)
            if args.json:
                print(json.dumps({"installed": True, "type": hook_type}))
            else:
                print(f"  \033[32m✓\033[0m Installed {hook_type}")
                print(f"    Timer: {timer_path}")
                print("    Check: systemctl --user status neurostack-decay.timer")
        else:
            print(f"  Unknown hook type: {hook_type}")

    elif subcmd == "status":
        import subprocess

        from ..adapters import claude_adapter_installed, omp_extension_path

        decay = subprocess.run(
            ["systemctl", "--user", "is-active", "neurostack-decay.timer"],
            capture_output=True, text=True,
        )
        decay_active = decay.stdout.strip() == "active"
        claude_adapter = claude_adapter_installed()
        omp_adapter = omp_extension_path().exists()
        if args.json:
            print(json.dumps({
                "decay_timer": "active" if decay_active else "inactive",
                "claude_adapter": "installed" if claude_adapter else "absent",
                "omp_adapter": "installed" if omp_adapter else "absent",
            }))
        else:
            def _mark(flag, yes="installed", no="absent"):
                return f"\033[32m{yes}\033[0m" if flag else f"\033[31m{no}\033[0m"

            print(f"  decay-timer: {_mark(decay_active, 'active', 'inactive')}")
            print(f"  claude-adapter: {_mark(claude_adapter)}")
            print(f"  omp-adapter: {_mark(omp_adapter)}")

    elif subcmd == "remove":
        if harness:
            _remove_harness_adapter(args, harness)
            return
        hook_type = getattr(args, "type", None) or "decay-timer"
        if hook_type == "decay-timer":
            _remove_user_timer("neurostack-decay")
        else:
            print(f"  Unknown hook type: {hook_type}")
            return
        if args.json:
            print(json.dumps({"removed": True, "type": hook_type}))
        else:
            print(f"  \033[32m\u2713\033[0m Removed {hook_type}")

    else:
        print("Usage: neurostack hooks {install,status,remove}")
        print("       neurostack hooks --harness {claude,omp}")
        print("       neurostack hooks --help")
