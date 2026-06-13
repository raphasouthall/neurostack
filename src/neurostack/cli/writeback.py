# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""CLI commands for vault write-back (issue #20): migrate + sync."""

import json as _json
import os
import sys
from pathlib import Path


def _get_writer_or_exit():
    from ..vault_writer import get_vault_writer

    writer = get_vault_writer()
    if writer is None:
        print(
            "Write-back is disabled. Enable it first:\n"
            "  set [writeback] enabled = true in ~/.config/neurostack/config.toml\n"
            "  (or export NEUROSTACK_WRITEBACK_ENABLED=1)",
            file=sys.stderr,
        )
        sys.exit(1)
    return writer


def _conn():
    from ..schema import DB_PATH, get_db

    db_path = Path(os.environ.get("NEUROSTACK_DB_PATH", DB_PATH))
    return get_db(db_path)


def cmd_migrate(args):
    """Dispatch `neurostack migrate <sub>`. Only `write-back` exists for now."""
    sub = getattr(args, "migrate_command", None)
    if sub != "write-back":
        print("usage: neurostack migrate write-back [--dry-run]", file=sys.stderr)
        sys.exit(1)
    _cmd_migrate_writeback(args)


def _cmd_migrate_writeback(args):
    from ..vault_writer import migrate_writeback

    writer = _get_writer_or_exit()
    conn = _conn()
    dry = getattr(args, "dry_run", False)
    report = migrate_writeback(conn, writer, dry_run=dry)

    if getattr(args, "json", False):
        print(_json.dumps(report, indent=2))
        return

    written = report["written"]
    skipped = report["skipped"]
    label = "Would write" if dry else "Wrote"
    print(f"{label} {len(written)} memory file(s) under {writer.writeback_path}/memories/")

    by_type: dict[str, int] = {}
    for w in written:
        by_type[w["entity_type"]] = by_type.get(w["entity_type"], 0) + 1
    for t, n in sorted(by_type.items()):
        print(f"  {t}: {n}")

    msg = (
        f"Skipped {skipped['ttl']} ephemeral (TTL), "
        f"{skipped['type']} non-qualifying type"
    )
    if skipped["no_uuid"]:
        msg += f", {skipped['no_uuid']} without uuid"
    print(msg + ".")

    if report.get("errors"):
        print(f"\n{len(report['errors'])} memory file(s) failed to write:")
        for e in report["errors"]:
            print(f"  - memory {e['memory_id']}: {e['error']}")

    if dry:
        print("\nDry run — no files written. Re-run without --dry-run to apply.")
    else:
        print(
            f"\nMemories written to {writer.writeback_path}/. A .gitignore inside it "
            "keeps them\nout of git by default; delete that file to version them. "
            "NeuroStack never commits."
        )


def cmd_sync(args):
    from ..vault_writer import sync_writeback

    writer = _get_writer_or_exit()
    conn = _conn()
    report = sync_writeback(conn, writer)

    if getattr(args, "json", False):
        print(_json.dumps(report, indent=2))
        return

    print("Sync complete (DB wins on conflict):")
    print(f"  created:   {len(report['created'])}")
    print(f"  updated:   {len(report['updated'])}")
    print(f"  in sync:   {report['in_sync']}")
    print(f"  removed:   {len(report['removed'])} orphan file(s)")
    if report.get("errors"):
        print(f"  errors:    {len(report['errors'])} memory(ies) failed:")
        for e in report["errors"]:
            print(f"    - memory {e['memory_id']}: {e['error']}")
    if report["conflicts"]:
        print(
            f"  conflicts: {len(report['conflicts'])} user-edited file(s) "
            "overwritten from DB:"
        )
        for c in report["conflicts"]:
            print(f"    - {c}")
