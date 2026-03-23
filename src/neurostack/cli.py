#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""CLI entry point for neurostack."""

import argparse
import json
import os
import sys
import time
import webbrowser
from pathlib import Path

import httpx

from . import __version__
from .cloud.client import CloudClient
from .cloud.config import CloudConfig, clear_cloud_credentials, load_cloud_config, save_cloud_config
from .config import CONFIG_PATH, get_config


def cmd_index(args):
    from .schema import DB_PATH, get_db
    from .watcher import full_index
    full_index(
        vault_root=Path(args.vault),
        embed_url=args.embed_url,
        summarize_url=args.summarize_url,
        skip_summary=args.skip_summary,
        skip_triples=args.skip_triples,
    )
    db_path = Path(os.environ.get("NEUROSTACK_DB_PATH", DB_PATH))
    conn = get_db(db_path)
    notes = conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
    chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    edges = conn.execute("SELECT COUNT(*) FROM graph_edges").fetchone()[0]
    print(f"Indexed {notes} notes, {chunks} chunks, {edges} graph edges.")
    if notes == 0:
        print("\n  \033[33m!\033[0m No Markdown files found in the vault.")
        print("  Add .md files to your vault, then run: neurostack index")


def _get_workspace(args) -> str | None:
    """Get workspace from args or NEUROSTACK_WORKSPACE env var."""
    ws = getattr(args, "workspace", None)
    if not ws:
        ws = os.environ.get("NEUROSTACK_WORKSPACE")
    return ws or None


def cmd_search(args):
    from .search import hybrid_search
    results = hybrid_search(
        query=args.query,
        top_k=args.top_k,
        mode=args.mode,
        embed_url=args.embed_url,
        context=args.context,
        rerank=args.rerank,
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
        from .schema import get_db
        db_path = Path(os.environ.get("NEUROSTACK_DB_PATH", ""))
        if not db_path.name:
            from .schema import DB_PATH
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
        print(f"📄 {r.title} ({r.note_path})")
        print(f"   Section: {r.heading_path}")
        print(f"   Score: {r.score:.4f}")
        if r.summary:
            print(f"   Summary: {r.summary}")
        print(f"   Snippet: {r.snippet[:200]}")


def cmd_ask(args):
    from .ask import ask_vault
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
    from .schema import DB_PATH, get_db
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
        from .search import hybrid_search
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
    from .graph import get_neighborhood
    from .search import _normalize_workspace
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


def cmd_related(args):
    from .related import find_related
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
    from .brief import generate_brief
    brief = generate_brief(vault_root=Path(args.vault), workspace=_get_workspace(args))
    if args.json:
        print(json.dumps({"brief": brief}, indent=2, default=str))
        return
    print(brief)


def cmd_capture(args):
    from .capture import capture_thought
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
    from .search import search_triples
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
    from .search import tiered_search
    result = tiered_search(
        query=args.query,
        top_k=args.top_k,
        depth=args.depth,
        mode=args.mode,
        embed_url=args.embed_url,
        context=getattr(args, "context", None),
        rerank=args.rerank,
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


def cmd_reembed_chunks(args):
    from .watcher import reembed_all_chunks
    reembed_all_chunks(embed_url=args.embed_url)


def cmd_backfill(args):
    from .watcher import backfill_stale_summaries, backfill_summaries, backfill_triples
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
    if args.target in ("cooccurrence", "all"):
        from .cooccurrence import persist_cooccurrence
        from .schema import DB_PATH, get_db
        conn = get_db(DB_PATH)
        n = persist_cooccurrence(conn)
        print(f"Co-occurrence backfill: {n} entity pairs populated.")


def cmd_communities(args):
    if args.communities_cmd == "build":
        from .community import summarize_all_communities
        from .leiden import detect_communities
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
        from .community_search import global_query
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
        from .schema import DB_PATH, get_db
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
                    f" {title} — {row['entity_count']} entities,"
                    f" {row['member_notes']} notes"
                )
    else:
        print("Usage: cli.py communities {build|query|list}")


def cmd_folder_summaries(args):
    """Build or rebuild folder-level summaries for semantic context= boosting."""
    import numpy as np

    from .embedder import get_embedding
    from .schema import DB_PATH, get_db
    from .summarizer import summarize_folder

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
    from .schema import DB_PATH, get_db
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

    from .cooccurrence import get_cooccurrence_stats
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
    from .schema import DB_PATH, get_db
    from .search import _normalize_workspace
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
            "low_overlap": "LOW OVERLAP  — semantically distant from retrieval query",
            "contextual_mismatch": "CONTEXT MISMATCH — surfaced outside expected domain",
        }.get(etype, etype.upper())
        print(f"▶ {label}")
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
    from .schema import DB_PATH, get_db

    conn = get_db(DB_PATH)
    conn.executemany(
        "INSERT INTO note_usage (note_path) VALUES (?)",
        [(p,) for p in args.note_paths],
    )
    conn.commit()
    print(f"Recorded usage for {len(args.note_paths)} note(s).")
    for p in args.note_paths:
        print(f"  {p}")


def cmd_watch(args):
    from .watcher import run_watcher
    run_watcher(
        vault_root=Path(args.vault),
        embed_url=args.embed_url,
        summarize_url=args.summarize_url,
    )


