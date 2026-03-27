# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Search and retrieval CLI commands."""

import json
import os
from pathlib import Path

from .utils import _get_workspace


def cmd_search(args):
    from ..search import hybrid_search
    results = hybrid_search(
        query=args.query,
        top_k=args.top_k,
        mode=args.mode,
        embed_url=args.embed_url,
        context=args.context,
        workspace=_get_workspace(args),
    )
    if args.json:
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
        print(json.dumps(output, indent=2, default=str))
        return
    if not results:
        print("  No results found.")
        # Check if DB has any notes at all
        from ..schema import get_db
        db_path = Path(os.environ.get("NEUROSTACK_DB_PATH", ""))
        if not db_path.name:
            from ..schema import DB_PATH
            db_path = Path(DB_PATH)
        if db_path.exists():
            conn = get_db(db_path)
            count = conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
            if count == 0:
                print("  \033[33m!\033[0m No notes indexed yet. Run: neurostack index")
        else:
            print("  \033[33m!\033[0m No database found. Run: neurostack index")
        return
    for r in results:
        print(f"\n{'='*60}")
        print(f"\U0001f4c4 {r.title} ({r.note_path})")
        print(f"   Section: {r.heading_path}")
        print(f"   Score: {r.score:.4f}")
        if r.summary:
            print(f"   Summary: {r.summary}")
        print(f"   Snippet: {r.snippet[:200]}")


def cmd_ask(args):
    from ..ask import ask_vault
    result = ask_vault(
        question=args.question,
        top_k=args.top_k,
        embed_url=args.embed_url,
        llm_url=args.summarize_url,
        workspace=_get_workspace(args),
    )
    if args.json:
        print(json.dumps(result, indent=2))
        return
    print(f"\n{result['answer']}\n")
    if result['sources']:
        print("Sources:")
        for s in result['sources']:
            print(f"  - {s['title']} ({s['path']})")


def cmd_summary(args):
    from ..schema import DB_PATH, get_db
    conn = get_db(DB_PATH)

    # Try as path first
    row = conn.execute(
        "SELECT n.path, n.title, n.frontmatter, s.summary_text FROM notes n "
        "LEFT JOIN summaries s ON s.note_path = n.path WHERE n.path = ?",
        (args.path_or_query,),
    ).fetchone()

    if row:
        if args.json:
            output = {
                "path": row["path"],
                "title": row["title"],
                "frontmatter": json.loads(row["frontmatter"]) if row["frontmatter"] else {},
                "summary": row["summary_text"] or "(not yet generated)",
            }
            print(json.dumps(output, indent=2, default=str))
            return
        print(f"Title: {row['title']}")
        print(f"Frontmatter: {row['frontmatter']}")
        print(f"Summary: {row['summary_text'] or '(not yet generated)'}")
    else:
        # Try as search query
        from ..search import hybrid_search
        results = hybrid_search(args.path_or_query, top_k=1, embed_url=args.embed_url)
        if results:
            r = results[0]
            if args.json:
                output = {
                    "path": r.note_path,
                    "title": r.title,
                    "summary": r.summary or "(not yet generated)",
                }
                print(json.dumps(output, indent=2, default=str))
                return
            print(f"Title: {r.title} ({r.note_path})")
            print(f"Summary: {r.summary or '(not yet generated)'}")
        else:
            if args.json:
                print(json.dumps({"error": "Note not found"}, indent=2, default=str))
                return
            print("No matching note found.")


