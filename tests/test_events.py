# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Tests for the event webhook (issue #165).

`post_event` mirrors LEARN outcomes to `client.toml`'s `event_url` so a
workflow board can show agent activity. `urlopen` is monkeypatched instead of
opening a real socket: deterministic, and it proves the request shape without
depending on a live receiver.
"""

import json

import pytest

import neurostack.cli.events as events_mod
from neurostack.cli.events import post_event
from neurostack.cli.hook import run_checkpoint_save, run_event
from neurostack.cli.learn_status import load_learn_status
from neurostack.client import ClientConfig

REPLY = json.dumps([{"content": "one memory worth keeping", "entity_type": "observation"}])


@pytest.fixture(autouse=True)
def _throwaway_home(isolated_home):
    """Every test here writes learn-status and session state into a throwaway HOME."""
    return isolated_home


def _cfg(server, **kwargs):
    return ClientConfig(url=server.url, timeout_s=5.0, **kwargs)


class _FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return b'{"ok": true}'


def _capture(monkeypatch):
    """Patch `urlopen` to record the request instead of touching the network."""
    calls = []

    def _fake_urlopen(request, timeout=None):
        calls.append(request)
        return _FakeResponse()

    monkeypatch.setattr(events_mod.urllib.request, "urlopen", _fake_urlopen)
    return calls


def _body(request) -> dict:
    return json.loads(request.data.decode("utf-8"))


def test_no_call_when_event_url_unset(monkeypatch):
    calls = _capture(monkeypatch)
    post_event(ClientConfig(), "session-start", "ok", "s1", "cli")
    assert calls == []


def test_session_start_body_shape(monkeypatch):
    calls = _capture(monkeypatch)
    cfg = ClientConfig(event_url="http://events.test/webhook")
    post_event(cfg, "session-start", "ok", "s1", "omp", workspace="home/projects/x")
    assert len(calls) == 1
    request = calls[0]
    assert request.full_url == "http://events.test/webhook"
    assert request.get_header("Content-type") == "application/json"
    body = _body(request)
    assert body == {
        "event": "session-start", "result": "ok", "session": "s1", "harness": "omp",
        "saved": 0, "error": None, "workspace": "home/projects/x",
        "host": body["host"], "at": body["at"],
    }
    assert body["host"]
    # ISO 8601 with an explicit offset, not a naive timestamp.
    assert body["at"][-6] in "+-" or body["at"].endswith("Z")


def test_checkpoint_saved_body(monkeypatch):
    calls = _capture(monkeypatch)
    cfg = ClientConfig(event_url="http://events.test/webhook")
    post_event(cfg, "checkpoint", "saved", "s2", "claude", saved=3)
    body = _body(calls[0])
    assert body["event"] == "checkpoint"
    assert body["result"] == "saved"
    assert body["saved"] == 3
    assert body["error"] is None


def test_checkpoint_busy_body(monkeypatch):
    calls = _capture(monkeypatch)
    cfg = ClientConfig(event_url="http://events.test/webhook")
    post_event(cfg, "checkpoint", "busy", "s3", "cli")
    body = _body(calls[0])
    assert body["result"] == "busy"
    assert body["saved"] == 0
    assert body["error"] is None


def test_checkpoint_failed_body(monkeypatch):
    calls = _capture(monkeypatch)
    cfg = ClientConfig(event_url="http://events.test/webhook")
    post_event(cfg, "checkpoint", "failed", "s4", "cli", error="server down")
    body = _body(calls[0])
    assert body["result"] == "failed"
    assert body["error"] == "server down"


def test_run_event_session_start_posts_ok(monkeypatch, server):
    calls = _capture(monkeypatch)
    server.replies["session_brief"] = {"brief": "hello"}
    cfg = _cfg(server, event_url="http://events.test/webhook")
    run_event("session-start", {"session": "s5", "harness": "omp"}, cfg=cfg)
    assert len(calls) == 1
    body = _body(calls[0])
    assert body["event"] == "session-start"
    assert body["result"] == "ok"
    assert body["session"] == "s5"
    assert body["harness"] == "omp"


def test_run_event_session_start_defaults_harness_to_cli(monkeypatch, server):
    calls = _capture(monkeypatch)
    server.replies["session_brief"] = {"brief": "hello"}
    cfg = _cfg(server, event_url="http://events.test/webhook")
    run_event("session-start", {"session": "s6"}, cfg=cfg)
    assert _body(calls[0])["harness"] == "cli"


def test_checkpoint_save_posts_saved(monkeypatch, server):
    calls = _capture(monkeypatch)
    server.replies["vault_remember"] = {"memory_id": 1}
    cfg = _cfg(server, event_url="http://events.test/webhook", harvest_timeout_s=5.0)
    run_checkpoint_save(REPLY, "ck-saved", "cli", cfg=cfg)
    assert len(calls) == 1
    body = _body(calls[0])
    assert body["event"] == "checkpoint"
    assert body["result"] == "saved"
    assert body["saved"] == 1


def test_raising_urlopen_never_touches_the_verdict(monkeypatch, server):
    """A dead webhook must not change the checkpoint's own outcome (issue #165)."""
    server.replies["vault_remember"] = {"memory_id": 1}

    def _boom(request, timeout=None):
        raise OSError("connection refused")

    monkeypatch.setattr(events_mod.urllib.request, "urlopen", _boom)
    cfg = _cfg(server, event_url="http://events.test/webhook", harvest_timeout_s=5.0)
    verdict = run_checkpoint_save(REPLY, "ck-dead-webhook", "cli", cfg=cfg)
    assert "saved 1 of 1" in verdict.text
    assert load_learn_status()["last_result"] == "saved"
    assert load_learn_status()["last_error"] is None
