# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Persistent tier storage backed by Google Cloud Storage.

Stripe webhook events update user tiers (free/pro/team). Without
persistence, these changes are lost on Cloud Run scale-down.

Tiers are stored as ``tiers/{user_id}.json`` in GCS. An in-memory
cache avoids repeated GCS reads. Writes are write-through.

The Secret Manager API keys JSON provides the *default* tier for each
user. This store provides *overrides* set by Stripe webhooks.
"""

from __future__ import annotations

import json
import logging
import threading

log = logging.getLogger("neurostack.cloud.tier_store")


class TierStore:
    """Write-through GCS-backed tier override store.

    Thread-safe via a lock on all public methods.
    """

    def __init__(self, bucket=None) -> None:
        self._bucket = bucket
        self._cache: dict[str, str] = {}
        self._lock = threading.Lock()

    def get(self, user_id: str) -> str | None:
        """Return the tier override for a user, or None if no override."""
        with self._lock:
            if user_id in self._cache:
                return self._cache[user_id]

            tier = self._load(user_id)
            if tier is not None:
                self._cache[user_id] = tier
            return tier

    def set(self, user_id: str, tier: str) -> None:
        """Set a tier override for a user. Persists to GCS."""
        with self._lock:
            self._cache[user_id] = tier
            self._persist(user_id, tier)

    def _persist(self, user_id: str, tier: str) -> None:
        if self._bucket is None:
            return
        try:
            blob = self._bucket.blob(f"tiers/{user_id}.json")
            blob.upload_from_string(
                json.dumps({"tier": tier}),
                content_type="application/json",
            )
        except Exception:
            log.warning(
                "Failed to persist tier for %s to GCS", user_id, exc_info=True
            )

    def _load(self, user_id: str) -> str | None:
        if self._bucket is None:
            return None
        try:
            blob = self._bucket.blob(f"tiers/{user_id}.json")
            if not blob.exists():
                return None
            data = json.loads(blob.download_as_bytes())
            return data.get("tier")
        except Exception:
            log.warning(
                "Failed to load tier for %s from GCS", user_id, exc_info=True
            )
            return None
