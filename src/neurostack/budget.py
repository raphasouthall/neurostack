# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Shared token-budget estimation for size-bounded retrieval (issue #62).

One ~4-chars-per-token estimator so vault_context and vault_search agree on how
big a result is before it lands in the caller's context window, instead of each
tool inlining its own `len(json.dumps(x)) // 4`.
"""

from __future__ import annotations

import json

CHARS_PER_TOKEN = 4


def estimate_tokens(obj) -> int:
    """Approximate the token cost of a JSON-serialisable object (~4 chars/token).

    Strings are measured as-is; anything else is measured by its JSON encoding,
    which is what actually crosses the wire to the caller.
    """
    if isinstance(obj, str):
        text = obj
    else:
        try:
            text = json.dumps(obj, default=str)
        except (TypeError, ValueError):
            text = str(obj)
    return len(text) // CHARS_PER_TOKEN


def trim_to_budget(entries, max_tokens: int | None):
    """Keep the longest prefix of `entries` whose cumulative token estimate fits.

    Args:
        entries: An iterable of JSON-serialisable result entries.
        max_tokens: Token ceiling, or None to keep everything.

    Returns a ``(kept, tokens_used, truncated)`` tuple. At least one entry is
    always kept when the input is non-empty, so a caller with a tiny budget still
    gets a usable result rather than an empty list. `truncated` is True when any
    entry was dropped to stay within budget.
    """
    entries = list(entries)
    if max_tokens is None:
        return entries, sum(estimate_tokens(e) for e in entries), False

    kept: list = []
    used = 0
    for entry in entries:
        cost = estimate_tokens(entry)
        if kept and used + cost > max_tokens:
            break
        kept.append(entry)
        used += cost
    return kept, used, len(kept) < len(entries)
