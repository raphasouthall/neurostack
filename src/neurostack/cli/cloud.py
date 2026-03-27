# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Cloud CLI commands."""

import json
import sys
import time
import webbrowser

import httpx

from ..cloud.client import CloudClient
from ..cloud.config import (
    CloudConfig,
    clear_cloud_credentials,
    load_cloud_config,
    save_cloud_config,
    save_consent,
)
from ..config import get_config


def _cmd_cloud_device_login() -> None:
    """Authenticate via OAuth device code flow (browser handoff)."""
    cfg = load_cloud_config()
    cloud_url = cfg.cloud_api_url or "https://neurostack-api-911077737485.us-central1.run.app"
    base = cloud_url.rstrip("/")

    # Step 1: Request device code
    try:
        resp = httpx.post(f"{base}/api/v1/auth/device-code", timeout=15.0)
        resp.raise_for_status()
    except httpx.ConnectError:
        print(f"  Error: Cannot reach cloud API at {base}.")
        sys.exit(1)
    except httpx.HTTPStatusError as e:
        print(f"  Error: Device code request failed ({e.response.status_code}).")
        sys.exit(1)

    data = resp.json()
    device_code = data["device_code"]
    user_code = data["user_code"]
    verification_uri = data.get("verification_uri", f"{base}/device")
    expires_in = data.get("expires_in", 600)
    interval = data.get("interval", 5)

    # Step 2: Show code and open browser (code passed via URL for auto-fill)
    verification_url = f"{verification_uri}?code={user_code}"
    print("\n  Opening browser to sign in...")
    print("  If the browser doesn't open, visit:")
    print(f"  URL:  {verification_url}")
    print(f"  Code: \033[1m{user_code}\033[0m\n")

    try:
        webbrowser.open(verification_url)
    except Exception:
        pass  # Non-fatal if browser fails to open

    # Step 3: Poll for token
    deadline = time.monotonic() + expires_in
    dots = 0
    while time.monotonic() < deadline:
        time.sleep(interval)
        dots = (dots + 1) % 4
        spinner = "." * (dots + 1)
        print(f"\r  Waiting for browser authorization{spinner}    ", end="", flush=True)

        try:
            token_resp = httpx.post(
                f"{base}/api/v1/auth/device-token",
                json={"device_code": device_code},
                timeout=15.0,
            )
        except (httpx.ConnectError, httpx.TimeoutException):
            continue  # Retry on transient errors

        if token_resp.status_code == 428:
            # Authorization pending -- keep polling
            continue
        elif token_resp.status_code == 200:
            token_data = token_resp.json()
            api_key = token_data["api_key"]
            save_cloud_config(cloud_api_url=cloud_url, cloud_api_key=api_key)
            print("\r  Login successful! API key stored in config.          ")
            return
        elif token_resp.status_code == 400:
            print("\r  Code expired. Please try again.                      ")
            sys.exit(1)
        else:
            status = token_resp.status_code
            print(f"\r  Unexpected error ({status}). Please try again.")
            sys.exit(1)

    print("\r  Authorization timed out. Please try again.           ")
    sys.exit(1)


def _ensure_cloud_auth():
    """Check cloud auth, trigger login if missing. Returns config."""
    cloud_cfg = load_cloud_config()
    if not cloud_cfg.cloud_api_url or not cloud_cfg.cloud_api_key:
        if sys.stdin.isatty():
            print("  Not logged in. Starting login...")
            print()
            _cmd_cloud_device_login()
            cloud_cfg = load_cloud_config()
            if not cloud_cfg.cloud_api_key:
                print("Error: Login failed.",
                      file=sys.stderr)
                sys.exit(1)
            print()
        else:
            print(
                "Error: Not authenticated."
                " Run `neurostack cloud login` first.",
                file=sys.stderr,
            )
            sys.exit(1)
    return cloud_cfg


