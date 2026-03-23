# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Persistent job store backed by Google Cloud Storage.

Jobs are stored as JSON blobs in GCS at ``jobs/{job_id}.json``.
An in-memory cache avoids repeated GCS reads for hot jobs.
Writes are write-through: every mutation persists to GCS immediately.

Falls back to memory-only mode when GCS is unavailable (tests, local dev).
"""

from __future__ import annotations

import json
import logging
import threading

log = logging.getLogger("neurostack.cloud.job_store")


class JobStore:
    """Write-through GCS-backed job store with in-memory cache.

    Thread-safe via a reentrant lock on all public methods.
    """

    def __init__(self, bucket=None) -> None:
        """Initialise the store.

        Args:
            bucket: A ``google.cloud.storage.Bucket`` instance.
                    If *None*, the store operates in memory-only mode.
        """
        self._bucket = bucket
        self._cache: dict[str, dict] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create(self, job_id: str, data: dict) -> None:
        """Create a new job entry."""
        with self._lock:
            self._cache[job_id] = dict(data)
            self._persist(job_id, data)

    def get(self, job_id: str) -> dict | None:
        """Return job data or *None* if not found.

        Checks the in-memory cache first, then GCS.
        """
        with self._lock:
            if job_id in self._cache:
                return dict(self._cache[job_id])

            # Cache miss — try GCS
            data = self._load(job_id)
            if data is not None:
                self._cache[job_id] = data
                return dict(data)

            return None

    def update(self, job_id: str, patch: dict) -> None:
        """Merge *patch* into an existing job.

        If the job doesn't exist in cache, attempts to load from GCS first.
        """
        with self._lock:
            if job_id not in self._cache:
                loaded = self._load(job_id)
                if loaded is not None:
                    self._cache[job_id] = loaded

            if job_id in self._cache:
                self._cache[job_id].update(patch)
                self._persist(job_id, self._cache[job_id])

    def list_user_jobs(self, user_id: str, limit: int = 10) -> list[dict]:
        """Return recent jobs for a user, sorted by creation time desc.

        Scans the in-memory cache (which is populated on create/get).
        """
        with self._lock:
            user_jobs = [
                {"job_id": jid, **data}
                for jid, data in self._cache.items()
                if data.get("user_id") == user_id
            ]
        # Sort by started timestamp descending (newest first)
        user_jobs.sort(key=lambda j: j.get("started") or "", reverse=True)
        return user_jobs[:limit]

    # ------------------------------------------------------------------
    # GCS persistence (called under lock)
    # ------------------------------------------------------------------

    def _persist(self, job_id: str, data: dict) -> None:
        """Write job data to GCS as JSON. No-op if bucket is None."""
        if self._bucket is None:
            return
        try:
            blob = self._bucket.blob(f"jobs/{job_id}.json")
            blob.upload_from_string(
                json.dumps(data, default=str),
                content_type="application/json",
            )
        except Exception:
            log.warning("Failed to persist job %s to GCS", job_id, exc_info=True)

    def _load(self, job_id: str) -> dict | None:
        """Load job data from GCS. Returns None if not found or no bucket."""
        if self._bucket is None:
            return None
        try:
            blob = self._bucket.blob(f"jobs/{job_id}.json")
            if not blob.exists():
                return None
            return json.loads(blob.download_as_bytes())
        except Exception:
            log.warning("Failed to load job %s from GCS", job_id, exc_info=True)
            return None
