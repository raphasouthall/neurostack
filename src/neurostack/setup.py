# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Client setup automation — auto-detect platform, merge MCP config."""

import json
import os
import platform
import shutil
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Client config definitions
# ---------------------------------------------------------------------------

def _neurostack_command() -> str:
    """Return the neurostack command path for MCP configs."""
    # Prefer the installed CLI wrapper
    which = shutil.which("neurostack")
    if which:
        return which
    return "neurostack"


def _mcp_server_entry() -> dict:
    """Standard MCP server entry for NeuroStack (stdio transport)."""
    return {
        "command": _neurostack_command(),
        "args": ["serve"],
        "env": {},
    }


def _detect_platform() -> str:
    """Detect OS: 'macos', 'linux', or 'windows'."""
    s = platform.system().lower()
    if s == "darwin":
        return "macos"
    if s == "windows":
        return "windows"
    return "linux"


# ---------------------------------------------------------------------------
# Config path registry
# ---------------------------------------------------------------------------

def _claude_desktop_config_path() -> Path:
    """Platform-aware Claude Desktop config path."""
    plat = _detect_platform()
    if plat == "macos":
        return (
            Path.home() / "Library" / "Application Support"
            / "Claude" / "claude_desktop_config.json"
        )
    if plat == "windows":
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            return Path(appdata) / "Claude" / "claude_desktop_config.json"
        return Path.home() / "AppData" / "Roaming" / "Claude" / "claude_desktop_config.json"
    # Linux
    return Path.home() / ".config" / "Claude" / "claude_desktop_config.json"


CLIENT_CONFIGS = {
    "cursor": {
        "name": "Cursor",
        "path": lambda: Path.home() / ".cursor" / "mcp.json",
        "key": "mcpServers",
        "docs": "Restart Cursor to pick up the new MCP server.",
    },
    "windsurf": {
        "name": "Windsurf",
        "path": lambda: Path.home() / ".codeium" / "windsurf" / "mcp_config.json",
        "key": "mcpServers",
        "docs": "Restart Windsurf to pick up the new MCP server.",
    },
    "gemini": {
        "name": "Gemini CLI",
        "path": lambda: Path.home() / ".gemini" / "settings.json",
        "key": "mcpServers",
        "docs": "Restart Gemini CLI to pick up the new MCP server.",
    },
    "vscode": {
        "name": "VS Code / Copilot",
        "path": lambda: Path.cwd() / ".vscode" / "mcp.json",
        "key": "servers",
        "docs": "Reload VS Code window (Ctrl+Shift+P → 'Reload Window').",
    },
    "claude-code": {
        "name": "Claude Code",
        "path": lambda: Path.home() / ".claude" / ".mcp.json",
        "key": "mcpServers",
        "docs": "Restart Claude Code to pick up the new MCP server.",
    },
}


# ---------------------------------------------------------------------------
# Core merge logic
# ---------------------------------------------------------------------------

def _read_json(path: Path) -> dict:
    """Read JSON file, return empty dict if missing or invalid."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _write_json(path: Path, data: dict) -> None:
    """Write JSON with pretty formatting, creating parent dirs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _merge_mcp_entry(config: dict, key: str, server_name: str, entry: dict) -> tuple[dict, bool]:
    """Merge an MCP server entry into config non-destructively.

    Returns (updated_config, was_already_present).
    """
    if key not in config:
        config[key] = {}

    already_present = server_name in config[key]
    if already_present:
        # Update command/args but preserve any user customizations in env
        existing = config[key][server_name]
        existing["command"] = entry["command"]
        existing["args"] = entry["args"]
        if "env" not in existing:
            existing["env"] = entry.get("env", {})
    else:
        config[key][server_name] = entry

    return config, already_present


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def setup_desktop(dry_run: bool = False) -> None:
    """Auto-configure Claude Desktop to use NeuroStack MCP server."""
    config_path = _claude_desktop_config_path()
    entry = _mcp_server_entry()

    print(f"  Platform: {_detect_platform()}")
    print(f"  Config:   {config_path}")
    print(f"  Command:  {entry['command']}")

    config = _read_json(config_path)
    config, already = _merge_mcp_entry(config, "mcpServers", "neurostack", entry)

    if dry_run:
        print(f"\n  [dry-run] Would write to {config_path}:")
        print(json.dumps(config, indent=2))
        return

    _write_json(config_path, config)

    if already:
        print(f"\n  Updated existing NeuroStack entry in {config_path}")
    else:
        print(f"\n  Added NeuroStack MCP server to {config_path}")

    print("\n  Next steps:")
    print("  1. Restart Claude Desktop")
    print("  2. NeuroStack tools will appear in the tools menu")
    print("  3. Try: \"Search my vault for recent projects\"")


def setup_client(client_name: str, dry_run: bool = False) -> None:
    """Auto-configure a supported AI client to use NeuroStack MCP server."""
    client_name = client_name.lower().replace(" ", "-")

    if client_name not in CLIENT_CONFIGS:
        supported = ", ".join(sorted(CLIENT_CONFIGS.keys()))
        print(f"  Unknown client: {client_name}", file=sys.stderr)
        print(f"  Supported clients: {supported}", file=sys.stderr)
        sys.exit(1)

    client = CLIENT_CONFIGS[client_name]
    config_path = client["path"]()
    entry = _mcp_server_entry()
    key = client["key"]

    # VS Code uses a different entry format with "type": "stdio"
    if client_name == "vscode":
        entry = {
            "type": "stdio",
            "command": entry["command"],
            "args": entry["args"],
        }

    print(f"  Client:   {client['name']}")
    print(f"  Config:   {config_path}")
    print(f"  Command:  {entry.get('command', entry.get('command', 'neurostack'))}")

    config = _read_json(config_path)
    config, already = _merge_mcp_entry(config, key, "neurostack", entry)

    if dry_run:
        print(f"\n  [dry-run] Would write to {config_path}:")
        print(json.dumps(config, indent=2))
        return

    _write_json(config_path, config)

    if already:
        print(f"\n  Updated existing NeuroStack entry in {config_path}")
    else:
        print(f"\n  Added NeuroStack MCP server to {config_path}")

    print(f"\n  {client['docs']}")


def list_clients() -> None:
    """Print supported clients and their config paths."""
    print("\n  Supported clients:\n")
    print(f"  {'Client':<16} {'Config path'}")
    print(f"  {'------':<16} {'-----------'}")

    # Claude Desktop (special case)
    print(f"  {'claude-desktop':<16} {_claude_desktop_config_path()}")

    for name, client in sorted(CLIENT_CONFIGS.items()):
        print(f"  {name:<16} {client['path']()}")

    print("\n  Usage:")
    print("    neurostack setup-desktop              # Claude Desktop")
    print("    neurostack setup-client cursor         # Cursor")
    print("    neurostack setup-client windsurf       # Windsurf")
    print("    neurostack setup-client gemini         # Gemini CLI")
    print("    neurostack setup-client vscode         # VS Code / Copilot")
    print("    neurostack setup-client claude-code    # Claude Code")
