# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Tests for Firestore-backed cloud usage metering and tier enforcement."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Mock Firestore for metering tests
# ---------------------------------------------------------------------------


class MockMeteringDoc:
    """In-memory mock of a Firestore usage document."""

    def __init__(self, data: dict | None = None):
        self._data = data or {}
        self.exists = data is not None

    def to_dict(self):
        return self._data


class MockMeteringCollection:
    """In-memory mock that mimics users/{uid}/usage/{period} pattern."""

    def __init__(self):
        self._store: dict[str, dict] = {}  # "users/{uid}/usage/{period}" -> data

    def collection(self, name):
        return _CollectionRef(self, name)


class _CollectionRef:
    def __init__(self, store: MockMeteringCollection, path: str):
        self._store = store
        self._path = path

    def document(self, doc_id: str):
        return _DocRef(self._store, f"{self._path}/{doc_id}")


class _DocRef:
    def __init__(self, store: MockMeteringCollection, path: str):
        self._store = store
        self._path = path

    def collection(self, name: str):
        return _CollectionRef(self._store, f"{self._path}/{name}")

    async def get(self):
        data = self._store._store.get(self._path)
        if data is not None:
            return MockMeteringDoc(dict(data))
        return MockMeteringDoc(None)

    async def set(self, data: dict, merge: bool = False):
        from google.cloud.firestore_v1.transforms import Increment

        existing = self._store._store.get(self._path, {})

        for key, value in data.items():
            if isinstance(value, Increment):
                existing[key] = existing.get(key, 0) + value.value
            else:
                existing[key] = value

        self._store._store[self._path] = existing


@pytest.fixture
def mock_meter():
    """Create a UsageMeter backed by an in-memory mock Firestore."""
    from neurostack.cloud.metering import UsageMeter

    mock_db = MockMeteringCollection()
    meter = UsageMeter(db=mock_db)
    return meter


# ---------------------------------------------------------------------------
# UsageMeter unit tests
# ---------------------------------------------------------------------------


class TestUsageMeterRecording:
    """Tests for UsageMeter.record_query() and record_index_job()."""

    @pytest.mark.asyncio
    async def test_record_query_increments_count(self, mock_meter):
        """record_query increments query count for current month."""
        count = await mock_meter.record_query("user-1")
        assert count == 1
        count = await mock_meter.record_query("user-1")
        assert count == 2

    @pytest.mark.asyncio
    async def test_record_index_job_increments_jobs_and_notes(self, mock_meter):
        """record_index_job increments both index_jobs and notes_indexed."""
        await mock_meter.record_index_job("user-1", 50)
        usage = await mock_meter.get_usage("user-1")
        assert usage["index_jobs"] == 1
        assert usage["notes_indexed"] == 50

        await mock_meter.record_index_job("user-1", 30)
        usage = await mock_meter.get_usage("user-1")
        assert usage["index_jobs"] == 2
        assert usage["notes_indexed"] == 80

    @pytest.mark.asyncio
    async def test_get_usage_returns_zeros_for_new_user(self, mock_meter):
        """get_usage returns all zeros for a user with no activity."""
        usage = await mock_meter.get_usage("new-user")
        assert usage["queries"] == 0
        assert usage["index_jobs"] == 0
        assert usage["notes_indexed"] == 0
        assert len(usage["period"]) == 7  # YYYY-MM format

    @pytest.mark.asyncio
    async def test_users_are_isolated(self, mock_meter):
        """Each user's counters are independent."""
        await mock_meter.record_query("user-1")
        await mock_meter.record_query("user-1")
        await mock_meter.record_query("user-2")

        u1 = await mock_meter.get_usage("user-1")
        u2 = await mock_meter.get_usage("user-2")
        assert u1["queries"] == 2
        assert u2["queries"] == 1


class TestUsageMeterLimits:
    """Tests for tier limit enforcement."""

    @pytest.mark.asyncio
    async def test_check_query_limit_allows_under_limit(self, mock_meter):
        """check_query_limit returns (True, None) when under limit."""
        await mock_meter.record_query("user-1")
        allowed, reason = await mock_meter.check_query_limit("user-1", "free")
        assert allowed is True
        assert reason is None

    @pytest.mark.asyncio
    async def test_check_query_limit_blocks_at_500(self, mock_meter):
        """check_query_limit returns (False, reason) at 500 queries on free tier."""
        # Seed 500 queries directly into the mock store
        from neurostack.cloud.metering import _current_period

        period = _current_period()
        path = f"users/user-1/usage/{period}"
        mock_meter._db._store[path] = {"queries": 500}

        allowed, reason = await mock_meter.check_query_limit("user-1", "free")
        assert allowed is False
        assert "500" in reason
        assert "/v1/billing/checkout" in reason

    @pytest.mark.asyncio
    async def test_check_note_limit_allows_under_limit(self, mock_meter):
        """check_note_limit returns (True, None) when adding notes stays under limit."""
        allowed, reason = await mock_meter.check_note_limit("user-1", "free", 100)
        assert allowed is True
        assert reason is None

    @pytest.mark.asyncio
    async def test_check_note_limit_blocks_over_200(self, mock_meter):
        """check_note_limit returns (False, reason) when notes would exceed 200 on free."""
        await mock_meter.record_index_job("user-1", 150)
        allowed, reason = await mock_meter.check_note_limit("user-1", "free", 60)
        assert allowed is False
        assert "200" in reason
        assert "/v1/billing/checkout" in reason

    @pytest.mark.asyncio
    async def test_pro_tier_has_higher_limits(self, mock_meter):
        """Pro tier allows much higher usage than free."""
        from neurostack.cloud.metering import _current_period

        period = _current_period()
        path = f"users/user-2/usage/{period}"
        mock_meter._db._store[path] = {"queries": 5000}

        allowed, reason = await mock_meter.check_query_limit("user-2", "pro")
        assert allowed is True
        assert reason is None


class TestTierLimitsValues:
    """Tests for TIER_LIMITS constant values."""

    def test_tier_limits_free(self):
        """Free tier limits match spec."""
        from neurostack.cloud.metering import TIER_LIMITS, TierLimits

        assert TIER_LIMITS["free"] == TierLimits(
            queries_per_month=500,
            notes_max=200,
            index_jobs_per_month=50,
        )

    def test_tier_limits_pro(self):
        """Pro tier limits match spec."""
        from neurostack.cloud.metering import TIER_LIMITS, TierLimits

        assert TIER_LIMITS["pro"] == TierLimits(
            queries_per_month=50_000,
            notes_max=10_000,
            index_jobs_per_month=1_000,
        )

    def test_tier_limits_team(self):
        """Team tier limits match spec."""
        from neurostack.cloud.metering import TIER_LIMITS, TierLimits

        assert TIER_LIMITS["team"] == TierLimits(
            queries_per_month=200_000,
            notes_max=50_000,
            index_jobs_per_month=5_000,
        )