def cmd_cloud(args):
    """Manage cloud authentication and configuration."""
    subcmd = getattr(args, "cloud_command", None)

    if subcmd == "login":
        api_key = getattr(args, "key", None)
        if api_key:
            # Direct API key login (--key flag)
            cfg = load_cloud_config()
            cloud_url = cfg.cloud_api_url or "https://neurostack-api-911077737485.us-central1.run.app"
            test_cfg = CloudConfig(cloud_api_url=cloud_url, cloud_api_key=api_key)
            client = CloudClient(test_cfg)
            try:
                if client.validate_key():
                    save_cloud_config(cloud_api_url=cloud_url, cloud_api_key=api_key)
                    print(f"  Logged in to {cloud_url}")
                else:
                    print("  Error: Invalid API key.")
                    sys.exit(1)
            except ConnectionError as e:
                print(f"  Error: {e}")
                sys.exit(1)
        else:
            # Device code flow (browser-based login)
            _cmd_cloud_device_login()

    elif subcmd == "logout":
        clear_cloud_credentials()
        print("  Logged out. Cloud credentials cleared.")

    elif subcmd == "status":
        cfg = load_cloud_config()
        client = CloudClient(cfg)

        result = {
            "authenticated": client.is_configured,
            "cloud_url": cfg.cloud_api_url or "(not configured)",
        }

        if client.is_configured:
            try:
                status = client.status()
                result.update(status)
            except (ConnectionError, Exception):
                result["connection"] = "unreachable"

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            if result["authenticated"]:
                print("  Status: Authenticated")
                print(f"  Cloud:  {result['cloud_url']}")
                tier = result.get("tier", "unknown")
                print(f"  Tier:   {tier}")
                if result.get("connection") == "unreachable":
                    print("  Note:   Cloud API unreachable (credentials stored locally)")
                # Staleness indicator
                try:
                    from ..cloud.sync import VaultSyncEngine
                    ns_cfg = get_config()
                    sync_engine = VaultSyncEngine(
                        cloud_api_url=cfg.cloud_api_url,
                        cloud_api_key=cfg.cloud_api_key,
                        vault_root=ns_cfg.vault_root,
                        db_dir=ns_cfg.db_dir,
                    )
                    staleness = sync_engine.get_staleness()
                    if staleness["is_stale"]:
                        parts = []
                        if staleness["stale_files_count"]:
                            parts.append(f"{staleness['stale_files_count']} files changed")
                        if staleness["behind_hours"] is not None:
                            parts.append(f"{staleness['behind_hours']} hours behind")
                        elif staleness["last_sync"] is None:
                            parts.append("never synced")
                        detail = ", ".join(parts) if parts else "changes detected"
                        print(f"  Sync:   Stale \u2014 {detail}")
                    else:
                        print(f"  Sync:   Up to date (last sync: {staleness['last_sync']})")
                except Exception:
                    pass  # Non-critical
            else:
                print("  Status: Not authenticated")
                url = result["cloud_url"]
                print(f"  Cloud:  {url}")
                print("  Run:    neurostack cloud login")

    elif subcmd == "setup":
        cfg = load_cloud_config()
        default_url = cfg.cloud_api_url or "https://neurostack-api-911077737485.us-central1.run.app"

        url = input(f"  Cloud API URL [{default_url}]: ").strip() or default_url
        api_key = input("  API key: ").strip()
        if not api_key:
            print("  Error: API key is required.")
            sys.exit(1)

        # Validate
        test_cfg = CloudConfig(cloud_api_url=url, cloud_api_key=api_key)
        client = CloudClient(test_cfg)
        try:
            if client.validate_key():
                save_cloud_config(cloud_api_url=url, cloud_api_key=api_key)
                print(f"  Cloud configured: {url}")
                print("  Authenticated successfully.")
            else:
                print("  Error: Invalid API key.")
                sys.exit(1)
        except ConnectionError as e:
            print(f"  Error: {e}")
            sys.exit(1)

    elif subcmd == "push":
        cmd_cloud_push(args)

    elif subcmd == "pull":
        cmd_cloud_pull(args)

    elif subcmd == "sync":
        cmd_cloud_sync(args)

    elif subcmd == "query":
        cmd_cloud_query(args)

    elif subcmd == "triples":
        cmd_cloud_triples(args)

    elif subcmd == "summary":
        cmd_cloud_summary(args)

    elif subcmd == "consent":
        prompt = (
            "Your vault content will be sent to Google's Gemini API for indexing. "
            "This includes note text, which is processed to generate embeddings, "
            "summaries, and knowledge graph triples. Continue? [y/N] "
        )
        answer = input(prompt).strip().lower()
        if answer in ("y", "yes"):
            save_consent()
            print("Consent granted.")
        else:
            print("Consent not granted. Cloud features require consent.")
            sys.exit(1)

    elif subcmd == "install-hooks":
        from ..cloud.hooks import install_hooks
        ns_cfg = get_config()
        try:
            result = install_hooks(ns_cfg.vault_root)
            if result["installed"]:
                print(f"  Installed: {', '.join(result['installed'])}")
            if result["skipped"]:
                print(f"  Already installed: {', '.join(result['skipped'])}")
            print(f"  Git dir: {result['git_dir']}")
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

    elif subcmd == "uninstall-hooks":
        from ..cloud.hooks import uninstall_hooks
        ns_cfg = get_config()
        try:
            result = uninstall_hooks(ns_cfg.vault_root)
            if result["removed"]:
                print(f"  Removed: {', '.join(result['removed'])}")
            if result["not_found"]:
                print(f"  Not found: {', '.join(result['not_found'])}")
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

    elif subcmd == "hooks-status":
        from ..cloud.hooks import hooks_status
        ns_cfg = get_config()
        status = hooks_status(ns_cfg.vault_root)
        if not status["git_repo"]:
            print("  Vault is not a git repository")
        else:
            for hook in ("post_commit", "post_merge"):
                name = hook.replace("_", "-")
                state = "installed" if status[hook] else "not installed"
                print(f"  {name}: {state}")

    elif subcmd == "auto-sync":
        auto_cmd = getattr(args, "auto_sync_command", None)
        if auto_cmd == "enable":
            from ..cloud.timer import install_timer
            result = install_timer(interval=args.interval)
            print(f"  Timer installed ({result['interval']} interval)")
            print(f"  Service: {result['service_path']}")
            print(f"  Timer:   {result['timer_path']}")
            if result['enabled']:
                print("  Status:  Active")
            else:
                print("  Status:  Installed but not started (systemctl not available)")
        elif auto_cmd == "disable":
            from ..cloud.timer import uninstall_timer
            result = uninstall_timer()
            if result['removed']:
                print("  Auto-sync disabled")
                for p in result['paths']:
                    print(f"  Removed: {p}")
            else:
                print("  No timer found")
        elif auto_cmd == "status":
            from ..cloud.timer import timer_status
            status = timer_status()
            if not status['installed']:
                print("  Auto-sync: Not installed")
                print("  Run: neurostack cloud auto-sync enable")
            else:
                state = "active" if status['active'] else "inactive"
                print(f"  Auto-sync: {state}")
                if status['interval']:
                    print(f"  Interval:  {status['interval']}")
                if status['next_run']:
                    print(f"  Next run:  {status['next_run']}")
        else:
            print("Usage: neurostack cloud auto-sync {enable|disable|status}")

    else:
        print(
            "Usage: neurostack cloud "
            "{login|logout|status|setup|push|pull|sync|query|triples|"
            "summary|consent|install-hooks|uninstall-hooks|hooks-status|auto-sync}"
        )
        print("\nCommands:")
        print("  login           Authenticate via browser (device code) or --key")
        print("  logout          Clear stored credentials")
        print("  status          Show authentication state and usage")
        print("  setup           Interactive cloud configuration")
        print("  consent         Grant privacy consent for cloud features")
        print("  push            Upload vault files for cloud indexing")
        print("  pull            Download indexed database from cloud")
        print("  sync            Push vault changes and fetch new memories")
        print("  query           Search vault via cloud API")
        print("  triples         Search knowledge graph triples")
        print("  summary         Get a note summary")
        print("  install-hooks   Install git hooks for automatic cloud sync")
        print("  uninstall-hooks Remove git hooks for cloud sync")
        print("  hooks-status    Check git hook installation status")
        print("  auto-sync       Manage automatic periodic sync (systemd timer)")


