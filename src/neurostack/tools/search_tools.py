# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Search and retrieval tools — registered against the singleton registry."""

from __future__ import annotations

import logging
import math
import re
from collections import Counter
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from .registry import ToolAnnotationHints as Hints
from .registry import registry

# Annotation constants
_READ_ONLY = Hints(read_only=True, open_world=False)
_WRITE_ADDITIVE = Hints(read_only=False, destructive=False, idempotent=True, open_world=False)

log = logging.getLogger("neurostack.tools.search")

# Ceiling for depth "auto" and "summaries" when the caller passes no max_tokens
# (issue #310). Uncapped live replies ran 1,700 to 3,000 tokens per copy, and
# the largest triples + summaries + merged ranking measured was 1,843, so 2,000
# keeps every note and fact whole and trims the trailing memories first.
DEFAULT_TIERED_MAX_TOKENS = 2000

# Issue #322: a reply that hits notes inside projects/<slug>/ carries the
# project note's status, because sibling notes and memories go stale while the
# project note moves on. Two projects at ~800 chars each stay well inside the
# 2,000-token default.
MAX_PROJECTS = 2
_STATUS_CHARS = 800
_LEAD_CHARS = 600
_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
_FENCE = re.compile(r"^```.*?^```", re.MULTILINE | re.DOTALL)
_STATUS_HEADING = re.compile(
    r"(?:project\s+)?(?:status|state|current|progress)\b", re.IGNORECASE
)
_OPEN_HEADING = re.compile(r"(?:open|next|to-?do)\b", re.IGNORECASE)
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
# Words too common to tell one project folder from another (#324).
_STOPWORDS = frozenset({"a", "an", "and", "for", "in", "of", "on", "the", "to", "via", "with"})


def _cfg():
    from ..config import get_config
    cfg = get_config()
    return cfg.vault_root, cfg.embed_url


def _community_level_stats(conn) -> list[dict]:
    """Return per-level community partition stats (size distribution + modularity).

    Reads community_level_stats populated by attractor.detect_communities.
    Empty list if the table doesn't exist yet or no levels have been written.
    """
    try:
        rows = conn.execute(
            "SELECT level, n_communities, min_size, max_size, mean_size,"
            " modularity FROM community_level_stats ORDER BY level"
        ).fetchall()
    except Exception:
        return []
    def _label(level: int) -> str:
        if level == 0:
            return "coarse"
        if level == 1:
            return "fine"
        return f"level{level}"

    return [
        {
            "level": r["level"],
            "label": _label(r["level"]),
            "n_communities": r["n_communities"],
            "min_size": r["min_size"],
            "max_size": r["max_size"],
            "mean_size": (
                round(r["mean_size"], 2) if r["mean_size"] is not None else None
            ),
            "modularity": (
                round(r["modularity"], 4) if r["modularity"] is not None else None
            ),
        }
        for r in rows
    ]


def _search_memories_for_results(
    query: str, workspace: str | None = None, limit: int = 3
) -> list[dict]:
    """Search memories and return compact results for inclusion in vault_search."""
    try:
        from ..memories import search_memories
        from ..schema import DB_PATH, get_db

        _, embed_url = _cfg()
        conn = get_db(DB_PATH)
        memories = search_memories(
            conn, query=query, workspace=workspace,
            limit=limit, embed_url=embed_url,
        )
        return [
            {
                "memory_id": m.memory_id,
                "content": m.content,
                "entity_type": m.entity_type,
                "source": m.source_agent,
                "created_at": m.created_at,
            }
            for m in memories
            if m.score > 0.35
        ]
    except Exception:
        return []


def _hit_paths(result: dict):
    """Note paths in the order the reply ranks them, best first."""
    for key in ("results", "merged_ranking", "summaries", "chunks", "triples"):
        for item in result.get(key) or []:
            yield item.get("path") or item["note"]


def _sections(body: str) -> list[tuple[str, str]]:
    """(heading, text) per heading, each running to the next of its level or above.

    Lines that look like headings inside code fences are shell comments, not
    headings, so they neither open nor close a section.
    """
    fences = [m.span() for m in _FENCE.finditer(body)]
    heads = [
        h for h in _HEADING.finditer(body)
        if not any(a <= h.start() < b for a, b in fences)
    ]
    sections = []
    for n, h in enumerate(heads):
        level = len(h.group(1))
        end = next(
            (x.start() for x in heads[n + 1:] if len(x.group(1)) <= level), len(body)
        )
        sections.append((h.group(2), body[h.end():end].strip()))
    return sections


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def _status_text(body: str) -> str:
    """The part of a project note that says where the project stands (#322).

    The first section headed status, state, current or progress. Most project
    notes have none, so next comes the section whose heading carries the newest
    ISO date plus the open, next or todo section, sharing the budget. The
    opening of the body only when neither exists.
    """
    sections = _sections(body)
    status = next((t for h, t in sections if _STATUS_HEADING.match(h)), None)
    if status is not None:
        return _clip(status, _STATUS_CHARS)
    dated = [(max(_ISO_DATE.findall(h)), h, t) for h, t in sections if _ISO_DATE.search(h)]
    picks = [max(dated)[1:]] if dated else []
    picks += [(h, t) for h, t in sections if _OPEN_HEADING.match(h)][:1]
    picks = list(dict.fromkeys(picks))
    if not picks:
        return _clip(body.strip(), _LEAD_CHARS)
    share = _STATUS_CHARS // len(picks)
    return "\n\n".join(_clip(f"**{h}**\n{t}", share) for h, t in picks)


