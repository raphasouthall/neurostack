# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Ranking-weight tuning driven from the dashboard (issue #291).

Labels are the `search_feedback` rows: the inferred ones the implicit-feedback
loop writes and the explicit ones the Search page's "Best result" button writes.
A run tunes on half of them (coordinate ascent, `tune.py`) and scores the other
half, so the number shown before Apply is out of sample. Apply stores the tuned
weights in `ranking_weights`, which every search reads (`search.active_weights`);
Revert deletes that row and config.toml decides again. A run is a child process
(`python -m neurostack.ui.tuning RUN_ID`), one at a time: it patches the search
module to serve cached embeddings, which must not leak into the server's own
searches. Its progress lives in `tune_runs`.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import subprocess
import sys
from dataclasses import asdict
from typing import Any

log = logging.getLogger(__name__)

METRIC = "ndcg"
K = 5
# Fewer labels than this and half of them cannot say whether a change helps.
MIN_LABELS = 10
# Each round tries 28 settings; three keep a run on a 3 GB index near 20 minutes.
MAX_ROUNDS = 3
# A run takes about 20 minutes; one still running after this long has died.
STALE_HOURS = 2


class TuningError(ValueError):
    """A request the tuner refuses: a run already going, too few labels, no gain."""


def _connect(db_path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=60.0)
    conn.row_factory = sqlite3.Row
    return conn


def prepare(db_path) -> None:
    """Server start: bring the index to the current schema, then fail stale runs.

    The dashboard reads through read-only connections, which never migrate, and
    the tuning tables arrived in schema v32. A run is a child process that
    outlives a server restart, so only a run older than any run can last is
    marked failed: its process died without writing its result.
    """
    from ..schema import _run_migrations

    conn = _connect(db_path)
    try:
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'schema_version'").fetchone():
            _run_migrations(conn)
        conn.execute("UPDATE tune_runs SET status = 'failed',"
                     " error = 'run stopped without a result',"
                     " finished_at = datetime('now') WHERE status = 'running'"
                     " AND started_at < datetime('now', ?)", (f"-{STALE_HOURS} hours",))
        conn.commit()
    except sqlite3.OperationalError:
        pass  # no index yet, or a database from before schema v32
    finally:
        conn.close()


def status(conn, cfg) -> dict[str, Any]:
    """Labels, the weights searches use now, and the recent runs."""
    from ..config import RankingWeights
    from ..feedback import feedback_labels
    from ..search import active_weights
    from ..tune import DEFAULT_GRIDS

    labels = feedback_labels(conn)
    explicit = conn.execute(
        "SELECT COUNT(DISTINCT query) FROM search_feedback WHERE source = 'explicit'").fetchone()[0]
    applied = conn.execute("SELECT run_id, applied_at FROM ranking_weights WHERE id = 1").fetchone()
    config_w = asdict(RankingWeights.from_config(cfg))
    active_w = asdict(active_weights(conn, cfg))
    runs = [dict(r) for r in conn.execute(
        "SELECT * FROM tune_runs ORDER BY run_id DESC LIMIT 10")]
    for r in runs:
        for key in ("baseline_weights", "tuned_weights"):
            r[key] = json.loads(r[key]) if r[key] else None
    return {
        "labels": len(labels), "explicit_labels": explicit, "min_labels": MIN_LABELS,
        "metric": METRIC, "k": K,
        "weights": [{"name": n, "config": config_w[n], "active": active_w[n]}
                    for n in DEFAULT_GRIDS],
        "applied": dict(applied) if applied else None,
        "runs": runs,
    }


