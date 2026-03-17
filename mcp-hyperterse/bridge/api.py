"""NeuroStack bridge API — exposes all MCP tools as HTTP endpoints for Hyperterse handlers."""

from __future__ import annotations

import json
import logging
import os
import sys
import time as _time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

# Ensure neurostack is importable from the parent project
_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if os.path.isdir(os.path.join(_project_root, "src", "neurostack")):
    sys.path.insert(0, os.path.join(_project_root, "src"))

from neurostack.config import get_config
from neurostack.vault_writer import VaultWriter

log = logging.getLogger("neurostack.bridge")

app = FastAPI(title="NeuroStack Bridge", docs_url=None, redoc_url=None)

_cfg = get_config()
VAULT_ROOT = _cfg.vault_root
EMBED_URL = _cfg.embed_url

_writer: VaultWriter | None = None
if _cfg.writeback_enabled:
    try:
        _writer = VaultWriter(_cfg.vault_root, _cfg.writeback_path)
    except ValueError as e:
        log.warning("Write-back disabled: %s", e)

# ---------------------------------------------------------------------------
# In-memory TTL cache (mirrors server.py)
# ---------------------------------------------------------------------------
_tool_cache: dict[str, tuple[float, str]] = {}
_CACHE_TTL = 300.0


def _cache_get(key: str) -> str | None:
    entry = _tool_cache.get(key)
    if entry and (_time.time() - entry[0]) < _CACHE_TTL:
        return entry[1]
    if entry:
        del _tool_cache[key]
    return None


def _cache_set(key: str, value: str) -> None:
    _tool_cache[key] = (_time.time(), value)


def _cache_clear() -> None:
    _tool_cache.clear()


def _search_memories_for_results(query: str, workspace: str = None, limit: int = 3) -> list[dict]:
    try:
        from neurostack.memories import search_memories
        from neurostack.schema import DB_PATH, get_db

        conn = get_db(DB_PATH)
        memories = search_memories(conn, query=query, workspace=workspace, limit=limit, embed_url=EMBED_URL)
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


def _parse_list(val) -> list[str] | None:
    """Parse a value that may be a list, JSON string, or comma-separated string."""
    if val is None:
        return None
    if isinstance(val, list):
        return val
    if isinstance(val, str):
        val = val.strip()
        if val.startswith("["):
            try:
                return json.loads(val)
            except json.JSONDecodeError:
                pass
        return [x.strip() for x in val.split(",") if x.strip()]
    return None


# ---------------------------------------------------------------------------
# Error handler
# ---------------------------------------------------------------------------

@app.exception_handler(Exception)
async def _generic_error(_request: Request, exc: Exception):
    log.exception("Bridge error")
    return JSONResponse(status_code=500, content={"error": str(exc)})


@app.get("/health")
async def health():
    return {"status": "ok", "service": "neurostack-bridge"}


# ---------------------------------------------------------------------------
# Search & Retrieval
# ---------------------------------------------------------------------------

@app.post("/tools/vault-search")
async def tool_vault_search(body: dict):
    query = body["query"]
    top_k = int(body.get("top_k", 5))
    mode = body.get("mode", "hybrid")
    depth = body.get("depth", "auto")
    context = body.get("context")
    workspace = body.get("workspace")

    if depth in ("triples", "summaries", "auto"):
        from neurostack.search import tiered_search

        result = tiered_search(
            query, top_k=top_k, depth=depth, mode=mode,
            embed_url=EMBED_URL, context=context, rerank=True, workspace=workspace,
        )
        if depth in ("auto", "summaries"):
            memories = _search_memories_for_results(query, workspace, limit=3)
            if memories:
                result["memories"] = memories
        return result

    from neurostack.search import hybrid_search

    results = hybrid_search(
        query, top_k=top_k, mode=mode,
        embed_url=EMBED_URL, context=context, rerank=True, workspace=workspace,
    )
    output = []
    for r in results:
        entry = {
            "path": r.note_path, "title": r.title, "section": r.heading_path,
            "score": round(r.score, 4), "snippet": r.snippet,
        }
        if r.summary:
            entry["summary"] = r.summary
        output.append(entry)

    memories = _search_memories_for_results(query, workspace, limit=3)
    if memories:
        output.append({"_memories": memories})
    return output


