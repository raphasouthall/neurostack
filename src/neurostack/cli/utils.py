# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Shared CLI utilities."""

import os
import sys
from pathlib import Path


def _get_vault_template_dir() -> Path | None:
    """Locate the vault-template directory.

    Checks the package directory first (pip/wheel installs), then
    falls back to the repo root (git checkout / editable installs).
    Returns None if not found.
    """
    # Package location: src/neurostack/vault_template/
    pkg_dir = Path(__file__).resolve().parent.parent / "vault_template"
    if pkg_dir.is_dir():
        return pkg_dir
    # Repo root fallback: vault-template/
    repo_dir = Path(__file__).resolve().parent.parent.parent.parent / "vault-template"
    if repo_dir.is_dir():
        return repo_dir
    return None


def _get_workspace(args) -> str | None:
    """Get workspace from args or NEUROSTACK_WORKSPACE env var."""
    ws = getattr(args, "workspace", None)
    if not ws:
        ws = os.environ.get("NEUROSTACK_WORKSPACE")
    return ws or None


def _db_lock_hint() -> str:
    """Try to identify what process holds the neurostack DB lock."""
    import shutil
    import subprocess

    db_path = os.environ.get(
        "NEUROSTACK_DB_PATH",
        os.path.expanduser("~/.local/share/neurostack/neurostack.db"),
    )
    fuser = shutil.which("fuser")
    if not fuser:
        return "Run `fuser <db_path>` to find the locking process."
    try:
        result = subprocess.run(
            [fuser, db_path],
            capture_output=True, text=True, timeout=5,
        )
        pids = result.stdout.strip().split()
        if not pids:
            return ""
        lines = []
        for pid in pids:
            try:
                cmd = Path(f"/proc/{pid}/cmdline").read_text().replace("\x00", " ").strip()
                lines.append(f"  PID {pid}: {cmd}")
            except OSError:
                lines.append(f"  PID {pid}: (unable to read command)")
        return "Processes holding the database:\n" + "\n".join(lines)
    except Exception:
        return ""


def _handle_error(exc: Exception, command: str) -> None:
    """Print a friendly diagnostic instead of a raw traceback."""
    import sqlite3

    RED = "\033[31m"
    YELLOW = "\033[33m"
    RESET = "\033[0m"
    BOLD = "\033[1m"

    exc_type = type(exc).__name__
    msg = str(exc)

    print(f"\n{RED}{BOLD}Error{RESET} [{exc_type}]: {msg}\n", file=sys.stderr)

    hint = ""

    # -- sqlite errors -------------------------------------------------------
    if isinstance(exc, sqlite3.OperationalError):
        if "locked" in msg or "busy" in msg:
            lock_info = _db_lock_hint()
            hint = (
                "The database is locked by another neurostack process.\n"
                "Wait for it to finish, or kill the locking process.\n"
            )
            if lock_info:
                hint += f"\n{lock_info}\n"
        elif "no such table" in msg or "no such column" in msg:
            hint = (
                "The database schema is outdated or corrupt.\n"
                "Try: neurostack init --force\n"
            )
        elif "disk I/O error" in msg or "readonly" in msg:
            hint = (
                "Cannot write to the database file.\n"
                "Check disk space and file permissions on the DB path.\n"
            )
    elif isinstance(exc, sqlite3.IntegrityError):
        hint = (
            "A database constraint was violated (duplicate or missing data).\n"
            "Try re-indexing: neurostack index\n"
        )

    # -- network / Ollama errors ---------------------------------------------
    elif isinstance(exc, ConnectionError):
        hint = (
            "Could not connect to a required service (likely Ollama).\n"
            "Check that Ollama is running: systemctl status ollama\n"
        )
    elif isinstance(exc, OSError) and "Connection refused" in msg:
        hint = (
            "Connection refused - is Ollama running?\n"
            "Start it with: systemctl start ollama\n"
        )

    # -- missing dependencies ------------------------------------------------
    elif isinstance(exc, ImportError):
        hint = (
            f"Missing dependency: {msg}\n"
            "Install it with: uv pip install <package>\n"
        )

    # -- file errors ---------------------------------------------------------
    elif isinstance(exc, FileNotFoundError):
        hint = (
            f"File not found: {msg}\n"
            "Check paths in ~/.config/neurostack/config.toml\n"
        )
    elif isinstance(exc, PermissionError):
        hint = f"Permission denied: {msg}\n"

    # -- httpx errors (Ollama calls) -----------------------------------------
    elif exc_type == "ConnectError":
        hint = (
            "Could not connect to Ollama.\n"
            "Check that Ollama is running: systemctl status ollama\n"
        )
    elif exc_type == "ReadTimeout":
        hint = (
            "Ollama request timed out.\n"
            "The model may be loading or the GPU is under heavy load.\n"
            "Try again in a moment.\n"
        )

    if hint:
        print(f"{YELLOW}Hint:{RESET} {hint}", file=sys.stderr)
    else:
        # Unknown error - show traceback for debugging
        import traceback
        print(f"{YELLOW}Full traceback:{RESET}", file=sys.stderr)
        traceback.print_exception(type(exc), exc, exc.__traceback__, file=sys.stderr)
