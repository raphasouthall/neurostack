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


def cmd_brief(args):
    from .brief import generate_brief
    brief = generate_brief(vault_root=Path(args.vault), workspace=_get_workspace(args))
    if args.json:
        print(json.dumps({"brief": brief}, indent=2, default=str))
        return
    print(brief)


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
            print(json.dumps({"coarse": n_coarse, "fine": n_fine, "status": "done"}, indent=2, default=str))
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
    from .search import _normalize_workspace
    from .schema import DB_PATH, get_db
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
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        f'vault_root = "{vault_root}"\n'
        f'embed_url = "{cfg.embed_url}"\n'
        f'llm_url = "{cfg.llm_url}"\n'
        f'llm_model = "{cfg.llm_model}"\n'
    )

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
    print("\n  \033[1mOllama Configuration\033[0m")
    print("  NeuroStack uses Ollama for embeddings and summaries.\n")

    embed_url = _prompt("Embedding endpoint", default=cfg.embed_url)
    llm_url = _prompt("LLM endpoint", default=cfg.llm_url)

    model_choices = [
        ("phi3.5", "phi3.5 — MIT licensed, fast, 3.8B params"),
        ("qwen3:8b", "qwen3:8b — Apache 2.0, strong reasoning"),
        ("llama3.1:8b", "llama3.1:8b — Meta community license, popular"),
        ("mistral:7b", "mistral:7b — Apache 2.0, efficient"),
    ]
    llm_model = _prompt("LLM model for summaries", default=cfg.llm_model, choices=model_choices)

    # 4. Index after init?
    run_index = _confirm("Index vault after setup?", default=False)

    # Show summary
    print("\n  \033[1m━━━ Summary ━━━\033[0m\n")
    print(f"  Vault:      {vault_root}")
    print(f"  Profession: {profession}")
    print(f"  Embed URL:  {embed_url}")
    print(f"  LLM URL:    {llm_url}")
    print(f"  LLM model:  {llm_model}")
    print(f"  Index now:  {'yes' if run_index else 'no'}")

    if not _confirm("\n  Proceed?", default=True):
        print("\n  Cancelled.")
        return

    # Apply settings to config
    cfg.vault_root = vault_root
    cfg.embed_url = embed_url
    cfg.llm_url = llm_url
    cfg.llm_model = llm_model

    _do_init(vault_root, cfg, profession_name=profession, run_index=run_index)

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


def cmd_doctor(args):
    """Validate all NeuroStack subsystems."""

    cfg = get_config()
    checks = []

    # Check vault exists
    if cfg.vault_root.exists():
        note_count = len(list(cfg.vault_root.rglob("*.md")))
        checks.append(("Vault", "OK", f"{cfg.vault_root} ({note_count} .md files)"))
    else:
        checks.append(("Vault", "MISSING", f"{cfg.vault_root} not found. Run: neurostack init"))

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
        checks.append(("Database", "MISSING", "Run: neurostack index"))

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
            "errors": sum(1 for _, s, _ in checks if s in ("ERROR", "MISSING")),
            "warnings": sum(1 for _, s, _ in checks if s == "WARN"),
        }
        print(json.dumps(output, indent=2, default=str))
        if output["errors"]:
            sys.exit(1)
        return

    print("\nNeuroStack Doctor\n" + "=" * 40)
    for name, status, detail in checks:
        icon = {"OK": "+", "WARN": "!", "ERROR": "X", "SKIP": "-", "MISSING": "X"}[status]
        print(f"  [{icon}] {name}: {detail}")

    errors = sum(1 for _, s, _ in checks if s in ("ERROR", "MISSING"))
    warns = sum(1 for _, s, _ in checks if s == "WARN")
    if errors:
        print(f"\n{errors} error(s) found. Fix them before proceeding.")
        sys.exit(1)
    elif warns:
        print(f"\n{warns} warning(s). Lite mode works. Install optional deps for full features.")
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


