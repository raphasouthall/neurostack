#!/usr/bin/env python3
"""CLI entry point for neurostack."""

import argparse
import json
import sys
from pathlib import Path

from .config import get_config


def cmd_index(args):
    from .watcher import full_index
    full_index(
        vault_root=Path(args.vault),
        embed_url=args.embed_url,
        summarize_url=args.summarize_url,
        skip_summary=args.skip_summary,
        skip_triples=args.skip_triples,
    )


def cmd_search(args):
    from .search import hybrid_search
    results = hybrid_search(
        query=args.query,
        top_k=args.top_k,
        mode=args.mode,
        embed_url=args.embed_url,
        context=args.context,
        rerank=args.rerank,
    )
    for r in results:
        print(f"\n{'='*60}")
        print(f"📄 {r.title} ({r.note_path})")
        print(f"   Section: {r.heading_path}")
        print(f"   Score: {r.score:.4f}")
        if r.summary:
            print(f"   Summary: {r.summary}")
        print(f"   Snippet: {r.snippet[:200]}")


def cmd_summary(args):
    from .schema import get_db, DB_PATH
    conn = get_db(DB_PATH)

    # Try as path first
    row = conn.execute(
        "SELECT n.title, n.frontmatter, s.summary_text FROM notes n "
        "LEFT JOIN summaries s ON s.note_path = n.path WHERE n.path = ?",
        (args.path_or_query,),
    ).fetchone()

    if row:
        print(f"Title: {row['title']}")
        print(f"Frontmatter: {row['frontmatter']}")
        print(f"Summary: {row['summary_text'] or '(not yet generated)'}")
    else:
        # Try as search query
        from .search import hybrid_search
        results = hybrid_search(args.path_or_query, top_k=1, embed_url=args.embed_url)
        if results:
            r = results[0]
            print(f"Title: {r.title} ({r.note_path})")
            print(f"Summary: {r.summary or '(not yet generated)'}")
        else:
            print("No matching note found.")


def cmd_graph(args):
    from .graph import get_neighborhood
    result = get_neighborhood(args.note, depth=args.depth)
    if not result:
        print(f"Note not found: {args.note}")
        return
    c = result.center
    print(f"\n📌 {c.title} ({c.path})")
    print(f"   PageRank: {c.pagerank:.4f} | In: {c.in_degree} | Out: {c.out_degree}")
    if c.summary:
        print(f"   Summary: {c.summary}")

    if result.neighbors:
        print(f"\n🔗 Neighbors ({len(result.neighbors)}):")
        for n in result.neighbors:
            print(f"   - {n.title} ({n.path}) PR:{n.pagerank:.4f}")
            if n.summary:
                print(f"     {n.summary[:100]}")


def cmd_brief(args):
    from .brief import generate_brief
    print(generate_brief(vault_root=Path(args.vault)))


def cmd_triples(args):
    from .search import search_triples
    results = search_triples(
        query=args.query,
        top_k=args.top_k,
        mode=args.mode,
        embed_url=args.embed_url,
    )
    for t in results:
        print(f"  [{t.score:.3f}] {t.subject} | {t.predicate} | {t.object}")
        print(f"          from: {t.title} ({t.note_path})")


def cmd_tiered(args):
    from .search import tiered_search
    result = tiered_search(
        query=args.query,
        top_k=args.top_k,
        depth=args.depth,
        mode=args.mode,
        embed_url=args.embed_url,
        context=getattr(args, "context", None),
        rerank=args.rerank,
    )
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


def cmd_reembed_chunks(args):
    from .watcher import reembed_all_chunks
    reembed_all_chunks(embed_url=args.embed_url)


def cmd_backfill(args):
    from .watcher import backfill_summaries, backfill_stale_summaries, backfill_triples
    if args.target in ("summaries", "all"):
        backfill_summaries(
            vault_root=Path(args.vault),
            summarize_url=args.summarize_url,
        )
        backfill_stale_summaries(
            vault_root=Path(args.vault),
            summarize_url=args.summarize_url,
        )
    if args.target in ("triples", "all"):
        backfill_triples(
            vault_root=Path(args.vault),
            embed_url=args.embed_url,
            summarize_url=args.summarize_url,
        )