def _words(text: str) -> frozenset[str]:
    return frozenset(re.findall(r"[a-z0-9]+", text.lower())) - _STOPWORDS


def _read_project_note(root: Path, folder: str, slug: str) -> tuple[str, str, Path] | None:
    """(name, text, absolute path) of ``<slug>.md``, else ``index.md``, in `folder`."""
    from .file_tools import PathSafetyError, _safe_path

    for name in (f"{slug}.md", "index.md"):
        try:
            abs_path = _safe_path(f"{folder}/{name}", root)
            return name, abs_path.read_text(encoding="utf-8"), abs_path
        except (PathSafetyError, OSError, UnicodeDecodeError):
            continue
    return None


def _title_and_body(text: str, slug: str) -> tuple[str, str]:
    """The note's H1, else `slug`, and the body after frontmatter and H1."""
    from .file_tools import _FRONTMATTER_RE

    fm = _FRONTMATTER_RE.match(text)
    body = text[fm.end():] if fm else text
    h1 = re.match(r"\s*# (.+)\n?", body)
    return (h1.group(1).strip(), body[h1.end():]) if h1 else (slug, body)


@lru_cache(maxsize=32)
def _project_words(root: Path, projects_dir: str, mtime: float) -> dict[str, frozenset[str]]:
    """Slug and project note title words of every folder in `projects_dir` (#324).

    Keyed on the directory's mtime, so adding or removing a project folder reads
    the listing afresh. A retitled note keeps its old words until restart.
    """
    words = {}
    for entry in (root / projects_dir).iterdir():
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        note = _read_project_note(root, f"{projects_dir}/{entry.name}", entry.name)
        title = _title_and_body(note[1], entry.name)[0] if note else ""
        words[entry.name] = _words(entry.name) | _words(title)
    return words


def _project_status(result: dict, query: str) -> list[dict]:
    """Status of the projects the query and its hits point at (#322, #324).

    Candidates are the folders of every projects/ directory that holds a hit. A
    folder ranks by the query words its slug and project note title share, each
    weighted by how few folders carry it, then by its best hit. A folder without
    a hit needs one shared word. Hit order alone put a project that shared one
    common word ahead of the one the query named (#324).

    The project note is ``projects/<slug>/<slug>.md``, else ``index.md`` in the
    same folder; `_status_text` picks the part of it to show.
    """
    from .file_tools import PathSafetyError, _safe_dir, _vault_root

    root = _vault_root()
    first_hit: dict[str, int] = {}
    dirs: set[str] = set()
    for n, path in enumerate(_hit_paths(result)):
        parts = path.split("/")
        if "projects" not in parts:
            continue
        i = parts.index("projects")
        if len(parts) < i + 3:  # projects/<note>.md sits in no project folder
            continue
        dirs.add("/".join(parts[: i + 1]))
        first_hit.setdefault("/".join(parts[: i + 2]), n)

    folders: dict[str, frozenset[str]] = dict.fromkeys(first_hit, frozenset())
    for d in dirs:
        try:
            listing = _project_words(root, d, _safe_dir(d, root).stat().st_mtime)
        except (PathSafetyError, OSError):
            continue
        folders.update((f"{d}/{slug}", words) for slug, words in listing.items())
    df = Counter(w for words in folders.values() for w in words)
    query_words = _words(query)
    match = {
        f: sum(math.log(1 + len(folders) / df[w]) for w in words & query_words)
        for f, words in folders.items()
    }
    ranked = sorted(
        (f for f in folders if f in first_hit or match[f] > 0),
        key=lambda f: (-match[f], first_hit.get(f, math.inf)),
    )

    projects: list[dict] = []
    for folder in ranked:
        slug = folder.rsplit("/", 1)[1]
        note = _read_project_note(root, folder, slug)
        if note is None:
            continue
        name, text, abs_path = note
        title, body = _title_and_body(text, slug)
        mtime = abs_path.stat().st_mtime
        projects.append({
            "path": f"{folder}/{name}",
            "title": title,
            "updated": datetime.fromtimestamp(mtime, timezone.utc).date().isoformat(),
            "status": _status_text(body),
        })
        if len(projects) == MAX_PROJECTS:
            break
    return projects


