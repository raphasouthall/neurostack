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
2. **attribute** — when a surfaced note is then deliberately used within a
   window, that use is attributed back to the most recent search that surfaced
   it, writing a ``search_feedback`` event with the note's rank at search time.
   Two entry points: ``vault_record_usage`` declares a use explicitly, and
   ``vault_read_file`` has one *inferred* server-side — opening a note the
   vault just surfaced is the observed act of using it (issue #103), so the
   strong signal no longer depends on the client remembering to declare it.
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
                    # One logical use = one event. A read + a record-usage for the
                    # same note (a normal RAG pairing), or re-opening it, must not
                    # each add a row — skip if this (query, path) is already
                    # recorded within the window.
                    dup = conn.execute(
                        "SELECT 1 FROM search_feedback WHERE query = ? AND "
                        "chosen_path = ? AND created_at >= datetime('now', ?) LIMIT 1",
                        (query, path, f"-{int(window_seconds)} seconds"),
                    ).fetchone()
                    if dup is None:
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


def capture_use(used_paths: list[str], conn=None) -> None:
    """Opt-in, fully-guarded entry point for the read/usage hooks: attribute a
    use only when ``feedback_enabled``. Never raises. When ``conn`` is omitted a
    DB connection is opened lazily — but only after the enabled check, so a
    default (disabled) deploy opens nothing.
    """
    try:
        from .config import get_config

        cfg = get_config()
        if not cfg.feedback_enabled:
            return
        if conn is None:
            from .schema import DB_PATH, get_db

            conn = get_db(DB_PATH)
        attribute_use(conn, used_paths, cfg.feedback_window_seconds)
    except Exception:
        pass  # feedback capture must never disrupt a read or a usage record


def record_use(note_paths: list[str], conn=None) -> int:
    """The single server path behind an EXPLICIT usage record (issue #103).

    Writes the strong 'used' tier with source 'explicit', then attributes the use
    back to the surfacing search. Shared by the ``vault_record_usage`` MCP tool
    and the ``record-usage`` CLI so both write the same rows and both attribute.

    The note_usage write is NOT feedback-gated — hotness has always counted
    declared uses regardless of ``feedback_enabled``; only the attribution
    (``capture_use``) is opt-in. Returns the number of rows recorded (deduped).
    """
    if not note_paths:
        return 0
    if conn is None:
        from .schema import DB_PATH, get_db

        conn = get_db(DB_PATH)

    # Lazy import: search imports feedback on its own hot path, so importing it
    # at module scope would close the cycle.
    from .search import _record_note_usage

    unique_paths = list(dict.fromkeys(note_paths))
    _record_note_usage(conn, unique_paths, tier="used", source="explicit")
    capture_use(unique_paths, conn=conn)
    return len(unique_paths)


def capture_read(path: str, conn=None) -> None:
    """Opt-in, fully-guarded read hook: infer a deliberate use from a read of a
    note the vault recently surfaced (issue #103). Never raises.

    Read-after-surface is the observable act of using a search result — the
    server watches for it instead of waiting for the client to declare a use.
    A read of a note NOT surfaced within ``feedback_window_seconds`` is a cold
    read (direct navigation, an unrelated lookup) and records nothing: there is
    no search to attribute it to and no evidence retrieval earned it.

    Records one 'used' / 'inferred' event plus the attribution. Repeated
    offset-0 re-opens each count, exactly as repeated explicit record_usage
    calls do; ``attribute_use`` still dedups the feedback event per
    (query, path) inside the window.
    """
    try:
        from .config import get_config

        cfg = get_config()
        if not cfg.feedback_enabled:
            return
        if conn is None:
            from .schema import DB_PATH, get_db

            conn = get_db(DB_PATH)

        rows = conn.execute(
            "SELECT shown_paths FROM search_log "
            "WHERE searched_at >= datetime('now', ?) "
            "ORDER BY searched_at DESC, search_id DESC",
            (f"-{int(cfg.feedback_window_seconds)} seconds",),
        ).fetchall()

        surfaced = False
        for r in rows:
            try:
                shown = json.loads(r[0])
            except (json.JSONDecodeError, TypeError):
                continue
            if path in shown:
                surfaced = True
                break
        if not surfaced:
            return

        from .search import _record_note_usage

        _record_note_usage(conn, [path], tier="used", source="inferred")
        attribute_use(conn, [path], cfg.feedback_window_seconds)
    except Exception:
        pass  # feedback capture must never disrupt a read


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
    """Summary of accumulated feedback — volume, rank distribution, and the
    two activation tiers (issue #95): deliberate 'used' events vs auto-RAG
    'primed' injections, with the in-window primed count that actually feeds
    hotness. The 'used' total also splits by provenance (issue #103) — how many
    uses the client declared vs how many the server inferred from a read of a
    just-surfaced note."""
    from .config import get_config

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
    used_events = conn.execute(
        "SELECT COUNT(*) FROM note_usage WHERE tier = 'used'"
    ).fetchone()[0]
    primed_events = conn.execute(
        "SELECT COUNT(*) FROM note_usage WHERE tier = 'primed'"
    ).fetchone()[0]
    used_explicit = conn.execute(
        "SELECT COUNT(*) FROM note_usage WHERE tier = 'used' AND source = 'explicit'"
    ).fetchone()[0]
    used_inferred = conn.execute(
        "SELECT COUNT(*) FROM note_usage WHERE tier = 'used' AND source = 'inferred'"
    ).fetchone()[0]
    primed_in_window = conn.execute(
        "SELECT COUNT(*) FROM note_usage WHERE tier = 'primed' "
        "AND used_at >= datetime('now', ?)",
        (f"-{float(get_config().primed_decay_days)} days",),
    ).fetchone()[0]
    return {
        "searches_logged": searches,
        "feedback_events": events,
        "distinct_queries": distinct_q,
        "distinct_chosen_notes": distinct_notes,
        "avg_chosen_rank": round(avg_rank, 2) if avg_rank is not None else None,
        "informative_events": below_top,  # chosen note was not already top-ranked
        "used_events": used_events,
        "used_explicit": used_explicit,  # declared via record_usage
        "used_inferred": used_inferred,  # observed as read-after-surface
        "primed_events": primed_events,
        "primed_in_window": primed_in_window,  # primes still contributing to hotness
    }