def start(cfg) -> int:
    """Record a run and start its child process; returns the run id."""
    from ..feedback import feedback_labels

    conn = _connect(cfg.db_path)
    try:
        labels = feedback_labels(conn)
        if len(labels) < MIN_LABELS:
            raise TuningError(f"{len(labels)} labels; tuning needs at least {MIN_LABELS}")
        # The check and the insert share one write lock, so two clicks start one run.
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute("SELECT 1 FROM tune_runs WHERE status = 'running'").fetchone():
            conn.rollback()
            raise TuningError("a tuning run is already going")
        explicit = conn.execute(
            "SELECT COUNT(DISTINCT query) FROM search_feedback WHERE source = 'explicit'"
        ).fetchone()[0]
        run_id: int = conn.execute(
            "INSERT INTO tune_runs (status, metric, labels, explicit_labels) VALUES"
            " ('running', ?, ?, ?)", (METRIC, len(labels), explicit)).lastrowid
        conn.commit()
    finally:
        conn.close()
    log_path = cfg.db_dir / "tmp" / f"tune-{run_id}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "w") as out:
        subprocess.Popen([sys.executable, "-m", "neurostack.ui.tuning", str(run_id)],
                         stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT)
    return run_id


def _run(cfg, run_id: int) -> None:
    from .. import eval as ev
    from .. import tune as tn
    from ..feedback import feedback_labels
    from ..search import active_weights

    try:
        conn = _connect(cfg.db_path)
        try:
            baseline = active_weights(conn, cfg)
            labels = feedback_labels(conn)
        finally:
            conn.close()
        cache = ev.build_embedding_cache(labels, embed_url=cfg.embed_url)
        train, holdout = tn.interleaved_split(labels)
        result = tn.coordinate_ascent(train, db_path=cfg.db_path, k=K, metric=METRIC,
                                      cache=cache, embed_url=cfg.embed_url, init=baseline,
                                      max_rounds=MAX_ROUNDS)
        hold_base, hold_tuned = tn.holdout_scores(result, holdout, db_path=cfg.db_path, k=K,
                                                  cache=cache, embed_url=cfg.embed_url)
        fields = {"status": "done", "train_baseline": result.baseline_score,
                  "train_tuned": result.best_score, "holdout_baseline": hold_base,
                  "holdout_tuned": hold_tuned,
                  "baseline_weights": json.dumps(asdict(result.baseline_weights)),
                  "tuned_weights": json.dumps(asdict(result.best_weights)), "error": None}
    except Exception as exc:  # the row must say why, or the page shows a run forever
        log.exception("tuning run %s failed", run_id)
        fields = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
    conn = _connect(cfg.db_path)
    try:
        sets = ", ".join(f"{k} = ?" for k in fields)
        conn.execute(f"UPDATE tune_runs SET {sets}, finished_at = datetime('now')"
                     " WHERE run_id = ?", (*fields.values(), run_id))
        conn.commit()
    finally:
        conn.close()


def apply(conn, run_id: int) -> None:
    """Make a finished run's weights the ones every search uses.

    Only a run that beat the weights in use on the held-out half can be applied,
    so Apply never trades real ranking for a better score on the labels it saw.
    """
    row = conn.execute("SELECT * FROM tune_runs WHERE run_id = ?", (run_id,)).fetchone()
    if row is None:
        raise KeyError(run_id)
    if row["status"] != "done":
        raise TuningError(f"run {run_id} is {row['status']}")
    if not row["holdout_tuned"] > row["holdout_baseline"]:
        raise TuningError(f"run {run_id} did not beat the current weights on the held-out labels")
    conn.execute("INSERT OR REPLACE INTO ranking_weights (id, weights, run_id, applied_at)"
                 " VALUES (1, ?, ?, datetime('now'))", (row["tuned_weights"], run_id))
    conn.commit()


def revert(conn) -> bool:
    """Drop applied weights; config.toml decides again. False when none were applied."""
    cur = conn.execute("DELETE FROM ranking_weights WHERE id = 1")
    conn.commit()
    return cur.rowcount > 0


if __name__ == "__main__":
    from ..config import get_config

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    _run(get_config(), int(sys.argv[1]))