@registry.tool(tags=["search", "retrieval"], annotations=_READ_ONLY)
def vault_search(
    query: str,
    top_k: int = 5,
    mode: str = "hybrid",
    depth: str = "auto",
    context: str | None = None,
    workspace: str | None = None,
    max_tokens: int | None = None,
    reference_only: bool = False,
    rerank: bool = False,
) -> dict:
    """Search the vault. One query, results ranked best first.

    Pick `depth` by what you are going to do with the answer:

    - Answering a factual question ("what IP", "which model") -> "triples".
    - Deciding which note to open -> "summaries", or reference_only=True.
    - About to edit or act on a note's content -> "full".
    - Unsure -> leave "auto", which starts cheap and escalates.

    Transcript evidence says agents mostly leave "auto" and sometimes invent
    values like "shallow" or "quick". Only the four names above are accepted;
    anything else raises rather than silently falling back, because a silent
    fallback reads as a working search returning the wrong footprint.

    Args:
        query: Natural language. Three or more words beats one; the index is
            hybrid, so distinguishing nouns (hostnames, project names, error
            strings) matter more than phrasing.
        top_k: Results to return, default 5. Raise to 10 when scanning.
        mode: "hybrid" (default), "semantic", or "keyword". Leave it alone
            unless keyword-exact matching is the point.
        depth: "triples" (~10-20 tokens/fact), "summaries" (~50-100
            tokens/note), "full" (~200-500 tokens/result), or "auto".
        context: Optional project or domain hint for boosting.
        workspace: Vault subdirectory prefix to restrict results,
            e.g. "work/acme-cloud".
        max_tokens: Size ceiling (~4 chars/token). Trims on top of `depth`
            across every depth and the reference list, so an explicit budget
            is never a silent no-op. The response carries "truncated": True.
            Depth "auto" and "summaries" default to 2000 tokens over the whole
            reply, memories included, cutting memories first, then chunks,
            summaries and triples from the tail. Pass a larger max_tokens to
            get more when the reply says "truncated".
        reference_only: Return {path, score, snippet} only, no bodies, plus a
            hint to fetch detail with vault_read_file(path, offset, limit).
            Ignores `depth`. Cheapest way to scan then commit to one read.
        rerank: Judge each result against the query with a judgement model and
            reorder best-first. Off by default and adds roughly 0.4s, so ask for
            it when precision matters more than speed. Applies to depth="full"
            and reference_only, the two paths that rank whole notes. Measured on
            76 real clicks: MRR 0.503 to 0.652, top-3 56.6% to 75.0%. Fails open
            to the normal ordering.

    The response shape follows the depth. "full" and reference_only return
    `results`. "triples", "summaries" and "auto" return `depth_used` plus
    whichever of `triples`, `summaries`, `chunks` was served. When a hit sits
    in a projects/<slug>/ folder, `projects` carries up to two project notes'
    current status, which outranks older sibling notes and memories. Projects
    whose folder name or title shares the query's words come first.

    After reading a result, call vault_record_usage([path]) once with every
    path that actually informed the answer. That is what teaches ranking.
    """
    VALID_DEPTHS = ("triples", "summaries", "full", "auto")
    if depth not in VALID_DEPTHS:
        raise ValueError(
            f"depth must be one of {', '.join(VALID_DEPTHS)}, got {depth!r}"
        )

    from ..budget import estimate_tokens, trim_to_budget

    _, embed_url = _cfg()

    # Lean reference mode (issue #62): IDs + snippets only, fetch bodies on demand.
    if reference_only:
        from ..search import hybrid_search

        results = hybrid_search(
            query, top_k=top_k, mode=mode,
            embed_url=embed_url, context=context,
            workspace=workspace,
        )
        if rerank:
            from ..rerank import rerank_results

            results = rerank_results(query, results)
        refs = [
            {"path": r.note_path, "score": round(r.score, 4), "snippet": r.snippet}
            for r in results
        ]
        kept, _, truncated = trim_to_budget(refs, max_tokens)
        result = {
            "results": kept,
            "reference_only": True,
            "hint": "Reference mode: fetch a chosen path with "
                    "vault_read_file(path, offset, limit) or vault_summary(path).",
        }
        if rerank:
            result["reranked"] = True
        if truncated:
            result["truncated"] = True
        if projects := _project_status(result, query):
            result["projects"] = projects
        return result

    if depth in ("triples", "summaries", "auto"):
        if rerank:
            raise ValueError(
                f"rerank=True needs whole notes to judge, but depth={depth!r} returns "
                "triples or summaries. Use depth='full' or reference_only=True."
            )
        from ..search import tiered_search

        result = tiered_search(
            query, top_k=top_k, depth=depth, mode=mode,
            embed_url=embed_url, context=context,
            workspace=workspace,
        )

        if depth in ("auto", "summaries"):
            memories = _search_memories_for_results(query, workspace, limit=3)
            if memories:
                result["memories"] = memories
            if max_tokens is None:
                max_tokens = DEFAULT_TIERED_MAX_TOKENS

        # Counted in the budget below but never trimmed, since the project
        # note is the freshest source in the reply (#322).
        if projects := _project_status(result, query):
            result["projects"] = projects

        if max_tokens is not None:
            # Keep the budget meaningful whatever the depth (issue #62): one
            # ceiling over the whole reply, so an explicit max_tokens never
            # silently no-ops on the default depth="auto". Entries drop from the
            # tail, memories first, until the reply as sent fits (issue #310);
            # summing per-entry estimates ran a few percent over. At least one
            # entry always stays.
            lists = [
                k for k in ("memories", "chunks", "summaries", "triples")
                if result.get(k)
            ]
            while (
                estimate_tokens(result) > max_tokens
                and sum(len(result[k]) for k in lists) > 1
            ):
                result[next(k for k in lists if result[k])].pop()
                result["truncated"] = True

        return result

    # Default: full depth
    from ..search import hybrid_search

    results = hybrid_search(
        query, top_k=top_k, mode=mode,
        embed_url=embed_url, context=context,
        workspace=workspace,
    )
    if rerank:
        from ..rerank import rerank_results

        results = rerank_results(query, results)

    output = []
    for r in results:
        entry = {
            "path": r.note_path,
            "title": r.title,
            "section": r.heading_path,
            "score": round(r.score, 4),
            "snippet": r.snippet,
        }
        if r.summary:
            entry["summary"] = r.summary
        output.append(entry)

    kept, _, truncated = trim_to_budget(output, max_tokens)
    result = {"results": kept}
    if rerank:
        # `score` stays the hybrid score; the order is the judge's. Say so, or a
        # caller reads descending scores that aren't there and calls it a bug.
        result["reranked"] = True
    if truncated:
        result["truncated"] = True

    memories = _search_memories_for_results(query, workspace, limit=3)
    if memories:
        result["memories"] = memories
    if projects := _project_status(result, query):
        result["projects"] = projects

    return result


