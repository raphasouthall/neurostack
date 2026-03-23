# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Firestore-backed usage metering for NeuroStack Cloud.

Tracks per-tenant query counts, index jobs, and notes indexed per month.
Enforces tier-based limits (free/pro/team) and provides usage stats.

Usage data is stored in Firestore at ``users/{uid}/usage/{period}``
where period is YYYY-MM. This survives Cloud Run scale-down events
(unlike the previous SQLite-based approach).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from google.cloud import firestore
from google.cloud.firestore_v1 import AsyncClient


@dataclass
class TierLimits:
    """Usage limits for a billing tier."""

    queries_per_month: int
    notes_max: int
    index_jobs_per_month: int


TIER_LIMITS: dict[str, TierLimits] = {
    "free": TierLimits(queries_per_month=500, notes_max=200, index_jobs_per_month=50),
    "pro": TierLimits(
        queries_per_month=50_000, notes_max=10_000, index_jobs_per_month=1_000
    ),
    "team": TierLimits(
        queries_per_month=200_000, notes_max=50_000, index_jobs_per_month=5_000
    ),
}


def _current_period() -> str:
    """Return current billing period as YYYY-MM."""
    return datetime.now(timezone.utc).strftime("%Y-%m")


class UsageMeter:
    """Firestore-backed per-tenant usage tracking.

    Stores query counts, index jobs, and notes indexed per user per month
    at ``users/{uid}/usage/{period}``. Usage resets automatically each
    calendar month via the period document ID.
    """

    def __init__(self, db: AsyncClient | None = None) -> None:
        self._db = db

    def _get_db(self) -> AsyncClient:
        """Return Firestore client, lazy-initializing if needed."""
        if self._db is None:
            self._db = AsyncClient()
        return self._db

    def _usage_ref(self, user_id: str):
        """Return a reference to the usage document for the current period."""
        period = _current_period()
        return (
            self._get_db()
            .collection("users")
            .document(user_id)
            .collection("usage")
            .document(period)
        )

    async def _increment(self, user_id: str, metric: str, amount: int = 1) -> int:
        """Increment a usage metric for the current period. Returns new count."""
        ref = self._usage_ref(user_id)
        await ref.set({metric: firestore.Increment(amount)}, merge=True)

        # Read back the current value
        doc = await ref.get()
        if doc.exists:
            return doc.to_dict().get(metric, 0)
        return 0

    async def _get_count(self, user_id: str, metric: str) -> int:
        """Get current period count for a metric."""
        ref = self._usage_ref(user_id)
        doc = await ref.get()
        if doc.exists:
            return doc.to_dict().get(metric, 0)
        return 0

    async def record_query(self, user_id: str) -> int:
        """Increment query count for current month. Returns new count."""
        return await self._increment(user_id, "queries")

    async def record_index_job(self, user_id: str, note_count: int) -> None:
        """Record an index job and the number of notes indexed."""
        await self._increment(user_id, "index_jobs")
        await self._increment(user_id, "notes_indexed", note_count)

    async def get_usage(self, user_id: str) -> dict:
        """Return current period usage stats for a user."""
        ref = self._usage_ref(user_id)
        doc = await ref.get()
        data = doc.to_dict() if doc.exists else {}
        return {
            "queries": data.get("queries", 0),
            "index_jobs": data.get("index_jobs", 0),
            "notes_indexed": data.get("notes_indexed", 0),
            "period": _current_period(),
        }

    async def check_query_limit(
        self, user_id: str, tier: str
    ) -> tuple[bool, str | None]:
        """Check if user is within query limit for their tier.

        Returns (True, None) if allowed, (False, reason) if over limit.
        """
        limits = TIER_LIMITS.get(tier, TIER_LIMITS["free"])
        current = await self._get_count(user_id, "queries")
        if current >= limits.queries_per_month:
            return (
                False,
                f"Query limit of {limits.queries_per_month}/month exceeded. "
                f"Upgrade at POST /v1/billing/checkout",
            )
        return (True, None)

    async def check_note_limit(
        self, user_id: str, tier: str, additional_notes: int
    ) -> tuple[bool, str | None]:
        """Check if uploading additional_notes would exceed tier note limit.

        Returns (True, None) if allowed, (False, reason) if over limit.
        """
        limits = TIER_LIMITS.get(tier, TIER_LIMITS["free"])
        current = await self._get_count(user_id, "notes_indexed")
        if current + additional_notes > limits.notes_max:
            return (
                False,
                f"Note limit of {limits.notes_max} exceeded. "
                f"Upgrade at POST /v1/billing/checkout",
            )
        return (True, None)
