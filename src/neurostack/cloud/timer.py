# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""systemd user timer for periodic cloud sync.

Installs a systemd user service and timer that runs
``neurostack cloud sync --quiet`` on a configurable interval.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

SERVICE_NAME = "neurostack-cloud-sync"

SERVICE_UNIT = """\
[Unit]
Description=NeuroStack Cloud Sync
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart={neurostack_path} cloud sync --quiet
Environment=PATH=/usr/local/bin:/usr/bin:/bin
"""

TIMER_UNIT = """\
[Unit]
Description=NeuroStack Cloud Sync Timer

[Timer]
OnBootSec=5min
OnUnitActiveSec={interval}
Persistent=true

[Install]
WantedBy=timers.target
"""


def _systemd_user_dir() -> Path:
    """Return ~/.config/systemd/user/ directory."""
    return Path.home() / ".config" / "systemd" / "user"


def _find_neurostack_path() -> str:
    """Find the neurostack executable path."""
    import shutil
    path = shutil.which("neurostack")
    if path:
        return path
    # Fallback: try common locations
    for candidate in [
        Path.home() / ".local" / "bin" / "neurostack",
        Path("/usr/local/bin/neurostack"),
        Path("/usr/bin/neurostack"),
    ]:
        if candidate.exists():
            return str(candidate)
    return "neurostack"  # Hope it's on PATH at runtime


def install_timer(interval: str = "15min") -> dict:
    """Install systemd user timer for periodic sync.

    Args:
        interval: Sync interval (systemd time format: 5min, 1h, 30s, etc.)

    Returns:
        {
            "service_path": str,
            "timer_path": str,
            "interval": str,
            "enabled": bool,
        }
    """
    user_dir = _systemd_user_dir()
    user_dir.mkdir(parents=True, exist_ok=True)

    neurostack_path = _find_neurostack_path()

    service_path = user_dir / f"{SERVICE_NAME}.service"
    timer_path = user_dir / f"{SERVICE_NAME}.timer"

    # Write service unit
    service_path.write_text(
        SERVICE_UNIT.format(neurostack_path=neurostack_path)
    )

    # Write timer unit
    timer_path.write_text(
        TIMER_UNIT.format(interval=interval)
    )

    # Reload systemd and enable timer
    enabled = False
    try:
        subprocess.run(
            ["systemctl", "--user", "daemon-reload"],
            check=True, capture_output=True,
        )
        subprocess.run(
            ["systemctl", "--user", "enable", "--now", f"{SERVICE_NAME}.timer"],
            check=True, capture_output=True,
        )
        enabled = True
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass  # systemctl may not be available in containers/CI

    return {
        "service_path": str(service_path),
        "timer_path": str(timer_path),
        "interval": interval,
        "enabled": enabled,
    }


def uninstall_timer() -> dict:
    """Remove systemd user timer.

    Returns:
        {"removed": bool, "paths": list[str]}
    """
    user_dir = _systemd_user_dir()
    service_path = user_dir / f"{SERVICE_NAME}.service"
    timer_path = user_dir / f"{SERVICE_NAME}.timer"

    # Stop and disable
    try:
        subprocess.run(
            ["systemctl", "--user", "disable", "--now", f"{SERVICE_NAME}.timer"],
            check=False, capture_output=True,
        )
        subprocess.run(
            ["systemctl", "--user", "daemon-reload"],
            check=False, capture_output=True,
        )
    except FileNotFoundError:
        pass

    removed_paths = []
    for path in (service_path, timer_path):
        if path.exists():
            path.unlink()
            removed_paths.append(str(path))

    return {
        "removed": len(removed_paths) > 0,
        "paths": removed_paths,
    }


def timer_status() -> dict:
    """Check if the systemd timer is installed and active.

    Returns:
        {
            "installed": bool,
            "active": bool,
            "interval": str | None,
            "next_run": str | None,
        }
    """
    user_dir = _systemd_user_dir()
    timer_path = user_dir / f"{SERVICE_NAME}.timer"

    if not timer_path.exists():
        return {"installed": False, "active": False, "interval": None, "next_run": None}

    # Parse interval from timer file
    interval = None
    for line in timer_path.read_text().splitlines():
        if line.startswith("OnUnitActiveSec="):
            interval = line.split("=", 1)[1].strip()
            break

    # Check if active
    active = False
    next_run = None
    try:
        result = subprocess.run(
            ["systemctl", "--user", "is-active", f"{SERVICE_NAME}.timer"],
            capture_output=True, text=True,
        )
        active = result.returncode == 0

        if active:
            result = subprocess.run(
                ["systemctl", "--user", "show", f"{SERVICE_NAME}.timer",
                 "--property=NextElapseUSecRealtime"],
                capture_output=True, text=True,
            )
            if result.returncode == 0:
                next_run = result.stdout.strip().split("=", 1)[-1]
    except FileNotFoundError:
        pass

    return {
        "installed": True,
        "active": active,
        "interval": interval,
        "next_run": next_run,
    }
