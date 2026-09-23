# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Schedule CLI command: one OS timer that runs `neurostack run-due` every minute.

Each platform gets exactly one backend. Linux uses a systemd --user timer,
macOS a launchd agent, and Windows a Task Scheduler task. Which jobs are due
is decided by `run-due` itself, so the timer never changes when jobs do.
"""

import json
import os
import platform
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

from .sessions import _mark

LAUNCHD_LABEL = "io.neurostack.run-due"
TASK_NAME = "NeuroStackRunDue"


def _binary():
    """Absolute path of the neurostack executable the timer should call."""
    return shutil.which("neurostack") or os.path.abspath(sys.argv[0])


def _run(cmd):
    """Run cmd without raising; return its error text on failure, None on success."""
    try:
        r = subprocess.run(cmd, check=False, capture_output=True, text=True)
    except OSError as exc:  # the scheduler binary itself is missing (no systemd, say)
        return str(exc)
    if r.returncode:
        return (r.stderr or r.stdout).strip() or f"{cmd[0]} exited {r.returncode}"
    return None


def _unit_dir():
    return Path.home() / ".config" / "systemd" / "user"


def _systemd_install(binary):
    unit_dir = _unit_dir()
    unit_dir.mkdir(parents=True, exist_ok=True)
    (unit_dir / "neurostack.service").write_text(
        f"""[Unit]
Description=NeuroStack scheduled jobs (neurostack run-due)

[Service]
Type=oneshot
ExecStart={binary} run-due
Environment=PATH=%h/.local/bin:/usr/local/bin:/usr/bin
"""
    )
    timer = unit_dir / "neurostack.timer"
    timer.write_text(
        """[Unit]
Description=Run neurostack run-due every minute

[Timer]
OnCalendar=*-*-* *:*:00
Persistent=true
AccuracySec=15s

[Install]
WantedBy=timers.target
"""
    )
    return timer, (
        _run(["systemctl", "--user", "daemon-reload"])
        or _run(["systemctl", "--user", "enable", "--now", "neurostack.timer"])
    )


def _systemd_remove():
    unit_dir = _unit_dir()
    err = _run(["systemctl", "--user", "disable", "--now", "neurostack.timer"])
    for name in ("neurostack.service", "neurostack.timer"):
        (unit_dir / name).unlink(missing_ok=True)
    return unit_dir / "neurostack.timer", err or _run(["systemctl", "--user", "daemon-reload"])


def _systemd_active():
    return _run(["systemctl", "--user", "is-active", "neurostack.timer"]) is None


def _launchd_plist():
    return Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"


def _launchd_install(binary):
    plist = _launchd_plist()
    plist.parent.mkdir(parents=True, exist_ok=True)
    plist.write_bytes(plistlib.dumps({
        "Label": LAUNCHD_LABEL,
        "ProgramArguments": [binary, "run-due"],
        "StartInterval": 60,
    }))
    domain = f"gui/{os.getuid()}"
    # A loaded older copy makes bootstrap fail, so unload it first.
    _run(["launchctl", "bootout", f"{domain}/{LAUNCHD_LABEL}"])
    return plist, _run(["launchctl", "bootstrap", domain, str(plist)])


def _launchd_remove():
    plist = _launchd_plist()
    err = _run(["launchctl", "bootout", f"gui/{os.getuid()}/{LAUNCHD_LABEL}"])
    plist.unlink(missing_ok=True)
    return plist, err


def _launchd_active():
    return _run(["launchctl", "print", f"gui/{os.getuid()}/{LAUNCHD_LABEL}"]) is None


def _schtasks_install(binary):
    return TASK_NAME, _run([
        "schtasks", "/Create", "/SC", "MINUTE", "/MO", "1", "/TN", TASK_NAME,
        "/TR", f'"{binary}" run-due', "/F",
    ])


def _schtasks_remove():
    return TASK_NAME, _run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"])


def _schtasks_active():
    return _run(["schtasks", "/Query", "/TN", TASK_NAME]) is None


_BACKENDS = {
    "Linux": ("systemd", _systemd_install, _systemd_remove, _systemd_active),
    "Darwin": ("launchd", _launchd_install, _launchd_remove, _launchd_active),
    "Windows": ("schtasks", _schtasks_install, _schtasks_remove, _schtasks_active),
}


def cmd_schedule(args):
    """Install, remove, or report the timer that runs `neurostack run-due`."""
    subcmd = getattr(args, "schedule_command", None)
    as_json = getattr(args, "json", False)
    if subcmd not in ("install", "remove", "status"):
        print("Usage: neurostack schedule {install,remove,status} [--json]")
        return

    system = platform.system()
    if system not in _BACKENDS:
        print(f"  \033[31m\u2717\033[0m No scheduler backend for {system}")
        sys.exit(1)
    backend, install, remove, active = _BACKENDS[system]

    if subcmd == "status":
        on = active()
        if as_json:
            print(json.dumps({"backend": backend, "active": on}))
        else:
            print(f"  run-due timer ({backend}): {_mark(on, 'active', 'inactive')}")
        return

    path, err = install(_binary()) if subcmd == "install" else remove()
    done = "installed" if subcmd == "install" else "removed"
    if as_json:
        out = {done: err is None, "backend": backend, "path": str(path)}
        if err:
            out["error"] = err
        print(json.dumps(out))
    elif err:
        print(f"  \033[31m\u2717\033[0m schedule {subcmd} failed ({backend}): {err}")
    else:
        print(f"  \033[32m\u2713\033[0m {done.capitalize()} the run-due timer ({backend})")
        print(f"    Path: {path}")
    if err:
        sys.exit(1)
