# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Typed judgement calls against a decisions model (Jev).

One narrow thing: ask a model to pick a label, score an option, or answer
yes/no, and get the answer back as a value rather than as prose to be parsed.
Every caller that needs a judgement goes through `decide`, so there is one
place that knows the endpoint, the auth, and the failure shape.

It cannot generate text. Summaries, triples and community labels stay on the
index LLM; this replaces the calls where the model is only choosing.

Why it exists: `harvest._parse_classify_reply` is 89 lines of guesswork around
a small model that wraps JSON in code fences, and a decisions call cannot
answer off-menu. Measured on 191 held-out agent-written memories, label choice
agreed with the stored type 55.5% of the time against gemma's 47.6%, a +7.9pp
difference (95% CI [+1.0, +14.7], paired permutation p=0.039), with macro-F1
0.514 against 0.424. Both scored against the same noisy key, so read the gap
and not the absolute numbers.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("neurostack.judge")


class JudgeError(RuntimeError):
    """The judgement model did not answer. Callers decide what to do about it."""


def decide(state: str, questions: dict[str, dict], cfg: Any = None) -> dict[str, dict]:
    """Answer every question in `questions` about `state`.

    `questions` maps an id to a question object: `{"type": "choice",
    "instructions": ..., "criteria": {label: rubric}}` for a label, `"score"`
    with an ordered criteria list for a rating, `"bool"` for yes/no.

    Returns the `answers` block, keyed by question id. A choice answer carries
    `choice`, `probabilities` and `confidence`; a score answer carries `score`.

    Raises JudgeError on any transport, HTTP, or shape failure. It raises
    rather than returning a default because the right fallback differs per
    caller: search keeps its existing order, harvest keeps the index LLM's
    answer, and neither wants the other's behaviour chosen for it.
    """
    if cfg is None:
        from .config import get_config

        cfg = get_config()

    if not cfg.judge_model:
        raise JudgeError("judge_model is unset")

    import httpx

    headers = {"Content-Type": "application/json"}
    if cfg.judge_api_key:
        headers["Authorization"] = f"Bearer {cfg.judge_api_key}"

    try:
        resp = httpx.post(
            f"{cfg.judge_url.rstrip('/')}/alpha/decisions",
            headers=headers,
            json={"model": cfg.judge_model, "state": state, "questions": questions},
            timeout=cfg.judge_timeout_s,
        )
        resp.raise_for_status()
        answers = resp.json()["answers"]
    except Exception as exc:
        raise JudgeError(str(exc)) from exc

    if not isinstance(answers, dict):
        raise JudgeError(f"expected an answers object, got {type(answers).__name__}")
    return answers


def decide_many(
    states: list[str], questions: dict[str, dict], cfg: Any = None
) -> list[dict[str, dict] | None]:
    """`decide` over many states concurrently. A failed state is None.

    One slow state must not stall the rest, and one failed state must not lose
    the others, so failures are per-item rather than per-batch.
    """
    if not states:
        return []

    if cfg is None:
        from .config import get_config

        cfg = get_config()

    import concurrent.futures

    def _one(state: str) -> dict[str, dict] | None:
        try:
            return decide(state, questions, cfg)
        except JudgeError as exc:
            log.warning("judge failed for one item: %s", exc)
            return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=cfg.judge_concurrency) as pool:
        return list(pool.map(_one, states))
