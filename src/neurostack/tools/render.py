# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Markdown for the replies an MCP client reads (issue #318).

The tool functions return dicts, and the CLI ``--json``, the OpenAI-compatible
API and the hook client consume those dicts as they are. A model reading an MCP
reply pays for every brace, quote and indent of pretty-printed JSON, so the MCP
adapter passes the replies of the tools in ``RENDERERS`` through ``render``.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

from ..memories import _BOOKKEEPING_TAG

log = logging.getLogger("neurostack.tools.render")

_TRUNCATED = "Truncated. Pass a larger max_tokens to see more."


def _compact(result: Any) -> str:
    return json.dumps(result, separators=(",", ":"), ensure_ascii=False, default=str)


def _heading(item: dict) -> str:
    path = item.get("path") or item["note"]
    title = item.get("title")
    head = f"### {title} ({path})" if title and title != path else f"### {path}"
    section = item.get("section")
    return f"{head} › {section}" if section and section != title else head


def _entry(item: dict) -> str:
    """A note hit: heading, then whichever of summary and snippet it carries."""
    lines = [_heading(item)]
    for key in ("summary", "snippet"):
        text = (item.get(key) or "").strip()
        if text and text not in lines:
            lines.append(text)
    return "\n".join(lines)


def _triples(triples: list[dict]) -> list[str]:
    """One block per note, its facts listed once under a single heading."""
    by_note: dict[str, list[dict]] = {}
    for t in triples:
        by_note.setdefault(t["note"], []).append(t)
    # The index can hold one fact several times over, so drop repeats (#320).
    return [
        _heading(facts[0]) + "\n" + "\n".join(dict.fromkeys(
            f"- {t['s']} → {t['p']} → {t['o']}" for t in facts
        ))
        for facts in by_note.values()
    ]


def _memory(m: dict) -> str:
    head = [f"#{m['memory_id']} {m.get('entity_type') or 'memory'}"]
    if m.get("created_at"):
        head.append(str(m["created_at"])[:10])
    if m.get("workspace"):
        head.append(m["workspace"])
    if m.get("expires_at"):
        head.append(f"expires {str(m['expires_at'])[:10]}")
    lines = [" · ".join(head), m["content"]]
    # Bookkeeping tags tell the reader nothing about the memory (#311).
    tags = [t for t in m.get("tags") or [] if not _BOOKKEEPING_TAG.search(t)]
    if tags:
        lines.append("tags: " + ", ".join(tags))
    return "\n".join(lines)


def _section(title: str, blocks: list[str]) -> list[str]:
    return [f"## {title}", *blocks] if blocks else []


def _project(p: dict) -> str:
    return f"{_heading(p)} · updated {p['updated']}\n{p['status']}"


def _search(r: dict) -> str:
    if "results" in r:
        parts = _section("Results", [_entry(x) for x in r["results"]])
    else:
        parts = [
            *_section("Facts", _triples(r["triples"])),
            *_section("Summaries", [_entry(x) for x in r["summaries"]]),
            *_section("Chunks", [_entry(x) for x in r["chunks"]]),
        ]
    parts += _section("Memories", [_memory(m) for m in r.get("memories") or []])
    if not parts:
        parts = ["No results."]
    if r.get("reranked"):
        parts.insert(0, "Reranked by the judgement model, best first.")
    # The project note's own status leads, ahead of older hits (#322).
    parts[:0] = _section("Project status", [_project(p) for p in r.get("projects") or []])
    if r.get("hint"):
        parts.append(r["hint"])
    if r.get("truncated"):
        parts.append(_TRUNCATED)
    return "\n\n".join(parts)


def _memories(r: dict) -> str:
    text = "\n\n".join(_memory(m) for m in r["memories"]) or "No memories."
    return f"{text}\n\n{_TRUNCATED}" if r.get("truncated") else text


def _triples_reply(r: dict) -> str:
    return "\n\n".join(_triples(r["triples"])) or "No facts."


def _summary(r: dict) -> str:
    return f"{_heading(r)}\n{r['summary']}"


def _related(r: dict) -> str:
    return "\n\n".join(_entry(x) for x in r["related"]) or "No related notes."


def _node(n: dict) -> str:
    lines = [f"{_heading(n)} · in {n['in_degree']} · out {n['out_degree']}"]
    if n.get("summary"):
        lines.append(n["summary"].strip())
    return "\n".join(lines)


def _graph(r: dict) -> str:
    neighbors = [_node(n) for n in r["neighbors"]]
    return "\n\n".join(
        [_node(r["center"]), *_section(f"Neighbors ({len(neighbors)})", neighbors)]
    )


def _communities(r: dict) -> str:
    hits = r["community_hits"]
    parts = [r["answer"].strip()] if r.get("answer") else []
    if parts:
        # The answer already carries the substance; name its sources only.
        parts += _section("Communities", [f"- {h['title']}" for h in hits])
    else:
        parts += [f"### {h['title']}\n{h['summary'].strip()}" for h in hits]
    build = r.get("community_build") or {}
    if build.get("stale"):
        parts.append(f"Community map is stale. {build.get('reason') or ''}".strip())
    return "\n\n".join(parts) or "No communities."


def _remember(r: dict) -> str:
    line = f"Saved memory #{r['memory_id']} ({r['entity_type']})"
    if r.get("expires_at"):
        line += f", expires {str(r['expires_at'])[:10]}"
    parts = [line + "."]
    dupes = r.get("near_duplicates") or []
    if dupes:
        parts.append("Near duplicates, merge with vault_merge if they say the same:")
        parts += [
            f"- #{d['memory_id']} · {str(d.get('created_at') or '')[:10]} · {d['content']}"
            for d in dupes
        ]
    if r.get("suggested_tags"):
        parts.append("Suggested tags: " + ", ".join(r["suggested_tags"]))
    return "\n".join(parts)


def _update(r: dict) -> str:
    fields = ", ".join(r["changed_fields"]) or "nothing"
    return f"Updated memory #{r['memory_id']} ({fields})."


def _read_file(r: dict) -> str:
    """The note as it sits on disk under one line naming it (#320)."""
    if not r["exists"]:
        return f"Not found: {r['path']}"
    head = f"{r['path']} · {r['size_bytes']} bytes"
    if r.get("truncated"):
        head += f" · truncated, next offset {r['offset'] + len(r['content'])}"
    return f"{head}\n{r['content']}"


RENDERERS: dict[str, Callable[[dict], str]] = {
    "vault_search": _search,
    "vault_memories": _memories,
    "vault_triples": _triples_reply,
    "vault_summary": _summary,
    "vault_related": _related,
    "vault_graph": _graph,
    "vault_communities": _communities,
    "vault_remember": _remember,
    "vault_update_memory": _update,
    "vault_read_file": _read_file,
}


def render(name: str, result: Any) -> str:
    """Markdown for ``name``'s reply, or compact JSON when the shape is unknown."""
    if isinstance(result, dict) and result.get("error"):
        return f"Error: {result['error']}"
    try:
        return RENDERERS[name](result)
    except Exception:
        log.debug("No Markdown for %s reply, sending compact JSON", name, exc_info=True)
        return _compact(result)
