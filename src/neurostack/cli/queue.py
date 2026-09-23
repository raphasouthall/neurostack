# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Checkpoint queue client (issue #176).

Checkpoints used to fire on their own — a message count, a quiet timer — and
run right there on the client machine. That made them impossible to audit or
throttle: a laptop could run twenty checkpoints before lunch and nobody would
know until the model bill did. Now a checkpoint is either manual (`/save`) or
scheduled by a queue that enforces a daily cap and runs one job at a time;
this module is the one place that knows how to ask that queue for a slot. It
never runs a checkpoint itself.

With `queue_url` set the request goes to that webhook. Without it the request
lands in the local `job_queue`, which `neurostack run-due`'s checkpoint-worker
drains (issue #229).
"""

from __future__ import annotations

import json
import re
import socket
import urllib.error
import urllib.request
from datetime import datetime

from ..client import ClientConfig

# The request webhook enqueues over SSH, so a normal reply takes about two
# seconds. The cap only exists so `/save` can never hang on a wedged queue.
_MAX_TIMEOUT_S = 10.0


def _enqueue_local(session: str, harness: str, workspace: str | None) -> tuple[int, str]:
    """Add the request to the local checkpoint queue, as the n8n webhook did."""
    from ..queue import CHECKPOINT_CAP_PER_DAY, QueueLimits, add
    from ..schema import DB_PATH, get_db

    key = re.sub(r"[^A-Za-z0-9._-]", "", session)
    if not key:
        return 1, "neurostack: no session id to queue"
    payload = {"session": key, "harness": harness or "omp",
               "workspace": workspace or "", "host": socket.gethostname()}
    try:
        reply = add(get_db(DB_PATH), "checkpoint", key, payload,
                    QueueLimits(cap_per_day=CHECKPOINT_CAP_PER_DAY))
    except Exception as exc:
        return 1, f"neurostack: local checkpoint queue unavailable: {exc}"
    if not reply["ok"]:
        return 1, f"neurostack: {reply.get('reason') or 'daily cap reached'}"
    if reply.get("duplicate"):
        return 0, "neurostack: checkpoint already queued locally"
    return 0, f"neurostack: checkpoint queued locally (position {reply['position']})"


def enqueue(cfg: ClientConfig, session: str, harness: str,
           workspace: str | None) -> tuple[int, str]:
    """Hand one checkpoint request to the queue. Never runs a checkpoint.

    Returns `(exit code, one line)`. Exit 0 covers a fresh queue position and
    a duplicate of a session already queued or running — both mean the
    request landed, so a caller has nothing left to do. Exit 1 is every way
    this can fail to land: the daily cap, or the queue being unreachable (a
    connection failure, a non-2xx/429 status, or a reply outside its own
    contract). Without `queue_url` the local queue takes the request.
    """
    if not cfg.queue_url:
        return _enqueue_local(session, harness, workspace)
    body = {
        "session": session,
        "harness": harness,
        "workspace": workspace,
        "host": socket.gethostname(),
        "requested_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    request = urllib.request.Request(
        cfg.queue_url,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(
            request, timeout=min(cfg.timeout_s, _MAX_TIMEOUT_S),
        ) as response:
            reply = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            try:
                reason = json.loads(exc.read().decode("utf-8")).get("reason")
            except (ValueError, OSError, AttributeError):
                reason = None
            return 1, f"neurostack: {reason or 'daily cap reached'}"
        return 1, f"neurostack: checkpoint queue unreachable: HTTP {exc.code}"
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return 1, f"neurostack: checkpoint queue unreachable: {exc}"
    if not isinstance(reply, dict) or reply.get("ok") is not True:
        return 1, "neurostack: checkpoint queue unreachable: unexpected reply"
    if reply.get("duplicate"):
        return 0, "neurostack: checkpoint already queued"
    position = reply.get("position")
    if isinstance(position, (int, float)) and not isinstance(position, bool) and position > 0:
        return 0, f"neurostack: checkpoint queued (position {int(position)})"
    return 0, "neurostack: checkpoint queued"
