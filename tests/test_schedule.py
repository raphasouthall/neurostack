# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""`neurostack schedule` (issue #222): what each backend writes and runs."""

import json
import os
import plistlib
import subprocess
from types import SimpleNamespace

import pytest

from neurostack.cli import schedule
from neurostack.cli.sessions import cmd_hooks

BINARY = "/opt/ns/bin/neurostack"


@pytest.fixture
def host(tmp_path, monkeypatch):
    """Fake home, binary, and subprocess. Set host.system and host.fail per test."""
    state = SimpleNamespace(system="Linux", fail={}, calls=[])

    def run(cmd, **kwargs):
        state.calls.append(cmd)
        err = state.fail.get(" ".join(cmd[:4]))
        return subprocess.CompletedProcess(cmd, 1 if err else 0, "", err or "")

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(schedule.shutil, "which", lambda name: BINARY)
    monkeypatch.setattr(schedule.platform, "system", lambda: state.system)
    monkeypatch.setattr(schedule.subprocess, "run", run)
    return state


def _schedule(capsys, command):
    schedule.cmd_schedule(SimpleNamespace(schedule_command=command, json=True))
    return json.loads(capsys.readouterr().out)


def test_systemd_install_writes_a_minute_timer_and_enables_it(host, tmp_path, capsys):
    out = _schedule(capsys, "install")

    unit_dir = tmp_path / ".config" / "systemd" / "user"
    assert out == {"installed": True, "backend": "systemd",
                   "path": str(unit_dir / "neurostack.timer")}
    service = (unit_dir / "neurostack.service").read_text()
    assert f"ExecStart={BINARY} run-due\n" in service
    assert "Type=oneshot" in service
    timer = (unit_dir / "neurostack.timer").read_text()
    assert "OnCalendar=*-*-* *:*:00" in timer
    assert "Persistent=true" in timer
    assert "AccuracySec=15s" in timer
    assert host.calls == [
        ["systemctl", "--user", "daemon-reload"],
        ["systemctl", "--user", "enable", "--now", "neurostack.timer"],
    ]


def test_install_failure_reports_stderr_and_exits_nonzero(host, capsys):
    host.fail["systemctl --user enable --now"] = "Failed to connect to bus"
    with pytest.raises(SystemExit) as exc:
        schedule.cmd_schedule(SimpleNamespace(schedule_command="install", json=True))
    out = json.loads(capsys.readouterr().out)
    assert exc.value.code == 1
    assert out["installed"] is False
    assert out["error"] == "Failed to connect to bus"


def test_systemd_remove_deletes_the_units(host, tmp_path, capsys):
    _schedule(capsys, "install")
    out = _schedule(capsys, "remove")

    unit_dir = tmp_path / ".config" / "systemd" / "user"
    assert out["removed"] is True
    assert not (unit_dir / "neurostack.timer").exists()
    assert not (unit_dir / "neurostack.service").exists()
    assert ["systemctl", "--user", "disable", "--now", "neurostack.timer"] in host.calls


def test_status_follows_the_backend_return_code(host, capsys):
    assert _schedule(capsys, "status") == {"backend": "systemd", "active": True}
    host.fail["systemctl --user is-active neurostack.timer"] = "inactive"
    assert _schedule(capsys, "status") == {"backend": "systemd", "active": False}


def test_launchd_install_writes_a_60s_agent_and_reloads_it(host, tmp_path, capsys):
    host.system = "Darwin"
    out = _schedule(capsys, "install")

    plist_path = tmp_path / "Library" / "LaunchAgents" / "io.neurostack.run-due.plist"
    assert out == {"installed": True, "backend": "launchd", "path": str(plist_path)}
    plist = plistlib.loads(plist_path.read_bytes())
    assert plist["ProgramArguments"] == [BINARY, "run-due"]
    assert plist["StartInterval"] == 60
    domain = f"gui/{os.getuid()}"
    # bootout first so a re-install replaces a loaded copy instead of failing
    assert host.calls == [
        ["launchctl", "bootout", f"{domain}/io.neurostack.run-due"],
        ["launchctl", "bootstrap", domain, str(plist_path)],
    ]


def test_schtasks_install_creates_a_one_minute_task(host, capsys):
    host.system = "Windows"
    out = _schedule(capsys, "install")

    assert out == {"installed": True, "backend": "schtasks", "path": "NeuroStackRunDue"}
    assert host.calls == [[
        "schtasks", "/Create", "/SC", "MINUTE", "/MO", "1", "/TN", "NeuroStackRunDue",
        "/TR", f'"{BINARY}" run-due', "/F",
    ]]


def test_hooks_status_no_longer_reports_a_decay_timer(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr("neurostack.adapters.claude_adapter_installed", lambda: False)
    monkeypatch.setattr("neurostack.adapters.omp_extension_path", lambda: tmp_path / "x.ts")
    cmd_hooks(SimpleNamespace(hooks_command="status", harness=None, json=True))
    assert json.loads(capsys.readouterr().out) == {
        "claude_adapter": "absent", "omp_adapter": "absent"}
