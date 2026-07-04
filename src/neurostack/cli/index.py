# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Indexing and maintenance CLI commands."""

import json
import os
from pathlib import Path


def cmd_index(args):
    from ..schema import DB_PATH, get_db
    from ..watcher import full_index
    pruned = full_index(
        vault_root=Path(args.vault),
        embed_url=args.embed_url,
        summarize_url=args.summarize_url,
        skip_summary=args.skip_summary,
        skip_triples=args.skip_triples,
        workers=getattr(args, "workers", 2),
        prune=not getattr(args, "no_prune", False),
    )
    db_path = Path(os.environ.get("NEUROSTACK_DB_PATH", DB_PATH))
    conn = get_db(db_path)
    notes = conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
    chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    edges = conn.execute("SELECT COUNT(*) FROM graph_edges").fetchone()[0]
    print(f"Indexed {notes} notes, {chunks} chunks, {edges} graph edges.")
    if pruned:
        print(f"Pruned {pruned} orphaned notes (deleted from disk).")
    if notes == 0:
        print("\n  \033[33m!\033[0m No Markdown files found in the vault.")
        print("  Add .md files to your vault, then run: neurostack index")


def cmd_reembed_chunks(args):
    from ..watcher import reembed_all_chunks
    reembed_all_chunks(embed_url=args.embed_url)


def cmd_backfill(args):
    from ..watcher import backfill_stale_summaries, backfill_summaries, backfill_triples
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
        from ..cooccurrence import persist_cooccurrence
        from ..schema import DB_PATH, get_db
        conn = get_db(DB_PATH)
        n = persist_cooccurrence(conn)
        print(f"Co-occurrence backfill: {n} entity pairs populated.")
    if args.target in ("memories", "all"):
        from ..memories import backfill_memory_embeddings
        from ..schema import DB_PATH, get_db
        conn = get_db(DB_PATH)
        n = backfill_memory_embeddings(conn, embed_url=args.embed_url)
        print(f"Memory embedding backfill: {n} memories (re-)embedded.")


def cmd_export(args):
    from ..export import export_notes
    from ..schema import DB_PATH, get_db
    db_path = Path(os.environ.get("NEUROSTACK_DB_PATH", DB_PATH))
    conn = get_db(db_path)
    include = set(args.include or [])
    notes = export_notes(conn, include_triples="triples" in include)
    text = json.dumps(notes, indent=2, default=str)
    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text + "\n")
        print(f"Exported {len(notes)} notes to {args.output}")
    else:
        print(text)


def cmd_watch(args):
    from ..watcher import run_watcher
    run_watcher(
        vault_root=Path(args.vault),
        embed_url=args.embed_url,
        summarize_url=args.summarize_url,
    )
