# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""`neurostack run-due` and `neurostack jobs` (issue #225)."""

import json
import logging
import sys
from datetime import datetime
from typing import Any


def _summary(run: dict[str, Any]) -> str:
    if run.get("error"):
        return run["error"].splitlines()[0][:120]
    return (run.get("result") or run.get("reason") or "")[:120]


def cmd_run_due(args):
    """Run every due scheduled job once; the OS timer calls this each minute."""
    from ..config import get_config
    from ..jobs import run_due

    # Job progress goes to stderr (the journal); stdout carries the report.
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr,
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    logging.getLogger("neurostack.jobs").setLevel(logging.INFO)

    runs = run_due(get_config(), only=args.job, force=args.force)
    if args.json:
        print(json.dumps(runs, default=str))
    elif runs == [{"busy": True}]:
        print("busy")
    else:
        for r in runs:
            took = f"{r['duration_s']:.1f}s" if "duration_s" in r else "-"
            print(f"  {r['job']:<12} {r['status']:<8} {took:>7}  {_summary(r)}")


def cmd_jobs(args):
    """List every scheduled job with its schedule, host status, and last run."""
    from ..config import get_config
    from ..jobs import JOBS, blocked, last_run, next_due
    from ..schema import get_db

    cfg = get_config()
    conn = get_db(cfg.db_path) if cfg.db_path.exists() else None
    now = datetime.now()
    rows = []
    for job in JOBS.values():
        last = last_run(conn, job.name) if conn else None
        due = next_due(conn, job, now) if conn else job.schedule.next_due(None, now)
        reason = blocked(cfg, job)
        rows.append({
            "job": job.name,
            "schedule": str(job.schedule),
            "enabled": reason is None,
            "reason": reason,
            "last_run": {"started_at": last["started_at"], "status": last["status"]}
            if last else None,
            "next_due": due.isoformat(timespec="minutes"),
            "description": job.description,
        })
    if args.json:
        print(json.dumps(rows))
        return
    for r in rows:
        state = "enabled" if r["enabled"] else f"off ({r['reason']})"
        last = (f"{r['last_run']['started_at']} {r['last_run']['status']}"
                if r["last_run"] else "never run")
        print(f"  {r['job']:<12} {r['schedule']:<18} {state}")
        print(f"  {'':<12} last: {last}  next: {r['next_due'].replace('T', ' ')}")