def cmd_graph(args):
    from ..graph import get_neighborhood
    from ..search import _normalize_workspace
    result = get_neighborhood(args.note, depth=args.depth)
    ws = _normalize_workspace(_get_workspace(args))
    if result and ws:
        result.neighbors = [
            n for n in result.neighbors
            if n.path.startswith(ws + "/")
        ]
    if not result:
        if args.json:
            print(json.dumps({"error": f"Note not found: {args.note}"}, indent=2, default=str))
            return
        print(f"Note not found: {args.note}")
        return

    if args.json:
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
        output = {
            "center": node_to_dict(result.center),
            "neighbors": [node_to_dict(n) for n in result.neighbors],
            "neighbor_count": len(result.neighbors),
        }
        print(json.dumps(output, indent=2, default=str))
        return

    c = result.center
    print(f"\n\U0001f4cc {c.title} ({c.path})")
    print(f"   PageRank: {c.pagerank:.4f} | In: {c.in_degree} | Out: {c.out_degree}")
    if c.summary:
        print(f"   Summary: {c.summary}")

    if result.neighbors:
        print(f"\n\U0001f517 Neighbors ({len(result.neighbors)}):")
        for n in result.neighbors:
            print(f"   - {n.title} ({n.path}) PR:{n.pagerank:.4f}")
            if n.summary:
                print(f"     {n.summary[:100]}")


def cmd_related(args):
    from ..related import find_related
    results = find_related(
        note_path=args.note,
        top_k=args.top_k,
        workspace=_get_workspace(args),
    )
    if args.json:
        print(json.dumps(results, indent=2))
        return
    if not results:
        print("No related notes found.")
        return
    for r in results:
        print(f"\n  {r['title']} ({r['path']})")
        print(f"    Similarity: {r['score']:.4f}")
        if r.get('summary'):
            print(f"    Summary: {r['summary'][:200]}")


def cmd_brief(args):
    from ..brief import generate_brief
    brief = generate_brief(vault_root=Path(args.vault), workspace=_get_workspace(args))
    if args.json:
        print(json.dumps({"brief": brief}, indent=2, default=str))
        return
    print(brief)


def cmd_capture(args):
    from ..capture import capture_thought
    result = capture_thought(
        content=args.content,
        vault_root=args.vault,
        tags=args.tags.split(",") if args.tags else None,
    )
    if args.json:
        print(json.dumps(result, indent=2))
        return
    print(f"  Captured to: {result['path']}")


def cmd_triples(args):
    from ..search import search_triples
    results = search_triples(
        query=args.query,
        top_k=args.top_k,
        mode=args.mode,
        embed_url=args.embed_url,
        workspace=_get_workspace(args),
    )
    if args.json:
        output = []
        for t in results:
            output.append({
                "note": t.note_path,
                "title": t.title,
                "s": t.subject,
                "p": t.predicate,
                "o": t.object,
                "score": round(t.score, 4),
            })
        print(json.dumps(output, indent=2, default=str))
        return
    for t in results:
        print(f"  [{t.score:.3f}] {t.subject} | {t.predicate} | {t.object}")
        print(f"          from: {t.title} ({t.note_path})")


def cmd_tiered(args):
    from ..search import tiered_search
    result = tiered_search(
        query=args.query,
        top_k=args.top_k,
        depth=args.depth,
        mode=args.mode,
        embed_url=args.embed_url,
        context=getattr(args, "context", None),
        workspace=_get_workspace(args),
    )
    if args.json:
        print(json.dumps(result, indent=2, default=str))
        return
    print(f"Depth used: {result['depth_used']}")
    if result["triples"]:
        print(f"\n--- Triples ({len(result['triples'])}) ---")
        for t in result["triples"]:
            print(f"  [{t['score']:.3f}] {t['s']} | {t['p']} | {t['o']}  ({t['title']})")
    if result["summaries"]:
        print(f"\n--- Summaries ({len(result['summaries'])}) ---")
        for s in result["summaries"]:
            print(f"  {s['title']} ({s['note']})")
            print(f"    {s['summary'][:200]}")
    if result["chunks"]:
        print(f"\n--- Chunks ({len(result['chunks'])}) ---")
        for c in result["chunks"]:
            print(f"  [{c['score']:.3f}] {c['title']} > {c['section']}")
            print(f"    {c['snippet'][:200]}")