def cmd_cloud_push(args):
    """Upload vault files to cloud for indexing."""
    from ..cloud.sync import ConsentError, SyncError, VaultSyncEngine

    cfg = get_config()
    cloud_cfg = _ensure_cloud_auth()

    engine = VaultSyncEngine(
        cloud_api_url=cloud_cfg.cloud_api_url,
        cloud_api_key=cloud_cfg.cloud_api_key,
        vault_root=cfg.vault_root,
        db_dir=cfg.db_dir,
        consent_given=cloud_cfg.consent_given,
    )

    def on_progress(msg: str):
        print(f"  {msg}")

    try:
        result = engine.push(progress_callback=on_progress)
    except ConsentError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except SyncError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if getattr(args, "json", False):
        print(json.dumps(result))
    else:
        print(f"Push complete: {result.get('message', 'done')}")


def cmd_cloud_sync(args):
    """Push vault changes and fetch new memories from cloud."""
    from ..cloud.sync import ConsentError, SyncError, VaultSyncEngine

    quiet = getattr(args, "quiet", False)

    cfg = get_config()
    cloud_cfg = _ensure_cloud_auth()

    engine = VaultSyncEngine(
        cloud_api_url=cloud_cfg.cloud_api_url,
        cloud_api_key=cloud_cfg.cloud_api_key,
        vault_root=cfg.vault_root,
        db_dir=cfg.db_dir,
        consent_given=cloud_cfg.consent_given,
    )

    def on_progress(msg: str):
        if not quiet:
            print(f"  {msg}")

    try:
        result = engine.sync(progress_callback=on_progress)
    except ConsentError as e:
        if not quiet:
            print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except SyncError as e:
        if not quiet:
            print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if quiet:
        return

    if getattr(args, "json", False):
        print(json.dumps(result))
    else:
        push_msg = result.get("message", "done")
        mem_count = result.get("memories_fetched", 0)
        print(f"Sync complete: {push_msg}")
        print(f"  Memories fetched: {mem_count}")


