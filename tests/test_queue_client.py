# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Tests for the checkpoint queue client (issue #193).

`enqueue` hands a `/save` to the request webhook. That webhook enqueues over
SSH, so a healthy reply takes about two seconds; an earlier two-second cap cut
every request off just before the reply landed and `/save` reported the queue
as unreachable. `urlopen` is monkeypatched so the timeout actually handed to
the socket is visible without waiting on a real one.
"""

import json
import socket

import pytest

import neurostack.cli.queue as queue_mod
from neurostack.cli.queue import enqueue
from neurostack.client import ClientConfig


class _FakeResponse:
    def __init__(self, payload: bytes):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._payload


def _capture(monkeypatch, payload: dict | None = None, raises: Exception | None = None):
    """Patch `urlopen`, recording the timeout each call was given."""
    timeouts: list[float] = []
    body = json.dumps(payload if payload is not None else {"ok": True, "position": 1})

    def _fake_urlopen(request, timeout=None):
        timeouts.append(timeout)
        if raises is not None:
            raise raises
        return _FakeResponse(body.encode("utf-8"))

    monkeypatch.setattr(queue_mod.urllib.request, "urlopen", _fake_urlopen)
    return timeouts


def _cfg(**kwargs) -> ClientConfig:
    return ClientConfig(queue_url="http://queue.test/webhook/checkpoint-request", **kwargs)


def test_a_reply_slower_than_two_seconds_still_queues(monkeypatch):
    """The webhook's SSH hop answers in about two seconds; that must not fail."""
    timeouts = _capture(monkeypatch)
    code, line = enqueue(_cfg(timeout_s=30.0), "session-1", "omp", None)
    assert (code, line) == (0, "neurostack: checkpoint queued (position 1)")
    assert timeouts == [10.0]


def test_a_short_configured_timeout_still_wins(monkeypatch):
    """The cap is a ceiling, not a floor: a tighter `timeout_s` is respected."""
    timeouts = _capture(monkeypatch)
    enqueue(_cfg(timeout_s=1.5), "session-2", "omp", None)
    assert timeouts == [1.5]


def test_a_wedged_queue_reports_unreachable(monkeypatch):
    """A timeout is still a failure, so `/save` never hangs on a dead queue."""
    _capture(monkeypatch, raises=socket.timeout("timed out"))
    code, line = enqueue(_cfg(timeout_s=30.0), "session-3", "omp", None)
    assert code == 1
    assert line.startswith("neurostack: checkpoint queue unreachable:")


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"ok": True, "duplicate": True}, "neurostack: checkpoint already queued"),
        ({"ok": True}, "neurostack: checkpoint queued"),
    ],
)
def test_reply_shapes_that_mean_the_request_landed(monkeypatch, payload, expected):
    _capture(monkeypatch, payload=payload)
    assert enqueue(_cfg(timeout_s=30.0), "session-4", "omp", None) == (0, expected)
