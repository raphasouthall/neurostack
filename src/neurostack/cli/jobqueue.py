"""`neurostack queue` — the job queue a scheduler drives (issue #191).

The transport-side client that asks a remote queue for a slot is cli/queue.py;
this module owns the local queue itself.
"""

from __future__ import annotations

import json
import sys


def _limits(args):
    from ..queue import QueueLimits

    return QueueLimits(
        cap_per_day=args.cap,
        stale_minutes=args.stale_minutes,
        concurrency=args.concurrency,
    )


def cmd_queue(args) -> None:
    """Dispatch one queue action, printing JSON when asked."""
    from .. import queue as q
    from ..schema import DB_PATH, get_db

    conn = get_db(DB_PATH)
    action = args.queue_action

    if action == "add":
        payload = json.loads(args.payload) if args.payload else {}
        result = q.add(conn, args.queue, args.key, payload, _limits(args))
        if args.json:
            print(json.dumps(result))
        elif result.get("duplicate"):
            print(f"  already queued: {args.key}")
        elif result["ok"]:
            print(f"  queued at position {result['position']}: {args.key}")
        else:
            print(f"  refused: {result['reason']}")
        if not result["ok"]:
            sys.exit(1)
        return

    if action == "claim":
        result = q.claim(conn, args.queue, _limits(args))
        if args.json:
            print(json.dumps(result))
        elif result["claimed"]:
            job = result["job"]
            print(f"  claimed job {job['job_id']}: {job['key']}")
        else:
            print(f"  nothing claimed: {result['reason']}")
        return

    if action == "finish":
        result = q.finish(conn, args.job_id, ok=not args.failed,
                          saved=args.saved, output=args.output or "")
        if args.json:
            print(json.dumps(result))
        else:
            print(f"  job {result['job_id']} {result['status']}")
        return

    if action == "reap":
        reaped = q.reap(conn, args.queue, _limits(args))
        if args.json:
            print(json.dumps({"reaped": reaped}))
        else:
            print(f"  reaped {len(reaped)} stale job(s)")
            for r in reaped:
                print(f"    {r['job_id']} {r['key']}")
        return

    result = q.listing(conn, queue=args.queue, status=args.status, limit=args.limit)
    if args.json:
        print(json.dumps(result))
        return
    counts = ", ".join(f"{k} {v}" for k, v in sorted(result["counts"].items()))
    print(f"  {counts or 'empty'}")
    for job in result["jobs"]:
        stamp = (job["finished_at"] or job["started_at"] or job["requested_at"])[:19]
        print(f"    {job['job_id']:<5} {job['status']:<8} {stamp}  {job['key']}")
        if job["output"]:
            print(f"          {job['output'][:100]}")