@registry.tool(tags=["search", "retrieval"], annotations=_READ_ONLY)
def vault_summary(path_or_query: str) -> dict:
    """Get pre-computed summary for a note by path or search query.

    Returns 2-3 sentence summary + frontmatter (~100-200 tokens)
    instead of reading the full file (~500-2000 tokens).

    Args:
        path_or_query: Note path (e.g. "research/predictive-coding.md") or search query
    """
    import json

    from ..schema import DB_PATH, get_db
    from ..search import _record_note_usage, hybrid_search

    _, embed_url = _cfg()
    conn = get_db(DB_PATH)

    row = conn.execute(
        """SELECT n.path, n.title, n.frontmatter, s.summary_text
           FROM notes n LEFT JOIN summaries s ON s.note_path = n.path
           WHERE n.path = ?""",
        (path_or_query,),
    ).fetchone()

    if not row:
        results = hybrid_search(path_or_query, top_k=1, embed_url=embed_url)
        if results:
            r = results[0]
            row = conn.execute(
                """SELECT n.path, n.title, n.frontmatter, s.summary_text
                   FROM notes n LEFT JOIN summaries s ON s.note_path = n.path
                   WHERE n.path = ?""",
                (r.note_path,),
            ).fetchone()

    if not row:
        return {"error": "Note not found"}

    # Returning a ~150-token summary is surfacing, not use (issues #95/#103/#109):
    # 'primed' here; a follow-up read of the note itself infers the strong
    # signal via capture_read. With feedback enabled, search-log the surfacing
    # so that read attributes back.
    _record_note_usage(conn, [row["path"]], tier="primed", source="summary")
    from ..config import get_config

    cfg = get_config()
    if cfg.feedback_enabled:
        from ..feedback import log_search

        log_search(conn, path_or_query, [row["path"]], cfg.feedback_log_retention)

    return {
        "path": row["path"],
        "title": row["title"],
        "frontmatter": json.loads(row["frontmatter"]) if row["frontmatter"] else {},
        "summary": row["summary_text"] or "(not yet generated)",
    }