def cmd_communities(args):
    if args.communities_cmd == "build":
        from .leiden import detect_communities
        from .community import summarize_all_communities
        n_coarse, n_fine = detect_communities()
        print(f"Detected {n_coarse} coarse communities, {n_fine} fine communities.")
        print("Generating LLM summaries (this may take a few minutes)...")
        summarize_all_communities(
            summarize_url=args.summarize_url,
            embed_url=args.embed_url,
        )
        print("Done.")
    elif args.communities_cmd == "query":
        from .community_search import global_query
        result = global_query(
            query=args.query,
            top_k=args.top_k,
            level=args.level,
            use_map_reduce=not args.no_map_reduce,
            embed_url=args.embed_url,
            summarize_url=args.summarize_url,
        )
        print(f"\nCommunities used: {result['communities_used']}")
        print(f"\nTop communities:")
        for hit in result["community_hits"][:5]:
            print(f"  [{hit['score']:.3f}] L{hit['level']} {hit['title']} ({hit['entity_count']} entities)")
        if result["answer"]:
            print(f"\n{'='*60}\n{result['answer']}")
    elif args.communities_cmd == "list":
        from .schema import get_db, DB_PATH
        conn = get_db(DB_PATH)
        level_filter = args.level if hasattr(args, "level") and args.level is not None else None
        q = "SELECT community_id, level, title, entity_count, member_notes FROM communities"
        params = []
        if level_filter is not None:
            q += " WHERE level = ?"
            params.append(level_filter)
        q += " ORDER BY level, entity_count DESC"
        rows = conn.execute(q, params).fetchall()
        if not rows:
            print("No communities found. Run: cli.py communities build")
        else:
            for row in rows:
                title = row["title"] or "(unsummarized)"
                print(f"  [L{row['level']}] #{row['community_id']} {title} — {row['entity_count']} entities, {row['member_notes']} notes")
    else:
        print("Usage: cli.py communities {build|query|list}")


def cmd_folder_summaries(args):
    """Build or rebuild folder-level summaries for semantic context= boosting."""
    import numpy as np
    from .schema import get_db, DB_PATH
    from .summarizer import summarize_folder
    from .embedder import get_embedding

    conn = get_db(DB_PATH)
    vault_root = Path(args.vault)

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
    from .schema import get_db, DB_PATH
    conn = get_db(DB_PATH)
    notes = conn.execute("SELECT COUNT(*) as c FROM notes").fetchone()["c"]
    chunks = conn.execute("SELECT COUNT(*) as c FROM chunks").fetchone()["c"]
    embedded = conn.execute("SELECT COUNT(*) as c FROM chunks WHERE embedding IS NOT NULL").fetchone()["c"]
    summaries = conn.execute("SELECT COUNT(*) as c FROM summaries").fetchone()["c"]
    edges = conn.execute("SELECT COUNT(*) as c FROM graph_edges").fetchone()["c"]
    total_triples = conn.execute("SELECT COUNT(*) as c FROM triples").fetchone()["c"]
    notes_with_triples = conn.execute("SELECT COUNT(DISTINCT note_path) as c FROM triples").fetchone()["c"]

    print(f"Notes:       {notes}")
    print(f"Chunks:      {chunks}")
    print(f"Embedded:    {embedded} ({embedded*100//max(chunks,1)}%)")
    print(f"Summarized:  {summaries} ({summaries*100//max(notes,1)}%)")
    print(f"Graph edges: {edges}")
    print(f"Triples:     {total_triples} from {notes_with_triples} notes ({notes_with_triples*100//max(notes,1)}%)")


def cmd_prediction_errors(args):
    from .schema import get_db, DB_PATH
    conn = get_db(DB_PATH)

    if args.resolve:
        paths = args.resolve
        conn.execute(
            "UPDATE prediction_errors SET resolved_at = datetime('now') WHERE note_path IN ({}) AND resolved_at IS NULL".format(
                ",".join("?" * len(paths))
            ),
            paths,
        )
        conn.commit()
        print(f"Resolved {len(paths)} note(s).")
        return

    where = "WHERE resolved_at IS NULL"
    params = []
    if args.type:
        where += " AND error_type = ?"
        params.append(args.type)

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

    total = conn.execute(
        "SELECT COUNT(DISTINCT note_path) FROM prediction_errors WHERE resolved_at IS NULL"
    ).fetchone()[0]

    if not rows:
        print("No unresolved prediction errors.")
        return

    print(f"\n=== Prediction Errors ({total} flagged notes) ===\n")
    by_type: dict = {}
    for r in rows:
        by_type.setdefault(r["error_type"], []).append(r)

    for etype, entries in sorted(by_type.items()):
        label = {
            "low_overlap": "LOW OVERLAP  — semantically distant from retrieval query",
            "contextual_mismatch": "CONTEXT MISMATCH — surfaced outside expected domain",
        }.get(etype, etype.upper())
        print(f"▶ {label}")
        for e in entries:
            ctx = f" [{e['context']}]" if e["context"] else ""
            print(f"  {e['note_path']}{ctx}")
            print(f"    distance={e['avg_distance']:.3f}  hits={e['occurrences']}  last={e['last_seen'][:10]}")
            print(f"    query: \"{e['sample_query'][:80]}\"")
        print()

    print(f"Resolve a note: cli.py prediction-errors --resolve <note_path>")


def cmd_watch(args):
    from .watcher import run_watcher
    run_watcher(
        vault_root=Path(args.vault),
        embed_url=args.embed_url,
        summarize_url=args.summarize_url,
    )


