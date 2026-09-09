# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Event webhook — so a workflow board can show agent activity (issue #165).

`neurostack hook` already tracks LEARN health locally (`learn_status.py`).
This module mirrors each outcome to `client.toml`'s `event_url`, if one is
configured, so an external board (n8n or otherwise) can show the same
session-start / checkpoint activity next to server-side jobs. Best effort,
always: a webhook that is down, slow, or misconfigured must never affect the
hook's own verdict, so every failure is swallowed.
"""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from datetime import datetime

from ..client import ClientConfig

_MAX_TIMEOUT_S = 2.0


def post_event(cfg: ClientConfig, event: str, result: str, session: str, harness: str,
               saved: int = 0, error: str | None = None,
               workspace: str | None = None) -> None:
    """POST one outcome to `cfg.event_url`. Never raises, never blocks long.

    `event` is `session-start` or `checkpoint`; `result` is `ok`, `saved`,
    `busy`, or `failed`. A missing `event_url` means no webhook is
    configured, so this returns immediately without touching the network.
    """
    if not cfg.event_url:
        return
    body = {
        "event": event,
        "result": result,
        "session": session,
        "harness": harness,
        "saved": max(saved, 0),
        "error": error,
        "workspace": workspace,
        "host": socket.gethostname(),
        "at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    request = urllib.request.Request(
        cfg.event_url,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=min(cfg.timeout_s, _MAX_TIMEOUT_S)) as resp:
            resp.read()
    except (urllib.error.URLError, OSError, ValueError):
        pass