@registry.tool(tags=["search", "graph"], annotations=_READ_ONLY)
def vault_graph(note: str, depth: int = 1, workspace: str | None = None) -> dict:
    """Get wiki-link neighborhood for a note with summaries and PageRank.

    One call replaces manually following links across files.

    Args:
        note: Note path (e.g. "research/predictive-coding.md")
        depth: How many link-hops to traverse (default 1)
        workspace: Optional vault subdirectory prefix to restrict
            neighbors (e.g. "work/acme-cloud")
    """
    from ..graph import get_neighborhood
    from ..search import _normalize_workspace

    result = get_neighborhood(note, depth=depth)
    ws = _normalize_workspace(workspace)
    if result and ws:
        result.neighbors = [
            n for n in result.neighbors
            if n.path.startswith(ws + "/")
        ]
    if not result:
        return {"error": f"Note not found: {note}"}

    def node_to_dict(n):
        d = {
            "path": n.path,
            "title": n.title,
            "pagerank": round(n.pagerank, 4),
            "in_degree": n.in_degree,
            "out_degree": n.out_degree,
        }
        if n.summary:
            d["summary"] = n.summary
        return d

    return {
        "center": node_to_dict(result.center),
        "neighbors": [node_to_dict(n) for n in result.neighbors],
        "neighbor_count": len(result.neighbors),
    }


@registry.tool(tags=["search", "graph"], annotations=_READ_ONLY)
def vault_graph_analysis(top_k: int = 10, min_shared: int = 2) -> dict:
    """Find structural gaps and bridge notes in the wiki-link graph.

    Pure structural analysis of the link graph — no embeddings, no LLM:
    - `gaps`: unlinked note pairs that share many neighbours, ranked by
      Adamic-Adar (rare shared neighbours count for more). These are candidate
      links worth adding — notes that discuss overlapping topics but aren't
      connected.
    - `bridges`: notes that hold the graph together, ranked by betweenness
      centrality. Each flags whether removing it fragments the graph (an
      articulation point) and into how many pieces — the notes whose loss would
      most isolate parts of the vault.
    - `stats`: note count, link count, connected components, isolated notes.

    Args:
        top_k: Max gaps and max bridges to return (default 10 each).
        min_shared: Minimum shared neighbours for a gap candidate (default 2).
    """
    from ..graph_analysis import analyze_graph
    from ..schema import DB_PATH, get_db

    conn = get_db(DB_PATH)
    return analyze_graph(conn, top_k=top_k, min_shared=min_shared)


@registry.tool(tags=["search", "semantic"], annotations=_READ_ONLY)
def vault_related(note: str, top_k: int = 10, workspace: str | None = None) -> dict:
    """Find semantically related notes using embedding similarity.

    Unlike vault_graph (which follows explicit wiki-links), this discovers
    connections based on semantic content similarity - notes that discuss
    similar topics even if not explicitly linked.

    Args:
        note: Note path (e.g. "research/predictive-coding.md")
        top_k: Number of related notes to return (default 10)
        workspace: Optional vault subdirectory prefix to restrict
            results (e.g. "work/acme-cloud")
    """
    from ..related import find_related

    return {"related": find_related(note_path=note, top_k=top_k, workspace=workspace)}


@registry.tool(tags=["search", "retrieval"], annotations=_READ_ONLY)
def vault_triples(
    query: str, top_k: int = 10, mode: str = "hybrid", workspace: str | None = None
) -> dict:
    """Search knowledge graph triples for structured facts.

    Returns compact Subject-Predicate-Object facts (~10-20 tokens each).
    Use this for quick factual lookups instead of reading full notes.

    Args:
        query: Natural language search query
        top_k: Number of triples to return (default 10)
        mode: Search mode - "hybrid" (default), "semantic", or "keyword"
        workspace: Optional vault subdirectory prefix to restrict
            results (e.g. "work/acme-cloud")
    """
    from ..search import search_triples

    _, embed_url = _cfg()
    results = search_triples(
        query, top_k=top_k, mode=mode,
        embed_url=embed_url, workspace=workspace,
    )

    return {
        "triples": [
            {
                "note": t.note_path,
                "title": t.title,
                "s": t.subject,
                "p": t.predicate,
                "o": t.object,
                "score": round(t.score, 4),
            }
            for t in results
        ],
    }


