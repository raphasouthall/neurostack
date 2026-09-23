# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""A failed job shows up on the desktop when no notify_command is set (issue #237)."""

from types import SimpleNamespace

import pytest

from neurostack import jobs
from neurostack.jobs import Daily, Job, run_due

# conftest swaps jobs._desktop_notify out for every test; keep the real one here.
_desktop_notify = jobs._desktop_notify


@pytest.fixture
def popen(monkeypatch):
    """Record every notification command instead of running it."""
    seen = []

    def fake(cmd, **kwargs):
        seen.append((cmd, kwargs["env"]))

    monkeypatch.setattr(jobs.subprocess, "Popen", fake)
    return seen


@pytest.mark.parametrize("platform, head", [
    ("linux", ["notify-send", "NeuroStack", "decay failed: boom"]),
    ("darwin", ["osascript", "-e", "on run argv"]),
    ("win32", ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command"]),
])
def test_each_os_gets_its_own_tool(monkeypatch, popen, platform, head):
    monkeypatch.setattr(jobs.sys, "platform", platform)
    _desktop_notify("NeuroStack", "decay failed: boom")

    (cmd, env), = popen
    assert cmd[:len(head)] == head
    if platform == "darwin":
        assert cmd[-2:] == ["NeuroStack", "decay failed: boom"]
    if platform == "win32":
        assert (env["NS_TITLE"], env["NS_BODY"]) == ("NeuroStack", "decay failed: boom")


def test_a_missing_tool_is_skipped_silently(monkeypatch):
    def missing(cmd, **kwargs):
        raise FileNotFoundError(cmd[0])

    monkeypatch.setattr(jobs.subprocess, "Popen", missing)
    _desktop_notify("NeuroStack", "x")  # must not raise


def _boom(cfg, conn):
    raise RuntimeError("disk on fire")


def test_a_failed_run_notifies_the_desktop_only_without_notify_command(tmp_path, monkeypatch):
    sent = []
    monkeypatch.setattr(jobs, "_desktop_notify", lambda title, body: sent.append(body))
    monkeypatch.setattr(jobs, "JOBS", {
        "boom": Job("boom", Daily("03:00"), _boom, lambda cfg: None, ""),
    })
    cfg = SimpleNamespace(jobs=None, db_dir=tmp_path, db_path=tmp_path / "neurostack.db",
                          notify_command="")

    run_due(cfg, force=True)
    assert sent == ["boom failed: disk on fire"]

    cfg.notify_command = "true"
    run_due(cfg, force=True)
    assert len(sent) == 1
