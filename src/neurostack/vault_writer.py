# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Vault write-back: persist qualifying memories as markdown files (issue #20).

The DB stays the source of truth; these files are readable exports living in a
single quarantined directory (default ``.neurostack/``) under ``vault_root``.
NeuroStack NEVER writes outside that directory and NEVER commits — the quarantine
dir self-ignores via its own ``.gitignore`` so memories don't enter a git-backed
vault unless the user opts in.

Layout: ``{vault_root}/{writeback_path}/memories/<entity_type>/<YYYY-MM>/<uuid>.md``

Filenames are the memory UUID (stable across content edits and DB rebuilds, so
Obsidian wiki-links don't break). Conflict detection uses a SHA256 of the file
body stored in frontmatter as ``neurostack_hash`` — not mtime, which is unreliable
across git checkout / rsync / cloud sync.

This module is the only writer for the quarantine dir; it deliberately does NOT
reuse ``tools.file_tools`` (which commits + pushes to origin and demands note
frontmatter).
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import uuid as _uuid
from pathlib import Path

import yaml

log = logging.getLogger("neurostack")

# Persistent types always written when write-back is enabled.
PERSISTENT_TYPES = frozenset({"decision", "convention", "learning", "bug"})
# Noisier types written only when include_observations is set.
OPTIN_TYPES = frozenset({"observation", "context"})

_FRONTMATTER_RE = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n?", re.DOTALL)

_GITIGNORE_BODY = (
    "# NeuroStack memory write-back (issue #20).\n"
    "# This directory is git-ignored by default so exported memories don't enter\n"
    "# your repository unless you choose to version them. To track them, delete\n"
    "# this file or replace '*' with specific exceptions. NeuroStack never commits.\n"
    "*\n"
)


class WriteBackError(Exception):
    """Raised on an unrecoverable write-back configuration/path error."""


def _body_hash(content: str) -> str:
    """SHA256 of the normalized memory body. Whitespace-stripped for stability."""
    digest = hashlib.sha256((content or "").strip().encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _year_month(created_at: str | None) -> str:
    """Extract YYYY-MM from a DB timestamp like '2026-06-13 12:00:00'."""
    if created_at and len(created_at) >= 7 and created_at[4] == "-":
        return created_at[:7]
    # Fallback bucket — only reached for malformed/missing timestamps.
    return "unknown"


class VaultWriter:
    """Writes qualifying memories to markdown files under the quarantine dir."""

    def __init__(
        self,
        vault_root: Path,
        writeback_path: str = ".neurostack",
        include_observations: bool = False,
    ):
        self.vault_root = Path(vault_root).resolve()
        # Guard against a dangerously shallow root (e.g. "/" or "/home"): a
        # misconfigured vault_root must never let write-back loose near the
        # filesystem root.
        if len(self.vault_root.parts) < 3:
            raise WriteBackError(
                f"vault_root is too shallow for safe write-back: {self.vault_root}"
            )
        rel = writeback_path.strip("/")
        if not rel or ".." in Path(rel).parts:
            raise WriteBackError(f"invalid writeback path: {writeback_path!r}")
        self.writeback_path = rel
        self.include_observations = include_observations
        self.writeback_dir = (self.vault_root / rel).resolve()
        self.memories_dir = self.writeback_dir / "memories"

    # --------------------------- policy --------------------------------------

    def should_write(self, memory) -> bool:
        """Whether this memory qualifies for a file under the current policy."""
        if getattr(memory, "expires_at", None):
            return False  # ephemeral / TTL memories are never written
        if not getattr(memory, "uuid", None):
            return False  # no stable filename without a UUID
        et = memory.entity_type
        if et in PERSISTENT_TYPES:
            return True
        if et in OPTIN_TYPES:
            return self.include_observations
        return False

    # --------------------------- paths ---------------------------------------

    def relpath(self, memory) -> str:
        """Vault-relative POSIX path for this memory's file. Validates the UUID."""
        # Normalize + validate the UUID so it can never inject path segments.
        canonical = str(_uuid.UUID(str(memory.uuid)))
        et = memory.entity_type
        if et not in PERSISTENT_TYPES and et not in OPTIN_TYPES:
            raise WriteBackError(f"unsupported entity_type for write-back: {et!r}")
        ym = _year_month(memory.created_at)
        return f"{self.writeback_path}/memories/{et}/{ym}/{canonical}.md"

    def _abs(self, relpath: str) -> Path:
        """Resolve a vault-relative path and assert it stays inside the dir."""
        abs_path = (self.vault_root / relpath).resolve()
        try:
            abs_path.relative_to(self.writeback_dir)
        except ValueError as exc:
            raise WriteBackError(
                f"path escapes write-back directory: {relpath!r}"
            ) from exc
        return abs_path

    def to_relpath(self, abs_path: Path) -> str:
        return Path(abs_path).resolve().relative_to(self.vault_root).as_posix()

    # --------------------------- serialization -------------------------------

    def render(self, memory) -> str:
        """Render a memory to its full file text (frontmatter + body)."""
        body = (memory.content or "").strip()
        title = self._title(memory)
        front = {
            "title": title,
            "neurostack_id": str(memory.uuid),
            "memory_id": memory.memory_id,
            "entity_type": memory.entity_type,
            "tags": list(memory.tags or []),
            "workspace": memory.workspace,
            "source_agent": memory.source_agent,
            "created_at": memory.created_at,
            "updated_at": memory.updated_at,
            "revision_count": memory.revision_count,
            "neurostack_hash": _body_hash(body),
        }
        fm = yaml.safe_dump(
            front, sort_keys=False, allow_unicode=True, default_flow_style=False,
        )
        return f"---\n{fm}---\n\n{body}\n"

    @staticmethod
    def _title(memory) -> str:
        """Human-readable title: first non-empty line of content, truncated."""
        for line in (memory.content or "").splitlines():
            line = line.strip().lstrip("#").strip()
            if line:
                return line[:80]
        return f"{memory.entity_type} {memory.memory_id}"

    def parse_file(self, abs_path: Path) -> dict:
        """Return {'frontmatter': dict|None, 'body': str} for an existing file."""
        text = Path(abs_path).read_text(encoding="utf-8")
        m = _FRONTMATTER_RE.match(text)
        if not m:
            return {"frontmatter": None, "body": text.strip()}
        try:
            fm = yaml.safe_load(m.group(1)) or {}
        except yaml.YAMLError:
            fm = None
        body = text[m.end():].strip()
        return {"frontmatter": fm if isinstance(fm, dict) else None, "body": body}

    # --------------------------- write / delete ------------------------------

    def write(self, memory) -> str:
        """Write (or overwrite) the memory's file atomically. Returns vault-rel path."""
        relpath = self.relpath(memory)
        abs_path = self._abs(relpath)
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        self.ensure_gitignore()
        text = self.render(memory).encode("utf-8")
        tmp = abs_path.with_name(abs_path.name + ".tmp")
        tmp.write_bytes(text)
        os.replace(tmp, abs_path)  # atomic on POSIX
        return relpath

    def delete(self, relpath: str) -> bool:
        """Delete the file at a vault-relative path. Prunes emptied dirs. Idempotent."""
        if not relpath:
            return False
        abs_path = self._abs(relpath)
        if not abs_path.exists():
            return False
        abs_path.unlink()
        # Prune now-empty type/month directories up to (not including) memories_dir.
        parent = abs_path.parent
        while parent != self.memories_dir and parent.is_relative_to(self.memories_dir):
            try:
                next(parent.iterdir())
                break  # not empty
            except StopIteration:
                parent.rmdir()
                parent = parent.parent
        return True

    def iter_existing_files(self):
        """Yield absolute paths of every memory file currently on disk."""
        if not self.memories_dir.is_dir():
            return
        for fp in sorted(self.memories_dir.rglob("*.md")):
            if fp.is_file():
                yield fp

    def ensure_gitignore(self) -> None:
        """Drop a self-ignoring .gitignore inside the quarantine dir (idempotent).

        This keeps the quarantine dir out of git by default without ever touching
        the user's repo-level .gitignore — write-back stays inside its own folder.
        """
        self.writeback_dir.mkdir(parents=True, exist_ok=True)
        gi = self.writeback_dir / ".gitignore"
        if not gi.exists():
            gi.write_text(_GITIGNORE_BODY, encoding="utf-8")


# --------------------------- factory + CRUD hooks ----------------------------


def get_vault_writer() -> VaultWriter | None:
    """Return a configured VaultWriter, or None when write-back is disabled.

    Built fresh from the current config each call (cheap) so it always reflects
    the live config singleton — important for tests that reset it.
    """
    from .config import get_config

    cfg = get_config()
    if not cfg.writeback_enabled:
        return None
    try:
        return VaultWriter(
            vault_root=cfg.vault_root,
            writeback_path=cfg.writeback_path,
            include_observations=cfg.writeback_include_observations,
        )
    except WriteBackError as exc:
        log.warning("write-back disabled: %s", exc)
        return None


def apply_writeback_create(conn, memory) -> None:
    """After an INSERT: write the file and record its path. Best-effort."""
    writer = get_vault_writer()
    if writer is None:
        return
    try:
        if not writer.should_write(memory):
            return
        relpath = writer.write(memory)
        conn.execute(
            "UPDATE memories SET file_path = ? WHERE memory_id = ?",
            (relpath, memory.memory_id),
        )
        conn.commit()
        memory.file_path = relpath
    except Exception as exc:  # never let file IO break the DB write
        log.warning("write-back (create) failed for memory %s: %s",
                    getattr(memory, "memory_id", "?"), exc)


def apply_writeback_update(conn, memory, old_file_path: str | None) -> None:
    """After an UPDATE/merge: reconcile the file (rewrite, move, or remove)."""
    writer = get_vault_writer()
    if writer is None:
        return
    try:
        if writer.should_write(memory):
            new_relpath = writer.write(memory)
            # Type or month change relocates the file — drop the stale one.
            if old_file_path and old_file_path != new_relpath:
                writer.delete(old_file_path)
            if memory.file_path != new_relpath:
                conn.execute(
                    "UPDATE memories SET file_path = ? WHERE memory_id = ?",
                    (new_relpath, memory.memory_id),
                )
                conn.commit()
                memory.file_path = new_relpath
        else:
            # No longer qualifies (TTL added, or type demoted without opt-in).
            if old_file_path:
                writer.delete(old_file_path)
            if memory.file_path is not None:
                conn.execute(
                    "UPDATE memories SET file_path = NULL WHERE memory_id = ?",
                    (memory.memory_id,),
                )
                conn.commit()
                memory.file_path = None
    except Exception as exc:
        log.warning("write-back (update) failed for memory %s: %s",
                    getattr(memory, "memory_id", "?"), exc)


def apply_writeback_delete(old_file_path: str | None) -> None:
    """After a DELETE: remove the backing file. Best-effort."""
    if not old_file_path:
        return
    writer = get_vault_writer()
    if writer is None:
        return
    try:
        writer.delete(old_file_path)
    except Exception as exc:
        log.warning("write-back (delete) failed for %s: %s", old_file_path, exc)


# --------------------------- migrate / sync ----------------------------------


def migrate_writeback(conn, writer: VaultWriter, dry_run: bool = False) -> dict:
    """Write files for all qualifying existing memories.

    Returns a report dict. With dry_run=True nothing is written; the report
    lists the paths that would be created and whether each already exists.
    """
    from .memories import _row_to_memory

    rows = conn.execute("SELECT * FROM memories ORDER BY memory_id").fetchall()
    written: list[dict] = []
    errors: list[dict] = []
    skipped = {"ttl": 0, "type": 0, "no_uuid": 0}
    for row in rows:
        # Isolate each row: one malformed memory must not abort the batch.
        try:
            mem = _row_to_memory(row)
            if not writer.should_write(mem):
                if getattr(mem, "expires_at", None):
                    skipped["ttl"] += 1
                elif not mem.uuid:
                    skipped["no_uuid"] += 1
                else:
                    skipped["type"] += 1
                continue
            relpath = writer.relpath(mem)
            if dry_run:
                written.append({
                    "memory_id": mem.memory_id,
                    "entity_type": mem.entity_type,
                    "path": relpath,
                    "exists": (writer.vault_root / relpath).exists(),
                })
                continue
            relpath = writer.write(mem)
            conn.execute(
                "UPDATE memories SET file_path = ? WHERE memory_id = ?",
                (relpath, mem.memory_id),
            )
            written.append({
                "memory_id": mem.memory_id,
                "entity_type": mem.entity_type,
                "path": relpath,
            })
        except Exception as exc:
            errors.append({"memory_id": row["memory_id"], "error": str(exc)})
            log.warning("write-back migrate failed for memory %s: %s",
                        row["memory_id"], exc)
    if not dry_run:
        conn.commit()
        writer.ensure_gitignore()
    return {"written": written, "skipped": skipped, "errors": errors,
            "dry_run": dry_run}


def sync_writeback(conn, writer: VaultWriter) -> dict:
    """Reconcile files against the DB. The DB always wins on conflict.

    - Missing file for a qualifying memory  -> created
    - File body differs from DB content     -> overwritten from DB
      (reported as a 'conflict' when the file was user-edited since last write)
    - File with no qualifying DB memory      -> removed (orphan)
    """
    from .memories import _row_to_memory

    def _set_path(memory_id: int, relpath: str) -> None:
        conn.execute(
            "UPDATE memories SET file_path = ? WHERE memory_id = ?",
            (relpath, memory_id),
        )

    rows = conn.execute("SELECT * FROM memories ORDER BY memory_id").fetchall()
    desired: dict[str, object] = {}
    created: list[str] = []
    updated: list[str] = []
    conflicts: list[str] = []
    removed: list[str] = []
    errors: list[dict] = []
    in_sync = 0

    for row in rows:
        try:
            mem = _row_to_memory(row)
            if not writer.should_write(mem):
                continue
            relpath = writer.relpath(mem)
            desired[relpath] = mem
            abs_path = writer.vault_root / relpath

            if not abs_path.exists():
                writer.write(mem)
                _set_path(mem.memory_id, relpath)
                created.append(relpath)
                continue

            parsed = writer.parse_file(abs_path)
            stored_hash = (parsed["frontmatter"] or {}).get("neurostack_hash")
            file_body_hash = _body_hash(parsed["body"])
            db_hash = _body_hash(mem.content)

            if db_hash == file_body_hash:
                if mem.file_path != relpath:
                    _set_path(mem.memory_id, relpath)
                in_sync += 1
                continue

            # Divergence — DB wins, overwrite the file.
            writer.write(mem)
            _set_path(mem.memory_id, relpath)
            if stored_hash and stored_hash != file_body_hash:
                conflicts.append(relpath)  # user had edited the file on disk
            else:
                updated.append(relpath)
        except Exception as exc:
            errors.append({"memory_id": row["memory_id"], "error": str(exc)})
            log.warning("write-back sync failed for memory %s: %s",
                        row["memory_id"], exc)

    # Orphans: files on disk with no qualifying memory backing them.
    for abs_path in writer.iter_existing_files():
        relpath = writer.to_relpath(abs_path)
        if relpath not in desired:
            writer.delete(relpath)
            removed.append(relpath)

    conn.commit()
    writer.ensure_gitignore()
    return {
        "created": created,
        "updated": updated,
        "conflicts": conflicts,
        "removed": removed,
        "errors": errors,
        "in_sync": in_sync,
    }
