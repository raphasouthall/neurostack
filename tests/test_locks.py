# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Tests for the cross-platform file lock (issue #221)."""

from neurostack.locks import file_lock


def test_non_blocking_lock_reports_contention_until_release(tmp_path):
    lock = tmp_path / "missing-dir" / "job.lock"
    with file_lock(lock) as first:
        with file_lock(lock, blocking=False) as second:
            assert (first, second) == (True, False)
    with file_lock(lock, blocking=False) as again:
        assert again is True
