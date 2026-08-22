# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Observation -> learning synthesis (issue #36): consolidate aged observation
heaps into single durable learnings.

Memory capture skews raw — observations pile up ~3.5x faster than learnings,
and near-duplicate observations about the same topic bury the insight they
collectively contain. This module is the rework pass:

1. Candidates: ``observation`` memories older than ``min_age_days`` that are
   alive (not expired) and not already superseded by an earlier synthesis run.
2. Cluster on stored embeddings: greedy anchor grouping, oldest anchor first,
   pairwise cosine >= ``threshold``. A cluster needs the anchor plus at least
   ``min_siblings`` related observations. Candidates without an embedding are
   reported, never silently dropped (#29 backfill heals them).
3. One LLM synthesis per cluster (same ``llm_url`` path as consolidation) — a
   single consolidated ``learning`` memory that preserves every concrete fact.
4. Save the learning through ``save_memory``, then tag each original with
   ``superseded_by:<new_memory_id>``. Originals are tagged, NEVER deleted or
   archived — the tag excludes them from future synthesis runs and keeps the
   provenance chain walkable in both directions.

``dry_run=True`` (the default everywhere) stops after step 2 and reports the
plan — no LLM calls, no writes. A per-run ``cap`` bounds how many clusters one
pass may synthesize so a backlog cannot flood the memory store.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3

log = logging.getLogger("neurostack")

DEFAULT_CAP = 5
DEFAULT_MIN_AGE_DAYS = 7
DEFAULT_MIN_SIBLINGS = 3
# Live-calibrated on the prod embedder (embeddinggemma:300m) against the real
# memory store: 0.35-0.55 chains dense early-harvest noise into 100+ member
# mega-clusters; 0.65 yields coherent 4-15 member topic groups. Paraphrases
# (~0.93) are handled earlier by harvest dedup — synthesis clusters are the
# same-topic tier.
SIBLING_THRESHOLD = 0.65
# Hard per-cluster member ceiling: one learning cannot faithfully preserve the
# facts of an unbounded heap, and the prompt must stay bounded. Oversized
# clusters keep the anchor plus its most similar members; the rest stay
# unsuperseded and regroup on a later pass.
MAX_CLUSTER = 20
_MEMORY_CHARS = 1500          # per-observation content budget in the prompt
_SUPERSEDED_PREFIX = "superseded_by:"

_SYNTH_PROMPT = """You are consolidating an engineer's raw session observations into one \
durable learning. Below are {n} related observations about the same topic.

Write ONE consolidated learning — the insight the observations collectively \
support — preserving every concrete fact: identifiers, versions, hosts, paths, \
commands, numbers. Merge overlap, keep disagreements visible, and do not invent \
or embellish anything. Respond with the learning text only: no preamble, no \
headings, no quotes around it.

Observations:
{observations}
"""


def _strip_fences(raw: str) -> str:
    raw = re.sub(r"<think>.*?(</think>|$)", "", raw, flags=re.DOTALL).strip()
    raw = re.sub(r"^```[a-z]*\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw)
    return raw.strip()


def _candidate_rows(
    conn: sqlite3.Connection,
    min_age_days: int,
    workspace: str | None = None,
) -> list[dict]:
    """Alive, non-superseded observations older than min_age_days, oldest first."""
    where = [
        "entity_type = 'observation'",
        "created_at <= datetime('now', ?)",
        "(expires_at IS NULL OR expires_at > datetime('now'))",
        "COALESCE(tags, '') NOT LIKE ?",
    ]
    params: list = [f"-{int(min_age_days)} days", f"%{_SUPERSEDED_PREFIX}%"]
    if workspace:
        ws = workspace.strip("/")
        where.append("(workspace = ? OR workspace LIKE ? || '/%')")
        params.extend([ws, ws])
    rows = conn.execute(
        f"SELECT * FROM memories WHERE {' AND '.join(where)} ORDER BY created_at",
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def cluster_observations(
    conn: sqlite3.Connection,
    min_age_days: int = DEFAULT_MIN_AGE_DAYS,
    min_siblings: int = DEFAULT_MIN_SIBLINGS,
    threshold: float = SIBLING_THRESHOLD,
    max_cluster: int = MAX_CLUSTER,
    workspace: str | None = None,
) -> tuple[list[dict], int]:
    """Greedy anchor clustering over stored embeddings. Pure read.

    Returns (clusters, no_embedding_count). Each cluster dict carries its
    member rows, oldest-anchor first. Clusters below ``1 + min_siblings``
    members are discarded — a heap that small is not yet worth consolidating.
    Clusters above ``max_cluster`` keep the anchor plus its most similar
    members; the overflow stays available for a later pass.
    """
    from .embedder import HAS_NUMPY, blob_to_embedding, cosine_similarity_batch

    if not HAS_NUMPY:
        raise ImportError(
            "Synthesis requires numpy. Install with: pip install neurostack[full]"
        )
    import numpy as np

    rows = _candidate_rows(conn, min_age_days, workspace=workspace)
    embedded: list[dict] = []
    no_embedding = 0
    vectors = []
    for r in rows:
        if not r.get("embedding"):
            no_embedding += 1
            continue
        try:
            vectors.append(blob_to_embedding(r["embedding"]))
        except ValueError:
            no_embedding += 1
            continue
        embedded.append(r)
    if len(embedded) < 1 + min_siblings:
        return [], no_embedding

    matrix = np.stack(vectors)
    assigned = [False] * len(embedded)
    clusters: list[dict] = []
    for i, anchor in enumerate(embedded):
        if assigned[i]:
            continue
        sims = cosine_similarity_batch(matrix[i], matrix)
        member_idx = [
            j for j in range(len(embedded))
            if not assigned[j] and (j == i or sims[j] >= threshold)
        ]
        if len(member_idx) < 1 + min_siblings:
            continue
        if len(member_idx) > max_cluster:
            member_idx = sorted(
                member_idx, key=lambda j: (j != i, -sims[j])
            )[:max_cluster]
            member_idx.sort()
        for j in member_idx:
            assigned[j] = True
        clusters.append({
            "anchor_id": anchor["memory_id"],
            "members": [embedded[j] for j in member_idx],
        })

    clusters.sort(key=lambda c: -len(c["members"]))
    return clusters, no_embedding


def _synthesize(
    members: list[dict],
    llm_url: str,
    llm_model: str,
    api_key: str = "",
) -> str:
    """One LLM synthesis for a cluster. Raises on failure — caller skips cluster."""
    import httpx

    from .config import _auth_headers

    blocks = []
    for m in members:
        blocks.append(
            f"[memory {m['memory_id']} · {m['created_at']}]\n"
            f"{(m['content'] or '')[:_MEMORY_CHARS]}"
        )
    prompt = _SYNTH_PROMPT.format(n=len(members), observations="\n\n".join(blocks))

    resp = httpx.post(
        f"{llm_url}/v1/chat/completions",
        headers=_auth_headers(api_key),
        json={
            "model": llm_model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "temperature": 0.2,
            "max_tokens": 1000,
        },
        timeout=300.0,
    )
    resp.raise_for_status()
    content = _strip_fences(resp.json()["choices"][0]["message"]["content"])
    if not content:
        raise ValueError("LLM returned an empty synthesis")
    return content


def _cluster_tags(members: list[dict], limit: int = 8) -> list[str]:
    """Union of member tags by frequency, synthesis marker last."""
    counts: dict[str, int] = {}
    for m in members:
        try:
            for t in json.loads(m.get("tags") or "[]"):
                t = t.strip() if isinstance(t, str) else ""
                if t and not t.startswith(_SUPERSEDED_PREFIX):
                    counts[t] = counts.get(t, 0) + 1
        except (TypeError, ValueError):
            continue
    ranked = sorted(counts, key=lambda t: (-counts[t], t))[:limit]
    return [*ranked, "synthesized"]


def _majority_workspace(members: list[dict]) -> str | None:
    ws = [m.get("workspace") for m in members if m.get("workspace")]
    return max(set(ws), key=ws.count) if ws else None


def observation_learning_ratio(conn: sqlite3.Connection) -> dict:
    """Active (non-superseded, non-expired) observation:learning counts."""
    row = conn.execute(
        """
        SELECT
          SUM(CASE WHEN entity_type = 'observation'
              AND COALESCE(tags, '') NOT LIKE ? THEN 1
              ELSE 0 END) AS observations,
          SUM(CASE WHEN entity_type = 'learning' THEN 1 ELSE 0 END) AS learnings
        FROM memories
        WHERE expires_at IS NULL OR expires_at > datetime('now')
        """,
        (f"%{_SUPERSEDED_PREFIX}%",),
    ).fetchone()
    observations = row["observations"] or 0
    learnings = row["learnings"] or 0
    return {
        "observations": observations,
        "learnings": learnings,
        "ratio": round(observations / learnings, 2) if learnings else None,
    }


def synthesize_observations(
    conn: sqlite3.Connection,
    cap: int = DEFAULT_CAP,
    dry_run: bool = True,
    min_age_days: int = DEFAULT_MIN_AGE_DAYS,
    min_siblings: int = DEFAULT_MIN_SIBLINGS,
    threshold: float = SIBLING_THRESHOLD,
    max_cluster: int = MAX_CLUSTER,
    workspace: str | None = None,
    llm_url: str | None = None,
    llm_model: str | None = None,
    embed_url: str | None = None,
) -> dict:
    """Run one synthesis pass. Returns a report dict.

    Dry run (default): cluster + plan only — no LLM, no writes. Real run: per
    cluster synthesize -> save one ``learning`` -> tag each original with
    ``superseded_by:<learning_id>``. Any per-cluster failure skips that
    cluster and is reported, never aborting the rest of the pass.
    """
    from .config import get_config

    cfg = get_config()
    llm_url = llm_url or cfg.llm_url
    llm_model = llm_model or cfg.llm_model

    clusters, no_embedding = cluster_observations(
        conn, min_age_days=min_age_days, min_siblings=min_siblings,
        threshold=threshold, max_cluster=max_cluster, workspace=workspace,
    )
    planned = clusters[: max(0, cap)]
    report: dict = {
        "dry_run": dry_run,
        "cap": cap,
        "min_age_days": min_age_days,
        "min_siblings": min_siblings,
        "threshold": threshold,
        "max_cluster": max_cluster,
        "clusters_found": len(clusters),
        "clusters_planned": len(planned),
        "candidates_without_embedding": no_embedding,
        "ratio_before": observation_learning_ratio(conn),
        "synthesized": [],
        "skipped": [],
    }

    def _plan(cluster: dict) -> dict:
        return {
            "anchor_id": cluster["anchor_id"],
            "memory_ids": [m["memory_id"] for m in cluster["members"]],
        }

    if dry_run:
        report["synthesized"] = [_plan(c) for c in planned]
        report["deferred"] = [_plan(c) for c in clusters[cap:]]
        report["ratio_after"] = report["ratio_before"]
        return report

    from .memories import save_memory, update_memory

    for cluster in planned:
        plan = _plan(cluster)
        members = cluster["members"]
        try:
            learning = _synthesize(members, llm_url, llm_model, cfg.llm_api_key)
        except Exception as exc:
            plan["error"] = f"synthesis failed: {exc}"
            report["skipped"].append(plan)
            continue

        try:
            memory = save_memory(
                conn, content=learning,
                tags=_cluster_tags(members),
                entity_type="learning",
                source_agent="synthesize",
                workspace=_majority_workspace(members),
                embed_url=embed_url,
                dedup=False,
            )
        except Exception as exc:
            plan["error"] = f"save failed: {exc}"
            report["skipped"].append(plan)
            continue

        for m in members:
            update_memory(
                conn, m["memory_id"],
                add_tags=[f"{_SUPERSEDED_PREFIX}{memory.memory_id}"],
            )
        conn.commit()
        plan["learning_id"] = memory.memory_id
        plan["learning"] = learning
        report["synthesized"].append(plan)
        log.info("Synthesized %d observations into learning %d",
                 len(members), memory.memory_id)

    report["ratio_after"] = observation_learning_ratio(conn)
    return report