@registry.tool(tags=["search", "community"], annotations=_READ_ONLY)
def vault_communities(
    query: str,
    top_k: int = 6,
    level: int = 0,
    map_reduce: bool = True,
    workspace: str | None = None,
) -> dict:
    """Answer global queries using GraphRAG community summaries.

    Unlike vault_search (which retrieves specific chunks), this answers
    thematic questions like "what topics dominate my vault?" or
    "what are the main research areas I've been exploring?" by running
    community detection summaries through a map-reduce synthesis.

    Args:
        query: Natural language question about vault themes/topics
        top_k: Number of communities to retrieve (default 6)
        level: Community hierarchy level — 0=coarse themes (default), 1=fine sub-themes
        map_reduce: Use LLM map-reduce synthesis (True) or raw hits (False)
        workspace: Optional vault subdirectory prefix to restrict
            results (e.g. "work/acme-cloud")
    """
    from ..community import community_build_status
    from ..community_search import global_query

    _, embed_url = _cfg()
    result = global_query(
        query=query,
        top_k=top_k,
        level=level,
        use_map_reduce=map_reduce,
        embed_url=embed_url,
        workspace=workspace,
    )
    # Flag a drifted partition so the caller knows the answer may be built on a
    # stale community map rather than silently trusting it (issue #65).
    result["community_build"] = community_build_status()
    return result


@registry.tool(tags=["search", "diff"], annotations=_READ_ONLY)
def vault_diff(since: str | None = None, baseline: str = "default") -> dict:
    """Show what changed in the vault: additions, modifications, deletions.

    Two modes:
    - Baseline (default): diff the current index against a named stored baseline
      (saved via vault_checkpoint). Reports added / modified / deleted notes —
      deletions and additions are only visible this way. `has_baseline` is False
      until you checkpoint at least once (until then every note reads as added).
    - Date (`since` given): notes with `updated_at` after an ISO date/datetime.
      Combines additions and modifications; cannot surface deletions.

    Args:
        since: Optional ISO date/datetime (e.g. "2026-07-01") to enable date mode.
        baseline: Named baseline to diff against in baseline mode (default "default").
    """
    from ..diff import compute_diff
    from ..schema import DB_PATH, get_db

    return compute_diff(get_db(DB_PATH), since=since, baseline=baseline)


@registry.tool(tags=["search", "diff"], annotations=_WRITE_ADDITIVE)
def vault_checkpoint(baseline: str = "default") -> dict:
    """Record the current vault state as a named diff baseline.

    Saves `{path -> content_hash}` for every indexed note under `baseline`,
    overwriting any previous snapshot of that name. A later vault_diff(baseline=…)
    then reports what changed since this checkpoint. Use distinct names for
    independent cursors (e.g. one per autonomous loop).

    Args:
        baseline: Baseline name to save under (default "default").
    """
    from ..diff import save_checkpoint
    from ..schema import DB_PATH, get_db

    return save_checkpoint(get_db(DB_PATH), baseline=baseline)


def index_stats(conn) -> dict:
    """Index health read from `conn`, shared by vault_stats and the dashboard."""
    from ..community import community_build_status as _community_build_status
    from ..cooccurrence import get_cooccurrence_stats
    from ..memories import get_memory_source_counts, get_memory_stats
    from ..search import get_dormancy_report
    from ..triggers import trigger_stats

    notes = conn.execute("SELECT COUNT(*) as c FROM notes").fetchone()["c"]
    chunks = conn.execute("SELECT COUNT(*) as c FROM chunks").fetchone()["c"]
    embedded = conn.execute(
        "SELECT COUNT(*) as c FROM chunks WHERE embedding IS NOT NULL"
    ).fetchone()["c"]
    summaries = conn.execute("SELECT COUNT(*) as c FROM summaries").fetchone()["c"]
    edges = conn.execute("SELECT COUNT(*) as c FROM graph_edges").fetchone()["c"]

    stale_summaries = conn.execute(
        """SELECT COUNT(*) as c FROM notes n
           LEFT JOIN summaries s ON s.note_path = n.path
           WHERE s.content_hash IS NULL OR s.content_hash != n.content_hash"""
    ).fetchone()["c"]

    total_triples = conn.execute("SELECT COUNT(*) as c FROM triples").fetchone()["c"]
    notes_with_triples = conn.execute(
        "SELECT COUNT(DISTINCT note_path) as c FROM triples"
    ).fetchone()["c"]
    embedded_triples = conn.execute(
        "SELECT COUNT(*) as c FROM triples WHERE embedding IS NOT NULL"
    ).fetchone()["c"]

    dormancy = get_dormancy_report(conn, threshold=0.05, limit=0)
    cooc_stats = get_cooccurrence_stats(conn)
    mem_stats = get_memory_stats(conn)

    result = {
        "notes": notes,
        "chunks": chunks,
        "embedded": embedded,
        "embedding_coverage": f"{embedded * 100 // max(chunks, 1)}%",
        "summaries": summaries,
        "summary_coverage": f"{summaries * 100 // max(notes, 1)}%",
        "stale_summaries": stale_summaries,
        "graph_edges": edges,
        "triples": total_triples,
        "notes_with_triples": notes_with_triples,
        "triple_coverage": f"{notes_with_triples * 100 // max(notes, 1)}%",
        "triple_embedding_coverage": f"{embedded_triples * 100 // max(total_triples, 1)}%",
        "communities_coarse": conn.execute(
            "SELECT COUNT(*) as c FROM communities WHERE level = 0"
        ).fetchone()["c"],
        "communities_fine": conn.execute(
            "SELECT COUNT(*) as c FROM communities WHERE level = 1"
        ).fetchone()["c"],
        "communities_summarized": conn.execute(
            "SELECT COUNT(*) as c FROM communities WHERE summary IS NOT NULL"
        ).fetchone()["c"],
        "community_levels": _community_level_stats(conn),
        "community_build": _community_build_status(conn),
        "excitability": {
            "active": dormancy["active_count"],
            "dormant": dormancy["dormant_count"],
            "never_used": dormancy["never_used_count"],
        },
        "cooccurrence_pairs": cooc_stats["pairs"],
        "cooccurrence_total_weight": cooc_stats["total_weight"],
        "cooccurrence_reinforced_pairs": cooc_stats["reinforced_pairs"],
        "cooccurrence_total_reinforcement": cooc_stats["total_reinforcement"],
        # `neurostack status` reads by_source_7d for its LEARN table (#151).
        "memories": {**mem_stats, "by_source_7d": get_memory_source_counts(conn)},
        # And triggers.last_30d for its WARN line (#159). The per-memory
        # breakdown stays behind `neurostack triggers stats` — this reply is
        # read on every status check.
        "triggers": {
            "last_30d": {
                k: v for k, v in trigger_stats(conn, days=30).items()
                if k != "memories"
            }
        },
    }
    return result


