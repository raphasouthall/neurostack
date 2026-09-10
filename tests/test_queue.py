# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Tests for the checkpoint queue client (issue #176).

`enqueue` never runs a checkpoint — it POSTs one request and relays what the
queue answers. `urlopen` is monkeypatched instead of touching the network:
deterministic, and it proves the request shape and every reply the queue's
contract defines (queued, duplicate, cap reached, unreachable) without a
live receiver.
"""

import io
import json
import urllib.error

import pytest

import neurostack.cli.queue as queue_mod
from neurostack.cli.queue import enqueue
from neurostack.client import ClientConfig


def _cfg(**kwargs):
    return ClientConfig(queue_url="http://queue.test/webhook/checkpoint-request", **kwargs)


def _body(request) -> dict:
    return json.loads(request.data.decode("utf-8"))


class _FakeResponse:
    def __init__(self, body: dict):
        self._body = json.dumps(body).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._body


def _capture(monkeypatch, body: dict):
    """Patch `urlopen` to record the request and answer with `body`."""
    calls = []

    def _fake_urlopen(request, timeout=None):
        calls.append((request, timeout))
        return _FakeResponse(body)

    monkeypatch.setattr(queue_mod.urllib.request, "urlopen", _fake_urlopen)
    return calls


def _raise(monkeypatch, exc: Exception):
    def _fake_urlopen(request, timeout=None):
        raise exc

    monkeypatch.setattr(queue_mod.urllib.request, "urlopen", _fake_urlopen)


def _http_error(code: int, body: dict) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "http://queue.test/webhook/checkpoint-request", code, "error", {},
        io.BytesIO(json.dumps(body).encode("utf-8")),
    )


def test_no_call_when_queue_url_unset(monkeypatch):
    calls = _capture(monkeypatch, {"ok": True, "position": 1})
    code, line = enqueue(ClientConfig(), "s1", "omp", None)
    assert calls == []
    assert code == 1
    assert "no queue_url" in line


def test_queued_body_shape(monkeypatch):
    calls = _capture(monkeypatch, {"ok": True, "position": 3})
    code, line = enqueue(_cfg(), "s1", "omp", "home/projects/x")
    assert code == 0
    assert "queued (position 3)" in line
    assert len(calls) == 1
    request, timeout = calls[0]
    assert request.full_url == "http://queue.test/webhook/checkpoint-request"
    assert request.get_header("Content-type") == "application/json"
    assert timeout == 2.0
    body = _body(request)
    assert body == {
        "session": "s1", "harness": "omp", "workspace": "home/projects/x",
        "host": body["host"], "requested_at": body["requested_at"],
    }
    assert body["host"]
    assert body["requested_at"][-6] in "+-" or body["requested_at"].endswith("Z")


def test_timeout_never_exceeds_two_seconds(monkeypatch):
    calls = _capture(monkeypatch, {"ok": True, "position": 1})
    enqueue(_cfg(timeout_s=30.0), "s1", "cli", None)
    assert calls[0][1] == 2.0


def test_duplicate_is_still_a_success(monkeypatch):
    _capture(monkeypatch, {"ok": True, "position": 0, "duplicate": True})
    code, line = enqueue(_cfg(), "s1", "omp", None)
    assert code == 0
    assert "already queued" in line


def test_daily_cap_reached_is_exit_one(monkeypatch):
    _raise(monkeypatch, _http_error(429, {"ok": False, "reason": "daily cap reached"}))
    code, line = enqueue(_cfg(), "s1", "omp", None)
    assert code == 1
    assert "daily cap reached" in line


def test_daily_cap_with_no_reason_still_says_cap(monkeypatch):
    _raise(monkeypatch, _http_error(429, {"ok": False}))
    code, line = enqueue(_cfg(), "s1", "omp", None)
    assert code == 1
    assert "cap" in line


def test_unreachable_on_connection_failure(monkeypatch):
    _raise(monkeypatch, OSError("connection refused"))
    code, line = enqueue(_cfg(), "s1", "omp", None)
    assert code == 1
    assert "unreachable" in line


def test_unreachable_on_an_unexpected_status(monkeypatch):
    _raise(monkeypatch, _http_error(500, {}))
    code, line = enqueue(_cfg(), "s1", "omp", None)
    assert code == 1
    assert "unreachable" in line


def test_unreachable_on_a_reply_outside_the_contract(monkeypatch):
    _capture(monkeypatch, {"ok": True})  # no position, no duplicate — still queued
    code, line = enqueue(_cfg(), "s1", "omp", None)
    assert code == 0
    assert "queued" in line

    _capture(monkeypatch, {"unexpected": "shape"})
    code, line = enqueue(_cfg(), "s1", "omp", None)
    assert code == 1
    assert "unreachable" in line


@pytest.mark.parametrize("bad_json", [b"not json", b"[]", b'"a string"'])
def test_unreachable_on_malformed_json(monkeypatch, bad_json):
    class _BadResponse:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return bad_json

    def _fake_urlopen(request, timeout=None):
        return _BadResponse()

    monkeypatch.setattr(queue_mod.urllib.request, "urlopen", _fake_urlopen)
    code, line = enqueue(_cfg(), "s1", "omp", None)
    assert code == 1
    assert "unreachable" in line
