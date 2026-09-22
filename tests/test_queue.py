# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Tests for the job queue (issue #191).

These pin the four rules the orchestrator used to own, each of which broke at
least once while it lived in n8n JavaScript: one live job per key, a daily cap
on finished jobs, a job claimed by exactly one worker, and a running job whose
runner vanished getting failed instead of wedging the queue.
"""

from datetime import datetime, timedelta, timezone

import pytest

from neurostack.queue import QueueLimits, add, claim, finish, listing, reap


def _iso(moment):
    return moment.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _age(conn, job_id, minutes):
    """Backdate a running job's start, the way a crashed runner leaves it."""
    conn.execute(
        "UPDATE job_queue SET started_at = ? WHERE job_id = ?",
        (_iso(datetime.now(timezone.utc) - timedelta(minutes=minutes)), job_id),
    )
    conn.commit()


class TestAdd:
    def test_second_request_for_a_live_key_is_a_duplicate(self, in_memory_db):
        first = add(in_memory_db, "checkpoint", "sess-1")
        second = add(in_memory_db, "checkpoint", "sess-1")

        assert first["job_id"] == second["job_id"]
        assert second["duplicate"] is True
        assert listing(in_memory_db, "checkpoint")["counts"] == {"queued": 1}

    def test_a_settled_key_can_be_queued_again(self, in_memory_db):
        job = add(in_memory_db, "checkpoint", "sess-1")
        claim(in_memory_db, "checkpoint")
        finish(in_memory_db, job["job_id"], ok=True)

        again = add(in_memory_db, "checkpoint", "sess-1")

        assert again["duplicate"] is False
        assert again["job_id"] != job["job_id"]

    def test_the_same_key_in_another_queue_is_independent(self, in_memory_db):
        add(in_memory_db, "checkpoint", "shared")
        other = add(in_memory_db, "harvest", "shared")

        assert other["duplicate"] is False

    def test_position_counts_the_jobs_ahead(self, in_memory_db):
        add(in_memory_db, "checkpoint", "a")
        add(in_memory_db, "checkpoint", "b")

        assert add(in_memory_db, "checkpoint", "c")["position"] == 3

    def test_cap_refuses_once_enough_finished_today(self, in_memory_db):
        limits = QueueLimits(cap_per_day=2)
        for key in ("a", "b"):
            job = add(in_memory_db, "harvest", key, limits=limits)
            claim(in_memory_db, "harvest", limits)
            finish(in_memory_db, job["job_id"], ok=True)

        refused = add(in_memory_db, "harvest", "c", limits=limits)

        assert refused["ok"] is False
        assert "cap" in refused["reason"]

    def test_a_missing_key_is_rejected(self, in_memory_db):
        with pytest.raises(ValueError):
            add(in_memory_db, "checkpoint", "")


