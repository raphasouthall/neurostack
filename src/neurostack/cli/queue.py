# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Checkpoint queue client (issues #176, #232).

Checkpoints used to fire on their own — a message count, a quiet timer — and
run right there on the client machine. That made them impossible to audit or
throttle: a laptop could run twenty checkpoints before lunch and nobody would
know until the model bill did. Now a checkpoint is either manual (`/save`) or
scheduled by the server's queue, which enforces a daily cap and runs one job
at a time. The server has no copy of the client's transcripts, so a job
carries its transcript: this module uploads it with the `queue_add` MCP tool.
It never runs a checkpoint itself.
"""

from __future__ import annotations

import base64
import gzip
import re
import socket
from pathlib import Path
from typing import Any

from ..client import ClientConfig, McpClient
from ..queue import TRANSCRIPT_CAP_BYTES

# A 10 MB transcript compresses to a few MB. This covers a slow link without
# letting `/save` hang on a wedged server.
_UPLOAD_TIMEOUT_S = 30.0


# The MCP server refuses request bodies over 4 MiB (mcp 2.0's default), and the
# transcript travels gzipped and base64-encoded inside one, so the encoded
# transcript must stay below this (#297).
UPLOAD_BLOB_CAP = 3_500_000


def _tail(text: str, cap: int = TRANSCRIPT_CAP_BYTES) -> str:
    """The newest whole JSONL records that fit in cap bytes."""
    kept: list[str] = []
    size = 0
    for line in reversed(text.splitlines(keepends=True)):
        size += len(line.encode("utf-8", "replace"))
        if size > cap:
            break
        kept.append(line)
    return "".join(reversed(kept))


def upload(client: McpClient, queue: str, key: str, payload: dict[str, Any], path: Path,
           source: str) -> dict[str, Any] | None:
    """Queue one job carrying the transcript at `path`.

    Returns the queue's reply, or None when no server answered (the reason is
    in `client.errors`). Raises OSError when the transcript cannot be read.
    """
    from .hook import parse_transcript

    full = path.read_text(errors="replace")
    text, cap = full, TRANSCRIPT_CAP_BYTES
    while True:
        if len(text.encode("utf-8", "replace")) > cap:
            text = _tail(text, cap)
        blob = base64.b64encode(gzip.compress(text.encode("utf-8", "replace"))).decode("ascii")
        if len(blob) <= UPLOAD_BLOB_CAP or not text:
            break
        # Shrink by the overshoot, with a margin, so a dense transcript fits in
        # a step or two rather than one record at a time.
        cap = int(len(text.encode("utf-8", "replace")) * UPLOAD_BLOB_CAP / len(blob) * 0.9)
    if text is not full:
        # Tell the worker how many messages the trim dropped, so the session's
        # saved index still points at the same message.
        dropped = len(parse_transcript(full, source)) - len(parse_transcript(text, source))
        payload = {**payload, "transcript_offset": max(dropped, 0)}
    return client.call_json(
        "queue_add",
        {"queue": queue, "key": key, "payload": payload, "transcript_gz_b64": blob},
        timeout_s=_UPLOAD_TIMEOUT_S,
    )


def enqueue(cfg: ClientConfig, session: str, harness: str, workspace: str | None,
            path: Path, source: str) -> tuple[int, str]:
    """Upload one checkpoint request with its transcript. Never runs a checkpoint.

    Returns `(exit code, one line)`. Exit 0 covers a fresh queue position and
    a duplicate of a session already queued or running — both mean the
    request landed, so a caller has nothing left to do. Exit 1 is every way
    this can fail to land: an unreadable transcript, the daily cap, or no
    server answering.
    """
    key = re.sub(r"[^A-Za-z0-9._-]", "", session)
    if not key:
        return 1, "neurostack: no session id to queue"
    payload = {"session": key, "harness": harness or "omp", "format": source,
               "workspace": workspace or "", "host": socket.gethostname()}
    client = McpClient(cfg)
    try:
        reply = upload(client, "checkpoint", key, payload, path, source)
    except OSError as exc:
        return 1, f"neurostack: transcript unreadable: {exc}"
    finally:
        client.close()
    if reply is None:
        reason = client.errors[-1] if client.errors else "no reply"
        return 1, f"neurostack: checkpoint queue unreachable: {reason}"
    if reply.get("ok") is not True:
        return 1, f"neurostack: {reply.get('reason') or 'checkpoint refused'}"
    if reply.get("duplicate"):
        return 0, "neurostack: checkpoint already queued"
    return 0, f"neurostack: checkpoint queued (position {reply.get('position')})"
