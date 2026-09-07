# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Vault-agnostic label generation for the eval / tuning harness (issue #66).

The eval harness scores ranking against a set of ``(query, target-note)`` labels.
Hand-writing those labels ties the benchmark to one person's vault — the paths
leak in a public repo, and nobody else's vault matches them. This module removes
the hand step: a note is its own answer key, so we manufacture queries *from the
vault under test* and take the source note as the target. Any Markdown vault
produces its own benchmark, with nobody labelling anything.

Labels come from the note itself, with no model call. A note's pre-computed
summary is a paraphrase of its content, so searching the summary and expecting
the note back exercises the semantic + convergence signals rather than a title
keyword match. Notes with no summary fall back to their title.

``heuristic_labels`` is the only tier. A model-written query tier lived here
until #142; it is gone, so the eval harness runs with no model reachable.

Usage signals (hotness) must NOT be tuned against these labels: a synthetic
known-item query reflects content, not what a user actually opens, which is the
exact confound that made hotness look bad on hand labels. Tune usage signals from
real click feedback instead (a later strategy); keep them frozen here.
"""
from __future__ import annotations

import random
import re

from .eval import EvalQuery


def _target_for(path: str) -> str:
    """Label target for a note path — drop the ``.md`` so eval's substring match
    (``matches``) still fires against the ``.md`` result path."""
    return path[:-3] if path.endswith(".md") else path


def _sample_paths(conn, n: int, seed: int) -> list[str]:
    """Deterministically sample up to ``n`` note paths across the vault.

    Seeded so a run is reproducible and diffable; sorted so the label order does
    not depend on the sample draw.
    """
    rows = conn.execute("SELECT path FROM notes ORDER BY path").fetchall()
    paths = [r[0] for r in rows]
    if n and len(paths) > n:
        paths = random.Random(seed).sample(paths, n)
    return sorted(paths)


def _first_sentence(text: str) -> str:
    """First sentence of a summary, capped — enough to be a query, not the whole blurb."""
    text = text.strip()
    m = re.search(r"(.+?[.!?])(\s|$)", text)
    sentence = m.group(1) if m else text
    return sentence[:200].strip()


def heuristic_labels(conn, *, n: int = 150, seed: int = 0) -> list[EvalQuery]:
    """Summary-derived queries (title fallback), one per sampled note.

    The summary is a model-written paraphrase already sitting in the DB, so this
    is a semantic label with zero generation cost. Notes with neither a summary
    nor a title are skipped.
    """
    labels: list[EvalQuery] = []
    for path in _sample_paths(conn, n, seed):
        row = conn.execute(
            "SELECT n.title, s.summary_text FROM notes n "
            "LEFT JOIN summaries s ON s.note_path = n.path WHERE n.path = ?",
            (path,),
        ).fetchone()
        if row is None:
            continue
        title, summary = row[0], row[1]
        if summary and summary.strip():
            query, category = _first_sentence(summary), "autolabel-summary"
        elif title and title.strip():
            query, category = title.strip(), "autolabel-title"
        else:
            continue
        labels.append(EvalQuery(query=query, targets=[_target_for(path)], category=category))
    return labels