@app.post("/tools/vault-ask")
async def tool_vault_ask(body: dict):
    question = body["question"]
    top_k = int(body.get("top_k", 8))
    workspace = body.get("workspace")

    cache_key = f"ask:{question}:{top_k}:{workspace}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return json.loads(cached)

    from neurostack.ask import ask_vault

    result = ask_vault(question=question, top_k=top_k, embed_url=EMBED_URL, workspace=workspace)
    _cache_set(cache_key, json.dumps(result))
    return result


@app.post("/tools/vault-summary")
async def tool_vault_summary(body: dict):
    path_or_query = body["path_or_query"]

    from neurostack.schema import DB_PATH, get_db
    from neurostack.search import hybrid_search

    conn = get_db(DB_PATH)
    row = conn.execute(
        """SELECT n.path, n.title, n.frontmatter, s.summary_text
           FROM notes n LEFT JOIN summaries s ON s.note_path = n.path
           WHERE n.path = ?""",
        (path_or_query,),
    ).fetchone()

    if not row:
        results = hybrid_search(path_or_query, top_k=1, embed_url=EMBED_URL)
        if results:
            row = conn.execute(
                """SELECT n.path, n.title, n.frontmatter, s.summary_text
                   FROM notes n LEFT JOIN summaries s ON s.note_path = n.path
                   WHERE n.path = ?""",
                (results[0].note_path,),
            ).fetchone()

    if not row:
        return {"error": "Note not found"}

    return {
        "path": row["path"],
        "title": row["title"],
        "frontmatter": json.loads(row["frontmatter"]) if row["frontmatter"] else {},
        "summary": row["summary_text"] or "(not yet generated)",
    }


@app.post("/tools/vault-graph")
async def tool_vault_graph(body: dict):
    note = body["note"]
    depth = int(body.get("depth", 1))
    workspace = body.get("workspace")

    from neurostack.graph import get_neighborhood
    from neurostack.search import _normalize_workspace

    result = get_neighborhood(note, depth=depth)
    ws = _normalize_workspace(workspace)
    if result and ws:
        result.neighbors = [n for n in result.neighbors if n.path.startswith(ws + "/")]
    if not result:
        return {"error": f"Note not found: {note}"}

    def node_to_dict(n):
        d = {"path": n.path, "title": n.title, "pagerank": round(n.pagerank, 4),
             "in_degree": n.in_degree, "out_degree": n.out_degree}
        if n.summary:
            d["summary"] = n.summary
        return d

    return {
        "center": node_to_dict(result.center),
        "neighbors": [node_to_dict(n) for n in result.neighbors],
        "neighbor_count": len(result.neighbors),
    }


@app.post("/tools/vault-related")
async def tool_vault_related(body: dict):
    from neurostack.related import find_related

    return find_related(
        note_path=body["note"],
        top_k=int(body.get("top_k", 10)),
        workspace=body.get("workspace"),
    )


@app.post("/tools/vault-triples")
async def tool_vault_triples(body: dict):
    from neurostack.search import search_triples

    results = search_triples(
        body["query"], top_k=int(body.get("top_k", 10)),
        mode=body.get("mode", "hybrid"), embed_url=EMBED_URL,
        workspace=body.get("workspace"),
    )
    return [
        {"note": t.note_path, "title": t.title, "s": t.subject,
         "p": t.predicate, "o": t.object, "score": round(t.score, 4)}
        for t in results
    ]


@app.post("/tools/vault-communities")
async def tool_vault_communities(body: dict):
    query = body["query"]
    top_k = int(body.get("top_k", 6))
    level = int(body.get("level", 0))
    map_reduce = body.get("map_reduce", True)
    workspace = body.get("workspace")

    cache_key = f"communities:{query}:{top_k}:{level}:{map_reduce}:{workspace}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return json.loads(cached)

    from neurostack.community_search import global_query

    result = global_query(
        query=query, top_k=top_k, level=level,
        use_map_reduce=map_reduce, embed_url=EMBED_URL, workspace=workspace,
    )
    _cache_set(cache_key, json.dumps(result))
    return result


@app.post("/tools/session-brief")
async def tool_session_brief(body: dict):
    from neurostack.brief import generate_brief

    text = generate_brief(vault_root=VAULT_ROOT, workspace=body.get("workspace"))
    return {"brief": text}


@app.post("/tools/vault-context")
async def tool_vault_context(body: dict):
    from neurostack.context import build_vault_context
    from neurostack.schema import DB_PATH, get_db

    conn = get_db(DB_PATH)
    return build_vault_context(
        conn, task=body["task"],
        token_budget=int(body.get("token_budget", 2000)),
        workspace=body.get("workspace"),
        include_memories=body.get("include_memories", True),
        include_triples=body.get("include_triples", True),
        embed_url=EMBED_URL,
    )