@registry.tool(tags=["search", "stats"], annotations=_READ_ONLY)
def vault_stats() -> dict:
    """Get index health: note count, embedding coverage, graph stats, triple stats."""
    from ..queue import learn_status
    from ..schema import DB_PATH, get_db

    conn = get_db(DB_PATH)
    stats = index_stats(conn)
    # `neurostack status` builds its LEARN line from this, as the brief does (#309).
    stats["learn"] = learn_status(conn)
    return stats


@registry.tool(tags=["search", "usage"], annotations=_WRITE_ADDITIVE)
def vault_record_usage(
    note_paths: list[str] | None = None, paths: list[str] | None = None,
) -> dict:
    """Record that specific notes were retrieved and used in this session.

    Drives hotness scoring — frequently used notes score higher in future
    searches. This is the strong 'used' tier of the two-tier activation signal
    (issue #95); surfacing alone (search returns, auto-RAG vault_context
    injections) is logged server-side as weak 'primed' events.

    Mostly unnecessary now: the server infers a use from read-after-surface —
    opening a just-surfaced note via vault_read_file (issue #103). This call is
    the explicit override, for consumption the server cannot observe: acting on a
    snippet or a summary without ever opening the note.

    Args:
        note_paths: List of note paths that were used (e.g. ["research/foo.md", "work/bar.md"])
        paths: Alias for note_paths (issue #205) — pass one or the other, not both.
    """
    if note_paths is not None and paths is not None:
        if note_paths != paths:
            raise ValueError(
                "vault_record_usage: pass either note_paths or paths, not both "
                "with different values"
            )
        resolved = note_paths
    elif note_paths is not None:
        resolved = note_paths
    elif paths is not None:
        resolved = paths
    else:
        raise ValueError("vault_record_usage requires note_paths (or its alias paths)")

    from ..feedback import record_use
    from ..schema import DB_PATH, get_db

    conn = get_db(DB_PATH)
    record_use(resolved, conn=conn)
    return {"recorded": len(resolved), "paths": resolved}