def cmd_communities(args):
    if args.communities_cmd == "build":
        from ..attractor import detect_communities
        from ..community import summarize_all_communities
        n_coarse, n_fine = detect_communities()
        if args.json:
            summarize_all_communities(
                summarize_url=args.summarize_url,
                embed_url=args.embed_url,
            )
            print(json.dumps(
                {"coarse": n_coarse, "fine": n_fine, "status": "done"},
                indent=2, default=str,
            ))
            return
        print(f"Detected {n_coarse} coarse communities, {n_fine} fine communities.")
        print("Generating LLM summaries (this may take a few minutes)...")
        summarize_all_communities(
            summarize_url=args.summarize_url,
            embed_url=args.embed_url,
        )
        print("Done.")
    elif args.communities_cmd == "query":
        from ..community_search import global_query
        result = global_query(
            query=args.query,
            top_k=args.top_k,
            level=args.level,
            use_map_reduce=not args.no_map_reduce,
            embed_url=args.embed_url,
            summarize_url=args.summarize_url,
            workspace=_get_workspace(args),
        )
        if args.json:
            print(json.dumps(result, indent=2, default=str))
            return
        print(f"\nCommunities used: {result['communities_used']}")
        print("\nTop communities:")
        for hit in result["community_hits"][:5]:
            print(
                f"  [{hit['score']:.3f}] L{hit['level']}"
                f" {hit['title']} ({hit['entity_count']} entities)"
            )
        if result["answer"]:
            print(f"\n{'='*60}\n{result['answer']}")
    elif args.communities_cmd == "list":
        from ..schema import DB_PATH, get_db
        conn = get_db(DB_PATH)
        level_filter = args.level if hasattr(args, "level") and args.level is not None else None
        q = "SELECT community_id, level, title, entity_count, member_notes FROM communities"
        params = []
        if level_filter is not None:
            q += " WHERE level = ?"
            params.append(level_filter)
        q += " ORDER BY level, entity_count DESC"
        rows = conn.execute(q, params).fetchall()
        if args.json:
            output = []
            for row in rows:
                output.append({
                    "community_id": row["community_id"],
                    "level": row["level"],
                    "title": row["title"] or None,
                    "entity_count": row["entity_count"],
                    "member_notes": row["member_notes"],
                })
            print(json.dumps(output, indent=2, default=str))
            return
        if not rows:
            print("No communities found. Run: cli.py communities build")
        else:
            for row in rows:
                title = row["title"] or "(unsummarized)"
                print(
                    f"  [L{row['level']}] #{row['community_id']}"
                    f" {title} \u2014 {row['entity_count']} entities,"
                    f" {row['member_notes']} notes"
                )
    else:
        print("Usage: cli.py communities {build|query|list}")


def cmd_folder_summaries(args):
    """Build or rebuild folder-level summaries for semantic context= boosting."""
    import numpy as np

    from ..embedder import get_embedding
    from ..schema import DB_PATH, get_db
    from ..summarizer import summarize_folder

    conn = get_db(DB_PATH)

    # Collect all unique folder paths that have indexed notes with summaries
    rows = conn.execute(
        """SELECT DISTINCT s.note_path, n.title, s.summary_text
           FROM summaries s
           JOIN notes n ON n.path = s.note_path
           WHERE s.summary_text IS NOT NULL"""
    ).fetchall()

    # Group notes by their immediate parent folder
    from collections import defaultdict
    folders: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        note_path = row["note_path"]
        parts = note_path.split("/")
        if len(parts) < 2:
            continue  # skip root-level notes (no folder)
        folder = "/".join(parts[:-1])
        folders[folder].append({"title": row["title"], "summary": row["summary_text"]})

    # Also add parent folders recursively (so "work" gets contributions from "work/my-project")
    all_folders = dict(folders)
    for folder, notes in list(folders.items()):
        parts = folder.split("/")
        for depth in range(1, len(parts)):
            parent = "/".join(parts[:depth])
            all_folders.setdefault(parent, []).extend(notes)

    print(f"Building summaries for {len(all_folders)} folders...")

    for folder_path, child_notes in sorted(all_folders.items()):
        # Skip if already up-to-date (same note count)
        existing = conn.execute(
            "SELECT note_count FROM folder_summaries WHERE folder_path = ?",
            (folder_path,),
        ).fetchone()
        if existing and existing["note_count"] == len(child_notes) and not args.force:
            continue

        print(f"  {folder_path} ({len(child_notes)} notes)...")
        summary_text = summarize_folder(
            folder_path=folder_path,
            child_summaries=child_notes,
            base_url=args.summarize_url,
        )
        if not summary_text:
            continue

        # Generate embedding for the folder summary
        embedding = get_embedding(summary_text, base_url=args.embed_url)
        embedding_blob = embedding.astype(np.float32).tobytes()

        conn.execute(
            """INSERT OR REPLACE INTO folder_summaries
               (folder_path, summary_text, embedding, note_count, generated_at)
               VALUES (?, ?, ?, ?, datetime('now'))""",
            (folder_path, summary_text, embedding_blob, len(child_notes)),
        )
        conn.commit()

    total = conn.execute("SELECT COUNT(*) as c FROM folder_summaries").fetchone()["c"]
    print(f"Done. {total} folder summaries in index.")