# ---------------------------------------------------------------------------
# Stats & Usage
# ---------------------------------------------------------------------------

@app.post("/tools/vault-stats")
async def tool_vault_stats(body: dict):
    from neurostack.memories import get_memory_stats
    from neurostack.schema import DB_PATH, get_db
    from neurostack.search import get_dormancy_report

    conn = get_db(DB_PATH)

    notes = conn.execute("SELECT COUNT(*) as c FROM notes").fetchone()["c"]
    chunks = conn.execute("SELECT COUNT(*) as c FROM chunks").fetchone()["c"]
    embedded = conn.execute("SELECT COUNT(*) as c FROM chunks WHERE embedding IS NOT NULL").fetchone()["c"]
    summaries = conn.execute("SELECT COUNT(*) as c FROM summaries").fetchone()["c"]
    edges = conn.execute("SELECT COUNT(*) as c FROM graph_edges").fetchone()["c"]
    stale_summaries = conn.execute(
        """SELECT COUNT(*) as c FROM notes n
           LEFT JOIN summaries s ON s.note_path = n.path
           WHERE s.content_hash IS NULL OR s.content_hash != n.content_hash"""
    ).fetchone()["c"]
    total_triples = conn.execute("SELECT COUNT(*) as c FROM triples").fetchone()["c"]
    notes_with_triples = conn.execute("SELECT COUNT(DISTINCT note_path) as c FROM triples").fetchone()["c"]
    embedded_triples = conn.execute("SELECT COUNT(*) as c FROM triples WHERE embedding IS NOT NULL").fetchone()["c"]

    dormancy = get_dormancy_report(conn, threshold=0.05, limit=0)
    mem_stats = get_memory_stats(conn)

    return {
        "notes": notes, "chunks": chunks, "embedded": embedded,
        "embedding_coverage": f"{embedded * 100 // max(chunks, 1)}%",
        "summaries": summaries,
        "summary_coverage": f"{summaries * 100 // max(notes, 1)}%",
        "stale_summaries": stale_summaries, "graph_edges": edges,
        "triples": total_triples, "notes_with_triples": notes_with_triples,
        "triple_coverage": f"{notes_with_triples * 100 // max(notes, 1)}%",
        "triple_embedding_coverage": f"{embedded_triples * 100 // max(total_triples, 1)}%",
        "communities_coarse": conn.execute("SELECT COUNT(*) as c FROM communities WHERE level = 0").fetchone()["c"],
        "communities_fine": conn.execute("SELECT COUNT(*) as c FROM communities WHERE level = 1").fetchone()["c"],
        "communities_summarized": conn.execute("SELECT COUNT(*) as c FROM communities WHERE summary IS NOT NULL").fetchone()["c"],
        "excitability": {
            "active": dormancy["active_count"],
            "dormant": dormancy["dormant_count"],
            "never_used": dormancy["never_used_count"],
        },
        "memories": mem_stats,
    }


@app.post("/tools/vault-record-usage")
async def tool_vault_record_usage(body: dict):
    from neurostack.schema import DB_PATH, get_db

    note_paths = _parse_list(body.get("note_paths")) or []
    conn = get_db(DB_PATH)
    conn.executemany("INSERT INTO note_usage (note_path) VALUES (?)", [(p,) for p in note_paths])
    conn.commit()
    return {"recorded": len(note_paths), "paths": note_paths}


