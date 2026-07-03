# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Implicit-feedback loop for ranking (issue #66).

Auto-generated labels (``autolabel``) reflect content, not behaviour, so they
cannot judge usage signals like hotness. This closes that gap: capture which
surfaced note a search actually led to being used, and turn those events into
labels the tuner learns from — with hotness *unfrozen*, because the labels now
reflect real usage.

Flow:

1. **log** — a search records ``(query, shown_paths)`` to ``search_log``.
2. **attribute** — when a surfaced note is then deliberately used
   (``vault_record_usage`` / ``vault_read_file``) within a window, that use is
   attributed back to the most recent search that surfaced it, writing a
   ``search_feedback`` event with the note's rank at search time.
3. **harvest** — :func:`feedback_labels` aggregates events into an ``EvalQuery``
   set for the existing eval / tune harness.

Capture (steps 1-2) is opt-in (``feedback_enabled``, default off) and every
capture call swallows its own errors — feedback must never disrupt search. The
signal is position-biased (top results get used more just for being on top); the
tuning framing absorbs the worst of it, since a use of an already-top result
gives the ranker no gradient, but treat any tuned weight as a candidate, not a
commit — the same #66 gate applies.
"""
from __future__ import annotations

import json
import logging

from .eval import EvalQuery

log = logging.getLogger("neurostack")


# ── capture (opt-in, on the hot path — must never raise) ───────────────────


def log_search(conn, query: str, shown_paths: list[str], retention: int = 5000) -> None:
    """Record what a search surfaced, for later attribution. Non-blocking."""
    if not query or not shown_paths:
        return
    try:
        cur = conn.execute(
            "INSERT INTO search_log (query, shown_paths) VALUES (?, ?)",
            (query, json.dumps(shown_paths)),
        )
        # Amortised pruning: keep the newest `retention` rows.
        if retention and cur.lastrowid and cur.lastrowid % 200 == 0:
            conn.execute(
                "DELETE FROM search_log WHERE search_id NOT IN "
                "(SELECT search_id FROM search_log ORDER BY search_id DESC LIMIT ?)",
                (retention,),
            )
        conn.commit()
    except Exception:
        pass  # feedback capture must never disrupt search


def attribute_use(conn, used_paths: list[str], window_seconds: float = 1800.0) -> int:
    """Attribute a deliberate use of one or more notes back to the recent search
    that surfaced them, writing feedback events. Returns the count written.

    Non-blocking. For each used path, links to the single most recent search
    within ``window_seconds`` whose result set contained it.
    """
    if not used_paths:
        return 0
    try:
        rows = conn.execute(
            "SELECT query, shown_paths FROM search_log "
            "WHERE searched_at >= datetime('now', ?) "
            "ORDER BY searched_at DESC, search_id DESC",
            (f"-{int(window_seconds)} seconds",),
        ).fetchall()
    except Exception:
        return 0

    recent = []
    for r in rows:
        try:
            recent.append((r[0], json.loads(r[1])))
        except (json.JSONDecodeError, TypeError):
            continue

    written = 0
    for path in dict.fromkeys(used_paths):  # dedup, preserve order
        for query, shown in recent:
            if path in shown:
                rank = shown.index(path) + 1
                try:
                    conn.execute(
                        "INSERT INTO search_feedback "
                        "(query, chosen_path, shown_paths, rank) VALUES (?, ?, ?, ?)",
                        (query, path, json.dumps(shown), rank),
                    )
                    written += 1
                except Exception:
                    pass
                break  # only the most recent surfacing search
    if written:
        try:
            conn.commit()
        except Exception:
            pass
    return written


# ── harvest (called from CLI — may raise) ──────────────────────────────────


def feedback_labels(conn, *, min_count: int = 1, max_age_days: float | None = None):
    """Aggregate feedback events into an ``EvalQuery`` label set.

    One label per distinct query; its targets are the notes chosen for that query
    at least ``min_count`` times. ``max_age_days`` restricts to recent feedback.
    """
    where = ""
    params: list = []
    if max_age_days is not None:
        where = "WHERE created_at >= datetime('now', ?)"
        params.append(f"-{float(max_age_days)} days")

    rows = conn.execute(
        f"SELECT query, chosen_path, COUNT(*) AS c FROM search_feedback {where} "
        f"GROUP BY query, chosen_path",
        params,
    ).fetchall()

    by_query: dict[str, list[str]] = {}
    for r in rows:
        if r[2] >= min_count:
            by_query.setdefault(r[0], []).append(r[1])

    return [
        EvalQuery(query=q, targets=targets, category="feedback")
        for q, targets in by_query.items()
        if targets
    ]


def feedback_stats(conn) -> dict:
    """Summary of accumulated feedback — volume and rank distribution."""
    searches = conn.execute("SELECT COUNT(*) FROM search_log").fetchone()[0]
    events = conn.execute("SELECT COUNT(*) FROM search_feedback").fetchone()[0]
    distinct_q = conn.execute(
        "SELECT COUNT(DISTINCT query) FROM search_feedback"
    ).fetchone()[0]
    distinct_notes = conn.execute(
        "SELECT COUNT(DISTINCT chosen_path) FROM search_feedback"
    ).fetchone()[0]
    avg_rank = conn.execute(
        "SELECT AVG(rank) FROM search_feedback WHERE rank IS NOT NULL"
    ).fetchone()[0]
    # How many chosen notes were NOT already rank 1 — the informative feedback.
    below_top = conn.execute(
        "SELECT COUNT(*) FROM search_feedback WHERE rank IS NOT NULL AND rank > 1"
    ).fetchone()[0]
    return {
        "searches_logged": searches,
        "feedback_events": events,
        "distinct_queries": distinct_q,
        "distinct_chosen_notes": distinct_notes,
        "avg_chosen_rank": round(avg_rank, 2) if avg_rank is not None else None,
        "informative_events": below_top,  # chosen note was not already top-ranked
    }