class TestClaim:
    def test_newest_queued_job_is_claimed_first(self, in_memory_db):
        add(in_memory_db, "checkpoint", "first")
        add(in_memory_db, "checkpoint", "second")

        assert claim(in_memory_db, "checkpoint")["job"]["key"] == "second"

    def test_a_stale_backlog_drains_newest_to_oldest(self, in_memory_db):
        add(in_memory_db, "checkpoint", "old")
        add(in_memory_db, "checkpoint", "middle")
        add(in_memory_db, "checkpoint", "new")

        order = []
        for _ in range(3):
            job = claim(in_memory_db, "checkpoint")["job"]
            order.append(job["key"])
            finish(in_memory_db, job["job_id"], ok=True)

        assert order == ["new", "middle", "old"]

    def test_payload_mtime_governs_order_not_job_id(self, in_memory_db):
        """issue #211: --enqueue lists transcripts newest-first and inserts
        them in that order, so the newest transcript gets the lowest job_id.
        claim() must follow the payload's own mtime, not insertion order."""
        add(in_memory_db, "harvest", "old", {"path": "old", "mtime": 100})
        add(in_memory_db, "harvest", "newest", {"path": "newest", "mtime": 300})
        add(in_memory_db, "harvest", "middle", {"path": "middle", "mtime": 200})

        order = []
        for _ in range(3):
            job = claim(in_memory_db, "harvest")["job"]
            order.append(job["key"])
            finish(in_memory_db, job["job_id"], ok=True)

        assert order == ["newest", "middle", "old"]

    def test_job_without_mtime_never_blocks_one_with_mtime(self, in_memory_db):
        add(in_memory_db, "harvest", "no-mtime")
        add(in_memory_db, "harvest", "has-mtime", {"path": "x", "mtime": 1})

        assert claim(in_memory_db, "harvest")["job"]["key"] == "has-mtime"

    def test_jobs_without_mtime_fall_back_to_job_id_order(self, in_memory_db):
        """The checkpoint queue carries no mtime; among mtime-less jobs the
        order stays newest-job_id-first, same as before issue #211."""
        add(in_memory_db, "checkpoint", "old")
        add(in_memory_db, "checkpoint", "new")

        assert claim(in_memory_db, "checkpoint")["job"]["key"] == "new"

    def test_payload_is_stored_as_real_json_not_a_python_repr(self, in_memory_db):
        """claim() reads mtime via SQLite's json_extract, which raises on a
        Python repr (single-quoted) string. add() must keep writing real
        JSON so every existing row stays claimable."""
        add(in_memory_db, "harvest", "a", {"path": "a", "mtime": 5.5})
        raw = in_memory_db.execute(
            "SELECT payload FROM job_queue WHERE key = 'a'"
        ).fetchone()[0]

        assert in_memory_db.execute(
            "SELECT json_extract(?, '$.mtime')", (raw,)
        ).fetchone()[0] == 5.5

    def test_a_job_is_claimed_only_once(self, in_memory_db):
        add(in_memory_db, "checkpoint", "only")
        add(in_memory_db, "checkpoint", "next")

        first = claim(in_memory_db, "checkpoint")
        second = claim(in_memory_db, "checkpoint")

        assert first["claimed"] is True
        assert second["claimed"] is False
        assert second["reason"] == "1 already running"

    def test_concurrency_allows_more_than_one(self, in_memory_db):
        limits = QueueLimits(concurrency=2)
        for key in ("a", "b", "c"):
            add(in_memory_db, "checkpoint", key)

        assert claim(in_memory_db, "checkpoint", limits)["claimed"] is True
        assert claim(in_memory_db, "checkpoint", limits)["claimed"] is True
        assert claim(in_memory_db, "checkpoint", limits)["claimed"] is False

    def test_empty_queue_says_so(self, in_memory_db):
        assert claim(in_memory_db, "checkpoint")["reason"] == "queue empty"

    def test_cap_blocks_claiming_too(self, in_memory_db):
        limits = QueueLimits(cap_per_day=1)
        job = add(in_memory_db, "harvest", "a", limits=limits)
        claim(in_memory_db, "harvest", limits)
        finish(in_memory_db, job["job_id"], ok=True)
        in_memory_db.execute(
            "INSERT INTO job_queue (queue, key) VALUES ('harvest', 'b')")
        in_memory_db.commit()

        result = claim(in_memory_db, "harvest", limits)

        assert result["claimed"] is False
        assert "daily cap 1/1" in result["reason"]


class TestReap:
    def test_a_stale_running_job_is_failed_and_unblocks_the_queue(self, in_memory_db):
        """The bug this replaces: a crashed runner held its queue for good."""
        stuck = add(in_memory_db, "checkpoint", "stuck")
        claim(in_memory_db, "checkpoint")
        _age(in_memory_db, stuck["job_id"], minutes=31)
        add(in_memory_db, "checkpoint", "waiting")

        result = claim(in_memory_db, "checkpoint")

        assert [r["key"] for r in result["reaped"]] == ["stuck"]
        assert result["job"]["key"] == "waiting"
        row = in_memory_db.execute(
            "SELECT status, output FROM job_queue WHERE job_id = ?",
            (stuck["job_id"],)).fetchone()
        assert row["status"] == "failed"
        assert "stale" in row["output"]

    def test_a_fresh_running_job_is_left_alone(self, in_memory_db):
        add(in_memory_db, "checkpoint", "busy")
        claim(in_memory_db, "checkpoint")

        assert reap(in_memory_db, "checkpoint") == []

    def test_a_running_job_with_no_start_stamp_counts_as_stale(self, in_memory_db):
        in_memory_db.execute(
            "INSERT INTO job_queue (queue, key, status) "
            "VALUES ('checkpoint', 'orphan', 'running')")
        in_memory_db.commit()

        assert [r["key"] for r in reap(in_memory_db, "checkpoint")] == ["orphan"]

    def test_only_the_named_queue_is_reaped(self, in_memory_db):
        other = add(in_memory_db, "harvest", "other")
        claim(in_memory_db, "harvest")
        _age(in_memory_db, other["job_id"], minutes=90)

        assert reap(in_memory_db, "checkpoint") == []


class TestFinish:
    def test_outcome_and_counts_are_recorded(self, in_memory_db):
        job = add(in_memory_db, "harvest", "t.jsonl", {"provider": "omp"})
        claim(in_memory_db, "harvest")

        done = finish(in_memory_db, job["job_id"], ok=True, saved=3,
                      output="haiku saved 3 of 3")

        assert done["status"] == "done"
        assert done["saved"] == 3
        assert done["finished_at"]
        assert done["payload"] == {"provider": "omp"}

    def test_failure_is_recorded_as_failed(self, in_memory_db):
        job = add(in_memory_db, "harvest", "t.jsonl")
        claim(in_memory_db, "harvest")

        done = finish(in_memory_db, job["job_id"], ok=False, output="vault offline")

        assert done["status"] == "failed"
        assert done["output"] == "vault offline"

    def test_an_unknown_job_raises(self, in_memory_db):
        with pytest.raises(ValueError):
            finish(in_memory_db, 999, ok=True)