@app.post("/tools/vault-prediction-errors")
async def tool_vault_prediction_errors(body: dict):
    from neurostack.schema import DB_PATH, get_db
    from neurostack.search import _normalize_workspace

    error_type = body.get("error_type")
    limit = int(body.get("limit", 20))
    resolve = _parse_list(body.get("resolve"))
    workspace = body.get("workspace")

    conn = get_db(DB_PATH)

    if resolve:
        conn.execute(
            "UPDATE prediction_errors SET resolved_at = datetime('now') "
            "WHERE note_path IN ({}) AND resolved_at IS NULL".format(",".join("?" * len(resolve))),
            resolve,
        )
        conn.commit()
        return {"resolved": len(resolve), "paths": resolve}

    where = "WHERE resolved_at IS NULL"
    params: list = []
    if error_type:
        where += " AND error_type = ?"
        params.append(error_type)

    ws = _normalize_workspace(workspace)
    if ws:
        where += " AND note_path LIKE ? || '%'"
        params.append(ws + "/")

    rows = conn.execute(
        f"""SELECT note_path, error_type, context,
                   AVG(cosine_distance) as avg_distance, COUNT(*) as occurrences,
                   MAX(detected_at) as last_seen, MIN(query) as sample_query
            FROM prediction_errors {where}
            GROUP BY note_path, error_type
            ORDER BY occurrences DESC, avg_distance DESC LIMIT ?""",
        params + [limit],
    ).fetchall()

    results = [
        {"note_path": r["note_path"], "error_type": r["error_type"], "context": r["context"],
         "avg_cosine_distance": round(r["avg_distance"], 3), "occurrences": r["occurrences"],
         "last_seen": r["last_seen"], "sample_query": r["sample_query"]}
        for r in rows
    ]

    total_where = "WHERE resolved_at IS NULL"
    total_params: list = []
    if ws:
        total_where += " AND note_path LIKE ? || '%'"
        total_params.append(ws + "/")
    total_unresolved = conn.execute(
        f"SELECT COUNT(DISTINCT note_path) FROM prediction_errors {total_where}", total_params,
    ).fetchone()[0]

    return {"total_flagged_notes": total_unresolved, "showing": len(results), "errors": results}


# ---------------------------------------------------------------------------
# Memories
# ---------------------------------------------------------------------------

@app.post("/tools/vault-remember")
async def tool_vault_remember(body: dict):
    from neurostack.memories import save_memory
    from neurostack.schema import DB_PATH, get_db

    conn = get_db(DB_PATH)
    memory = save_memory(
        conn, content=body["content"], tags=_parse_list(body.get("tags")),
        entity_type=body.get("entity_type", "observation"),
        source_agent=body.get("source_agent"), workspace=body.get("workspace"),
        ttl_hours=float(body["ttl_hours"]) if body.get("ttl_hours") is not None else None,
        embed_url=EMBED_URL,
        session_id=int(body["session_id"]) if body.get("session_id") is not None else None,
    )
    if _writer:
        _writer.write(memory)

    result = {"saved": True, "memory_id": memory.memory_id,
              "entity_type": memory.entity_type, "expires_at": memory.expires_at}
    if memory.near_duplicates:
        result["near_duplicates"] = memory.near_duplicates
    if memory.suggested_tags:
        result["suggested_tags"] = memory.suggested_tags
    return result


@app.post("/tools/vault-forget")
async def tool_vault_forget(body: dict):
    from neurostack.memories import _row_to_memory, forget_memory
    from neurostack.schema import DB_PATH, get_db

    memory_id = int(body["memory_id"])
    conn = get_db(DB_PATH)

    mem_to_delete = None
    if _writer:
        row = conn.execute("SELECT * FROM memories WHERE memory_id = ?", (memory_id,)).fetchone()
        if row:
            mem_to_delete = _row_to_memory(row)

    deleted = forget_memory(conn, memory_id)
    if _writer and mem_to_delete and deleted:
        _writer.delete(mem_to_delete)
    return {"deleted": deleted, "memory_id": memory_id}


@app.post("/tools/vault-update-memory")
async def tool_vault_update_memory(body: dict):
    from neurostack.memories import update_memory
    from neurostack.schema import DB_PATH, get_db

    memory_id = int(body["memory_id"])
    content = body.get("content")
    tags = _parse_list(body.get("tags"))
    add_tags = _parse_list(body.get("add_tags"))
    remove_tags = _parse_list(body.get("remove_tags"))
    entity_type = body.get("entity_type")
    workspace = body.get("workspace")
    ttl_hours_raw = body.get("ttl_hours")
    ttl_hours = float(ttl_hours_raw) if ttl_hours_raw is not None else None

    conn = get_db(DB_PATH)
    try:
        memory = update_memory(
            conn, memory_id=memory_id, content=content, tags=tags,
            add_tags=add_tags, remove_tags=remove_tags,
            entity_type=entity_type, workspace=workspace,
            ttl_hours=ttl_hours, embed_url=EMBED_URL,
        )
    except ValueError as exc:
        return {"updated": False, "error": str(exc), "memory_id": memory_id}

    if not memory:
        return {"updated": False, "error": "Memory not found", "memory_id": memory_id}

    if _writer:
        _writer.overwrite(memory)

    changed = []
    if content is not None:
        changed.append("content")
    if tags is not None or add_tags is not None or remove_tags is not None:
        changed.append("tags")
    if entity_type is not None:
        changed.append("entity_type")
    if workspace is not None:
        changed.append("workspace")
    if ttl_hours is not None:
        changed.append("ttl")

    return {
        "updated": True, "memory_id": memory.memory_id,
        "changed_fields": changed, "content": memory.content,
        "entity_type": memory.entity_type, "tags": memory.tags,
        "created_at": memory.created_at, "updated_at": memory.updated_at,
        "expires_at": memory.expires_at,
    }


