# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Client-side MCP transport for harness hooks (issue #141).

A hook runs on the machine the agent runs on; the server may live elsewhere.
This module is the only place that knows how to reach it: read
``~/.config/neurostack/client.toml``, speak MCP streamable HTTP, and fail open.
``call`` never raises and never blocks longer than the configured budget — a
hook that cannot reach the server must not stall or block the agent.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from .config import _config_dir

DEFAULT_URL = "http://localhost:8001/mcp"
PROTOCOL_VERSION = "2025-06-18"
CLIENT_NAME = "neurostack-hook"
_MIN_REQUEST_TIMEOUT = 0.05


@dataclass
class ClientConfig:
    """Where the hook sends its calls, and how long it may wait."""

    url: str = DEFAULT_URL
    fallback_url: str | None = None
    token: str | None = None
    timeout_s: float = 5.0
    # session-end posts a whole transcript and the server harvests it inline;
    # that is minutes of work, so it gets its own budget instead of the
    # interactive one (which exists to keep tool calls responsive).
    harvest_timeout_s: float = 600.0
    # `checkpoint --run` pipes the prompt through this shell command and saves
    # what comes back. Empty means the harness model answers the prompt itself.
    checkpoint_command: str | None = None
    checkpoint_timeout_s: float = 300.0
    workspace_map: dict[str, str] = field(default_factory=dict)
    # Where to POST session-start/checkpoint outcomes so a board can show
    # agent activity next to the server-side jobs (issue #165). None means
    # no webhook: `post_event` is a no-op.
    event_url: str | None = None
    # Where to POST a checkpoint request so the server-side queue can run it
    # in turn (issue #176). None means no queue: `enqueue` fails closed
    # instead of guessing at a checkpoint the caller never asked to run.
    queue_url: str | None = None

    def urls(self) -> list[str]:
        """Primary URL, then the fallback when it is a distinct address."""
        urls = [self.url]
        if self.fallback_url and self.fallback_url != self.url:
            urls.append(self.fallback_url)
        return urls

    def workspace_for(self, path: str | None) -> str | None:
        """Map a filesystem path to a vault workspace via ``workspace_map``.

        Longest matching prefix wins. A value that is already a vault-relative
        workspace (no leading slash) passes through untouched, so a harness may
        send either its cwd or a workspace name.
        """
        if not path:
            return None
        if not path.startswith("/"):
            return path
        best: tuple[int, str] | None = None
        for prefix, workspace in self.workspace_map.items():
            expanded = os.path.expanduser(prefix).rstrip("/")
            if not expanded:
                continue
            if path == expanded or path.startswith(expanded + "/"):
                if best is None or len(expanded) > best[0]:
                    best = (len(expanded), workspace)
        return best[1] if best else None


def client_config_path() -> Path:
    """Location of the hook's client config."""
    return _config_dir() / "client.toml"


def load_client_config(path: Path | None = None) -> ClientConfig:
    """Read client.toml, then apply the ``NEUROSTACK_URL`` override.

    A missing or malformed file is not an error: the defaults point at a
    local server, which is what a single-machine install runs.
    """
    try:
        import tomllib
    except ImportError:  # Python 3.10 fallback
        import tomli as tomllib  # type: ignore[no-redef]

    cfg = ClientConfig()
    path = path or client_config_path()
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}

    if isinstance(raw.get("url"), str):
        cfg.url = raw["url"]
    if isinstance(raw.get("fallback_url"), str):
        cfg.fallback_url = raw["fallback_url"]
    if isinstance(raw.get("token"), str):
        cfg.token = raw["token"]
    if isinstance(raw.get("event_url"), str) and raw["event_url"].strip():
        cfg.event_url = raw["event_url"].strip()
    if isinstance(raw.get("queue_url"), str) and raw["queue_url"].strip():
        cfg.queue_url = raw["queue_url"].strip()
    if isinstance(raw.get("checkpoint_command"), str) and raw["checkpoint_command"].strip():
        cfg.checkpoint_command = raw["checkpoint_command"].strip()
    for key in ("timeout_s", "harvest_timeout_s", "checkpoint_timeout_s"):
        value = raw.get(key)
        if isinstance(value, (int, float)) and value > 0:
            setattr(cfg, key, float(value))
    mapping = raw.get("workspace_map")
    if isinstance(mapping, dict):
        cfg.workspace_map = {
            str(k): str(v) for k, v in mapping.items() if isinstance(v, str)
        }

    env_url = os.environ.get("NEUROSTACK_URL")
    if env_url:
        cfg.url = env_url
    return cfg


