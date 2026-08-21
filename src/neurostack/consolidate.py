# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Consolidation replay (issue #96): promote episodic memories into semantic notes.

Sleep-phase systems consolidation — hippocampal replay to neocortex. The
promotion queue (#92) computes WHICH memories should become notes; this module
is the nightly job that RUNS it:

1. Take the queue's ``debt`` + ``uncovered`` buckets (durable knowledge with no
   covering note). ``drift`` needs conflict judgment and ``dead_handoffs`` want
   forgetting, not promotion — both stay interactive work.
2. Cluster candidates by attractor basin: each memory maps to its nearest note
   (embedding argmax over chunks), the note to its coarse (level 0) Hopfield
   community. Memories with no resolvable basin group by workspace.
3. One LLM synthesis per cluster (existing ``llm_url`` failover path) — a
   consolidated section, not a raw dump.
4. Write/extend the target vault note through the existing write path
   (``vault_write_file``: validation, flock, commit + push with
   rebase-on-conflict), then archive the promoted memories with a
   ``promoted:<note_path>`` pointer (#90 archive, restorable).

``dry_run=True`` (the default everywhere) stops after step 2 and reports the
plan — no LLM calls, no writes, no archiving. A per-run ``cap`` bounds how many
clusters one night may consolidate so a backlog cannot flood the vault.
"""
from __future__ import annotations

import datetime
import logging
import re
import sqlite3

log = logging.getLogger("neurostack")

DEFAULT_CAP = 5
# At or above this similarity the cluster extends its nearest note; below it
# the knowledge has no home and a new note is created. Matches the promotion
# queue's uncovered floor so the two mechanisms agree on what "covered" means.
EXTEND_SIM_FLOOR = 0.55
_MEMORY_CHARS = 1500          # per-memory content budget in the synthesis prompt
_COARSE_LEVEL = 0             # attractor level 0 = broad basins

_SYNTH_PROMPT = """You are consolidating an engineer's session memories into their permanent \
notes vault. Below are {n} related memories from the same knowledge area.

Write ONE consolidated markdown section that preserves every concrete fact — \
identifiers, versions, hosts, paths, commands, numbers, decisions and their \
reasons. Merge overlap, keep disagreements visible, and do not invent or embellish \
anything. No preamble, no headings above ###.

Respond in EXACTLY this format — first line the title, then the section:
TITLE: <short specific title, 3-8 words>

<markdown section>

Memories:
{memories}
"""


def _strip_fences(raw: str) -> str:
    raw = re.sub(r"<think>.*?(</think>|$)", "", raw, flags=re.DOTALL).strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```\w*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw).strip()
    return raw


def _parse_synthesis(raw: str) -> dict:
    """Parse the TITLE:-line response format. Prose rides outside any JSON
    string, so backslashes/quotes in the body can never break parsing (the
    JSON contract did, on the first live rehearsal)."""
    lines = raw.split("\n")
    title = "Consolidated session knowledge"
    body_start = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.upper().startswith("TITLE:"):
            title = stripped[6:].strip() or title
            body_start = i + 1
        break
    synthesis = "\n".join(lines[body_start:]).strip()
    if not synthesis:
        raise ValueError("LLM returned an empty synthesis")
    return {"title": title, "synthesis": synthesis}


def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:60] or "consolidated"


def _memory_rows(conn: sqlite3.Connection, memory_ids: list[int]) -> list[dict]:
    if not memory_ids:
        return []
    placeholders = ",".join("?" * len(memory_ids))
    rows = conn.execute(
        f"SELECT memory_id, content, entity_type, workspace, tags, created_at,"
        f" uuid, embedding FROM memories WHERE memory_id IN ({placeholders})",
        memory_ids,
    ).fetchall()
    return [dict(r) for r in rows]


def _chunk_matrix(conn: sqlite3.Connection):
    """All chunk embeddings + their note paths, or (None, []) without any."""
    import numpy as np

    from .embedder import blob_to_embedding

    rows = conn.execute(
        "SELECT note_path, embedding FROM chunks WHERE embedding IS NOT NULL"
    ).fetchall()
    if not rows:
        return None, []
    matrix = np.vstack([blob_to_embedding(r["embedding"]) for r in rows])
    return matrix, [r["note_path"] for r in rows]


def _nearest_note(row: dict, chunk_matrix, chunk_paths) -> tuple[str | None, float]:
    from .embedder import blob_to_embedding, cosine_similarity_batch

    if chunk_matrix is None or not row.get("embedding"):
        return None, 0.0
    emb = blob_to_embedding(row["embedding"])
    if emb is None:
        return None, 0.0
    sims = cosine_similarity_batch(emb, chunk_matrix)
    best = int(sims.argmax())
    return chunk_paths[best], float(sims[best])


def _note_community(conn: sqlite3.Connection, note_path: str) -> int | None:
    row = conn.execute(
        "SELECT cm.community_id FROM community_members cm"
        " JOIN communities c ON c.community_id = cm.community_id"
        " WHERE cm.entity = ? AND c.level = ?",
        (note_path, _COARSE_LEVEL),
    ).fetchone()
    return row["community_id"] if row else None


def cluster_candidates(
    conn: sqlite3.Connection,
    workspace: str | None = None,
) -> list[dict]:
    """Compute the night's clusters from the promotion queue. Pure read.

    Returns a list of cluster dicts sorted largest-first (biggest debt relief),
    each carrying its members (full memory rows + nearest-note info), the
    planned action ('extend' or 'create'), and the planned target path.
    """
    from .promotion import compute_promotion_queue

    queue = compute_promotion_queue(conn, workspace=workspace)
    seen: set[int] = set()
    candidate_ids: list[int] = []
    for bucket in ("debt", "uncovered"):
        for entry in queue[bucket]:
            if entry["memory_id"] not in seen:
                seen.add(entry["memory_id"])
                candidate_ids.append(entry["memory_id"])
    if not candidate_ids:
        return []

    chunk_matrix, chunk_paths = _chunk_matrix(conn)
    clusters: dict[object, dict] = {}
    for row in _memory_rows(conn, candidate_ids):
        note, sim = _nearest_note(row, chunk_matrix, chunk_paths)
        community = _note_community(conn, note) if note else None
        key = community if community is not None else f"ws:{row.get('workspace') or ''}"
        cluster = clusters.setdefault(key, {
            "basin": key, "members": [],
        })
        row["nearest_note"] = note
        row["nearest_similarity"] = round(sim, 4)
        cluster["members"].append(row)

    out = []
    for cluster in clusters.values():
        members = cluster["members"]
        best = max(members, key=lambda m: m["nearest_similarity"])
        if best["nearest_note"] and best["nearest_similarity"] >= EXTEND_SIM_FLOOR:
            cluster["action"] = "extend"
            cluster["target"] = best["nearest_note"]
        else:
            cluster["action"] = "create"
            cluster["target"] = None  # named after synthesis; folder decided now
            ws = [m.get("workspace") for m in members if m.get("workspace")]
            cluster["target_folder"] = max(set(ws), key=ws.count) if ws else "inbox"
        out.append(cluster)

    out.sort(key=lambda c: (-len(c["members"]), str(c["basin"])))
    return out


def _synthesize(
    members: list[dict],
    llm_url: str,
    llm_model: str,
    api_key: str = "",
) -> dict:
    """One LLM synthesis for a cluster. Raises on failure — caller skips cluster."""
    import httpx

    from .config import _auth_headers

    blocks = []
    for m in members:
        blocks.append(
            f"[memory {m['memory_id']} · {m['entity_type']} · {m['created_at']}]\n"
            f"{(m['content'] or '')[:_MEMORY_CHARS]}"
        )
    prompt = _SYNTH_PROMPT.format(n=len(members), memories="\n\n".join(blocks))

    resp = httpx.post(
        f"{llm_url}/v1/chat/completions",
        headers=_auth_headers(api_key),
        json={
            "model": llm_model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "temperature": 0.2,
            "max_tokens": 1500,
        },
        timeout=300.0,
    )
    resp.raise_for_status()
    raw = _strip_fences(resp.json()["choices"][0]["message"]["content"])
    return _parse_synthesis(raw)


def _sources_block(members: list[dict]) -> str:
    lines = [
        f"- memory {m['memory_id']} ({m['entity_type']}, {m['created_at']})"
        for m in members
    ]
    return "Sources (archived memories):\n" + "\n".join(lines)


def _new_note_content(title: str, synthesis: str, members: list[dict]) -> str:
    today = datetime.date.today().isoformat()
    return (
        f"---\ndate: {today}\ntags: [consolidated]\ntype: note\n---\n\n"
        f"# {title}\n\n{synthesis}\n\n{_sources_block(members)}\n"
    )


def _extended_content(existing: str, title: str, synthesis: str,
                      members: list[dict]) -> str:
    today = datetime.date.today().isoformat()
    return (
        existing.rstrip("\n")
        + f"\n\n## {title} (consolidated {today})\n\n"
        + synthesis
        + "\n\n"
        + _sources_block(members)
        + "\n"
    )


def consolidate_replay(
    conn: sqlite3.Connection,
    cap: int = DEFAULT_CAP,
    dry_run: bool = True,
    workspace: str | None = None,
    llm_url: str | None = None,
    llm_model: str | None = None,
) -> dict:
    """Run one consolidation replay pass. Returns a report dict.

    Dry run (default): cluster + plan only — no LLM, no writes, no archiving.
    Real run: per cluster synthesize -> write/extend note -> archive members
    with a ``promoted:<note_path>`` reason. A cluster is archived ONLY after
    its note write committed AND pushed; any per-cluster failure skips that
    cluster and is reported, never aborting the rest of the night.
    """
    from .config import get_config

    cfg = get_config()
    llm_url = llm_url or cfg.llm_url
    llm_model = llm_model or cfg.llm_model

    clusters = cluster_candidates(conn, workspace=workspace)
    planned = clusters[: max(0, cap)]
    report: dict = {
        "dry_run": dry_run,
        "cap": cap,
        "clusters_found": len(clusters),
        "clusters_planned": len(planned),
        "consolidated": [],
        "skipped": [],
    }

    def _plan(cluster: dict) -> dict:
        return {
            "basin": str(cluster["basin"]),
            "action": cluster["action"],
            "target": cluster["target"] or f"{cluster.get('target_folder')}/<slug>.md",
            "memory_ids": [m["memory_id"] for m in cluster["members"]],
        }

    if dry_run:
        report["consolidated"] = [_plan(c) for c in planned]
        report["deferred"] = [_plan(c) for c in clusters[cap:]]
        return report

    from .memories import _archive_memories
    from .tools import file_tools

    for cluster in planned:
        plan = _plan(cluster)
        members = cluster["members"]
        try:
            synth = _synthesize(members, llm_url, llm_model, cfg.llm_api_key)
        except Exception as exc:
            plan["error"] = f"synthesis failed: {exc}"
            report["skipped"].append(plan)
            continue

        if cluster["action"] == "extend":
            target = cluster["target"]
            abs_path = file_tools._vault_root() / target
            try:
                existing = abs_path.read_text(encoding="utf-8")
            except OSError as exc:
                plan["error"] = f"target note unreadable: {exc}"
                report["skipped"].append(plan)
                continue
            content = _extended_content(existing, synth["title"],
                                        synth["synthesis"], members)
        else:
            target = f"{cluster['target_folder']}/{_slugify(synth['title'])}.md"
            content = _new_note_content(synth["title"], synth["synthesis"], members)

        result = file_tools.vault_write_file(
            target, content,
            commit_message=f"consolidate: {target} (nightly replay, issue #96)",
        )
        if not result.get("pushed"):
            reason = result.get("git_error") or result.get("error") or "unknown"
            plan["error"] = f"write not pushed: {reason}"
            report["skipped"].append(plan)
            continue

        ids = [m["memory_id"] for m in members]
        archived = _archive_memories(
            conn,
            f"memory_id IN ({','.join('?' * len(ids))})",
            tuple(ids),
            f"promoted:{target}",
        )
        conn.commit()
        plan["target"] = target
        plan["title"] = synth["title"]
        plan["archived"] = archived
        plan["commit_sha"] = result.get("commit_sha")
        report["consolidated"].append(plan)
        log.info("Consolidated %d memories into %s", archived, target)

    return report