def cmd_stats(args):
    from ..schema import DB_PATH, get_db
    conn = get_db(DB_PATH)
    notes = conn.execute("SELECT COUNT(*) as c FROM notes").fetchone()["c"]
    chunks = conn.execute("SELECT COUNT(*) as c FROM chunks").fetchone()["c"]
    embedded = conn.execute(
        "SELECT COUNT(*) as c FROM chunks"
        " WHERE embedding IS NOT NULL"
    ).fetchone()["c"]
    summaries = conn.execute(
        "SELECT COUNT(*) as c FROM summaries"
    ).fetchone()["c"]
    edges = conn.execute(
        "SELECT COUNT(*) as c FROM graph_edges"
    ).fetchone()["c"]
    total_triples = conn.execute(
        "SELECT COUNT(*) as c FROM triples"
    ).fetchone()["c"]
    notes_with_triples = conn.execute(
        "SELECT COUNT(DISTINCT note_path) as c FROM triples"
    ).fetchone()["c"]

    from ..cooccurrence import get_cooccurrence_stats
    cooc = get_cooccurrence_stats(conn)

    if args.json:
        embed_pct = embedded * 100 // max(chunks, 1)
        sum_pct = summaries * 100 // max(notes, 1)
        triple_pct = notes_with_triples * 100 // max(notes, 1)
        output = {
            "notes": notes,
            "chunks": chunks,
            "embedded": embedded,
            "embedding_coverage": f"{embed_pct}%",
            "summaries": summaries,
            "summary_coverage": f"{sum_pct}%",
            "graph_edges": edges,
            "triples": total_triples,
            "notes_with_triples": notes_with_triples,
            "triple_coverage": f"{triple_pct}%",
            "cooccurrence_pairs": cooc["pairs"],
            "cooccurrence_total_weight": cooc["total_weight"],
        }
        print(json.dumps(output, indent=2, default=str))
        return

    # Detect if running in lite mode
    is_lite = False
    try:
        import numpy  # noqa: F401
    except ImportError:
        is_lite = True
    full_tag = " \033[33m(full mode required)\033[0m" if is_lite else ""

    print(f"Notes:       {notes}")
    print(f"Chunks:      {chunks}")
    embed_pct = embedded * 100 // max(chunks, 1)
    print(f"Embedded:    {embedded} ({embed_pct}%){full_tag}")
    sum_pct = summaries * 100 // max(notes, 1)
    print(f"Summarized:  {summaries} ({sum_pct}%){full_tag}")
    print(f"Graph edges: {edges}")
    triple_pct = notes_with_triples * 100 // max(notes, 1)
    print(
        f"Triples:     {total_triples} from"
        f" {notes_with_triples} notes ({triple_pct}%){full_tag}"
    )
    print(
        f"Co-occurrence: {cooc['pairs']} pairs"
        f" ({cooc['total_weight']:.1f} total weight)"
    )