def _parse_body(text: str) -> dict | None:
    """Decode an MCP reply: SSE frames (``data: {...}``) or a plain JSON body."""
    payload = ""
    for line in text.splitlines():
        if line.startswith("data:"):
            payload = line[5:].strip()
    if not payload:
        payload = text.strip()
    if not payload:
        return None
    try:
        parsed = json.loads(payload)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _result_text(reply: dict | None) -> str | None:
    """Join the text blocks of a ``tools/call`` result."""
    result = (reply or {}).get("result")
    if not isinstance(result, dict):
        return None
    content = result.get("content")
    if not isinstance(content, list):
        return None
    parts = [
        c["text"] for c in content
        if isinstance(c, dict) and c.get("type") == "text" and isinstance(c.get("text"), str)
    ]
    text = "\n".join(parts).strip()
    return text or None


class McpClient:
    """MCP tool caller with a hard wall-clock budget.

    Each ``call`` re-initializes, because a hook process is short-lived and
    there is no session worth keeping warm; the connection pool is shared, so
    a hook that fires several lookups pays for one handshake. Transport
    failures move on to ``fallback_url``; everything that goes wrong is
    recorded in ``errors`` and reported as ``None`` so callers can degrade
    instead of crashing.
    """

    def __init__(
        self,
        config: ClientConfig,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.config = config
        self.errors: list[str] = []
        self._transport = transport
        self._http: httpx.Client | None = None

    def call(
        self,
        name: str,
        arguments: dict,
        timeout_s: float | None = None,
    ) -> str | None:
        """Call one tool and return its text, or None when it did not answer.

        The budget covers every attempt, so a dead primary plus a dead
        fallback still returns inside ``timeout_s``.
        """
        budget = timeout_s if timeout_s is not None else self.config.timeout_s
        deadline = time.monotonic() + budget
        for url in self.config.urls():
            if time.monotonic() >= deadline:
                self.errors.append(f"{url}: budget of {budget:g}s exhausted")
                break
            try:
                return self._call_once(url, name, arguments, deadline)
            except Exception as exc:  # transport, protocol, or decode failure
                self.errors.append(f"{url}: {type(exc).__name__}: {exc}")
        return None

    def call_json(
        self,
        name: str,
        arguments: dict,
        timeout_s: float | None = None,
    ) -> dict | None:
        """``call`` plus JSON decoding — tools return JSON as their text block."""
        text = self.call(name, arguments, timeout_s=timeout_s)
        if text is None:
            return None
        try:
            parsed = json.loads(text)
        except ValueError:
            self.errors.append(f"{name}: reply was not JSON")
            return None
        return parsed if isinstance(parsed, dict) else None

    def _headers(self) -> dict[str, str]:
        headers = {
            "content-type": "application/json",
            "accept": "application/json, text/event-stream",
        }
        if self.config.token:
            headers["authorization"] = f"Bearer {self.config.token}"
        return headers

    def _client(self) -> httpx.Client:
        if self._http is None:
            self._http = httpx.Client(transport=self._transport, headers=self._headers())
        return self._http

    def close(self) -> None:
        if self._http is not None:
            self._http.close()
            self._http = None

    def _call_once(self, url: str, name: str, arguments: dict, deadline: float) -> str | None:
        http = self._client()
        sid, init = self._rpc(
            http, url, "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": CLIENT_NAME, "version": "1"},
            },
            deadline, rpc_id=1,
        )
        if not sid and not (init or {}).get("result"):
            raise RuntimeError("initialize returned no session and no result")
        self._rpc(http, url, "notifications/initialized", {}, deadline, sid=sid)
        _, reply = self._rpc(
            http, url, "tools/call",
            {"name": name, "arguments": arguments},
            deadline, sid=sid, rpc_id=2,
        )
        if reply and reply.get("error"):
            self.errors.append(f"{name}: {reply['error']}")
            return None
        return _result_text(reply)

    def _rpc(
        self,
        http: httpx.Client,
        url: str,
        method: str,
        params: dict,
        deadline: float,
        sid: str | None = None,
        rpc_id: int | None = None,
    ) -> tuple[str | None, dict | None]:
        body: dict = {"jsonrpc": "2.0", "method": method, "params": params}
        if rpc_id is not None:
            body["id"] = rpc_id
        headers = {"mcp-session-id": sid} if sid else None
        remaining = max(_MIN_REQUEST_TIMEOUT, deadline - time.monotonic())
        response = http.post(url, json=body, headers=headers, timeout=remaining)
        new_sid = response.headers.get("mcp-session-id") or sid
        if rpc_id is None:
            return new_sid, None
        return new_sid, _parse_body(response.text)
