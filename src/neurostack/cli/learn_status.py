# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""LEARN health — proof that the idle checkpoint is still saving (issue #151).

The checkpoint (#143, #147) runs where nobody is watching: a timer, a Stop
hook, a slash command. When the model login expires or the server is down it
fails quietly and the only trace is a journal line. So every attempt writes
one small file, and the two places the owner already reads — the session brief
and `neurostack status` — turn that file into a single line.

Four states, in the order they are checked: the last attempt failed
(`FAILING`), nothing ever ran (`never ran`), the last success is over 48 hours
old (`stale`), or all is well (`ok`).

Never raises: a health file that cannot be read or written costs a stderr line
at worst, never a checkpoint.
"""

from __future__ import annotations

import fcntl
import json
import os
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

# A checkpoint fires on an idle session, so a working setup writes most days.
# Two days of silence is a laptop that was shut, three is a broken hook.
STALE_AFTER_S = 48 * 3600
# The line is read at a glance; a stack trace would push the brief off screen.
ERROR_CHARS = 200


def cache_dir() -> Path:
    """NeuroStack's client-side cache root (`~/.cache/neurostack`)."""
    cache = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(cache) / "neurostack"


def learn_status_path() -> Path:
    """The health file every checkpoint attempt rewrites."""
    return cache_dir() / "learn-status.json"


@contextmanager
def _status_lock():
    path = cache_dir() / "learn-status.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def load_learn_status() -> dict:
    """The health file, or an empty dict when it is absent or unreadable."""
    try:
        raw = json.loads(learn_status_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def record_ok(session: str, harness: str, saved: int) -> dict:
    """Record a checkpoint that reached the server.

    Success clears the error, so `last_error` set means the LAST attempt
    failed — that is what the `FAILING` state reads.
    """
    now = _now()
    with _status_lock():
        status = load_learn_status()
        status.update({
            "last_ok_at": _iso(now),
            "last_error_at": None,
            "last_error": None,
            "saved_today": _saved_today(status, now) + max(saved, 0),
            "session": session,
            "harness": harness,
            "last_attempt_at": _iso(now),
            "last_result": "saved",
        })
        _write(status)
        return status


def record_busy(session: str, harness: str) -> dict:
    """Record overlap without turning a healthy checkpoint into a failure."""
    now = _now()
    with _status_lock():
        status = load_learn_status()
        status.update({
            "last_attempt_at": _iso(now),
            "last_result": "busy",
            "saved_today": _saved_today(status, now),
            "session": session,
            "harness": harness,
        })
        status.setdefault("last_ok_at", None)
        status.setdefault("last_error_at", None)
        status.setdefault("last_error", None)
        _write(status)
        return status


def record_error(session: str, harness: str, error: str) -> dict:
    """Record a checkpoint that failed. `last_ok_at` survives untouched."""
    now = _now()
    with _status_lock():
        status = load_learn_status()
        status.update({
            "last_error_at": _iso(now),
            "last_error": _one_line(error),
            "saved_today": _saved_today(status, now),
            "session": session,
            "harness": harness,
            "last_attempt_at": _iso(now),
            "last_result": "failed",
        })
        status.setdefault("last_ok_at", None)
        _write(status)
        return status


def learn_line(status: dict | None = None, now: datetime | None = None) -> str:
    """The one-line summary that goes first in the brief and in `status`."""
    status = load_learn_status() if status is None else status
    now = now or _now()
    error = status.get("last_error")
    if isinstance(error, str) and error.strip():
        at = _parse(status.get("last_error_at"))
        return (f"LEARN: FAILING since {_stamp(at) if at else 'an unknown time'}: "
                f"{error.strip()}")
    last_ok = _parse(status.get("last_ok_at"))
    if last_ok is None:
        return "LEARN: never ran"
    if (now - last_ok).total_seconds() > STALE_AFTER_S:
        return f"LEARN: stale, no checkpoint since {_stamp(last_ok)}"
    return (f"LEARN: ok, {_saved_today(status, now)} memories today, "
            f"last {last_ok.strftime('%H:%M')}")


def warn_line(warn: dict | None) -> str:
    """Did the trigger warnings change anything? (issue #159)"""
    if warn is None:
        return "WARN: unavailable (the server predates issue #159)"
    return (f"WARN: {warn['fired']} fired, {warn['followed']} followed, "
            f"{warn['ignored']} ignored ({warn['days']}d)")


def learn_report(client=None, cfg=None) -> dict:
    """The LEARN block for `neurostack status`.

    The 7-day counts come from the server's `vault_stats`, which groups them
    in SQL. `vault_memories` returns rows and takes no date filter, so
    counting client-side would mean shipping every memory of the week over
    MCP — a server-side count is the cheap answer (issue #151). The same reply
    carries the 30-day trigger counts behind the WARN line (issue #159).
    """
    from ..client import McpClient, load_client_config
    from .hook import sessions_behind

    report = {
        "line": learn_line(),
        "by_source": {},
        "sessions_behind": sessions_behind(),
        "warn": None,
        "error": None,
    }
    client = client or McpClient(cfg or load_client_config())
    try:
        stats = client.call_json("vault_stats", {})
    finally:
        client.close()
    if stats is None:
        report["error"] = client.errors[0] if client.errors else "vault_stats did not answer"
        return report
    report["warn"] = _warn_counts(stats.get("triggers"))
    memories = stats.get("memories")
    counts = memories.get("by_source_7d") if isinstance(memories, dict) else None
    if not isinstance(counts, dict):
        report["error"] = "server returned no 7-day counts (it predates issue #151)"
        return report
    report["by_source"] = {str(k): int(v) for k, v in counts.items()
                           if isinstance(v, int) and not isinstance(v, bool)}
    return report


def _warn_counts(triggers) -> dict | None:
    """`triggers.last_30d` from vault_stats, or None when the server lacks it."""
    window = triggers.get("last_30d") if isinstance(triggers, dict) else None
    if not isinstance(window, dict):
        return None
    out = {key: _count(window.get(key))
           for key in ("fired", "followed", "ignored", "pending")}
    out["days"] = _count(window.get("days")) or 30
    return out


def _count(value) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _now() -> datetime:
    return datetime.now().astimezone()


def _iso(when: datetime) -> str:
    return when.isoformat(timespec="seconds")


def _parse(value) -> datetime | None:
    """An ISO timestamp from the file as an aware datetime, or None."""
    if not isinstance(value, str) or not value:
        return None
    try:
        # A naive stamp is local time — that is what this file has always
        # written, and `astimezone` attaches the local zone to it.
        return datetime.fromisoformat(value).astimezone()
    except ValueError:
        return None


def _stamp(when: datetime) -> str:
    return when.strftime("%Y-%m-%d %H:%M")


def _one_line(error) -> str:
    return " ".join(str(error).split())[:ERROR_CHARS]


def _saved_today(status: dict, now: datetime) -> int:
    """`saved_today`, zeroed once the date has rolled over.

    The count belongs to the date of the last success, so no second field is
    needed and yesterday's total can never be reported as today's.
    """
    count = status.get("saved_today")
    last_ok = _parse(status.get("last_ok_at"))
    if not isinstance(count, int) or isinstance(count, bool) or count < 0 or last_ok is None:
        return 0
    return count if last_ok.date() == now.date() else 0


def _write(status: dict) -> None:
    path = learn_status_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{os.getpid()}.json.tmp")
        tmp.write_text(json.dumps(status, indent=2), encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        print(f"neurostack: LEARN status not written: {exc}", file=sys.stderr)
