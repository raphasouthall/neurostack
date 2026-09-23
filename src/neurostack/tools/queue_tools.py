# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Checkpoint and harvest queue tools (issue #232).

A client on another machine queues a checkpoint or a harvest by uploading the
session transcript with the job. The server's workers claim the job and run
the checkpoint against that text, so the queue no longer needs the
transcript files on the host that drains it. The tools wrap `queue.py`, so
dedupe, the daily caps and stale reaping stay in one place.
"""

from __future__ import annotations

import base64
import zlib
from typing import Any

from .registry import ToolAnnotationHints as Hints
from .registry import registry

_WRITE = Hints(read_only=False, destructive=False, idempotent=False, open_world=False)


def _conn():
    from ..schema import DB_PATH, get_db
    return get_db(DB_PATH)


def _limits(queue: str):
    from ..queue import LIMITS
    if queue not in LIMITS:
        raise ValueError(f"unknown queue {queue!r}; expected one of {sorted(LIMITS)}")
    return LIMITS[queue]


def _inflate(blob: str) -> str:
    """Decode a gzip+base64 transcript, refusing more than the cap when inflated."""
    from ..queue import TRANSCRIPT_CAP_BYTES

    inflater = zlib.decompressobj(wbits=31)  # 31 = gzip framing
    raw = inflater.decompress(base64.b64decode(blob, validate=True), TRANSCRIPT_CAP_BYTES + 1)
    if len(raw) > TRANSCRIPT_CAP_BYTES:
        raise ValueError(f"transcript is over the {TRANSCRIPT_CAP_BYTES} byte cap")
    return raw.decode("utf-8", errors="replace")


@registry.tool(tags=["queue"], annotations=_WRITE)
def queue_add(queue: str, key: str, payload: dict[str, Any] | None = None,
              transcript_gz_b64: str | None = None) -> dict[str, Any]:
    """Queue a checkpoint or harvest job with the transcript it runs on.

    Idempotent per key while a job for that key is queued or running: a
    repeat returns `duplicate: true` and changes nothing. The checkpoint queue
    refuses past its daily cap (`ok: false`, `reason`).

    Args:
        queue: "checkpoint" or "harvest"
        key: Dedupe key; the session id for a checkpoint, path@mtime for a harvest
        payload: Job fields the worker reads (session, harness, format, path, provider)
        transcript_gz_b64: The session transcript, gzip-compressed then base64-encoded,
            at most 10 MB once decompressed
    """
    from ..queue import QueueLimits, add

    limits = _limits(queue)
    text = _inflate(transcript_gz_b64) if transcript_gz_b64 else None
    # Harvest adds were never capped; its daily cap applies when a worker claims.
    return add(_conn(), queue, key, payload,
               limits if queue == "checkpoint" else QueueLimits(), text)


@registry.tool(tags=["queue"], annotations=_WRITE)
def queue_claim(queue: str) -> dict[str, Any]:
    """Take the freshest queued job, transcript included, or say why the queue waits.

    Reaps runs whose worker went stale first. At most one job per queue runs at
    a time, and the daily cap counts jobs finished since local midnight.

    Args:
        queue: "checkpoint" or "harvest"
    """
    from ..queue import claim

    return claim(_conn(), queue, _limits(queue))


@registry.tool(tags=["queue"], annotations=_WRITE)
def queue_finish(job_id: int, ok: bool, saved: int = 0, output: str = "") -> dict[str, Any]:
    """Record how a claimed job ended and drop its transcript.

    Args:
        job_id: The job_id queue_claim returned
        ok: True marks the job done, False marks it failed
        saved: Memories the run saved
        output: One line on the outcome, kept to 2000 characters
    """
    from ..queue import finish

    return finish(_conn(), job_id, ok, saved=saved, output=output)