@app.post("/tools/vault-merge")
async def tool_vault_merge(body: dict):
    from neurostack.memories import _row_to_memory, merge_memories
    from neurostack.schema import DB_PATH, get_db

    target_id = int(body["target_id"])
    source_id = int(body["source_id"])
    conn = get_db(DB_PATH)

    source_mem = None
    if _writer:
        row = conn.execute("SELECT * FROM memories WHERE memory_id = ?", (source_id,)).fetchone()
        if row:
            source_mem = _row_to_memory(row)

    memory = merge_memories(conn, target_id, source_id, embed_url=EMBED_URL)

    if _writer and memory:
        _writer.overwrite(memory)
    if _writer and source_mem:
        _writer.delete(source_mem)

    if not memory:
        return {"merged": False, "error": "One or both memory IDs not found",
                "target_id": target_id, "source_id": source_id}

    return {
        "merged": True, "memory_id": memory.memory_id,
        "content": memory.content, "entity_type": memory.entity_type,
        "tags": memory.tags, "merge_count": memory.merge_count,
        "merged_from": memory.merged_from,
    }


@app.post("/tools/vault-memories")
async def tool_vault_memories(body: dict):
    from neurostack.memories import search_memories
    from neurostack.schema import DB_PATH, get_db

    conn = get_db(DB_PATH)
    memories = search_memories(
        conn, query=body.get("query"), entity_type=body.get("entity_type"),
        workspace=body.get("workspace"), limit=int(body.get("limit", 20)),
        embed_url=EMBED_URL,
    )
    output = []
    for m in memories:
        entry = {"memory_id": m.memory_id, "content": m.content,
                 "entity_type": m.entity_type, "tags": m.tags, "created_at": m.created_at}
        if m.source_agent:
            entry["source_agent"] = m.source_agent
        if m.workspace:
            entry["workspace"] = m.workspace
        if m.expires_at:
            entry["expires_at"] = m.expires_at
        if m.score > 0:
            entry["score"] = round(m.score, 4)
        output.append(entry)
    return output


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

@app.post("/tools/vault-session-start")
async def tool_vault_session_start(body: dict):
    from neurostack.memories import start_session
    from neurostack.schema import DB_PATH, get_db

    conn = get_db(DB_PATH)
    return start_session(conn, source_agent=body.get("source_agent"), workspace=body.get("workspace"))


@app.post("/tools/vault-session-end")
async def tool_vault_session_end(body: dict):
    from neurostack.memories import end_session, summarize_session
    from neurostack.schema import DB_PATH, get_db

    _cache_clear()
    session_id = int(body["session_id"])
    summarize = body.get("summarize", True)
    auto_harvest = body.get("auto_harvest", True)

    conn = get_db(DB_PATH)
    summary = None
    if summarize:
        summary = summarize_session(conn, session_id)
    result = end_session(conn, session_id, summary=summary)

    if auto_harvest:
        try:
            from neurostack.harvest import harvest_sessions
            harvest_report = harvest_sessions(n_sessions=1)
            result["harvest"] = {
                "saved": len(harvest_report.get("saved", [])),
                "skipped": len(harvest_report.get("skipped", [])),
            }
        except Exception as e:
            result["harvest"] = {"error": str(e)}
    return result


@app.post("/tools/vault-capture")
async def tool_vault_capture(body: dict):
    from neurostack.capture import capture_thought

    return capture_thought(
        content=body["content"], vault_root=str(VAULT_ROOT),
        tags=_parse_list(body.get("tags")),
    )


@app.post("/tools/vault-harvest")
async def tool_vault_harvest(body: dict):
    from neurostack.harvest import harvest_sessions

    result = harvest_sessions(
        n_sessions=int(body.get("sessions", 1)),
        dry_run=body.get("dry_run", False),
        embed_url=EMBED_URL,
        provider=body.get("provider"),
    )
    return json.loads(json.dumps(result, default=str))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("BRIDGE_PORT", "8100"))
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
