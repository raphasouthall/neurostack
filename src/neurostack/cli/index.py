# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Indexing and maintenance CLI commands."""

import os
from pathlib import Path


def cmd_index(args):
    from ..schema import DB_PATH, get_db
    from ..watcher import full_index
    full_index(
        vault_root=Path(args.vault),
        embed_url=args.embed_url,
        summarize_url=args.summarize_url,
        skip_summary=args.skip_summary,
        skip_triples=args.skip_triples,
        workers=getattr(args, "workers", 2),
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


def cmd_watch(args):
    from ..watcher import run_watcher
    run_watcher(
        vault_root=Path(args.vault),
        embed_url=args.embed_url,
        summarize_url=args.summarize_url,
    )
