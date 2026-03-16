#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""CLI entry point for neurostack."""

import argparse
import json
import os
import sys
from pathlib import Path

from . import __version__
from .config import CONFIG_PATH, get_config


def cmd_index(args):
    from .schema import DB_PATH, get_db
    from .watcher import full_index
    cfg = get_config()
    exclude = []
    if cfg.writeback_enabled:
        exclude.append(cfg.writeback_path)
    full_index(
        vault_root=Path(args.vault),
        embed_url=args.embed_url,
        summarize_url=args.summarize_url,
        skip_summary=args.skip_summary,
        skip_triples=args.skip_triples,
        exclude_dirs=exclude or None,
    )
    db_path = Path(os.environ.get("NEUROSTACK_DB_PATH", DB_PATH))
    conn = get_db(db_path)
    notes = conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
    chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    edges = conn.execute("SELECT COUNT(*) FROM graph_edges").fetchone()[0]
    print(f"Indexed {notes} notes, {chunks} chunks, {edges} graph edges.")


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
        }
        print(json.dumps(output, indent=2, default=str))
        return

    print(f"Notes:       {notes}")
    print(f"Chunks:      {chunks}")
    embed_pct = embedded * 100 // max(chunks, 1)
    print(f"Embedded:    {embedded} ({embed_pct}%)")
    sum_pct = summaries * 100 // max(notes, 1)
    print(f"Summarized:  {summaries} ({sum_pct}%)")
    print(f"Graph edges: {edges}")
    triple_pct = notes_with_triples * 100 // max(notes, 1)
    print(
        f"Triples:     {total_triples} from"
        f" {notes_with_triples} notes ({triple_pct}%)"
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
    cfg = get_config()
    exclude = []
    if cfg.writeback_enabled:
        exclude.append(cfg.writeback_path)
    run_watcher(
        vault_root=Path(args.vault),
        embed_url=args.embed_url,
        summarize_url=args.summarize_url,
        exclude_dirs=exclude or None,
    )


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
        src_claude = base_template / "CLAUDE.md"
        dst_claude = vault_root / "CLAUDE.md"
        if src_claude.exists() and not dst_claude.exists():
            shutil.copy2(src_claude, dst_claude)
            created.append("CLAUDE.md")

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
    wb_enabled = str(cfg.writeback_enabled).lower()
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
    config_text += (
        f'\n[writeback]\n'
        f'enabled = {wb_enabled}\n'
        f'path = "{cfg.writeback_path}"\n'
    )
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
        from .indexer import index_vault
        from .schema import get_db

        db = get_db(cfg.db_path)
        indexed = index_vault(db, vault_root, cfg)
        print(f"  \033[32m✓\033[0m Indexed {indexed} notes")


def cmd_init(args):
    """Initialize a new NeuroStack vault and config."""
    from .professions import list_professions

    cfg = get_config()

    # Non-interactive mode: use flags directly (backwards compatible)
    if args.path or args.profession or not sys.stdin.isatty():
        vault_root = Path(args.path) if args.path else cfg.vault_root
        _do_init(vault_root, cfg, profession_name=args.profession)
        print("\nNext steps:")
        print("  neurostack index          # Index your vault")
        print("  neurostack search 'query' # Search")
        print("  neurostack doctor         # Check health")
        return

    # ── Interactive setup wizard ──
    print("\n  \033[1m━━━ NeuroStack Setup ━━━\033[0m\n")

    # 1. Vault path
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

    # 3. LLM configuration
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

    # 3b. API keys (optional — only needed for cloud providers)
    llm_api_key = ""
    embed_api_key = ""
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

    # 4. Write-back
    print(
        "\n  Enable memory write-back? Memories will be"
        " saved as browsable\n  markdown files in your vault."
    )
    writeback = _confirm("Enable write-back?", default=False)

    # 5. Index after init?
    run_index = _confirm("Index vault after setup?", default=False)

    # Show summary
    wb_label = "yes" if writeback else "no"
    auth_label = "yes" if (llm_api_key or embed_api_key) else "no"
    print("\n  \033[1m━━━ Summary ━━━\033[0m\n")
    print(f"  Vault:      {vault_root}")
    print(f"  Profession: {profession}")
    print(f"  Embed URL:  {embed_url}")
    print(f"  LLM URL:    {llm_url}")
    print(f"  LLM model:  {llm_model}")
    print(f"  API auth:   {auth_label}")
    print(f"  Write-back: {wb_label}")
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
    cfg.writeback_enabled = writeback

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


def cmd_writeback(args):
    """Manage vault write-back for memories."""
    cfg = get_config()
    subcmd = getattr(args, "writeback_command", None)

    if subcmd == "status":
        state = "enabled" if cfg.writeback_enabled else "disabled"
        wb_dir = cfg.vault_root / cfg.writeback_path
        if wb_dir.exists():
            md_count = sum(
                1 for _ in wb_dir.rglob("*.md")
            )
        else:
            md_count = 0
        print(f"  Write-back: {state}")
        print(f"  Path:       {wb_dir}")
        print(f"  Files:      {md_count}")

    elif subcmd == "migrate":
        from .memories import Memory
        from .schema import DB_PATH, get_db
        from .vault_writer import VaultWriter

        dry_run = getattr(args, "dry_run", False)
        conn = get_db(DB_PATH)

        qualifying = (
            "decision", "convention", "learning", "bug",
        )
        placeholders = ", ".join("?" for _ in qualifying)
        rows = conn.execute(
            f"SELECT memory_id, content, tags,"
            f" entity_type, source_agent,"
            f" workspace, created_at,"
            f" expires_at, updated_at, uuid"
            f" FROM memories"
            f" WHERE entity_type IN ({placeholders})"
            f" AND (expires_at IS NULL"
            f"  OR expires_at > datetime('now'))",
            qualifying,
        ).fetchall()

        if not rows:
            print("No qualifying memories to migrate.")
            return

        if dry_run:
            print(
                f"[dry-run] Would write {len(rows)}"
                f" memories to"
                f" {cfg.vault_root / cfg.writeback_path}"
            )
            for row in rows:
                etype = row["entity_type"]
                mid = row["memory_id"]
                snippet = row["content"][:60]
                print(f"  #{mid} ({etype}): {snippet}")
            return

        writer = VaultWriter(
            cfg.vault_root, cfg.writeback_path,
        )
        wrote = 0
        for row in rows:
            tags_raw = row["tags"]
            if tags_raw:
                try:
                    tags = json.loads(tags_raw)
                except (ValueError, TypeError):
                    tags = []
            else:
                tags = []
            mem = Memory(
                memory_id=row["memory_id"],
                content=row["content"],
                tags=tags,
                entity_type=row["entity_type"],
                source_agent=row["source_agent"],
                workspace=row["workspace"],
                created_at=row["created_at"],
                expires_at=row["expires_at"],
                updated_at=row["updated_at"],
                uuid=row["uuid"],
            )
            result = writer.write(mem)
            if result:
                wrote += 1

        wb_path = cfg.vault_root / cfg.writeback_path
        print(
            f"Wrote {wrote} files to {wb_path}."
            f" Add to .gitignore if you don't"
            f" want them versioned."
        )

    else:
        print("Usage: neurostack writeback <status|migrate>")
        print("  status   - Show write-back status")
        print("  migrate  - Write files for existing memories")
        sys.exit(1)


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

    # 2. Add missing frontmatter
    today = date.today().isoformat()
    # Files to skip — NeuroStack scaffolding, not user notes
    skip_names = {"index.md", "CLAUDE.md"}
    skip_dirs = {"templates", ".obsidian", ".claude"}

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
            tags = f"[{parent_tag}]" if parent_tag else "[]"

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

            new_fm = (
                f"---\ndate: {today}\ntags: {tags}\n"
                f"type: {note_type}\nstatus: active\n---\n\n"
            )
            if not dry_run:
                md.write_text(
                    new_fm + content, encoding="utf-8",
                )
            print(f"  {prefix}+ frontmatter → {rel}")
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

    # 5. Copy CLAUDE.md and base templates if missing
    base_template = (
        Path(__file__).resolve().parent.parent.parent / "vault-template"
    )
    if base_template.exists():
        src_claude = base_template / "CLAUDE.md"
        dst_claude = target / "CLAUDE.md"
        if src_claude.exists() and not dst_claude.exists():
            if not dry_run:
                shutil.copy2(src_claude, dst_claude)
            print(f"  {prefix}+ CLAUDE.md")

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

    project_root = Path(__file__).resolve().parent.parent.parent
    if not (project_root / "pyproject.toml").exists():
        fallback = Path.home() / ".local" / "share" / "neurostack" / "repo"
        if (fallback / "pyproject.toml").exists():
            project_root = fallback
        else:
            print("  \033[31m✗\033[0m Cannot find project root")
            sys.exit(1)

    git = shutil.which("git")
    if not git:
        print("  \033[31m✗\033[0m git not found")
        sys.exit(1)

    print(f"  Updating from {project_root}...\n")

    # Show current version
    print(f"  Current version: {__version__}")

    # Git pull
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
    sync_cmd = ["uv", "sync", "--project", str(project_root)]
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
            ["uv", "run", "--project", str(project_root),
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
    """Streamlined installation: mode selection, deps, and optional Ollama setup."""
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
    else:
        # ── Interactive wizard ──
        print("\n  \033[1m━━━ NeuroStack Install ━━━\033[0m\n")

        # 1. Show system info
        py_ver = platform.python_version()
        print(f"  Python:   {py_ver}")
        try:
            conn = sqlite3.connect(":memory:")
            conn.execute("CREATE VIRTUAL TABLE _t USING fts5(c)")
            conn.close()
            print("  FTS5:     available")
        except Exception:
            print("  \033[31mFTS5:     MISSING — SQLite compiled without FTS5\033[0m")
            sys.exit(1)

        uv_path = shutil.which("uv")
        if uv_path:
            try:
                uv_ver = subprocess.run(
                    ["uv", "--version"], capture_output=True, text=True, timeout=5
                ).stdout.strip()
                print(f"  uv:       {uv_ver}")
            except Exception:
                print(f"  uv:       {uv_path}")
        else:
            print("  \033[31muv:       NOT FOUND\033[0m")
            print("  Install:  curl -LsSf https://astral.sh/uv/install.sh | sh")
            sys.exit(1)

        # 2. Detect current mode
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

        # 3. Choose mode
        mode_choices = [
            ("lite", "Lite — FTS5 search + graph, no ML (~130 MB)"),
            ("full", "Full — + embeddings, summaries, reranking (~560 MB)"),
            ("community", "Community — + GraphRAG Leiden detection (~575 MB)"),
        ]
        mode = _prompt("Installation mode", default=current_mode, choices=mode_choices)

        # 4. Ollama models (only for full/community)
        pull_models = False
        embed_model = cfg.embed_model
        llm_model = cfg.llm_model
        if mode in ("full", "community"):
            print("\n  \033[1mOllama Models\033[0m")
            print("  Full mode uses Ollama for embeddings and summaries.")
            pull_models = _confirm("Pull Ollama models now?", default=True)
            if pull_models:
                embed_model = _prompt("Embedding model", default=cfg.embed_model)
                model_choices = [
                    ("phi3.5", "phi3.5 — MIT, fast, 3.8B"),
                    ("qwen3:8b", "qwen3:8b — Apache 2.0, strong reasoning"),
                    ("llama3.1:8b", "llama3.1:8b — Meta license, popular"),
                    ("mistral:7b", "mistral:7b — Apache 2.0, efficient"),
                ]
                llm_model = _prompt("LLM model", default=cfg.llm_model, choices=model_choices)

        # Confirm
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
    print(f"  \033[32m✓\033[0m CLI wrapper: {wrapper}")

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

    # Summary
    print(f"\n  \033[32mInstalled!\033[0m ({mode} mode)")
    print()
    print("  Next steps:")
    print("    neurostack init          # Set up vault")
    print("    neurostack doctor        # Verify setup")
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
            and f.name != "CLAUDE.md"
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


def cmd_harvest(args):
    """Extract insights from recent Claude Code sessions."""
    from .harvest import harvest_sessions

    result = harvest_sessions(
        n_sessions=args.sessions,
        dry_run=args.dry_run,
        embed_url=args.embed_url,
    )

    if args.json:
        print(json.dumps(result, indent=2, default=str))
        return

    if "error" in result:
        print(f"  Error: {result['error']}")
        return

    mode = "DRY RUN" if result.get("dry_run") else "Harvest"
    print(f"\n  {mode} - scanned {result['sessions_scanned']} session(s)\n")

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
    p.set_defaults(func=cmd_onboard)

    # demo
    p = sub.add_parser("demo", help="Run interactive demo with sample vault")
    p.set_defaults(func=cmd_demo)

    # status
    p = sub.add_parser("status", help="Show NeuroStack status")
    p.set_defaults(func=cmd_status)

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
        "(e.g. 'work/nyk-europe-azure'). "
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
        "(e.g. 'work/nyk-europe-azure'). "
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
        "(e.g. 'work/nyk-europe-azure'). "
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
        "(e.g. 'work/nyk-europe-azure'). "
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
        "(e.g. 'work/nyk-europe-azure'). "
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
        "(e.g. 'work/nyk-europe-azure'). "
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
    p_q.add_argument(
        "--no-map-reduce", action="store_true",
        help="Return raw community hits without LLM synthesis",
    )
    p_q.add_argument(
        "--workspace", "-w", default=None,
        help="Restrict results to vault subdirectory "
        "(e.g. 'work/nyk-europe-azure'). "
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
        "(e.g. 'work/nyk-europe-azure'). "
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
        "(e.g. 'work/nyk-europe-azure'). "
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
    p.set_defaults(func=cmd_decay)

    # harvest
    p = sub.add_parser("harvest", help="Extract insights from recent Claude Code sessions")
    p.add_argument(
        "--sessions", type=int, default=1,
        help="Number of recent sessions to harvest (default: 1)",
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

    # writeback
    p = sub.add_parser(
        "writeback",
        help="Manage vault write-back for memories",
    )
    wb_sub = p.add_subparsers(dest="writeback_command")
    wb_sub.add_parser("status", help="Show write-back status")
    wp = wb_sub.add_parser(
        "migrate",
        help="Write files for all existing qualifying memories",
    )
    wp.add_argument(
        "--dry-run", "-n", action="store_true",
        help="Show what would be written without writing",
    )
    p.set_defaults(func=cmd_writeback)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
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
