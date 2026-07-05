# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Unit tests for the shared token-budget helper (issue #62)."""

from neurostack.budget import estimate_tokens, trim_to_budget


class TestEstimateTokens:
    def test_string_measured_directly(self):
        assert estimate_tokens("a" * 40) == 10  # 40 chars / 4

    def test_dict_measured_by_json_encoding(self):
        entry = {"path": "a.md", "score": 0.5}
        assert estimate_tokens(entry) == len(
            '{"path": "a.md", "score": 0.5}'
        ) // 4

    def test_non_serialisable_falls_back_to_str(self):
        assert estimate_tokens(object()) > 0  # does not raise


class TestTrimToBudget:
    def test_none_budget_keeps_everything(self):
        entries = [{"n": i} for i in range(5)]
        kept, used, truncated = trim_to_budget(entries, None)
        assert kept == entries
        assert truncated is False
        assert used == sum(estimate_tokens(e) for e in entries)

    def test_trims_and_flags_truncation(self):
        entries = [{"pad": "x" * 400} for _ in range(5)]  # ~100 tokens each
        kept, used, truncated = trim_to_budget(entries, max_tokens=250)
        assert 0 < len(kept) < len(entries)
        assert truncated is True
        assert used <= 250 + estimate_tokens(entries[0])

    def test_keeps_at_least_one_when_first_exceeds_budget(self):
        entries = [{"pad": "x" * 4000}]  # ~1000 tokens, budget is 10
        kept, _used, truncated = trim_to_budget(entries, max_tokens=10)
        assert len(kept) == 1  # never return an empty, useless result
        assert truncated is False  # nothing was dropped

    def test_empty_input(self):
        kept, used, truncated = trim_to_budget([], max_tokens=100)
        assert kept == []
        assert used == 0
        assert truncated is False