def cmd_cloud_pull(args):
    """Download indexed database from cloud."""
    from ..cloud.sync import SyncError, VaultSyncEngine

    cfg = get_config()
    cloud_cfg = _ensure_cloud_auth()

    engine = VaultSyncEngine(
        cloud_api_url=cloud_cfg.cloud_api_url,
        cloud_api_key=cloud_cfg.cloud_api_key,
        vault_root=cfg.vault_root,
        db_dir=cfg.db_dir,
    )

    try:
        db_path = engine.pull()
    except SyncError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if getattr(args, "json", False):
        print(json.dumps({
            "db_path": str(db_path),
            "size": db_path.stat().st_size,
        }))
    else:
        size_mb = db_path.stat().st_size / (1024 * 1024)
        print(f"  \033[32m\u2713\033[0m Downloaded"
              f" ({size_mb:.1f} MB)")
        print()
        print("  \033[1m\u2501\u2501\u2501 Setup complete \u2501\u2501\u2501\033[0m")
        print()
        print("  All search modes now available:")
        print("    neurostack cloud query '...'"
              "  # Search via cloud API")
        print("    neurostack search 'query'"
              "    # Hybrid search (local)")
        print("    neurostack serve"
              "             # Start MCP server")
        print()
        print("  Dashboard:"
              "  https://app.neurostack.sh")
        print()


def cmd_cloud_query(args):
    """Query vault via cloud API with tiered search."""
    cloud_cfg = _ensure_cloud_auth()
    client = CloudClient(cloud_cfg)

    try:
        result = client.query(
            args.query,
            top_k=args.top_k,
            depth=args.depth,
            mode=args.mode,
            workspace=getattr(args, "workspace", None),
        )
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if getattr(args, "json", False):
        print(json.dumps(result))
        return

    depth = result.get("depth_used", "unknown")
    print(f"  Depth: {depth}\n")

    triples = result.get("triples", [])
    if triples:
        print(f"  Triples ({len(triples)}):")
        for t in triples:
            print(f"    {t['subject']} -> {t['predicate']} -> {t['object']}")
            print(f"      [{t.get('score', 0):.2f}] {t['note']}")
        print()

    summaries = result.get("summaries", [])
    if summaries:
        print(f"  Summaries ({len(summaries)}):")
        for s in summaries:
            title = s.get("title", s.get("note", "untitled"))
            summary = s.get("summary", "")[:200]
            print(f"    {title}")
            print(f"      {summary}")
        print()

    chunks = result.get("chunks", [])
    if chunks:
        print(f"  Results ({len(chunks)}):")
        for i, c in enumerate(chunks, 1):
            title = c.get("title", c.get("note", "untitled"))
            section = c.get("section", "")
            snippet = c.get("snippet", "")[:150]
            score = c.get("score", 0)
            print(f"    {i}. [{score:.2f}] {title}")
            if section:
                print(f"       Section: {section}")
            if snippet:
                print(f"       {snippet}")

    if not triples and not summaries and not chunks:
        print("  No results found.")


def cmd_cloud_triples(args):
    """Search knowledge graph triples via cloud API."""
    cloud_cfg = load_cloud_config()
    if not cloud_cfg.cloud_api_url or not cloud_cfg.cloud_api_key:
        print("Error: Not authenticated. Run `neurostack cloud login` first.", file=sys.stderr)
        sys.exit(1)

    client = CloudClient(cloud_cfg)

    try:
        results = client.triples(
            args.query,
            top_k=args.top_k,
            workspace=getattr(args, "workspace", None),
        )
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if getattr(args, "json", False):
        print(json.dumps(results))
        return

    if not results:
        print("No triples found.")
        return

    for t in results:
        print(f"  {t['subject']} -> {t['predicate']} -> {t['object']}")
        print(f"    [{t.get('score', 0):.2f}] {t.get('note', '')}")


def cmd_cloud_summary(args):
    """Get a note summary via cloud API."""
    cloud_cfg = load_cloud_config()
    if not cloud_cfg.cloud_api_url or not cloud_cfg.cloud_api_key:
        print("Error: Not authenticated. Run `neurostack cloud login` first.", file=sys.stderr)
        sys.exit(1)

    client = CloudClient(cloud_cfg)

    try:
        result = client.summary(args.note_path)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if result is None:
        print(f"No summary found for: {args.note_path}", file=sys.stderr)
        sys.exit(1)

    if getattr(args, "json", False):
        print(json.dumps(result))
        return

    print(f"  {result.get('title', args.note_path)}")
    print(f"  {result.get('summary', 'No summary')}")
