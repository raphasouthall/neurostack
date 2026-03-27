# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Memory management CLI commands."""

import json

from .utils import _get_workspace


def cmd_memories(args):
    """Manage agent-written memories."""
    from ..memories import (
        forget_memory,
        get_memory_stats,
        merge_memories,
        prune_memories,
        save_memory,
        search_memories,
        update_memory,
    )
    from ..schema import DB_PATH, get_db

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
            print(
                f"  \033[32m\u2713\033[0m Saved memory"
                f" #{memory.memory_id} ({memory.entity_type})"
            )
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
                print(f"  \033[32m\u2713\033[0m Deleted memory #{args.id}")
            else:
                print(f"  \033[31m\u2717\033[0m Memory #{args.id} not found")

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
                print(f"  \033[32m\u2713\033[0m Updated memory #{memory.memory_id}")
            else:
                print(f"  \033[31m\u2717\033[0m Memory #{args.id} not found")

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
                print(f"  \033[32m\u2713\033[0m Merged into memory #{memory.memory_id}")
                print(f"    Merge count: {memory.merge_count}")
            else:
                print("  \033[31m\u2717\033[0m One or both memory IDs not found")

    else:
        print("Usage: neurostack memories {add,search,list,forget,prune,stats,update,merge}")
        print("       neurostack memories --help")