def _detect_hardware():
    """Detect RAM and GPU for mode recommendation."""
    import shutil
    import subprocess

    ram_gb = 0
    try:
        import os as _os
        mem_bytes = _os.sysconf("SC_PAGE_SIZE") * _os.sysconf("SC_PHYS_PAGES")
        ram_gb = mem_bytes / (1024 ** 3)
    except (ValueError, OSError):
        pass

    gpu_name = None
    gpu_vram_gb = 0
    nvidia_smi = shutil.which("nvidia-smi")
    if nvidia_smi:
        try:
            result = subprocess.run(
                [nvidia_smi, "--query-gpu=name,memory.total",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                line = result.stdout.strip().split("\n")[0]
                parts = line.split(", ")
                if len(parts) == 2:
                    gpu_name = parts[0].strip()
                    gpu_vram_gb = int(parts[1].strip()) / 1024
        except Exception:
            pass

    return ram_gb, gpu_name, gpu_vram_gb


def _print_hardware_recommendation():
    """Print hardware info and recommend lite or full mode."""
    ram_gb, gpu_name, gpu_vram_gb = _detect_hardware()

    print("  \033[1mSystem\033[0m")
    if ram_gb > 0:
        print(f"    RAM:  {ram_gb:.0f} GB")
    if gpu_name:
        print(f"    GPU:  {gpu_name} ({gpu_vram_gb:.0f} GB VRAM)")
    else:
        print("    GPU:  None detected")

    # Recommendation: full needs 16GB+ RAM and a GPU with 6GB+ VRAM
    if gpu_name and gpu_vram_gb >= 6 and ram_gb >= 16:
        print(
            "    \033[32m✓\033[0m Recommended: \033[1mfull\033[0m mode"
            " (embeddings + LLM summaries)"
        )
        print("      Upgrade anytime: neurostack install --mode full")
    elif gpu_name and gpu_vram_gb >= 4:
        print(
            "    \033[33m!\033[0m Recommended: \033[1mlite\033[0m mode"
            " (GPU has limited VRAM for full mode)"
        )
        print("      Upgrade anytime: neurostack install --mode full")
    else:
        print(
            "    \033[36m▸\033[0m Recommended: \033[1mlite\033[0m mode"
            " (full mode requires a GPU with 6+ GB VRAM)"
        )
        print("      Upgrade anytime: neurostack install --mode full")


def _prompt(label, default="", choices=None):
    """Interactive prompt with optional default and choices."""
    if choices:
        print(f"\n  \033[1m{label}\033[0m")
        for i, (value, desc) in enumerate(choices, 1):
            marker = "\033[36m>\033[0m" if value == default else " "
            print(f"  {marker} {i}) {desc}")
        while True:
            raw = input(f"\n  Choice [1-{len(choices)}] (default: {default}): ").strip()
            if not raw:
                return default
            try:
                idx = int(raw) - 1
                if 0 <= idx < len(choices):
                    return choices[idx][0]
            except ValueError:
                # Allow typing the value directly
                for value, _ in choices:
                    if raw.lower() == value.lower():
                        return value
            print(f"  \033[31mInvalid choice.\033[0m Enter 1-{len(choices)}.")
    else:
        raw = input(f"  {label} [{default}]: ").strip()
        return raw if raw else default


def _confirm(label, default=True):
    """Yes/no prompt."""
    suffix = "[Y/n]" if default else "[y/N]"
    raw = input(f"  {label} {suffix}: ").strip().lower()
    if not raw:
        return default
    return raw in ("y", "yes")


def _do_init(vault_root, cfg, profession_name=None, run_index=False):
    """Core init logic — creates vault, config, applies profession."""
    import shutil

    from .config import CONFIG_PATH
    from .professions import apply_profession, get_profession

    vault_root = Path(vault_root)

    # Create vault directory structure
    dirs = ["research", "literature", "calendar", "inbox", "templates", "archive", "meta"]
    context_dirs = ["home/projects", "home/resources", "work"]
    created = []
    for d in dirs + context_dirs:
        p = vault_root / d
        if not p.exists():
            p.mkdir(parents=True)
            created.append(d)

    # Copy base templates from vault-template/
    base_template = Path(__file__).resolve().parent.parent.parent / "vault-template"
    if base_template.exists():
        src_agents = base_template / "AGENTS.md"
        dst_agents = vault_root / "AGENTS.md"
        if src_agents.exists() and not dst_agents.exists():
            shutil.copy2(src_agents, dst_agents)
            created.append("AGENTS.md")

        src_templates = base_template / "templates"
        dst_templates = vault_root / "templates"
        if src_templates.exists():
            for tmpl in sorted(src_templates.glob("*.md")):
                dst = dst_templates / tmpl.name
                if not dst.exists():
                    shutil.copy2(tmpl, dst)

        src_research = base_template / "research"
        if src_research.exists():
            for note in sorted(src_research.glob("*.md")):
                dst = vault_root / "research" / note.name
                if not dst.exists():
                    shutil.copy2(note, dst)

    # Create index.md files
    for d in dirs + context_dirs:
        idx = vault_root / d / "index.md"
        if not idx.exists():
            label = d.split("/")[-1].replace("-", " ").title()
            idx.write_text(f"# {label}\n\n")

    # Write config
    config_text = (
        f'vault_root = "{vault_root}"\n'
        f'embed_url = "{cfg.embed_url}"\n'
        f'llm_url = "{cfg.llm_url}"\n'
        f'llm_model = "{cfg.llm_model}"\n'
    )
    if cfg.llm_api_key:
        config_text += f'llm_api_key = "{cfg.llm_api_key}"\n'
    if cfg.embed_api_key:
        config_text += f'embed_api_key = "{cfg.embed_api_key}"\n'
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(config_text)

    # Create DB directory
    cfg.db_dir.mkdir(parents=True, exist_ok=True)

    if created:
        print(f"\n  \033[32m✓\033[0m Created vault at {vault_root}")
        print(f"    Directories: {', '.join(created)}")
    else:
        print(f"\n  \033[32m✓\033[0m Vault already exists at {vault_root}")

    print(f"  \033[32m✓\033[0m Config: {CONFIG_PATH}")

    # Apply profession pack
    if profession_name and profession_name != "none":
        profession = get_profession(profession_name)
        if profession:
            print(f"  \033[32m✓\033[0m Applying '{profession.name}' profession pack...")
            actions = apply_profession(vault_root, profession)
            for action in actions:
                print(f"  {action}")

    print(f"  \033[32m✓\033[0m Database: {cfg.db_path}")

    # Run index if requested
    if run_index:
        print("\n  Indexing vault...")
        from .watcher import full_index

        full_index(
            vault_root=vault_root,
            embed_url=cfg.embed_url,
            summarize_url=cfg.llm_url,
            skip_summary=True,
            skip_triples=True,
        )
        print("  \033[32m✓\033[0m Indexing complete")


def cmd_init(args):
    """Initialize a new NeuroStack vault and config."""
    from .professions import list_professions

    cfg = get_config()

    # Non-interactive mode: use flags directly (backwards compatible)
    if args.path or args.profession or not sys.stdin.isatty():
        vault_root = Path(args.path) if args.path else cfg.vault_root
        _do_init(vault_root, cfg, profession_name=args.profession,
                 run_index=args.index)
        print("\nNext steps:")
        if not args.index:
            print("  neurostack index          # Index your vault")
        print("  neurostack search 'query' # Search")
        print("  neurostack doctor         # Check health")
        return

    # ── Interactive setup wizard ──
    print("\n  \033[1m━━━ NeuroStack Setup ━━━\033[0m\n")

    # Hardware check — skip if using cloud mode
    from .cloud.config import load_cloud_config
    _cloud_cfg = load_cloud_config()
    if _cloud_cfg.cloud_api_key:
        print("  \033[1mMode\033[0m")
        print("    \033[32m✓\033[0m Cloud — Gemini handles indexing")
        print()
    else:
        _print_hardware_recommendation()
        print()

    # 1. Vault path
    print("  Your vault is the directory where your Markdown notes live.")
    print("  NeuroStack will create subdirectories for organization.")
    print("  Point this to an existing notes folder, or a new path to start fresh.\n")
    vault_root = Path(_prompt(
        "\033[1mVault path\033[0m",
        default=str(cfg.vault_root),
    )).expanduser()

    # 2. Profession pack
    professions = list_professions()
    prof_choices = [("none", "None — start with base structure")]
    for p in professions:
        prof_choices.append((p.name, f"{p.name.title()} — {p.description}"))
    profession = _prompt("Profession pack", default="none", choices=prof_choices)

    # Detect install mode (full/community have numpy installed)
    is_full_mode = False
    try:
        import numpy  # noqa: F401
        is_full_mode = True
    except ImportError:
        pass

    # 3. LLM configuration (only for full/community mode)
    embed_url = cfg.embed_url
    llm_url = cfg.llm_url
    llm_model = cfg.llm_model
    llm_api_key = ""
    embed_api_key = ""

    if is_full_mode:
        print("\n  \033[1mLLM Configuration\033[0m")
        print("  NeuroStack works with any OpenAI-compatible endpoint")
        print("  (Ollama, vLLM, Together AI, Groq, OpenRouter, etc.)\n")

        embed_url = _prompt("Embedding endpoint", default=cfg.embed_url)
        llm_url = _prompt("LLM endpoint", default=cfg.llm_url)

        model_choices = [
            ("phi3.5", "phi3.5 — MIT licensed, fast, 3.8B params"),
            ("qwen3:8b", "qwen3:8b — Apache 2.0, strong reasoning"),
            ("llama3.1:8b", "llama3.1:8b — Meta community license, popular"),
            ("mistral:7b", "mistral:7b — Apache 2.0, efficient"),
        ]
        llm_model = _prompt("LLM model for summaries", default=cfg.llm_model, choices=model_choices)

        # API keys (optional — only needed for cloud providers)
        is_local = any(h in llm_url for h in ("localhost", "127.0.0.1", "0.0.0.0"))
        if not is_local:
            print("\n  \033[1mAPI Authentication\033[0m")
            print("  Cloud providers require an API key.\n")
            llm_api_key = _prompt("LLM API key", default="")
            if embed_url != llm_url:
                embed_api_key = _prompt("Embedding API key", default="")
            else:
                embed_api_key = llm_api_key
        elif _confirm("\n  Configure API keys? (only needed for cloud providers)", default=False):
            llm_api_key = _prompt("LLM API key", default="")
            embed_api_key = _prompt("Embedding API key", default=llm_api_key)

    # 4. Index after init?
    if is_full_mode:
        run_index = _confirm("Index vault after setup?", default=True)
    else:
        run_index = True  # Lite mode: always index (FTS5 only, fast)

    # Show summary
    print("\n  \033[1m━━━ Summary ━━━\033[0m\n")
    print(f"  Vault:      {vault_root}")
    print(f"  Profession: {profession}")
    print(f"  Mode:       {'full' if is_full_mode else 'lite'}")
    if is_full_mode:
        auth_label = "yes" if (llm_api_key or embed_api_key) else "no"
        print(f"  Embed URL:  {embed_url}")
        print(f"  LLM URL:    {llm_url}")
        print(f"  LLM model:  {llm_model}")
        print(f"  API auth:   {auth_label}")
    print(f"  Index now:  {'yes' if run_index else 'no'}")

    if not _confirm("\n  Proceed?", default=True):
        print("\n  Cancelled.")
        return

    # Apply settings to config
    cfg.vault_root = vault_root
    cfg.embed_url = embed_url
    cfg.llm_url = llm_url
    cfg.llm_model = llm_model
    cfg.llm_api_key = llm_api_key
    cfg.embed_api_key = embed_api_key

    _do_init(
        vault_root, cfg,
        profession_name=profession, run_index=run_index,
    )

    print("\n  \033[1mNext steps:\033[0m")
    if not run_index:
        print("    neurostack index          # Index your vault")
    print("    neurostack search 'query' # Search")
    print("    neurostack doctor         # Check health")
    print("    neurostack serve          # Start MCP server")
    print()


def cmd_scaffold(args):
    """Apply a profession pack to an existing vault."""
    from .professions import apply_profession, get_profession, list_professions

    if args.list:
        professions = list_professions()
        print("Available profession packs:\n")
        for p in professions:
            print(f"  {p.name:<20} {p.description}")
        return

    if not args.profession:
        print("Usage: neurostack scaffold <profession>")
        print("       neurostack scaffold --list")
        sys.exit(1)

    profession = get_profession(args.profession)
    if not profession:
        names = ", ".join(p.name for p in list_professions())
        print(f"Unknown profession: {args.profession}")
        print(f"Available: {names}")
        sys.exit(1)

    cfg = get_config()
    vault_root = Path(args.vault) if hasattr(args, "vault") and args.vault else cfg.vault_root

    if not vault_root.exists():
        print(f"Vault not found at {vault_root}")
        print("Run 'neurostack init' first, or use --vault to specify the path")
        sys.exit(1)

    print(f"Applying '{profession.name}' pack to {vault_root}...")
    actions = apply_profession(vault_root, profession)
    for action in actions:
        print(action)
    if actions:
        print(f"\n{len(actions)} items added")
    else:
        print("Pack already applied (no new items)")


def cmd_onboard(args):
    """Onboard an existing directory of notes into a NeuroStack vault."""
    import shutil
    from datetime import date

    from .chunker import parse_frontmatter
    from .config import CONFIG_PATH

    cfg = get_config()
    target = Path(args.path).resolve()

    if not target.exists():
        print(f"Directory not found: {target}")
        sys.exit(1)
    if not target.is_dir():
        print(f"Not a directory: {target}")
        sys.exit(1)

    dry_run = args.dry_run
    prefix = "[dry-run] " if dry_run else ""

    # Stats
    notes_found = 0
    frontmatter_added = 0
    indexes_created = 0
    dirs_created = 0

    # 1. Scan for all markdown files
    md_files = sorted(target.rglob("*.md"))
    notes_found = len(md_files)

    print(f"Scanning {target}...")
    print(f"  Found {notes_found} markdown files\n")

    # 2. Generate metadata for notes without frontmatter
    #    Stored in SQLite note_metadata — vault files are NEVER modified.
    #    Use --write-frontmatter to opt in to file modification.
    today = date.today().isoformat()
    write_fm = getattr(args, "write_frontmatter", False)
    # Files to skip — NeuroStack scaffolding, not user notes
    skip_names = {"index.md", "AGENTS.md", "CLAUDE.md"}
    skip_dirs = {"templates", ".obsidian", ".claude"}

    # Collect metadata for SQLite insertion after indexing
    pending_metadata: list[tuple] = []

    for md in md_files:
        if md.name in skip_names:
            continue
        rel = md.relative_to(target)
        if any(part in skip_dirs for part in rel.parts):
            continue
        content = md.read_text(encoding="utf-8", errors="replace")
        fm, _ = parse_frontmatter(content)
        if not fm:
            # Derive tags from parent dir name
            parent_tag = rel.parent.name if rel.parent.name else ""
            tags_list = [parent_tag] if parent_tag else []

            # Guess note type from location
            parent_lower = rel.parent.name.lower() if rel.parent.name else ""
            if parent_lower in ("literature", "sources", "references"):
                note_type = "literature"
            elif parent_lower in (
                "projects", "work", "home",
            ):
                note_type = "project"
            elif parent_lower in ("calendar", "daily", "journal"):
                note_type = "daily"
            else:
                note_type = "permanent"

            if write_fm and not dry_run:
                tags_str = f"[{parent_tag}]" if parent_tag else "[]"
                new_fm = (
                    f"---\ndate: {today}\ntags: {tags_str}\n"
                    f"type: {note_type}\nstatus: active\n---\n\n"
                )
                md.write_text(
                    new_fm + content, encoding="utf-8",
                )
                print(f"  {prefix}+ frontmatter → {rel}")
            else:
                pending_metadata.append((
                    str(rel), "active",
                    json.dumps(tags_list),
                    note_type, 0, 0, today,
                ))
                print(f"  {prefix}+ metadata → {rel}")
            frontmatter_added += 1

    # 3. Generate index.md for directories that have .md files
    dirs_with_notes: dict[Path, list[Path]] = {}
    for md in md_files:
        if md.name in skip_names:
            continue
        rel_check = md.relative_to(target)
        if any(part in skip_dirs for part in rel_check.parts):
            continue
        parent = md.parent
        if parent not in dirs_with_notes:
            dirs_with_notes[parent] = []
        dirs_with_notes[parent].append(md)

    for dir_path, notes in sorted(dirs_with_notes.items()):
        idx = dir_path / "index.md"
        if idx.exists():
            continue
        rel_dir = dir_path.relative_to(target)
        label = dir_path.name.replace("-", " ").replace("_", " ").title()
        lines = [f"# {label}\n"]
        for note in sorted(notes, key=lambda p: p.stem):
            # Try to extract title from first heading
            desc = _extract_first_heading(note)
            if desc:
                lines.append(f"- [[{note.stem}]] — {desc}")
            else:
                display = note.stem.replace("-", " ").replace(
                    "_", " ",
                ).title()
                lines.append(f"- [[{note.stem}]] — {display}")
        content = "\n".join(lines) + "\n"
        if not dry_run:
            idx.write_text(content, encoding="utf-8")
        print(f"  {prefix}+ index.md → {rel_dir}/ ({len(notes)} entries)")
        indexes_created += 1

    # 4. Add missing NeuroStack structural dirs
    structural = [
        "templates", "meta", "inbox", "archive", "calendar",
    ]
    for d in structural:
        p = target / d
        if not p.exists():
            if not dry_run:
                p.mkdir(parents=True)
                idx = p / "index.md"
                label = d.replace("-", " ").title()
                idx.write_text(f"# {label}\n\n")
            print(f"  {prefix}+ {d}/")
            dirs_created += 1

    # 5. Copy AGENTS.md and base templates if missing
    base_template = (
        Path(__file__).resolve().parent.parent.parent / "vault-template"
    )
    if base_template.exists():
        src_agents = base_template / "AGENTS.md"
        dst_agents = target / "AGENTS.md"
        if src_agents.exists() and not dst_agents.exists():
            if not dry_run:
                shutil.copy2(src_agents, dst_agents)
            print(f"  {prefix}+ AGENTS.md")

        src_templates = base_template / "templates"
        dst_templates = target / "templates"
        if src_templates.exists():
            dst_templates.mkdir(parents=True, exist_ok=True)
            for tmpl in sorted(src_templates.glob("*.md")):
                dst = dst_templates / tmpl.name
                if not dst.exists():
                    if not dry_run:
                        shutil.copy2(tmpl, dst)
                    print(f"  {prefix}+ templates/{tmpl.name}")

    # 6. Create config pointing to this vault
    if not dry_run and not CONFIG_PATH.exists():
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(
            f'vault_root = "{target}"\n'
            f'embed_url = "{cfg.embed_url}"\n'
            f'llm_url = "{cfg.llm_url}"\n'
            f'llm_model = "{cfg.llm_model}"\n'
        )
        print(f"  Config written to {CONFIG_PATH}")

    # Summary
    print(f"\n{'[DRY RUN] ' if dry_run else ''}Onboard complete:")
    print(f"  {notes_found} notes found")
    print(f"  {frontmatter_added} frontmatter blocks added")
    print(f"  {indexes_created} index files generated")
    print(f"  {dirs_created} structural dirs created")

    # 7. Apply profession pack if specified
    if args.profession and not dry_run:
        from .professions import apply_profession, get_profession, list_professions

        profession = get_profession(args.profession)
        if not profession:
            names = ", ".join(p.name for p in list_professions())
            print(f"\nUnknown profession: {args.profession}")
            print(f"Available: {names}")
        else:
            print(f"\nApplying '{profession.name}' profession pack...")
            actions = apply_profession(target, profession)
            for action in actions:
                print(action)
            if actions:
                print(f"  {len(actions)} items added")

    # 8. Index the vault unless skipped or dry run
    if not dry_run and not args.no_index:
        print("\nIndexing vault...")
        from .schema import DB_PATH, get_db
        from .watcher import full_index

        full_index(
            vault_root=target,
            embed_url=cfg.embed_url,
            summarize_url=cfg.llm_url,
            skip_summary=False,
            skip_triples=False,
        )
        db_path = Path(os.environ.get("NEUROSTACK_DB_PATH", DB_PATH))
        conn = get_db(db_path)

        # Insert pending metadata for notes without frontmatter
        if pending_metadata:
            conn.executemany(
                "INSERT OR IGNORE INTO note_metadata"
                " (note_path, status, tags, note_type,"
                "  actionable, compositional, date_added)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                pending_metadata,
            )
            conn.commit()

        notes = conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
        chunks = conn.execute(
            "SELECT COUNT(*) FROM chunks",
        ).fetchone()[0]
        edges = conn.execute(
            "SELECT COUNT(*) FROM graph_edges",
        ).fetchone()[0]
        print(
            f"Indexed {notes} notes, {chunks} chunks, {edges} graph edges.",
        )

        print("\nNext steps:")
        print("  neurostack search 'query' # Search")
        print("  neurostack doctor         # Check health")
    elif not dry_run:
        print("\nNext steps:")
        print("  neurostack index          # Index your vault")
        print("  neurostack search 'query' # Search")
        print("  neurostack doctor         # Check health")
    else:
        print(
            "\nRun without --dry-run to apply changes.",
        )


def _extract_first_heading(path: Path) -> str:
    """Extract the first markdown heading from a file, or empty string."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line.startswith("# ") and not line.startswith("# {"):
                    return line.lstrip("# ").strip()
    except OSError:
        pass
    return ""


def _install_ollama(subprocess):
    """Attempt to install Ollama via the official installer."""
    import platform as _plat

    system = _plat.system()
    if system == "Linux":
        print("  Installing Ollama (Linux)...")
        proc = subprocess.run(
            ["bash", "-c",
             "curl -fsSL https://ollama.com/install.sh | sh"],
            timeout=120,
        )
        if proc.returncode == 0:
            print("  \033[32m✓\033[0m Ollama installed")
        else:
            print("  \033[31m✗\033[0m Ollama install failed")
            print(
                "    Try manually:"
                " https://ollama.com/download"
            )
    elif system == "Darwin":
        print(
            "  \033[33m!\033[0m On macOS, download Ollama from:"
            " https://ollama.com/download"
        )
    else:
        print(
            "  \033[33m!\033[0m Install Ollama from:"
            " https://ollama.com/download"
        )


def _get_ollama_models(ollama_bin, subprocess):
    """Return set of locally available Ollama model names."""
    try:
        proc = subprocess.run(
            [ollama_bin, "list"],
            capture_output=True, text=True, timeout=10,
        )
        if proc.returncode != 0:
            return set()
        models = set()
        for line in proc.stdout.strip().splitlines()[1:]:
            name = line.split()[0] if line.split() else ""
            if name:
                models.add(name)
                # Also add without :latest tag
                if ":" in name:
                    models.add(name.split(":")[0])
        return models
    except Exception:
        return set()


def _pull_ollama_models(ollama_bin, embed_model, llm_model, subprocess):
    """Pull Ollama models, skipping any already available."""
    available = _get_ollama_models(ollama_bin, subprocess)

    for model_name in (embed_model, llm_model):
        base = model_name.split(":")[0] if ":" in model_name else model_name
        if model_name in available or base in available:
            print(f"  \033[32m✓\033[0m {model_name} already available")
            continue
        print(f"  Pulling {model_name}...")
        try:
            proc = subprocess.run(
                [ollama_bin, "pull", model_name],
                timeout=600,
            )
            if proc.returncode == 0:
                print(f"  \033[32m✓\033[0m {model_name} ready")
            else:
                print(
                    f"  \033[33m!\033[0m Failed to pull"
                    f" {model_name}"
                )
        except subprocess.TimeoutExpired:
            print(
                f"  \033[33m!\033[0m Timeout pulling {model_name}"
                f" — try: ollama pull {model_name}"
            )


def cmd_skills(args):
    """Manage agent skill files (.md slash commands)."""
    import shutil

    skills_dir = Path(__file__).resolve().parent / "skills"
    subcmd = getattr(args, "skills_command", None)

    if subcmd == "list":
        if not skills_dir.exists():
            print("No skills directory found.")
            return
        files = sorted(skills_dir.glob("*.md"))
        if not files:
            print("No skill files found.")
            return
        for f in files:
            print(f"  {f.stem}")
        print(f"\n{len(files)} skill(s) available.")
        return

    if subcmd == "install":
        if not skills_dir.exists():
            print("No skills directory found in package.")
            sys.exit(1)

        provider = getattr(args, "provider", "claude")
        provider_paths = {
            "claude": Path.home() / ".claude" / "commands",
            "codex": Path.home() / ".codex" / "commands",
            "gemini": Path.home() / ".gemini" / "commands",
        }
        target = provider_paths.get(provider)
        if not target:
            print(
                f"Unknown provider: {provider}. "
                f"Supported: {', '.join(provider_paths)}"
            )
            sys.exit(1)

        target.mkdir(parents=True, exist_ok=True)

        files = sorted(skills_dir.glob("*.md"))
        if not files:
            print("No skill files found.")
            return

        for f in files:
            dest = target / f.name
            shutil.copy2(f, dest)
            print(f"  Installed {f.name} -> {dest}")
        print(
            f"\n{len(files)} skill(s) installed"
            f" to {target} ({provider})"
        )
        return

    # No subcommand - show help
    print("Usage: neurostack skills {install,list}")
    print("  install [provider]  Install skills"
          " (claude, codex, gemini)")
    print("  list                List available skills")


def cmd_update(args):
    """Pull latest source from GitHub and re-sync dependencies."""
    import shutil
    import subprocess
    import tarfile
    import tempfile
    import urllib.request

    TARBALL_URL = "https://github.com/raphasouthall/neurostack/archive/refs/heads/main.tar.gz"

    project_root = Path(__file__).resolve().parent.parent.parent
    if not (project_root / "pyproject.toml").exists():
        fallback = Path.home() / ".local" / "share" / "neurostack" / "repo"
        if (fallback / "pyproject.toml").exists():
            project_root = fallback
        else:
            print("  \033[31m✗\033[0m Cannot find project root")
            sys.exit(1)

    print(f"  Updating from {project_root}...\n")
    print(f"  Current version: {__version__}")

    is_git_repo = (project_root / ".git").exists()
    git = shutil.which("git")

    if is_git_repo and git:
        # Check for stale pre-rewrite history (sensitive refs removed 2026-03-20).
        # If old root commit exists, re-clone to drop stale objects.
        old_root_check = subprocess.run(
            ["git", "cat-file", "-t", "e146d12"],
            cwd=project_root, capture_output=True, text=True,
        )
        if old_root_check.returncode == 0:
            print("  \033[33m!\033[0m Outdated history detected — re-cloning for clean history...")
            repo_url = "https://github.com/raphasouthall/neurostack.git"
            parent = project_root.parent
            import tempfile
            tmp = Path(tempfile.mkdtemp(dir=parent))
            subprocess.run(["git", "clone", repo_url, str(tmp / "repo")],
                           capture_output=True, text=True, timeout=120)
            # Swap directories
            old_dir = project_root.with_name(project_root.name + ".old")
            project_root.rename(old_dir)
            (tmp / "repo").rename(project_root)
            shutil.rmtree(old_dir, ignore_errors=True)
            shutil.rmtree(tmp, ignore_errors=True)
            print("  \033[32m✓\033[0m Re-cloned with clean history")
        else:
            # Normal git pull
            result = subprocess.run(
                ["git", "pull", "--ff-only"],
                cwd=project_root, capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                print(f"  \033[31m✗\033[0m git pull failed:\n{result.stderr}")
                sys.exit(1)
            pulled = result.stdout.strip()
            if "Already up to date" in pulled:
                print("  \033[32m✓\033[0m Already up to date")
            else:
                print(f"  \033[32m✓\033[0m Pulled: {pulled.splitlines()[-1]}")
    else:
        # Tarball-based install — re-download from GitHub
        print("  Downloading latest source...")
        try:
            with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
                tmp_path = tmp.name
                urllib.request.urlretrieve(TARBALL_URL, tmp_path)

            # Extract over existing install (strip top-level dir)
            with tarfile.open(tmp_path, "r:gz") as tar:
                members = tar.getmembers()
                # Strip the first path component (neurostack-main/)
                for member in members:
                    parts = Path(member.name).parts
                    if len(parts) > 1:
                        member.name = str(Path(*parts[1:]))
                        tar.extract(member, project_root)

            Path(tmp_path).unlink(missing_ok=True)
            print("  \033[32m✓\033[0m Source updated")
        except Exception as e:
            print(f"  \033[31m✗\033[0m Download failed: {e}")
            sys.exit(1)

    # Detect current mode
    mode = "lite"
    try:
        import numpy  # noqa: F401
        mode = "full"
        try:
            import leidenalg  # noqa: F401
            mode = "community"
        except ImportError:
            pass
    except ImportError:
        pass

    # uv sync
    uv = shutil.which("uv")
    if not uv:
        uv_fallback = Path.home() / ".local" / "bin" / "uv"
        if uv_fallback.exists():
            uv = str(uv_fallback)
        else:
            print("  \033[31m✗\033[0m uv not found")
            sys.exit(1)

    sync_cmd = [uv, "sync", "--project", str(project_root)]
    if mode == "full":
        sync_cmd += ["--extra", "full"]
    elif mode == "community":
        sync_cmd += ["--extra", "full", "--extra", "community"]

    print(f"  Syncing dependencies ({mode} mode)...")
    result = subprocess.run(
        sync_cmd, capture_output=True, text=True, timeout=300,
    )
    if result.returncode != 0:
        print(f"  \033[31m✗\033[0m uv sync failed:\n{result.stderr}")
        sys.exit(1)
    print("  \033[32m✓\033[0m Dependencies synced")

    # Show new version
    try:
        new_ver = subprocess.run(
            [uv, "run", "--project", str(project_root),
             "python", "-c",
             "from neurostack import __version__; print(__version__)"],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()
        if new_ver and new_ver != __version__:
            print(f"  \033[32m✓\033[0m Updated: {__version__} -> {new_ver}")
        else:
            print(f"  Version: {new_ver or __version__}")
    except Exception:
        pass

    print("\n  Done.")


def cmd_install(args):
    """Streamlined installation: local or cloud, deps, and setup."""
    import platform
    import shutil
    import sqlite3
    import subprocess

    cfg = get_config()

    # ── Non-interactive mode ──
    if args.mode or not sys.stdin.isatty():
        mode = args.mode or "lite"
        pull_models = args.pull_models
        embed_model = args.embed_model or cfg.embed_model
        llm_model = args.llm_model or cfg.llm_model
        use_cloud = False
    else:
        # ── Interactive wizard ──
        print("\n  \033[1m━━━ NeuroStack Install ━━━\033[0m\n")

        # 1. Show system info
        py_ver = platform.python_version()
        print(f"  Python:   {py_ver}")
        try:
            conn = sqlite3.connect(":memory:")
            conn.execute(
                "CREATE VIRTUAL TABLE _t USING fts5(c)"
            )
            conn.close()
            print("  FTS5:     available")
        except Exception:
            print(
                "  \033[31mFTS5:     MISSING"
                " — SQLite compiled without FTS5\033[0m"
            )
            sys.exit(1)

        uv_path = shutil.which("uv")
        if uv_path:
            try:
                uv_ver = subprocess.run(
                    ["uv", "--version"],
                    capture_output=True, text=True, timeout=5,
                ).stdout.strip()
                print(f"  uv:       {uv_ver}")
            except Exception:
                print(f"  uv:       {uv_path}")
        else:
            print("  \033[31muv:       NOT FOUND\033[0m")
            print(
                "  Install:  curl -LsSf"
                " https://astral.sh/uv/install.sh | sh"
            )
            sys.exit(1)

        # 2. Local or Cloud?
        setup_choices = [
            ("cloud", "Cloud — Gemini indexes your vault, no GPU needed"),
            ("local", "Local — self-hosted with Ollama (requires GPU)"),
        ]
        setup = _prompt(
            "How do you want to run NeuroStack?",
            default="cloud", choices=setup_choices,
        )
        use_cloud = setup == "cloud"

        if use_cloud:
            # ── Cloud path: lite deps, then login + push ──
            mode = "lite"
            pull_models = False
            embed_model = cfg.embed_model
            llm_model = cfg.llm_model

            print("\n  \033[1m━━━ Plan ━━━\033[0m\n")
            print("  Mode:     lite (cloud handles indexing)")
            print("  Auth:     browser login via Google")
            print("  Index:    neurostack cloud push")
            if not _confirm("\n  Proceed?", default=True):
                print("\n  Cancelled.")
                return
        else:
            # ── Local path: existing flow ──
            # Detect current mode
            current_mode = "lite"
            try:
                import numpy  # noqa: F401
                current_mode = "full"
                try:
                    import leidenalg  # noqa: F401
                    current_mode = "community"
                except ImportError:
                    pass
            except ImportError:
                pass
            print(f"  Current:  {current_mode} mode\n")

            mode_choices = [
                ("lite",
                 "Lite — FTS5 search + graph, no ML (~130 MB)"),
                ("full",
                 "Full — + embeddings, summaries (~560 MB)"),
                ("community",
                 "Community — + GraphRAG Leiden (~575 MB)"),
            ]
            mode = _prompt(
                "Installation mode",
                default=current_mode, choices=mode_choices,
            )

            pull_models = False
            embed_model = cfg.embed_model
            llm_model = cfg.llm_model
            if mode in ("full", "community"):
                print("\n  \033[1mOllama Models\033[0m")
                print(
                    "  Full mode uses Ollama for embeddings"
                    " and summaries."
                )
                pull_models = _confirm(
                    "Pull Ollama models now?", default=True,
                )
                if pull_models:
                    embed_model = _prompt(
                        "Embedding model", default=cfg.embed_model,
                    )
                    model_choices = [
                        ("phi3.5",
                         "phi3.5 — MIT, fast, 3.8B"),
                        ("qwen3:8b",
                         "qwen3:8b — Apache 2.0, strong"),
                        ("llama3.1:8b",
                         "llama3.1:8b — Meta license"),
                        ("mistral:7b",
                         "mistral:7b — Apache 2.0"),
                    ]
                    llm_model = _prompt(
                        "LLM model",
                        default=cfg.llm_model,
                        choices=model_choices,
                    )

            print("\n  \033[1m━━━ Plan ━━━\033[0m\n")
            print(f"  Mode:     {mode}")
            if pull_models:
                print(f"  Embed:    ollama pull {embed_model}")
                print(f"  LLM:      ollama pull {llm_model}")
            else:
                print("  Models:   skip")
            if not _confirm("\n  Proceed?", default=True):
                print("\n  Cancelled.")
                return

    # ── Execute installation ──
    print()

    # Find project root (where pyproject.toml lives)
    project_root = Path(__file__).resolve().parent.parent.parent
    if not (project_root / "pyproject.toml").exists():
        # Fallback: check standard install location
        fallback = Path.home() / ".local" / "share" / "neurostack" / "repo"
        if (fallback / "pyproject.toml").exists():
            project_root = fallback
        else:
            print("  \033[31m✗\033[0m Cannot find project root (pyproject.toml)")
            sys.exit(1)

    # 1. uv sync — find uv on PATH or at ~/.local/bin/uv
    uv_bin = shutil.which("uv")
    if not uv_bin:
        fallback_uv = Path.home() / ".local" / "bin" / "uv"
        if fallback_uv.exists():
            uv_bin = str(fallback_uv)
    if not uv_bin:
        print("  \033[31m✗\033[0m uv not found.")
        print("  Install: curl -LsSf https://astral.sh/uv/install.sh | sh")
        sys.exit(1)

    sync_cmd = [uv_bin, "sync", "--project", str(project_root)]
    if mode == "full":
        sync_cmd += ["--extra", "full"]
    elif mode == "community":
        sync_cmd += ["--extra", "full", "--extra", "community"]

    print(f"  Syncing dependencies ({mode} mode)...")
    try:
        result = subprocess.run(
            sync_cmd, capture_output=True, text=True, timeout=300
        )
        if result.returncode != 0:
            print(f"  \033[31m✗\033[0m uv sync failed:\n{result.stderr}")
            sys.exit(1)
        print(f"  \033[32m✓\033[0m Dependencies synced ({mode})")
    except FileNotFoundError:
        print(f"  \033[31m✗\033[0m Failed to run: {uv_bin}")
        sys.exit(1)

    # 2. Create/update wrapper script
    wrapper = Path.home() / ".local" / "bin" / "neurostack"
    wrapper.parent.mkdir(parents=True, exist_ok=True)
    wrapper_content = (
        "#!/usr/bin/env bash\n"
        f'exec uv run --project "{project_root}" python -m neurostack.cli "$@"\n'
    )
    wrapper.write_text(wrapper_content)
    wrapper.chmod(0o755)
    # Create ns alias
    alias = wrapper.parent / "ns"
    alias.write_text(wrapper_content)
    alias.chmod(0o755)
    print(f"  \033[32m✓\033[0m CLI wrapper: {wrapper} (alias: ns)")

    # 3. Ollama setup (full/community modes)
    if pull_models or (mode in ("full", "community") and not pull_models
                       and not args.mode):
        # Check if Ollama is installed
        ollama = shutil.which("ollama")
        if not ollama:
            if mode in ("full", "community"):
                print("  \033[33m!\033[0m Ollama not found")
                if sys.stdin.isatty() and _confirm(
                    "Install Ollama now?", default=True
                ):
                    _install_ollama(subprocess)
                    ollama = shutil.which("ollama")
                    if not ollama:
                        print(
                            "  \033[33m!\033[0m Ollama install"
                            " may need a shell restart"
                        )
                        print(
                            "    Then run:"
                            " neurostack install --pull-models"
                        )
                else:
                    print(
                        "    Install later:"
                        " https://ollama.com/download"
                    )

        if ollama and pull_models:
            _pull_ollama_models(
                ollama, embed_model, llm_model, subprocess
            )

            # Update config with chosen models
            cfg.embed_model = embed_model
            cfg.llm_model = llm_model
            from .config import CONFIG_PATH
            CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            CONFIG_PATH.write_text(
                f'vault_root = "{cfg.vault_root}"\n'
                f'embed_url = "{cfg.embed_url}"\n'
                f'embed_model = "{embed_model}"\n'
                f'llm_url = "{cfg.llm_url}"\n'
                f'llm_model = "{llm_model}"\n'
            )
            print(f"  \033[32m✓\033[0m Config updated: {CONFIG_PATH}")

    # 4. PATH check
    local_bin = str(Path.home() / ".local" / "bin")
    if local_bin not in os.environ.get("PATH", ""):
        print("\n  \033[33m!\033[0m Add to PATH:"
              " export PATH=\"$HOME/.local/bin:$PATH\"")

    # 5. Cloud setup (if cloud path was chosen)
    if use_cloud:
        print("\n  \033[32m✓\033[0m Dependencies installed (lite)")
        print("\n  \033[1m━━━ Cloud Setup ━━━\033[0m\n")
        print("  Logging in to NeuroStack Cloud...")
        _cmd_cloud_device_login()

        # Check if login succeeded
        from .cloud.config import load_cloud_config
        cloud_cfg = load_cloud_config()
        if cloud_cfg.cloud_api_key:
            print("\n  \033[32m✓\033[0m Logged in")
            print("\n  \033[32mReady!\033[0m")
            print()
            print("  Next steps:")
            print("    neurostack init"
                  "          # Set up vault")
            print("    neurostack cloud push"
                  "    # Index vault in cloud")
            print("    neurostack cloud pull"
                  "    # Download indexed DB")
            print()
        else:
            print("\n  \033[33m!\033[0m Login skipped")
            print("\n  \033[32mInstalled!\033[0m (lite)")
            print()
            print("  Next steps:")
            print("    neurostack init"
                  "          # Set up vault")
            print("    neurostack cloud login"
                  "   # Sign in later")
            print()
        return

    # Summary (local path)
    print(f"\n  \033[32mInstalled!\033[0m ({mode} mode)")
    print()
    print("  Next steps:")
    print("    neurostack init          # Set up vault")
    print("    neurostack doctor        # Verify setup")
    print()


def cmd_uninstall(args):
    """Remove NeuroStack data, database, and CLI wrapper."""
    import shutil

    cfg = get_config()
    install_dir = Path.home() / ".local" / "share" / "neurostack"
    config_dir = Path.home() / ".config" / "neurostack"
    wrapper = Path.home() / ".local" / "bin" / "neurostack"

    if not args.yes and sys.stdin.isatty():
        print("\n  \033[1m━━━ NeuroStack Uninstall ━━━\033[0m\n")
        print("  This will remove:")
        print(f"    Source + venv:  {install_dir / 'repo'}")
        if not args.keep_db:
            print(f"    Database:       {cfg.db_path}")
        if wrapper.exists():
            print(f"    CLI wrapper:    {wrapper}")
        print()
        if not args.keep_db:
            print("  \033[33m!\033[0m Your vault will NOT be touched.")
        if not _confirm("  Proceed with uninstall?", default=False):
            print("\n  Cancelled.")
            return

    print("\n  \033[1mUninstalling NeuroStack\033[0m\n")

    # Remove source repo + venv
    repo_dir = install_dir / "repo"
    if repo_dir.exists():
        shutil.rmtree(repo_dir)
        print(f"  \033[36m▸\033[0m Removed source and venv: {repo_dir}")
    else:
        print("  \033[36m▸\033[0m Source directory not found (already clean)")

    # Remove database
    if not args.keep_db:
        for suffix in ("", "-wal", "-shm"):
            db_file = Path(str(cfg.db_path) + suffix)
            if db_file.exists():
                db_file.unlink()
        session_db = cfg.session_db
        for suffix in ("", "-wal", "-shm"):
            sf = Path(str(session_db) + suffix)
            if sf.exists():
                sf.unlink()
        if cfg.db_path.exists() or session_db.exists():
            print(f"  \033[36m▸\033[0m Removed database: {cfg.db_path}")

    # Remove parent dir if empty
    if install_dir.exists():
        try:
            install_dir.rmdir()
            print(f"  \033[36m▸\033[0m Removed empty directory: {install_dir}")
        except OSError:
            print(f"  \033[33m▸\033[0m Directory not empty, kept: {install_dir}")

    # Remove CLI wrapper and alias
    if wrapper.exists():
        wrapper.unlink()
        print(f"  \033[36m▸\033[0m Removed CLI wrapper: {wrapper}")
    alias = wrapper.parent / "ns"
    if alias.exists():
        alias.unlink()
        print(f"  \033[36m▸\033[0m Removed alias: {alias}")

    # Config
    if config_dir.exists():
        print(f"  \033[33m▸\033[0m Config preserved: {config_dir}")
        print(f"  \033[33m▸\033[0m To remove manually: rm -rf {config_dir}")

    # Hint about npm package
    print()
    print("  \033[32m✓ NeuroStack uninstalled.\033[0m")
    print()
    print("  To also remove the npm bootstrap package:")
    print("    npm uninstall -g neurostack")
    print()


def cmd_doctor(args):
    """Validate all NeuroStack subsystems."""

    cfg = get_config()
    checks = []

    # Check vault exists
    if cfg.vault_root.exists():
        note_count = len(list(cfg.vault_root.rglob("*.md")))
        checks.append(("Vault", "OK", f"{cfg.vault_root} ({note_count} .md files)"))
    else:
        checks.append(("Vault", "WARN", f"{cfg.vault_root} not found. Run: neurostack init"))

    # Check database
    if cfg.db_path.exists():
        import sqlite3
        try:
            conn = sqlite3.connect(str(cfg.db_path))
            notes = conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
            conn.close()
            checks.append(("Database", "OK", f"{cfg.db_path} ({notes} indexed notes)"))
        except Exception as e:
            checks.append(("Database", "ERROR", str(e)))
    else:
        checks.append(("Database", "WARN", "Run: neurostack index"))

    # Check Python version
    import platform
    py_ver = platform.python_version()
    checks.append(("Python", "OK", py_ver))

    # Check FTS5
    import sqlite3
    try:
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE VIRTUAL TABLE test_fts USING fts5(content)")
        conn.close()
        checks.append(("FTS5", "OK", "Available"))
    except Exception:
        checks.append(("FTS5", "ERROR", "SQLite compiled without FTS5 support"))

    # Check Ollama embedding endpoint
    try:
        import httpx
        r = httpx.get(f"{cfg.embed_url}/api/tags", timeout=3)
        if r.status_code == 200:
            models = [m["name"] for m in r.json().get("models", [])]
            has_embed = any(cfg.embed_model in m for m in models)
            status = "OK" if has_embed else "WARN"
            if models:
                detail = (
                    f"{cfg.embed_url}"
                    f" ({', '.join(models[:3])})"
                )
            else:
                detail = f"{cfg.embed_url} (no models)"
            if not has_embed:
                detail += (
                    f"\n         {cfg.embed_model}"
                    " not found. Pull:"
                    f" ollama pull {cfg.embed_model}"
                )
            checks.append(("Embeddings", status, detail))
        else:
            checks.append((
                "Embeddings", "WARN",
                f"{cfg.embed_url} returned"
                f" {r.status_code} (lite mode still works)",
            ))
    except Exception:
        checks.append((
            "Embeddings", "WARN",
            f"{cfg.embed_url} unreachable"
            " (lite mode still works)",
        ))

    # Check Ollama LLM endpoint
    try:
        import httpx
        r = httpx.get(f"{cfg.llm_url}/api/tags", timeout=3)
        if r.status_code == 200:
            models = [m["name"] for m in r.json().get("models", [])]
            has_llm = any(cfg.llm_model in m for m in models)
            status = "OK" if has_llm else "WARN"
            detail = (
                f"{cfg.llm_url}"
                f" ({', '.join(models[:3])})"
            )
            if not has_llm:
                detail += (
                    f"\n         {cfg.llm_model}"
                    " not found. Pull:"
                    f" ollama pull {cfg.llm_model}"
                )
            checks.append(("LLM", status, detail))
        else:
            checks.append((
                "LLM", "WARN",
                f"{cfg.llm_url} returned {r.status_code}",
            ))
    except Exception:
        checks.append((
            "LLM", "WARN",
            f"{cfg.llm_url} unreachable"
            " (search still works, summaries disabled)",
        ))

    # Check optional deps
    try:
        import numpy
        checks.append(("numpy", "OK", numpy.__version__))
    except ImportError:
        checks.append((
            "numpy", "SKIP",
            "Not installed (install with:"
            " pip install neurostack[full])",
        ))

    try:
        import sentence_transformers
        checks.append((
            "sentence-transformers", "OK",
            sentence_transformers.__version__,
        ))
    except ImportError:
        checks.append((
            "sentence-transformers", "SKIP",
            "Not installed (install with:"
            " pip install neurostack[full])",
        ))

    try:
        import leidenalg
        checks.append(("leidenalg", "OK", leidenalg.__version__))
    except ImportError:
        checks.append((
            "leidenalg", "SKIP",
            "Not installed (install with:"
            " pip install neurostack[community])",
        ))

    # Print results
    if args.json:
        output = {
            "checks": [
                {"name": name, "status": status, "detail": detail}
                for name, status, detail in checks
            ],
            "errors": sum(1 for _, s, _ in checks if s == "ERROR"),
            "warnings": sum(1 for _, s, _ in checks if s == "WARN"),
        }
        print(json.dumps(output, indent=2, default=str))
        if output["errors"]:
            sys.exit(1)
        if args.strict and output["warnings"]:
            sys.exit(1)
        return

    print("\nNeuroStack Doctor\n" + "=" * 40)
    for name, status, detail in checks:
        icon = {"OK": "+", "WARN": "!", "ERROR": "X", "SKIP": "-", "MISSING": "X"}[status]
        print(f"  [{icon}] {name}: {detail}")

    errors = sum(1 for _, s, _ in checks if s == "ERROR")
    warns = sum(1 for _, s, _ in checks if s == "WARN")
    if errors:
        print(f"\n{errors} error(s) found. Fix them before proceeding.")
        sys.exit(1)
    elif warns:
        print(f"\n{warns} warning(s). Lite mode works. Install optional deps for full features.")
        if args.strict:
            sys.exit(1)
    else:
        print("\nAll systems operational.")


def cmd_demo(args):
    """Run an interactive demo with the sample vault."""
    import shutil
    import tempfile

    from .chunker import parse_note
    from .graph import build_graph, compute_pagerank, get_neighborhood
    from .schema import SCHEMA_SQL, SCHEMA_VERSION
    from .search import fts_search

    # Copy sample vault to a temp directory
    sample_src = Path(__file__).parent.parent.parent / "vault-template"
    if not sample_src.exists():
        print("Error: vault-template not found. "
              "Demo requires the full repo checkout.")
        sys.exit(1)

    tmpdir = Path(tempfile.mkdtemp(prefix="neurostack-demo-"))
    vault = tmpdir / "demo-vault"
    shutil.copytree(sample_src, vault)
    db_path = tmpdir / "demo.db"

    print("=" * 60)
    print("  NeuroStack Demo")
    print("=" * 60)
    print()
    print(f"  Sample vault: {vault}")
    print(f"  Database: {db_path}")
    print()

    try:
        # Create DB directly (bypass module-level singletons)
        import hashlib
        import sqlite3
        from datetime import datetime, timezone

        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        conn.executescript(SCHEMA_SQL)
        conn.execute(
            "INSERT INTO schema_version VALUES (?)",
            (SCHEMA_VERSION,),
        )
        conn.commit()

        # Step 1: Index
        print("--- Step 1: Indexing sample vault (FTS5 lite mode) ---")
        print()

        md_files = sorted(vault.rglob("*.md"))
        md_files = [
            f for f in md_files
            if ".git" not in f.parts
            and f.name not in ("AGENTS.md", "CLAUDE.md")
        ]

        now = datetime.now(timezone.utc).isoformat()
        for path in md_files:
            parsed = parse_note(path, vault)
            fm_json = json.dumps(parsed.frontmatter, default=str)
            conn.execute(
                "INSERT OR REPLACE INTO notes "
                "(path, title, frontmatter, content_hash, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (parsed.path, parsed.title, fm_json,
                 parsed.content_hash, now),
            )
            for chunk in parsed.chunks:
                conn.execute(
                    "INSERT INTO chunks (note_path, heading_path, "
                    "content, content_hash, position) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (parsed.path, chunk.heading_path, chunk.content,
                     hashlib.sha256(
                         chunk.content.encode()
                     ).hexdigest()[:16],
                     chunk.position),
                )
        conn.commit()

        notes = conn.execute(
            "SELECT COUNT(*) as c FROM notes"
        ).fetchone()["c"]
        chunks = conn.execute(
            "SELECT COUNT(*) as c FROM chunks"
        ).fetchone()["c"]
        print(f"  Indexed {notes} notes, {chunks} chunks")

        # Step 2: Search
        print()
        print("--- Step 2: FTS5 search for 'prediction errors' ---")
        print()
        results = fts_search(conn, "prediction errors", limit=3)
        for r in results:
            snippet = r["content"][:120].replace("\n", " ")
            print(f"  {r['note_path']}")
            print(f"    {snippet}...")
            print()

        # Step 3: Graph
        print(
            "--- Step 3: Wiki-link graph for "
            "'memory-consolidation' ---"
        )
        print()
        build_graph(conn, vault)
        compute_pagerank(conn)
        result = get_neighborhood(
            "research/memory-consolidation.md", depth=1, conn=conn
        )
        if result:
            print(f"  Center: {result.center.title} "
                  f"(PageRank: {result.center.pagerank:.4f})")
            print(f"  Neighbors ({len(result.neighbors)}):")
            for n in result.neighbors:
                print(f"    - {n.title} "
                      f"(PageRank: {n.pagerank:.4f})")

        # Step 4: Stats
        print()
        print("--- Step 4: Index stats ---")
        print()
        edges = conn.execute(
            "SELECT COUNT(*) as c FROM graph_edges"
        ).fetchone()["c"]
        print(f"  Notes: {notes}")
        print(f"  Chunks: {chunks}")
        print(f"  Wiki-link edges: {edges}")

        conn.close()

        print()
        print("=" * 60)
        print("  Demo complete!")
        print()
        print("  To use with your own vault:")
        print("    neurostack init ~/my-vault")
        print("    neurostack index")
        print("    neurostack search 'your query'")
        print("=" * 60)

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def cmd_serve(args):
    """Start the NeuroStack MCP server."""
    from .server import mcp
    mcp.run(transport=args.transport)


def cmd_api(args):
    """Start the OpenAI-compatible HTTP API server."""
    try:
        from .api import run_server
    except ImportError:
        print(
            "API dependencies not installed. "
            "Install with: pip install neurostack[api]",
            file=sys.stderr,
        )
        sys.exit(1)
    print(f"Starting NeuroStack API on {args.host}:{args.port}")
    run_server(host=args.host, port=args.port)


def cmd_sessions(args):
    """Manage memory sessions and search session transcripts."""
    sessions_cmd = getattr(args, "sessions_command", None)

    if sessions_cmd == "search" or sessions_cmd is None:
        # Delegate to session-index (existing behavior)
        from .session_index import main as session_main
        extra = getattr(args, "session_args", []) or []
        if args.json and "--json" not in extra:
            extra = ["--json"] + extra
        sys.argv = ["neurostack-sessions"] + extra
        session_main()
        return

    if sessions_cmd == "start":
        from .memories import start_session
        from .schema import DB_PATH, get_db
        conn = get_db(DB_PATH)
        result = start_session(
            conn,
            source_agent=getattr(args, "source", None),
            workspace=_get_workspace(args),
        )
        if args.json:
            print(json.dumps(result, indent=2))
            return
        print(
            f"  Session {result['session_id']} started"
            f" at {result['started_at']}"
        )
        return

    if sessions_cmd == "end":
        from .memories import end_session, summarize_session
        from .schema import DB_PATH, get_db
        conn = get_db(DB_PATH)
        summary = None
        if getattr(args, "summarize", False):
            print("  Generating session summary...")
            summary = summarize_session(
                conn, args.id,
                llm_url=args.summarize_url,
            )
        result = end_session(conn, args.id, summary=summary)
        if "error" in result:
            print(f"  Error: {result['error']}")
            return

        # Auto-harvest unless --no-harvest
        if not getattr(args, "no_harvest", False):
            try:
                from .harvest import harvest_sessions
                harvest_report = harvest_sessions(n_sessions=1)
                result["harvest"] = {
                    "saved": len(harvest_report.get("saved", [])),
                    "skipped": len(harvest_report.get("skipped", [])),
                }
            except Exception as e:
                result["harvest"] = {"error": str(e)}

        if args.json:
            print(json.dumps(result, indent=2))
            return
        print(
            f"  Session {result['session_id']} ended"
            f" at {result['ended_at']}"
        )
        if result.get("summary"):
            print(f"  Summary: {result['summary']}")
        harvest_info = result.get("harvest", {})
        if "error" not in harvest_info:
            saved = harvest_info.get("saved", 0)
            skipped = harvest_info.get("skipped", 0)
            if saved or skipped:
                print(f"  Harvest: {saved} saved, {skipped} skipped")
        return

    if sessions_cmd == "list":
        from .memories import list_sessions
        from .schema import DB_PATH, get_db
        conn = get_db(DB_PATH)
        sessions = list_sessions(
            conn,
            limit=args.limit,
            workspace=_get_workspace(args),
        )
        if args.json:
            print(json.dumps(sessions, indent=2))
            return
        if not sessions:
            print("  No sessions found.")
            return
        for s in sessions:
            status = (
                "active" if not s["ended_at"] else "ended"
            )
            agent = s["source_agent"] or "unknown"
            print(
                f"  #{s['session_id']} [{status}] "
                f"{agent} - {s['started_at']} "
                f"({s['memory_count']} memories)"
            )
            if s.get("summary"):
                print(f"    {s['summary'][:120]}")
        return

    if sessions_cmd == "show":
        from .memories import get_session
        from .schema import DB_PATH, get_db
        conn = get_db(DB_PATH)
        session = get_session(conn, args.id)
        if not session:
            print(f"  Session {args.id} not found.")
            return
        if args.json:
            print(json.dumps(session, indent=2))
            return
        sid = session["session_id"]
        status = (
            "active" if not session["ended_at"]
            else "ended"
        )
        print(f"  Session #{sid} [{status}]")
        print(f"  Started: {session['started_at']}")
        if session["ended_at"]:
            print(f"  Ended: {session['ended_at']}")
        if session.get("source_agent"):
            print(
                f"  Agent: {session['source_agent']}"
            )
        if session.get("workspace"):
            print(
                f"  Workspace: {session['workspace']}"
            )
        if session.get("summary"):
            print(
                f"  Summary: {session['summary']}"
            )
        print(
            f"  Memories: {session['memory_count']}"
        )
        for m in session.get("memories", []):
            print(
                f"    [{m['entity_type']}] "
                f"{m['content'][:100]}"
            )
        return


def cmd_status(args):
    """Show NeuroStack status overview."""
    cfg = get_config()

    if args.json:
        output = {
            "version": __version__,
            "vault_root": str(cfg.vault_root),
            "db_path": str(cfg.db_path),
            "config_path": str(CONFIG_PATH),
            "initialized": cfg.db_path.exists(),
        }
        if cfg.db_path.exists():
            import sqlite3
            conn = sqlite3.connect(str(cfg.db_path))
            conn.row_factory = sqlite3.Row
            output["notes"] = conn.execute("SELECT COUNT(*) as c FROM notes").fetchone()["c"]
            output["chunks"] = conn.execute("SELECT COUNT(*) as c FROM chunks").fetchone()["c"]
            output["embedded"] = conn.execute(
                "SELECT COUNT(*) as c FROM chunks WHERE embedding IS NOT NULL"
            ).fetchone()["c"]
            conn.close()
            output["mode"] = "full" if output["embedded"] > 0 else "lite"
        print(json.dumps(output, indent=2, default=str))
        return

    print(f"NeuroStack v{__version__}")
    print(f"  Vault:    {cfg.vault_root}")
    print(f"  Database: {cfg.db_path}")
    print(f"  Config:   {CONFIG_PATH}")

    if cfg.db_path.exists():
        import sqlite3
        conn = sqlite3.connect(str(cfg.db_path))
        conn.row_factory = sqlite3.Row
        notes = conn.execute("SELECT COUNT(*) as c FROM notes").fetchone()["c"]
        chunks = conn.execute("SELECT COUNT(*) as c FROM chunks").fetchone()["c"]
        embedded = conn.execute(
            "SELECT COUNT(*) as c FROM chunks"
            " WHERE embedding IS NOT NULL"
        ).fetchone()["c"]
        conn.close()

        mode = "full" if embedded > 0 else "lite"
        print(f"  Mode:     {mode}")
        print(f"  Notes:    {notes}")
        print(f"  Chunks:   {chunks} ({embedded} embedded)")
    else:
        print("  Status:   Not initialized. Run: neurostack init")


def cmd_memories(args):
    """Manage agent-written memories."""
    from .memories import (
        forget_memory,
        get_memory_stats,
        merge_memories,
        prune_memories,
        save_memory,
        search_memories,
        update_memory,
    )
    from .schema import DB_PATH, get_db

    conn = get_db(DB_PATH)
    subcmd = getattr(args, "memories_command", None)

    if subcmd == "add":
        memory = save_memory(
            conn,
            content=args.content,
            tags=args.tags.split(",") if args.tags else None,
            entity_type=args.type,
            source_agent=args.source or "cli",
            workspace=_get_workspace(args) if hasattr(args, "workspace") else None,
            ttl_hours=args.ttl,
            embed_url=args.embed_url,
        )
        if args.json:
            result = {
                "saved": True,
                "memory_id": memory.memory_id,
                "entity_type": memory.entity_type,
                "created_at": memory.created_at,
                "expires_at": memory.expires_at,
            }
            if memory.near_duplicates:
                result["near_duplicates"] = memory.near_duplicates
            if memory.suggested_tags:
                result["suggested_tags"] = memory.suggested_tags
            print(json.dumps(result, indent=2))
        else:
            print(f"  \033[32m✓\033[0m Saved memory #{memory.memory_id} ({memory.entity_type})")
            if memory.expires_at:
                print(f"    Expires: {memory.expires_at}")
            if memory.suggested_tags:
                print(f"  Suggested tags: {', '.join(memory.suggested_tags)}")
                print(f"  Apply: neurostack memories update {memory.memory_id} "
                      f"--add-tags {','.join(memory.suggested_tags)}")
            if memory.near_duplicates:
                print("  \033[33m!\033[0m Near-duplicates found:")
                for dup in memory.near_duplicates:
                    print(f"    #{dup['memory_id']} (similarity: {dup['similarity']:.2f})")
                    print(f"      {dup['content'][:80]}")
                print("  Merge: neurostack memories merge <target> <source>")

    elif subcmd == "search":
        memories = search_memories(
            conn,
            query=args.query,
            entity_type=args.type,
            workspace=_get_workspace(args) if hasattr(args, "workspace") else None,
            limit=args.limit,
            embed_url=args.embed_url,
        )
        if args.json:
            print(json.dumps([
                {
                    "memory_id": m.memory_id,
                    "content": m.content,
                    "entity_type": m.entity_type,
                    "tags": m.tags,
                    "source_agent": m.source_agent,
                    "workspace": m.workspace,
                    "created_at": m.created_at,
                    "expires_at": m.expires_at,
                    "score": round(m.score, 4) if m.score else None,
                }
                for m in memories
            ], indent=2, default=str))
        else:
            if not memories:
                print("  No memories found.")
                return
            for m in memories:
                score_str = f" (score: {m.score:.4f})" if m.score else ""
                print(f"\n  \033[1m#{m.memory_id}\033[0m [{m.entity_type}]{score_str}")
                print(f"  {m.content}")
                if m.tags:
                    print(f"  Tags: {', '.join(m.tags)}")
                if m.source_agent:
                    print(f"  Source: {m.source_agent}")
                if m.workspace:
                    print(f"  Workspace: {m.workspace}")
                print(f"  Created: {m.created_at}")
                if m.expires_at:
                    print(f"  Expires: {m.expires_at}")

    elif subcmd == "list":
        memories = search_memories(
            conn,
            entity_type=args.type,
            workspace=_get_workspace(args) if hasattr(args, "workspace") else None,
            limit=args.limit,
        )
        if args.json:
            print(json.dumps([
                {
                    "memory_id": m.memory_id,
                    "content": m.content,
                    "entity_type": m.entity_type,
                    "tags": m.tags,
                    "source_agent": m.source_agent,
                    "workspace": m.workspace,
                    "created_at": m.created_at,
                    "expires_at": m.expires_at,
                }
                for m in memories
            ], indent=2, default=str))
        else:
            if not memories:
                print("  No memories stored.")
                return
            for m in memories:
                expire = f" [expires {m.expires_at}]" if m.expires_at else ""
                src = f" ({m.source_agent})" if m.source_agent else ""
                print(f"  #{m.memory_id:<4} [{m.entity_type}]{src}{expire}")
                print(f"        {m.content[:120]}")

    elif subcmd == "forget":
        deleted = forget_memory(conn, args.id)
        if args.json:
            print(json.dumps({"deleted": deleted, "memory_id": args.id}))
        else:
            if deleted:
                print(f"  \033[32m✓\033[0m Deleted memory #{args.id}")
            else:
                print(f"  \033[31m✗\033[0m Memory #{args.id} not found")

    elif subcmd == "prune":
        count = prune_memories(
            conn,
            older_than_days=args.older_than,
            expired_only=args.expired,
        )
        if args.json:
            print(json.dumps({"pruned": count}))
        else:
            print(f"  Pruned {count} memories.")

    elif subcmd == "stats":
        stats = get_memory_stats(conn)
        if args.json:
            print(json.dumps(stats, indent=2))
        else:
            print(f"  Total:    {stats['total']}")
            print(f"  Embedded: {stats['embedded']}")
            print(f"  Expired:  {stats['expired']}")
            if stats["by_type"]:
                print("  By type:")
                for t, c in sorted(stats["by_type"].items()):
                    print(f"    {t}: {c}")

    elif subcmd == "update":
        try:
            memory = update_memory(
                conn,
                memory_id=args.id,
                content=args.content,
                tags=args.tags.split(",") if args.tags else None,
                add_tags=args.add_tags.split(",") if args.add_tags else None,
                remove_tags=args.remove_tags.split(",") if args.remove_tags else None,
                entity_type=args.type,
                workspace=_get_workspace(args) if hasattr(args, "workspace") else None,
                ttl_hours=args.ttl,
                embed_url=args.embed_url,
            )
        except ValueError as exc:
            if args.json:
                print(json.dumps({"updated": False, "error": str(exc)}))
            else:
                print(f"  \033[31m!\033[0m {exc}")
            return

        if args.json:
            if memory:
                print(json.dumps({
                    "updated": True,
                    "memory_id": memory.memory_id,
                    "content": memory.content,
                    "entity_type": memory.entity_type,
                    "tags": memory.tags,
                    "created_at": memory.created_at,
                    "updated_at": memory.updated_at,
                    "expires_at": memory.expires_at,
                    "revision_count": memory.revision_count,
                }, indent=2))
            else:
                print(json.dumps({"updated": False, "error": "Memory not found"}))
        else:
            if memory:
                print(f"  \033[32m✓\033[0m Updated memory #{memory.memory_id}")
            else:
                print(f"  \033[31m✗\033[0m Memory #{args.id} not found")

    elif subcmd == "merge":
        memory = merge_memories(
            conn, target_id=args.target, source_id=args.source,
            embed_url=args.embed_url,
        )
        if args.json:
            if memory:
                print(json.dumps({
                    "merged": True,
                    "memory_id": memory.memory_id,
                    "content": memory.content,
                    "entity_type": memory.entity_type,
                    "tags": memory.tags,
                    "merge_count": memory.merge_count,
                    "merged_from": memory.merged_from,
                }, indent=2))
            else:
                print(json.dumps({"merged": False, "error": "One or both IDs not found"}))
        else:
            if memory:
                print(f"  \033[32m✓\033[0m Merged into memory #{memory.memory_id}")
                print(f"    Merge count: {memory.merge_count}")
            else:
                print("  \033[31m✗\033[0m One or both memory IDs not found")

    else:
        print("Usage: neurostack memories {add,search,list,forget,prune,stats,update,merge}")
        print("       neurostack memories --help")


def cmd_hooks(args):
    """Manage neurostack automation hooks."""
    subcmd = getattr(args, "hooks_command", None)

    if subcmd == "install":
        import subprocess

        hook_type = args.type or "harvest-timer"

        if hook_type == "harvest-timer":
            # Create a systemd user timer for periodic harvest
            timer_dir = Path.home() / ".config" / "systemd" / "user"
            timer_dir.mkdir(parents=True, exist_ok=True)

            service_content = (
                "[Unit]\n"
                "Description=NeuroStack harvest - extract session insights\n\n"
                "[Service]\n"
                "Type=oneshot\n"
                "ExecStart=%h/.local/bin/neurostack harvest --sessions 3\n"
                "Environment=PATH=%h/.local/bin:/usr/local/bin:/usr/bin\n"
            )
            timer_content = (
                "[Unit]\n"
                "Description=Run neurostack harvest every hour\n\n"
                "[Timer]\n"
                "OnCalendar=hourly\n"
                "Persistent=true\n\n"
                "[Install]\n"
                "WantedBy=timers.target\n"
            )

            (timer_dir / "neurostack-harvest.service").write_text(service_content)
            (timer_dir / "neurostack-harvest.timer").write_text(timer_content)

            subprocess.run(
                ["systemctl", "--user", "daemon-reload"],
                check=False, capture_output=True,
            )
            subprocess.run(
                ["systemctl", "--user", "enable", "--now", "neurostack-harvest.timer"],
                check=False, capture_output=True,
            )

            if args.json:
                print(json.dumps({"installed": True, "type": hook_type}))
            else:
                print(f"  \033[32m✓\033[0m Installed {hook_type}")
                print(f"    Timer: {timer_dir / 'neurostack-harvest.timer'}")
                print("    Check: systemctl --user status neurostack-harvest.timer")
        else:
            print(f"  Unknown hook type: {hook_type}")

    elif subcmd == "status":
        import subprocess

        result = subprocess.run(
            ["systemctl", "--user", "is-active", "neurostack-harvest.timer"],
            capture_output=True, text=True,
        )
        active = result.stdout.strip() == "active"
        if args.json:
            print(json.dumps({"harvest_timer": "active" if active else "inactive"}))
        else:
            status = "\033[32mactive\033[0m" if active else "\033[31minactive\033[0m"
            print(f"  harvest-timer: {status}")

    elif subcmd == "remove":
        import subprocess

        subprocess.run(
            ["systemctl", "--user", "disable", "--now", "neurostack-harvest.timer"],
            check=False, capture_output=True,
        )
        timer_dir = Path.home() / ".config" / "systemd" / "user"
        for f in ("neurostack-harvest.service", "neurostack-harvest.timer"):
            p = timer_dir / f
            if p.exists():
                p.unlink()
        subprocess.run(
            ["systemctl", "--user", "daemon-reload"],
            check=False, capture_output=True,
        )
        if args.json:
            print(json.dumps({"removed": True}))
        else:
            print("  \033[32m✓\033[0m Removed harvest timer")

    else:
        print("Usage: neurostack hooks {install,status,remove}")
        print("       neurostack hooks --help")


def cmd_context(args):
    """Assemble task-scoped context for session recovery."""
    from .context import build_vault_context
    from .schema import DB_PATH, get_db

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
    from .schema import DB_PATH, get_db
    from .search import get_dormancy_report

    conn = get_db(DB_PATH)

    if getattr(args, "demote", False):
        from .search import run_excitability_demotion
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
    from .cooccurrence import get_cooccurrence_stats, get_top_pairs
    from .schema import DB_PATH, get_db

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


def cmd_harvest(args):
    """Extract insights from recent AI coding sessions."""
    from .harvest import get_provider_names, harvest_sessions

    if getattr(args, "list_providers", False):
        for name in get_provider_names():
            print(f"  {name}")
        return

    result = harvest_sessions(
        n_sessions=args.sessions,
        dry_run=args.dry_run,
        embed_url=args.embed_url,
        provider=getattr(args, "provider", None),
    )

    if args.json:
        print(json.dumps(result, indent=2, default=str))
        return

    if "error" in result:
        print(f"  Error: {result['error']}")
        return

    mode = "DRY RUN" if result.get("dry_run") else "Harvest"
    providers = ", ".join(result.get("providers", []))
    print(f"\n  {mode} - scanned {result['sessions_scanned']} session(s)"
          + (f" [{providers}]" if providers else "") + "\n")

    if result["counts"]:
        print("  Counts by type:")
        for etype, count in sorted(result["counts"].items()):
            print(f"    {etype}: {count}")
        print()

    for item in result["saved"]:
        mid = item.get("memory_id", "-")
        print(f"  \033[32m+\033[0m [{item['entity_type']}] #{mid} {item['content'][:80]}")
        if item.get("tags"):
            print(f"    tags: {', '.join(item['tags'])}")

    for item in result["skipped"]:
        status = item.get("status", "skipped")
        snip = item["content"][:60]
        print(f"  \033[33m-\033[0m [{item['entity_type']}] {status}: {snip}")

    n_saved = len(result["saved"])
    n_skip = len(result["skipped"])
    total = n_saved + n_skip
    print(f"\n  Total: {n_saved} saved, {n_skip} skipped ({total} found)")


def _cmd_cloud_device_login() -> None:
    """Authenticate via OAuth device code flow (browser handoff).

    1. POST /api/v1/auth/device-code to get user_code + device_code
    2. Open browser to verification_uri (the /device page)
    3. Poll /api/v1/auth/device-token until confirmed, expired, or timed out
    4. Store resulting API key in config.toml
    """
    cfg = load_cloud_config()
    cloud_url = cfg.cloud_api_url or "https://neurostack-api-911077737485.us-central1.run.app"
    base = cloud_url.rstrip("/")

    # Step 1: Request device code
    try:
        resp = httpx.post(f"{base}/api/v1/auth/device-code", timeout=15.0)
        resp.raise_for_status()
    except httpx.ConnectError:
        print(f"  Error: Cannot reach cloud API at {base}.")
        sys.exit(1)
    except httpx.HTTPStatusError as e:
        print(f"  Error: Device code request failed ({e.response.status_code}).")
        sys.exit(1)

    data = resp.json()
    device_code = data["device_code"]
    user_code = data["user_code"]
    verification_uri = data.get("verification_uri", f"{base}/device")
    expires_in = data.get("expires_in", 600)
    interval = data.get("interval", 5)

    # Step 2: Show code and open browser
    print("\n  Opening browser... Sign in with Google,"
          " then enter this code:")
    print(f"  Code: \033[1m{user_code}\033[0m")
    print(f"  URL:  {verification_uri}\n")

    try:
        webbrowser.open(verification_uri)
    except Exception:
        pass  # Non-fatal if browser fails to open

    # Step 3: Poll for token
    deadline = time.monotonic() + expires_in
    dots = 0
    while time.monotonic() < deadline:
        time.sleep(interval)
        dots = (dots + 1) % 4
        spinner = "." * (dots + 1)
        print(f"\r  Waiting for browser authorization{spinner}    ", end="", flush=True)

        try:
            token_resp = httpx.post(
                f"{base}/api/v1/auth/device-token",
                json={"device_code": device_code},
                timeout=15.0,
            )
        except (httpx.ConnectError, httpx.TimeoutException):
            continue  # Retry on transient errors

        if token_resp.status_code == 428:
            # Authorization pending -- keep polling
            continue
        elif token_resp.status_code == 200:
            token_data = token_resp.json()
            api_key = token_data["api_key"]
            save_cloud_config(cloud_api_url=cloud_url, cloud_api_key=api_key)
            print("\r  Login successful! API key stored in config.          ")
            return
        elif token_resp.status_code == 400:
            print("\r  Code expired. Please try again.                      ")
            sys.exit(1)
        else:
            status = token_resp.status_code
            print(f"\r  Unexpected error ({status}). Please try again.")
            sys.exit(1)

    print("\r  Authorization timed out. Please try again.           ")
    sys.exit(1)


def cmd_cloud(args):
    """Manage cloud authentication and configuration."""
    subcmd = getattr(args, "cloud_command", None)

    if subcmd == "login":
        api_key = getattr(args, "key", None)
        if api_key:
            # Direct API key login (--key flag)
            cfg = load_cloud_config()
            cloud_url = cfg.cloud_api_url or "https://neurostack-api-911077737485.us-central1.run.app"
            test_cfg = CloudConfig(cloud_api_url=cloud_url, cloud_api_key=api_key)
            client = CloudClient(test_cfg)
            try:
                if client.validate_key():
                    save_cloud_config(cloud_api_url=cloud_url, cloud_api_key=api_key)
                    print(f"  Logged in to {cloud_url}")
                else:
                    print("  Error: Invalid API key.")
                    sys.exit(1)
            except ConnectionError as e:
                print(f"  Error: {e}")
                sys.exit(1)
        else:
            # Device code flow (browser-based login)
            _cmd_cloud_device_login()

    elif subcmd == "logout":
        clear_cloud_credentials()
        print("  Logged out. Cloud credentials cleared.")

    elif subcmd == "status":
        cfg = load_cloud_config()
        client = CloudClient(cfg)

        result = {
            "authenticated": client.is_configured,
            "cloud_url": cfg.cloud_api_url or "(not configured)",
        }

        if client.is_configured:
            try:
                status = client.status()
                result.update(status)
            except (ConnectionError, Exception):
                result["connection"] = "unreachable"

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            if result["authenticated"]:
                print("  Status: Authenticated")
                print(f"  Cloud:  {result['cloud_url']}")
                tier = result.get("tier", "unknown")
                print(f"  Tier:   {tier}")
                if result.get("connection") == "unreachable":
                    print("  Note:   Cloud API unreachable (credentials stored locally)")
            else:
                print("  Status: Not authenticated")
                url = result["cloud_url"]
                print(f"  Cloud:  {url}")
                print("  Run:    neurostack cloud login")

    elif subcmd == "setup":
        cfg = load_cloud_config()
        default_url = cfg.cloud_api_url or "https://neurostack-api-911077737485.us-central1.run.app"

        url = input(f"  Cloud API URL [{default_url}]: ").strip() or default_url
        api_key = input("  API key: ").strip()
        if not api_key:
            print("  Error: API key is required.")
            sys.exit(1)

        # Validate
        test_cfg = CloudConfig(cloud_api_url=url, cloud_api_key=api_key)
        client = CloudClient(test_cfg)
        try:
            if client.validate_key():
                save_cloud_config(cloud_api_url=url, cloud_api_key=api_key)
                print(f"  Cloud configured: {url}")
                print("  Authenticated successfully.")
            else:
                print("  Error: Invalid API key.")
                sys.exit(1)
        except ConnectionError as e:
            print(f"  Error: {e}")
            sys.exit(1)

    elif subcmd == "push":
        cmd_cloud_push(args)

    elif subcmd == "pull":
        cmd_cloud_pull(args)

    elif subcmd == "query":
        cmd_cloud_query(args)

    elif subcmd == "triples":
        cmd_cloud_triples(args)

    elif subcmd == "summary":
        cmd_cloud_summary(args)

    else:
        print("Usage: neurostack cloud {login|logout|status|setup|push|pull|query|triples|summary}")
        print("\nCommands:")
        print("  login    Authenticate via browser (device code) or --key")
        print("  logout   Clear stored credentials")
        print("  status   Show authentication state and usage")
        print("  setup    Interactive cloud configuration")
        print("  push     Upload vault files for cloud indexing")
        print("  pull     Download indexed database from cloud")
        print("  query    Search vault via cloud API")
        print("  triples  Search knowledge graph triples")
        print("  summary  Get a note summary")


def cmd_cloud_push(args):
    """Upload vault files to cloud for indexing."""
    from .cloud.config import load_cloud_config
    from .cloud.sync import SyncError, VaultSyncEngine

    cfg = get_config()
    cloud_cfg = load_cloud_config()

    if not cloud_cfg.cloud_api_url or not cloud_cfg.cloud_api_key:
        print("Error: Not authenticated. Run `neurostack cloud login` first.", file=sys.stderr)
        sys.exit(1)

    engine = VaultSyncEngine(
        cloud_api_url=cloud_cfg.cloud_api_url,
        cloud_api_key=cloud_cfg.cloud_api_key,
        vault_root=cfg.vault_root,
        db_dir=cfg.db_dir,
    )

    def on_progress(msg: str):
        print(f"  {msg}")

    try:
        result = engine.push(progress_callback=on_progress)
    except SyncError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if getattr(args, "json", False):
        print(json.dumps(result))
    else:
        print(f"Push complete: {result.get('message', 'done')}")


def cmd_cloud_pull(args):
    """Download indexed database from cloud."""
    from .cloud.config import load_cloud_config
    from .cloud.sync import SyncError, VaultSyncEngine

    cfg = get_config()
    cloud_cfg = load_cloud_config()

    if not cloud_cfg.cloud_api_url or not cloud_cfg.cloud_api_key:
        print("Error: Not authenticated. Run `neurostack cloud login` first.", file=sys.stderr)
        sys.exit(1)

    engine = VaultSyncEngine(
        cloud_api_url=cloud_cfg.cloud_api_url,
        cloud_api_key=cloud_cfg.cloud_api_key,
        vault_root=cfg.vault_root,
        db_dir=cfg.db_dir,
    )

    try:
        db_path = engine.pull()
    except SyncError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if getattr(args, "json", False):
        print(json.dumps({"db_path": str(db_path), "size": db_path.stat().st_size}))
    else:
        size_mb = db_path.stat().st_size / (1024 * 1024)
        print(f"Downloaded database to {db_path} ({size_mb:.1f} MB)")


def cmd_cloud_query(args):
    """Query vault via cloud API with tiered search."""
    from .cloud.client import CloudClient
    from .cloud.config import load_cloud_config

    cloud_cfg = load_cloud_config()
    if not cloud_cfg.cloud_api_url or not cloud_cfg.cloud_api_key:
        print("Error: Not authenticated. Run `neurostack cloud login` first.", file=sys.stderr)
        sys.exit(1)

    client = CloudClient(cloud_cfg)

    try:
        result = client.query(
            args.query,
            top_k=args.top_k,
            depth=args.depth,
            mode=args.mode,
            workspace=getattr(args, "workspace", None),
        )
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if getattr(args, "json", False):
        print(json.dumps(result))
        return

    depth = result.get("depth_used", "unknown")
    print(f"  Depth: {depth}\n")

    triples = result.get("triples", [])
    if triples:
        print(f"  Triples ({len(triples)}):")
        for t in triples:
            print(f"    {t['subject']} -> {t['predicate']} -> {t['object']}")
            print(f"      [{t.get('score', 0):.2f}] {t['note']}")
        print()

    summaries = result.get("summaries", [])
    if summaries:
        print(f"  Summaries ({len(summaries)}):")
        for s in summaries:
            title = s.get("title", s.get("note", "untitled"))
            summary = s.get("summary", "")[:200]
            print(f"    {title}")
            print(f"      {summary}")
        print()

    chunks = result.get("chunks", [])
    if chunks:
        print(f"  Results ({len(chunks)}):")
        for i, c in enumerate(chunks, 1):
            title = c.get("title", c.get("note", "untitled"))
            section = c.get("section", "")
            snippet = c.get("snippet", "")[:150]
            score = c.get("score", 0)
            print(f"    {i}. [{score:.2f}] {title}")
            if section:
                print(f"       Section: {section}")
            if snippet:
                print(f"       {snippet}")

    if not triples and not summaries and not chunks:
        print("  No results found.")


def cmd_cloud_triples(args):
    """Search knowledge graph triples via cloud API."""
    from .cloud.client import CloudClient
    from .cloud.config import load_cloud_config

    cloud_cfg = load_cloud_config()
    if not cloud_cfg.cloud_api_url or not cloud_cfg.cloud_api_key:
        print("Error: Not authenticated. Run `neurostack cloud login` first.", file=sys.stderr)
        sys.exit(1)

    client = CloudClient(cloud_cfg)

    try:
        results = client.triples(
            args.query,
            top_k=args.top_k,
            workspace=getattr(args, "workspace", None),
        )
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if getattr(args, "json", False):
        print(json.dumps(results))
        return

    if not results:
        print("No triples found.")
        return

    for t in results:
        print(f"  {t['subject']} -> {t['predicate']} -> {t['object']}")
        print(f"    [{t.get('score', 0):.2f}] {t.get('note', '')}")


def cmd_cloud_summary(args):
    """Get a note summary via cloud API."""
    from .cloud.client import CloudClient
    from .cloud.config import load_cloud_config

    cloud_cfg = load_cloud_config()
    if not cloud_cfg.cloud_api_url or not cloud_cfg.cloud_api_key:
        print("Error: Not authenticated. Run `neurostack cloud login` first.", file=sys.stderr)
        sys.exit(1)

    client = CloudClient(cloud_cfg)

    try:
        result = client.summary(args.note_path)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if result is None:
        print(f"No summary found for: {args.note_path}", file=sys.stderr)
        sys.exit(1)

    if getattr(args, "json", False):
        print(json.dumps(result))
        return

    print(f"  {result.get('title', args.note_path)}")
    print(f"  {result.get('summary', 'No summary')}")


def main():
    cfg = get_config()

    parser = argparse.ArgumentParser(description="neurostack: Local AI context engine")
    parser.add_argument("--vault", default=str(cfg.vault_root), help="Vault root path")
    parser.add_argument("--embed-url", default=cfg.embed_url, help="Ollama embed URL")
    parser.add_argument("--summarize-url", default=cfg.llm_url, help="Ollama summarize URL")
    parser.add_argument("--json", action="store_true", default=False, help="Output results as JSON")

    sub = parser.add_subparsers(dest="command")

    # init
    p = sub.add_parser("init", help="Initialize a new vault and config")
    p.add_argument("path", nargs="?", help="Vault path (default: from config)")
    p.add_argument(
        "--profession", "-p",
        help="Apply a profession pack (e.g., developer, writer, "
        "student, devops, data-scientist, researcher). "
        "Use 'scaffold --list' to see all",
    )
    p.add_argument(
        "--index", action="store_true", default=True,
        help="Index vault after init (default: true)",
    )
    p.add_argument(
        "--no-index", action="store_false", dest="index",
        help="Skip indexing after init",
    )
    p.set_defaults(func=cmd_init)

    # scaffold
    p = sub.add_parser("scaffold", help="Apply a profession pack to an existing vault")
    p.add_argument(
        "profession", nargs="?",
        help="Profession name (e.g., developer, writer, "
        "student, devops, data-scientist, researcher)",
    )
    p.add_argument("--list", "-l", action="store_true", help="List available profession packs")
    p.set_defaults(func=cmd_scaffold)

    # onboard
    p = sub.add_parser(
        "onboard",
        help="Onboard an existing directory of notes into a NeuroStack vault",
    )
    p.add_argument("path", help="Path to the directory to onboard")
    p.add_argument(
        "--dry-run", "-n", action="store_true",
        help="Show what would be done without making changes",
    )
    p.add_argument(
        "--profession", "-p",
        help="Also apply a profession pack after onboarding",
    )
    p.add_argument(
        "--no-index", action="store_true",
        help="Skip indexing after onboarding",
    )
    p.add_argument(
        "--write-frontmatter", action="store_true",
        help="Write frontmatter into vault files (default: metadata stored in SQLite only)",
    )
    p.set_defaults(func=cmd_onboard)

    # demo
    p = sub.add_parser("demo", help="Run interactive demo with sample vault")
    p.set_defaults(func=cmd_demo)

    # status
    p = sub.add_parser("status", help="Show NeuroStack status")
    p.set_defaults(func=cmd_status)

    # cloud
    p = sub.add_parser("cloud", help="Manage NeuroStack Cloud authentication")
    cloud_sub = p.add_subparsers(dest="cloud_command")

    cp = cloud_sub.add_parser("login", help="Authenticate with an API key")
    cp.add_argument("--key", "-k", help="API key (or prompted interactively)")

    cloud_sub.add_parser("logout", help="Clear stored cloud credentials")

    cp = cloud_sub.add_parser("status", help="Show cloud auth state and usage")
    cp.add_argument("--json", action="store_true", default=False, help="Output as JSON")

    cloud_sub.add_parser("setup", help="Interactive cloud endpoint and key configuration")

    cp = cloud_sub.add_parser("push", help="Upload vault files for cloud indexing")
    cp.add_argument("--json", action="store_true", default=False, help="Output as JSON")

    cp = cloud_sub.add_parser("pull", help="Download indexed database from cloud")
    cp.add_argument("--json", action="store_true", default=False, help="Output as JSON")

    cp = cloud_sub.add_parser("query", help="Search vault via cloud API")
    cp.add_argument("query", help="Search text")
    cp.add_argument("--top-k", type=int, default=10, help="Number of results")
    cp.add_argument(
        "--depth", default="auto",
        choices=["triples", "summaries", "full", "auto"],
        help="Result depth (default: auto)",
    )
    cp.add_argument(
        "--mode", default="hybrid",
        choices=["hybrid", "semantic", "keyword"],
        help="Search mode (default: hybrid)",
    )
    cp.add_argument("--workspace", "-w", help="Scope to vault subdirectory")
    cp.add_argument("--json", action="store_true", default=False, help="Output as JSON")

    cp = cloud_sub.add_parser("triples", help="Search knowledge graph triples via cloud")
    cp.add_argument("query", help="Search text")
    cp.add_argument("--top-k", type=int, default=10, help="Number of results")
    cp.add_argument("--workspace", "-w", help="Scope to vault subdirectory")
    cp.add_argument("--json", action="store_true", default=False, help="Output as JSON")

    cp = cloud_sub.add_parser("summary", help="Get note summary from cloud")
    cp.add_argument("note_path", help="Note path (e.g. research/my-note.md)")
    cp.add_argument("--json", action="store_true", default=False, help="Output as JSON")

    p.set_defaults(func=cmd_cloud)

    # memories
    p = sub.add_parser("memories", help="Manage agent-written memories")
    mem_sub = p.add_subparsers(dest="memories_command")

    mp = mem_sub.add_parser("add", help="Save a new memory")
    mp.add_argument("content", help="Memory content")
    mp.add_argument("--tags", "-t", help="Comma-separated tags")
    mp.add_argument(
        "--type", default="observation",
        choices=["observation", "decision", "convention", "learning", "context", "bug"],
        help="Memory type (default: observation)",
    )
    mp.add_argument("--source", help="Source agent name")
    mp.add_argument("--workspace", "-w", help="Workspace scope")
    mp.add_argument("--ttl", type=float, help="Time-to-live in hours")

    mp = mem_sub.add_parser("search", help="Search memories")
    mp.add_argument("query", help="Search query")
    mp.add_argument("--type", help="Filter by entity type")
    mp.add_argument("--workspace", "-w", help="Workspace scope")
    mp.add_argument("--limit", type=int, default=20)

    mp = mem_sub.add_parser("list", help="List recent memories")
    mp.add_argument("--type", help="Filter by entity type")
    mp.add_argument("--workspace", "-w", help="Workspace scope")
    mp.add_argument("--limit", type=int, default=20)

    mp = mem_sub.add_parser("forget", help="Delete a memory by ID")
    mp.add_argument("id", type=int, help="Memory ID")

    mp = mem_sub.add_parser("prune", help="Delete expired or old memories")
    mp.add_argument("--older-than", type=int, help="Delete memories older than N days")
    mp.add_argument("--expired", action="store_true", help="Delete only expired memories")

    mp = mem_sub.add_parser("stats", help="Show memory statistics")

    mp = mem_sub.add_parser("update", help="Update an existing memory")
    mp.add_argument("id", type=int, help="Memory ID to update")
    mp.add_argument("--content", "-c", help="New content")
    mp.add_argument("--tags", "-t", help="Replace tags (comma-separated)")
    mp.add_argument("--add-tags", help="Add tags (comma-separated)")
    mp.add_argument("--remove-tags", help="Remove tags (comma-separated)")
    mp.add_argument("--type", help="New entity type")
    mp.add_argument("--workspace", "-w", help="New workspace scope")
    mp.add_argument("--ttl", type=float, help="New TTL in hours (0 = permanent)")

    mp = mem_sub.add_parser("merge", help="Merge source memory into target")
    mp.add_argument("target", type=int, help="Target memory ID (kept)")
    mp.add_argument("source", type=int, help="Source memory ID (deleted after merge)")

    p.set_defaults(func=cmd_memories)

    # install
    p = sub.add_parser("install", help="Install or upgrade dependencies and Ollama models")
    p.add_argument(
        "--mode", "-m", choices=["lite", "full", "community"],
        help="Installation mode (lite=FTS5 only, full=+ML, community=+GraphRAG)",
    )
    p.add_argument(
        "--pull-models", action="store_true", default=False,
        help="Pull Ollama models after syncing deps",
    )
    p.add_argument("--embed-model", help="Embedding model (default: nomic-embed-text)")
    p.add_argument("--llm-model", help="LLM model (default: phi3.5)")
    p.set_defaults(func=cmd_install)

    # uninstall
    p = sub.add_parser("uninstall", help="Remove NeuroStack data, database, and CLI wrapper")
    p.add_argument(
        "--keep-config", action="store_true", default=False,
        help="Preserve ~/.config/neurostack/ (default: keep config)",
    )
    p.add_argument(
        "--keep-db", action="store_true", default=False,
        help="Preserve database files",
    )
    p.add_argument(
        "-y", "--yes", action="store_true", default=False,
        help="Skip confirmation prompt",
    )
    p.set_defaults(func=cmd_uninstall)

    # skills
    p = sub.add_parser(
        "skills",
        help="Manage agent skill files (.md slash commands)",
    )
    skills_sub = p.add_subparsers(dest="skills_command")
    install_p = skills_sub.add_parser(
        "install", help="Install skills for an AI provider",
    )
    install_p.add_argument(
        "provider", nargs="?", default="claude",
        choices=["claude", "codex", "gemini"],
        help="Target provider (default: claude)",
    )
    skills_sub.add_parser("list", help="List available skills")
    p.set_defaults(func=cmd_skills)

    # update
    p = sub.add_parser(
        "update",
        help="Pull latest source and re-sync dependencies",
    )
    p.set_defaults(func=cmd_update)

    # doctor
    p = sub.add_parser("doctor", help="Validate all subsystems")
    p.add_argument(
        "--strict", action="store_true",
        help="Exit 1 on missing vault/database",
    )
    p.set_defaults(func=cmd_doctor)

    # serve
    p = sub.add_parser("serve", help="Start MCP server")
    p.add_argument("--transport", choices=["stdio", "sse"], default="stdio")
    p.set_defaults(func=cmd_serve)

    # api
    p = sub.add_parser("api", help="Start OpenAI-compatible HTTP API server")
    p.add_argument("--host", default=cfg.api_host, help="Bind host (default: 127.0.0.1)")
    p.add_argument("--port", type=int, default=cfg.api_port, help="Bind port (default: 8000)")
    p.set_defaults(func=cmd_api)

    # sessions
    p = sub.add_parser(
        "sessions",
        help="Memory sessions and transcript search",
    )
    sess_sub = p.add_subparsers(dest="sessions_command")

    # sessions search (delegates to session-index)
    sp = sess_sub.add_parser(
        "search", help="Search session transcripts",
    )
    sp.add_argument(
        "session_args", nargs=argparse.REMAINDER,
        help="Arguments passed to session-index",
    )

    # sessions start
    sp = sess_sub.add_parser(
        "start", help="Start a new memory session",
    )
    sp.add_argument(
        "--source", help="Source agent name",
    )
    sp.add_argument(
        "--workspace", "-w", default=None,
        help="Workspace scope",
    )

    # sessions end
    sp = sess_sub.add_parser(
        "end", help="End a memory session",
    )
    sp.add_argument("id", type=int, help="Session ID")
    sp.add_argument(
        "--summarize", action="store_true",
        help="Generate LLM summary of session memories",
    )
    sp.add_argument(
        "--no-harvest", action="store_true",
        help="Skip auto-harvest of session insights",
    )

    # sessions list
    sp = sess_sub.add_parser(
        "list", help="List recent memory sessions",
    )
    sp.add_argument(
        "--limit", type=int, default=20,
    )
    sp.add_argument(
        "--workspace", "-w", default=None,
        help="Filter by workspace",
    )

    # sessions show
    sp = sess_sub.add_parser(
        "show",
        help="Show session details and memories",
    )
    sp.add_argument("id", type=int, help="Session ID")

    p.set_defaults(func=cmd_sessions)

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
    p.add_argument(
        "--context", "-c", default=None,
        help="Project/domain context for result boosting",
    )
    p.add_argument(
        "--rerank", action="store_true", default=False,
        help="Apply cross-encoder reranking",
    )
    p.add_argument(
        "--workspace", "-w", default=None,
        help="Restrict results to vault subdirectory "
        "(e.g. 'work/acme-cloud'). "
        "Also reads NEUROSTACK_WORKSPACE env var",
    )
    p.set_defaults(func=cmd_search)

    # ask
    p = sub.add_parser("ask", help="Ask a question using vault content (RAG)")
    p.add_argument("question", help="Natural language question")
    p.add_argument("--top-k", type=int, default=8, help="Number of chunks to retrieve for context")
    p.add_argument(
        "--workspace", "-w", default=None,
        help="Restrict results to vault subdirectory "
        "(e.g. 'work/acme-cloud'). "
        "Also reads NEUROSTACK_WORKSPACE env var",
    )
    p.set_defaults(func=cmd_ask)

    # summary
    p = sub.add_parser("summary", help="Get note summary")
    p.add_argument("path_or_query", help="Note path or search query")
    p.set_defaults(func=cmd_summary)

    # graph
    p = sub.add_parser("graph", help="Get note neighborhood")
    p.add_argument("note", help="Note path")
    p.add_argument("--depth", type=int, default=1)
    p.add_argument(
        "--workspace", "-w", default=None,
        help="Restrict neighbors to vault subdirectory "
        "(e.g. 'work/acme-cloud'). "
        "Also reads NEUROSTACK_WORKSPACE env var",
    )
    p.set_defaults(func=cmd_graph)

    # related
    p = sub.add_parser("related", help="Find semantically related notes")
    p.add_argument("note", help="Note path to find related notes for")
    p.add_argument("--top-k", type=int, default=10)
    p.add_argument(
        "--workspace", "-w", default=None,
        help="Restrict results to vault subdirectory "
        "(e.g. 'work/acme-cloud'). "
        "Also reads NEUROSTACK_WORKSPACE env var",
    )
    p.set_defaults(func=cmd_related)

    # triples
    p = sub.add_parser("triples", help="Search knowledge graph triples")
    p.add_argument("query", help="Search query")
    p.add_argument("--top-k", type=int, default=10)
    p.add_argument("--mode", choices=["hybrid", "semantic", "keyword"], default="hybrid")
    p.add_argument(
        "--workspace", "-w", default=None,
        help="Restrict results to vault subdirectory "
        "(e.g. 'work/acme-cloud'). "
        "Also reads NEUROSTACK_WORKSPACE env var",
    )
    p.set_defaults(func=cmd_triples)

    # tiered
    p = sub.add_parser("tiered", help="Tiered search (triples → summaries → full)")
    p.add_argument("query", help="Search query")
    p.add_argument("--top-k", type=int, default=5)
    p.add_argument("--depth", choices=["triples", "summaries", "full", "auto"], default="auto")
    p.add_argument("--mode", choices=["hybrid", "semantic", "keyword"], default="hybrid")
    p.add_argument(
        "--context", "-c", default=None,
        help="Project/domain context for result boosting",
    )
    p.add_argument(
        "--rerank", action="store_true", default=False,
        help="Apply cross-encoder reranking",
    )
    p.add_argument(
        "--workspace", "-w", default=None,
        help="Restrict results to vault subdirectory "
        "(e.g. 'work/acme-cloud'). "
        "Also reads NEUROSTACK_WORKSPACE env var",
    )
    p.set_defaults(func=cmd_tiered)

    # reembed-chunks
    p = sub.add_parser(
        "reembed-chunks",
        help="Re-embed all chunks with contextual text"
        " (title+tags+summary+chunk)",
    )
    p.set_defaults(func=cmd_reembed_chunks)

    # backfill
    p = sub.add_parser("backfill", help="Backfill missing summaries and/or triples")
    p.add_argument(
        "target", choices=["summaries", "triples", "cooccurrence", "all"],
        default="all", nargs="?",
    )
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
    p_q.add_argument(
        "--no-map-reduce", action="store_true",
        help="Return raw community hits without LLM synthesis",
    )
    p_q.add_argument(
        "--workspace", "-w", default=None,
        help="Restrict results to vault subdirectory "
        "(e.g. 'work/acme-cloud'). "
        "Also reads NEUROSTACK_WORKSPACE env var",
    )

    # communities list
    p_l = comm_sub.add_parser("list", help="List detected communities")
    p_l.add_argument("--level", type=int, default=None, help="Filter by level (0 or 1)")

    p.set_defaults(func=cmd_communities)

    # brief
    p = sub.add_parser("brief", help="Generate session brief")
    p.add_argument(
        "--workspace", "-w", default=None,
        help="Restrict brief to vault subdirectory "
        "(e.g. 'work/acme-cloud'). "
        "Also reads NEUROSTACK_WORKSPACE env var",
    )
    p.set_defaults(func=cmd_brief)

    # capture
    p = sub.add_parser("capture", help="Quick-capture a thought into the vault inbox")
    p.add_argument("content", help="The thought to capture")
    p.add_argument("--tags", "-t", help="Comma-separated tags")
    p.set_defaults(func=cmd_capture)

    # folder-summaries
    p = sub.add_parser(
        "folder-summaries",
        help="Build folder-level summaries for semantic"
        " context boosting",
    )
    p.add_argument("--force", action="store_true", help="Regenerate all even if up-to-date")
    p.set_defaults(func=cmd_folder_summaries)

    # prediction-errors
    p = sub.add_parser(
        "prediction-errors",
        help="Show notes flagged as prediction errors"
        " (poor retrieval fit)",
    )
    p.add_argument("--type", choices=["low_overlap", "contextual_mismatch"], default=None,
                   help="Filter by error type")
    p.add_argument("--limit", type=int, default=30, help="Max results to show")
    p.add_argument("--resolve", nargs="+", metavar="NOTE_PATH",
                   help="Mark note(s) as resolved")
    p.add_argument(
        "--workspace", "-w", default=None,
        help="Restrict results to vault subdirectory "
        "(e.g. 'work/acme-cloud'). "
        "Also reads NEUROSTACK_WORKSPACE env var",
    )
    p.set_defaults(func=cmd_prediction_errors)

    # stats
    p = sub.add_parser("stats", help="Show index stats")
    p.set_defaults(func=cmd_stats)

    # record-usage
    p = sub.add_parser(
        "record-usage", help="Record note usage for hotness scoring"
    )
    p.add_argument(
        "note_paths", nargs="+", help="Note paths to mark as used"
    )
    p.set_defaults(func=cmd_record_usage)

    # hooks
    p = sub.add_parser("hooks", help="Manage automation hooks (harvest timer)")
    hooks_sub = p.add_subparsers(dest="hooks_command")
    hp = hooks_sub.add_parser("install", help="Install automation hooks")
    hp.add_argument("--type", default="harvest-timer",
                    help="Hook type (default: harvest-timer)")
    hooks_sub.add_parser("status", help="Show hook status")
    hooks_sub.add_parser("remove", help="Remove automation hooks")
    p.set_defaults(func=cmd_hooks)

    # context
    p = sub.add_parser("context", help="Assemble task-scoped context for session recovery")
    p.add_argument("task", help="Description of the current task or goal")
    p.add_argument("--budget", type=int, default=2000,
                   help="Token budget (default: 2000)")
    p.add_argument("--workspace", "-w", help="Workspace scope")
    p.add_argument("--no-memories", action="store_true",
                   help="Exclude memories from context")
    p.add_argument("--no-triples", action="store_true",
                   help="Exclude triples from context")
    p.set_defaults(func=cmd_context)

    # decay
    p = sub.add_parser("decay", help="Report note excitability and dormancy")
    p.add_argument("--threshold", type=float, default=0.05,
                   help="Hotness threshold below which notes are dormant (default: 0.05)")
    p.add_argument("--half-life", type=float, default=30.0,
                   help="Half-life in days for hotness decay (default: 30)")
    p.add_argument("--limit", type=int, default=50,
                   help="Max notes to show per category (default: 50)")
    p.add_argument("--demote", action="store_true",
                   help="Demote dormant notes to status=dormant in note_metadata")
    p.set_defaults(func=cmd_decay)

    # cooccurrence
    p = sub.add_parser("cooccurrence", help="Inspect entity co-occurrence pairs")
    p.add_argument("--limit", type=int, default=20,
                   help="Number of top pairs to show (default: 20)")
    p.add_argument("--json", action="store_true", help="Output as JSON")
    p.set_defaults(func=cmd_cooccurrence)

    # harvest
    p = sub.add_parser("harvest", help="Extract insights from recent AI coding sessions")
    p.add_argument(
        "--sessions", type=int, default=1,
        help="Number of recent sessions to harvest (default: 1)",
    )
    p.add_argument(
        "--provider", type=str, default=None,
        help="Restrict to a single provider (e.g. claude-code, vscode-chat, codex-cli, aider)",
    )
    p.add_argument(
        "--list-providers", action="store_true",
        help="List available session providers and exit",
    )
    p.add_argument(
        "--dry-run", "-n", action="store_true",
        help="Show what would be saved without saving",
    )
    p.add_argument("--json", action="store_true", help="Output as JSON")
    p.set_defaults(func=cmd_harvest)

    # watch
    p = sub.add_parser("watch", help="Watch vault for changes")
    p.set_defaults(func=cmd_watch)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Preflight: nudge user to run init if vault doesn't exist yet
    _skip_preflight = {
        "init", "install", "uninstall", "doctor", "status", "demo", "update", "cloud",
    }
    vault_path = Path(args.vault)
    if args.command not in _skip_preflight and not vault_path.exists():
        print(f"\n  \033[33m!\033[0m Vault not found at {vault_path}")
        print("  Run \033[1mneurostack init\033[0m to set up your vault.\n")
        sys.exit(1)

    try:
        args.func(args)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
    except Exception as exc:
        _handle_error(exc, args.command)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Friendly error diagnostics
# ---------------------------------------------------------------------------

def _db_lock_hint() -> str:
    """Try to identify what process holds the neurostack DB lock."""
    import shutil
    import subprocess

    db_path = os.environ.get(
        "NEUROSTACK_DB_PATH",
        os.path.expanduser("~/.local/share/neurostack/neurostack.db"),
    )
    fuser = shutil.which("fuser")
    if not fuser:
        return "Run `fuser <db_path>` to find the locking process."
    try:
        result = subprocess.run(
            [fuser, db_path],
            capture_output=True, text=True, timeout=5,
        )
        pids = result.stdout.strip().split()
        if not pids:
            return ""
        lines = []
        for pid in pids:
            try:
                cmd = Path(f"/proc/{pid}/cmdline").read_text().replace("\x00", " ").strip()
                lines.append(f"  PID {pid}: {cmd}")
            except OSError:
                lines.append(f"  PID {pid}: (unable to read command)")
        return "Processes holding the database:\n" + "\n".join(lines)
    except Exception:
        return ""


def _handle_error(exc: Exception, command: str) -> None:
    """Print a friendly diagnostic instead of a raw traceback."""
    import sqlite3

    RED = "\033[31m"
    YELLOW = "\033[33m"
    RESET = "\033[0m"
    BOLD = "\033[1m"

    exc_type = type(exc).__name__
    msg = str(exc)

    print(f"\n{RED}{BOLD}Error{RESET} [{exc_type}]: {msg}\n", file=sys.stderr)

    hint = ""

    # -- sqlite errors -------------------------------------------------------
    if isinstance(exc, sqlite3.OperationalError):
        if "locked" in msg or "busy" in msg:
            lock_info = _db_lock_hint()
            hint = (
                "The database is locked by another neurostack process.\n"
                "Wait for it to finish, or kill the locking process.\n"
            )
            if lock_info:
                hint += f"\n{lock_info}\n"
        elif "no such table" in msg or "no such column" in msg:
            hint = (
                "The database schema is outdated or corrupt.\n"
                "Try: neurostack init --force\n"
            )
        elif "disk I/O error" in msg or "readonly" in msg:
            hint = (
                "Cannot write to the database file.\n"
                "Check disk space and file permissions on the DB path.\n"
            )
    elif isinstance(exc, sqlite3.IntegrityError):
        hint = (
            "A database constraint was violated (duplicate or missing data).\n"
            "Try re-indexing: neurostack index\n"
        )

    # -- network / Ollama errors ---------------------------------------------
    elif isinstance(exc, ConnectionError):
        hint = (
            "Could not connect to a required service (likely Ollama).\n"
            "Check that Ollama is running: systemctl status ollama\n"
        )
    elif isinstance(exc, OSError) and "Connection refused" in msg:
        hint = (
            "Connection refused - is Ollama running?\n"
            "Start it with: systemctl start ollama\n"
        )

    # -- missing dependencies ------------------------------------------------
    elif isinstance(exc, ImportError):
        hint = (
            f"Missing dependency: {msg}\n"
            "Install it with: uv pip install <package>\n"
        )

    # -- file errors ---------------------------------------------------------
    elif isinstance(exc, FileNotFoundError):
        hint = (
            f"File not found: {msg}\n"
            "Check paths in ~/.config/neurostack/config.toml\n"
        )
    elif isinstance(exc, PermissionError):
        hint = f"Permission denied: {msg}\n"

    # -- httpx errors (Ollama calls) -----------------------------------------
    elif exc_type == "ConnectError":
        hint = (
            "Could not connect to Ollama.\n"
            "Check that Ollama is running: systemctl status ollama\n"
        )
    elif exc_type == "ReadTimeout":
        hint = (
            "Ollama request timed out.\n"
            "The model may be loading or the GPU is under heavy load.\n"
            "Try again in a moment.\n"
        )

    if hint:
        print(f"{YELLOW}Hint:{RESET} {hint}", file=sys.stderr)
    else:
        # Unknown error - show traceback for debugging
        import traceback
        print(f"{YELLOW}Full traceback:{RESET}", file=sys.stderr)
        traceback.print_exception(type(exc), exc, exc.__traceback__, file=sys.stderr)


if __name__ == "__main__":
    main()