@registry.tool(tags=["search", "quality"], annotations=_READ_ONLY)
def vault_prediction_errors(
    error_type: str | None = None,
    limit: int = 20,
    resolve: list[str] | None = None,
    workspace: str | None = None,
    memory_id: int | None = None,
) -> dict:
    """Return prediction errors — note or memory signals that surprised at retrieval.

    Note-centric (semantic distance between a note and the query that retrieved it):
    - low_overlap: cosine distance > 0.62 — note is semantically distant from what retrieved it
    - contextual_mismatch: note surfaced outside its expected domain context AND was only a
      weak fit (sim < 0.45) — a strong hit outside the context boost set is not a mismatch
    Only notes that surprised >= 2 distinct retrieval events are surfaced.

    Memory-centric (issue #38):
    - memory_drift: an agent-written memory has drifted from the current content of the
      notes it references (its embedding is far from those notes' chunks). Each row carries
      the memory content so an agent can update_memory or forget it. No occurrence threshold —
      the detector debounces to one row per (memory, note).

    Args:
        error_type: Filter by type — "low_overlap", "contextual_mismatch", or
            "memory_drift". None = all.
        limit: Max errors to return per class (default 20).
        resolve: List of note paths to mark as resolved (clears their unresolved flags).
        workspace: Optional vault subdirectory prefix to restrict note results.
        memory_id: Filter memory-drift rows to a single memory (implies memory rows only).
    """
    import json

    from ..schema import DB_PATH, get_db
    from ..search import PREDICTION_ERROR_MIN_OCCURRENCES, _normalize_workspace

    conn = get_db(DB_PATH)

    if resolve:
        # Only note-centric rows are resolved by path; memory drift is reconciled
        # through the memory lifecycle (update/forget), not by note path.
        conn.execute(
            """
            UPDATE prediction_errors SET resolved_at = datetime('now')
            WHERE note_path IN ({}) AND memory_id IS NULL AND resolved_at IS NULL
            """.format(",".join("?" * len(resolve))),
            resolve,
        )
        conn.commit()
        return {"resolved": len(resolve), "paths": resolve}

    ws = _normalize_workspace(workspace)
    results: list = []
    total_notes = 0

    # Note-centric errors (memory_id IS NULL), aggregated with the >=2 threshold.
    if memory_id is None and error_type != "memory_drift":
        where = "WHERE resolved_at IS NULL AND memory_id IS NULL"
        params: list = []
        if error_type:
            where += " AND error_type = ?"
            params.append(error_type)
        if ws:
            where += " AND note_path LIKE ? || '%'"
            params.append(ws + "/")

        rows = conn.execute(
            f"""
            SELECT note_path, error_type, context,
                   AVG(cosine_distance) as avg_distance,
                   COUNT(*) as occurrences,
                   MAX(detected_at) as last_seen,
                   MIN(query) as sample_query
            FROM prediction_errors
            {where}
            GROUP BY note_path, error_type
            HAVING COUNT(*) >= ?
            ORDER BY occurrences DESC, avg_distance DESC
            LIMIT ?
            """,
            params + [PREDICTION_ERROR_MIN_OCCURRENCES, limit],
        ).fetchall()
        results = [
            {
                "note_path": r["note_path"],
                "error_type": r["error_type"],
                "context": r["context"],
                "avg_cosine_distance": round(r["avg_distance"], 3),
                "occurrences": r["occurrences"],
                "last_seen": r["last_seen"],
                "sample_query": r["sample_query"],
            }
            for r in rows
        ]

        total_where = "WHERE resolved_at IS NULL AND memory_id IS NULL"
        total_params: list = []
        if ws:
            total_where += " AND note_path LIKE ? || '%'"
            total_params.append(ws + "/")
        total_notes = conn.execute(
            f"""
            SELECT COUNT(*) FROM (
                SELECT note_path FROM prediction_errors {total_where}
                GROUP BY note_path, error_type
                HAVING COUNT(*) >= ?
            )
            """,
            total_params + [PREDICTION_ERROR_MIN_OCCURRENCES],
        ).fetchone()[0]

    # Memory-centric drift rows (issue #38): one open row per (memory, note),
    # no occurrence threshold, carrying the memory content to act on.
    memory_errors: list = []
    total_memories = 0
    if memory_id is not None or error_type in (None, "memory_drift"):
        mwhere = (
            "WHERE pe.resolved_at IS NULL AND pe.memory_id IS NOT NULL"
            " AND pe.error_type = 'memory_drift'"
        )
        mparams: list = []
        if memory_id is not None:
            mwhere += " AND pe.memory_id = ?"
            mparams.append(memory_id)
        total_memories = conn.execute(
            f"SELECT COUNT(*) FROM prediction_errors pe {mwhere}", mparams
        ).fetchone()[0]
        mrows = conn.execute(
            f"""
            SELECT pe.memory_id, pe.note_path, pe.cosine_distance, pe.context,
                   pe.detected_at, m.content, m.entity_type, m.tags, m.created_at
            FROM prediction_errors pe
            JOIN memories m ON m.memory_id = pe.memory_id
            {mwhere}
            ORDER BY pe.cosine_distance DESC
            LIMIT ?
            """,
            mparams + [limit],
        ).fetchall()
        memory_errors = [
            {
                "error_type": "memory_drift",
                "memory_id": r["memory_id"],
                "note_path": r["note_path"],
                "cosine_distance": round(r["cosine_distance"], 3),
                "detected_at": r["detected_at"],
                "context": r["context"],
                "memory": {
                    "content": r["content"],
                    "entity_type": r["entity_type"],
                    "tags": json.loads(r["tags"]) if r["tags"] else [],
                    "created_at": r["created_at"],
                },
            }
            for r in mrows
        ]

    return {
        "total_flagged_notes": total_notes,
        "total_flagged_memories": total_memories,
        "showing": len(results) + len(memory_errors),
        "errors": results + memory_errors,
    }