def main():
    from .config import get_config
    cfg = get_config()

    parser = argparse.ArgumentParser(description="neurostack: Local AI context engine")
    parser.add_argument("--vault", default=str(cfg.vault_root), help="Vault root path")
    parser.add_argument("--embed-url", default=cfg.embed_url, help="Ollama embed URL")
    parser.add_argument("--summarize-url", default=cfg.llm_url, help="Ollama summarize URL")

    sub = parser.add_subparsers(dest="command")

    # index
    p = sub.add_parser("index", help="Full re-index of vault")
    p.add_argument("--skip-summary", action="store_true", help="Skip LLM summarization")
    p.add_argument("--skip-triples", action="store_true", help="Skip triple extraction")
    p.set_defaults(func=cmd_index)

    # search
    p = sub.add_parser("search", help="Search the vault")
    p.add_argument("query", help="Search query")
    p.add_argument("--top-k", type=int, default=5)
    p.add_argument("--mode", choices=["hybrid", "semantic", "keyword"], default="hybrid")
    p.add_argument("--context", "-c", default=None, help="Project/domain context for result boosting")
    p.add_argument("--rerank", action="store_true", default=False, help="Apply cross-encoder reranking")
    p.set_defaults(func=cmd_search)

    # summary
    p = sub.add_parser("summary", help="Get note summary")
    p.add_argument("path_or_query", help="Note path or search query")
    p.set_defaults(func=cmd_summary)

    # graph
    p = sub.add_parser("graph", help="Get note neighborhood")
    p.add_argument("note", help="Note path")
    p.add_argument("--depth", type=int, default=1)
    p.set_defaults(func=cmd_graph)

    # triples
    p = sub.add_parser("triples", help="Search knowledge graph triples")
    p.add_argument("query", help="Search query")
    p.add_argument("--top-k", type=int, default=10)
    p.add_argument("--mode", choices=["hybrid", "semantic", "keyword"], default="hybrid")
    p.set_defaults(func=cmd_triples)

    # tiered
    p = sub.add_parser("tiered", help="Tiered search (triples → summaries → full)")
    p.add_argument("query", help="Search query")
    p.add_argument("--top-k", type=int, default=5)
    p.add_argument("--depth", choices=["triples", "summaries", "full", "auto"], default="auto")
    p.add_argument("--mode", choices=["hybrid", "semantic", "keyword"], default="hybrid")
    p.add_argument("--context", "-c", default=None, help="Project/domain context for result boosting")
    p.add_argument("--rerank", action="store_true", default=False, help="Apply cross-encoder reranking")
    p.set_defaults(func=cmd_tiered)

    # reembed-chunks
    p = sub.add_parser("reembed-chunks", help="Re-embed all chunks with contextual text (title+tags+summary+chunk)")
    p.set_defaults(func=cmd_reembed_chunks)

    # backfill
    p = sub.add_parser("backfill", help="Backfill missing summaries and/or triples")
    p.add_argument("target", choices=["summaries", "triples", "all"], default="all", nargs="?")
    p.set_defaults(func=cmd_backfill)

    # communities
    p = sub.add_parser("communities", help="GraphRAG community detection and global queries")
    comm_sub = p.add_subparsers(dest="communities_cmd")

    # communities build
    comm_sub.add_parser("build", help="Run Leiden detection + generate LLM community summaries")

    # communities query
    p_q = comm_sub.add_parser("query", help="Global query over community summaries (GraphRAG)")
    p_q.add_argument("query", help="Natural language question")
    p_q.add_argument("--top-k", type=int, default=6)
    p_q.add_argument("--level", type=int, default=0, help="Community level (0=coarse, 1=fine)")
    p_q.add_argument("--no-map-reduce", action="store_true", help="Return raw community hits without LLM synthesis")

    # communities list
    p_l = comm_sub.add_parser("list", help="List detected communities")
    p_l.add_argument("--level", type=int, default=None, help="Filter by level (0 or 1)")

    p.set_defaults(func=cmd_communities)

    # brief
    p = sub.add_parser("brief", help="Generate session brief")
    p.set_defaults(func=cmd_brief)

    # folder-summaries
    p = sub.add_parser("folder-summaries", help="Build folder-level summaries for semantic context= boosting")
    p.add_argument("--force", action="store_true", help="Regenerate all even if up-to-date")
    p.set_defaults(func=cmd_folder_summaries)

    # prediction-errors
    p = sub.add_parser("prediction-errors", help="Show notes flagged as prediction errors (poor retrieval fit)")
    p.add_argument("--type", choices=["low_overlap", "contextual_mismatch"], default=None,
                   help="Filter by error type")
    p.add_argument("--limit", type=int, default=30, help="Max results to show")
    p.add_argument("--resolve", nargs="+", metavar="NOTE_PATH",
                   help="Mark note(s) as resolved")
    p.set_defaults(func=cmd_prediction_errors)

    # stats
    p = sub.add_parser("stats", help="Show index stats")
    p.set_defaults(func=cmd_stats)

    # watch
    p = sub.add_parser("watch", help="Watch vault for changes")
    p.set_defaults(func=cmd_watch)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