def cmd_sessions(args):
    """Search session transcripts."""
    from .session_index import main as session_main
    # Forward remaining args to session_index
    extra = args.session_args
    if args.json and "--json" not in extra:
        extra = ["--json"] + extra
    sys.argv = ["neurostack-sessions"] + extra
    session_main()


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
        prune_memories,
        save_memory,
        search_memories,
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
            print(json.dumps({
                "saved": True,
                "memory_id": memory.memory_id,
                "entity_type": memory.entity_type,
                "created_at": memory.created_at,
                "expires_at": memory.expires_at,
            }, indent=2))
        else:
            print(f"  \033[32m✓\033[0m Saved memory #{memory.memory_id} ({memory.entity_type})")
            if memory.expires_at:
                print(f"    Expires: {memory.expires_at}")

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

    else:
        print("Usage: neurostack memories {add,search,list,forget,prune,stats}")
        print("       neurostack memories --help")


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
        help="Apply a profession pack (e.g., developer, writer, student, devops, data-scientist, researcher). Use 'scaffold --list' to see all",
    )
    p.set_defaults(func=cmd_init)

    # scaffold
    p = sub.add_parser("scaffold", help="Apply a profession pack to an existing vault")
    p.add_argument("profession", nargs="?", help="Profession name (e.g., developer, writer, student, devops, data-scientist, researcher)")
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

    p.set_defaults(func=cmd_memories)

    # doctor
    p = sub.add_parser("doctor", help="Validate all subsystems")
    p.set_defaults(func=cmd_doctor)

    # serve
    p = sub.add_parser("serve", help="Start MCP server")
    p.add_argument("--transport", choices=["stdio", "sse"], default="stdio")
    p.set_defaults(func=cmd_serve)

    # sessions
    p = sub.add_parser("sessions", help="Search session transcripts")
    p.add_argument(
        "session_args", nargs=argparse.REMAINDER,
        help="Arguments passed to session-index",
    )
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
        help="Restrict results to vault subdirectory (e.g. 'work/nyk-europe-azure'). Also reads NEUROSTACK_WORKSPACE env var",
    )
    p.set_defaults(func=cmd_search)

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
        help="Restrict neighbors to vault subdirectory (e.g. 'work/nyk-europe-azure'). Also reads NEUROSTACK_WORKSPACE env var",
    )
    p.set_defaults(func=cmd_graph)

    # triples
    p = sub.add_parser("triples", help="Search knowledge graph triples")
    p.add_argument("query", help="Search query")
    p.add_argument("--top-k", type=int, default=10)
    p.add_argument("--mode", choices=["hybrid", "semantic", "keyword"], default="hybrid")
    p.add_argument(
        "--workspace", "-w", default=None,
        help="Restrict results to vault subdirectory (e.g. 'work/nyk-europe-azure'). Also reads NEUROSTACK_WORKSPACE env var",
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
        help="Restrict results to vault subdirectory (e.g. 'work/nyk-europe-azure'). Also reads NEUROSTACK_WORKSPACE env var",
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
        help="Restrict results to vault subdirectory (e.g. 'work/nyk-europe-azure'). Also reads NEUROSTACK_WORKSPACE env var",
    )

    # communities list
    p_l = comm_sub.add_parser("list", help="List detected communities")
    p_l.add_argument("--level", type=int, default=None, help="Filter by level (0 or 1)")

    p.set_defaults(func=cmd_communities)

    # brief
    p = sub.add_parser("brief", help="Generate session brief")
    p.add_argument(
        "--workspace", "-w", default=None,
        help="Restrict brief to vault subdirectory (e.g. 'work/nyk-europe-azure'). Also reads NEUROSTACK_WORKSPACE env var",
    )
    p.set_defaults(func=cmd_brief)

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
        help="Restrict results to vault subdirectory (e.g. 'work/nyk-europe-azure'). Also reads NEUROSTACK_WORKSPACE env var",
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