def cmd_prediction_errors(args):
    from ..schema import DB_PATH, get_db
    from ..search import _normalize_workspace
    conn = get_db(DB_PATH)

    if args.resolve:
        paths = args.resolve
        placeholders = ",".join("?" * len(paths))
        conn.execute(
            "UPDATE prediction_errors"
            " SET resolved_at = datetime('now')"
            f" WHERE note_path IN ({placeholders})"
            " AND resolved_at IS NULL",
            paths,
        )
        conn.commit()
        if args.json:
            print(json.dumps({"resolved": len(paths), "paths": paths}, indent=2, default=str))
            return
        print(f"Resolved {len(paths)} note(s).")
        return

    where = "WHERE resolved_at IS NULL"
    params = []
    if args.type:
        where += " AND error_type = ?"
        params.append(args.type)

    ws = _normalize_workspace(_get_workspace(args))
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
        ORDER BY occurrences DESC, avg_distance DESC
        LIMIT ?
        """,
        params + [args.limit],
    ).fetchall()

    total_where = "WHERE resolved_at IS NULL"
    total_params = []
    if ws:
        total_where += " AND note_path LIKE ? || '%'"
        total_params.append(ws + "/")

    total = conn.execute(
        f"SELECT COUNT(DISTINCT note_path) FROM prediction_errors {total_where}",
        total_params,
    ).fetchone()[0]

    if args.json:
        errors = [
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
        print(json.dumps({
            "total_flagged_notes": total,
            "showing": len(errors),
            "errors": errors,
        }, indent=2, default=str))
        return

    if not rows:
        print("No unresolved prediction errors.")
        return

    print(f"\n=== Prediction Errors ({total} flagged notes) ===\n")
    by_type: dict = {}
    for r in rows:
        by_type.setdefault(r["error_type"], []).append(r)

    for etype, entries in sorted(by_type.items()):
        label = {
            "low_overlap": "LOW OVERLAP  \u2014 semantically distant from retrieval query",
            "contextual_mismatch": "CONTEXT MISMATCH \u2014 surfaced outside expected domain",
        }.get(etype, etype.upper())
        print(f"\u25b6 {label}")
        for e in entries:
            ctx = f" [{e['context']}]" if e["context"] else ""
            print(f"  {e['note_path']}{ctx}")
            print(
                f"    distance={e['avg_distance']:.3f}"
                f"  hits={e['occurrences']}"
                f"  last={e['last_seen'][:10]}"
            )
            sample = e['sample_query'][:80]
            print(f"    query: \"{sample}\"")
        print()

    print("Resolve a note: cli.py prediction-errors --resolve <note_path>")


def cmd_record_usage(args):
    """Record that specific notes were used, driving hotness scoring."""
    from ..schema import DB_PATH, get_db

    conn = get_db(DB_PATH)
    conn.executemany(
        "INSERT INTO note_usage (note_path) VALUES (?)",
        [(p,) for p in args.note_paths],
    )
    conn.commit()
    print(f"Recorded usage for {len(args.note_paths)} note(s).")
    for p in args.note_paths:
        print(f"  {p}")


def cmd_context(args):
    """Assemble task-scoped context for session recovery."""
    from ..context import build_vault_context
    from ..schema import DB_PATH, get_db

    conn = get_db(DB_PATH)
    result = build_vault_context(
        conn,
        task=args.task,
        token_budget=args.budget,
        workspace=_get_workspace(args) if hasattr(args, "workspace") else None,
        include_memories=not args.no_memories,
        include_triples=not args.no_triples,
        embed_url=args.embed_url,
    )

    if args.json:
        print(json.dumps(result, indent=2))
        return

    print(f"\n  Context for: {result['task']}")
    print(f"  Tokens used: ~{result['tokens_used']}")
    if result.get("workspace"):
        print(f"  Workspace: {result['workspace']}")

    ctx = result.get("context", {})

    if ctx.get("memories"):
        print(f"\n  \033[1mMemories ({len(ctx['memories'])}):\033[0m")
        for m in ctx["memories"]:
            tags = f" [{', '.join(m['tags'])}]" if m.get("tags") else ""
            print(f"    [{m['entity_type']}] {m['content'][:100]}{tags}")

    if ctx.get("triples"):
        print(f"\n  \033[1mTriples ({len(ctx['triples'])}):\033[0m")
        for t in ctx["triples"]:
            print(f"    {t['s']} -> {t['p']} -> {t['o']}")

    if ctx.get("summaries"):
        print(f"\n  \033[1mRelevant notes ({len(ctx['summaries'])}):\033[0m")
        for s in ctx["summaries"]:
            print(f"    {s['path']} ({s['score']:.4f})")
            if s.get("summary"):
                print(f"      {s['summary'][:120]}")

    if ctx.get("session_history"):
        print(f"\n  \033[1mRecent sessions ({len(ctx['session_history'])}):\033[0m")
        for s in ctx["session_history"]:
            print(f"    #{s['session_id']} ({s['started_at']}): {s['summary']}")


def cmd_decay(args):
    """Report note excitability and dormancy status."""
    from ..schema import DB_PATH, get_db
    from ..search import get_dormancy_report

    conn = get_db(DB_PATH)

    if getattr(args, "demote", False):
        from ..search import run_excitability_demotion
        result = run_excitability_demotion(
            conn,
            threshold=args.threshold,
            half_life_days=args.half_life,
        )
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"\n  Demoted {result['demoted']} notes to dormant status")
            for p in result["paths"]:
                print(f"    {p}")
        return

    report = get_dormancy_report(
        conn,
        threshold=args.threshold,
        half_life_days=args.half_life,
        limit=args.limit,
    )

    if args.json:
        print(json.dumps(report, indent=2))
        return

    print(f"\n  Excitability Report (threshold={report['threshold']}, "
          f"half-life={report['half_life_days']}d)")
    print(f"  Total: {report['total_notes']} notes | "
          f"Active: {report['active_count']} | "
          f"Dormant: {report['dormant_count']} | "
          f"Never used: {report['never_used_count']}")

    if report["dormant"]:
        print(f"\n  \033[33mDormant notes (hotness < {report['threshold']}):\033[0m")
        for n in report["dormant"]:
            print(f"    {n['hotness']:.4f}  {n['path']}")

    if report["never_used"]:
        print("\n  \033[90mNever-used notes:\033[0m")
        for n in report["never_used"][:20]:
            print(f"    -  {n['path']}")
        if report["never_used_count"] > 20:
            print(f"    ... and {report['never_used_count'] - 20} more")

    if report["active"]:
        print("\n  \033[32mTop active notes:\033[0m")
        for n in report["active"][:10]:
            print(f"    {n['hotness']:.4f}  {n['path']}")


def cmd_cooccurrence(args):
    """Inspect entity co-occurrence pairs."""
    from ..cooccurrence import get_cooccurrence_stats, get_top_pairs
    from ..schema import DB_PATH, get_db

    conn = get_db(DB_PATH)
    pairs = get_top_pairs(conn, limit=args.limit)

    if args.json:
        print(json.dumps(pairs, indent=2, default=str))
        return

    stats = get_cooccurrence_stats(conn)

    if not pairs:
        print("No co-occurrence data. Run 'neurostack communities build' to populate.")
        return

    print(
        f"\n  Co-occurrence: {stats['pairs']} pairs"
        f" ({stats['total_weight']:.1f} total weight)"
    )
    print(f"\n  Top {args.limit} entity pairs by weight:")
    for p in pairs:
        last = p["last_seen"][:10] if len(p["last_seen"]) >= 10 else p["last_seen"]
        print(f"    {p['weight']:>8.2f}  {p['entity_a']} <-> {p['entity_b']}  (last: {last})")
