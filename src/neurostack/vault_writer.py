# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Vault write-back - persist memories as markdown files."""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path

from .memories import Memory

log = logging.getLogger("neurostack")


class VaultWriter:
    """Writes Memory objects to the vault as markdown files."""

    def __init__(
        self,
        vault_root: Path,
        writeback_path: str = "memories",
    ):
        self.vault_root = vault_root.resolve()
        self.memories_dir = self.vault_root / writeback_path
        self._created_dirs: set[str] = set()
        self._check_vault_root()

    # -- public API --------------------------------------------------

    def write(self, memory: Memory) -> Path | None:
        """Write a Memory to the vault as a markdown file.

        Returns the path written, or None on failure.
        """
        try:
            path = self._build_path(memory)
            if not self._check_containment(path):
                return None

            content_body = memory.content
            content_hash = self._compute_hash(content_body)
            frontmatter = self._render_frontmatter(
                memory, content_hash,
            )
            full_text = f"{frontmatter}\n{content_body}\n"

            self._ensure_dir(path.parent)
            tmp_path = path.with_suffix(".tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(full_text)
            os.rename(tmp_path, path)

            log.info("Wrote memory %s to %s", memory.memory_id, path)
            return path
        except Exception:
            log.warning(
                "Failed to write memory %s",
                memory.memory_id,
                exc_info=True,
            )
            return None

    def delete(self, memory: Memory) -> bool:
        """Delete a memory's markdown file from the vault.

        Returns True if deleted, False if not found or error.
        """
        try:
            path = self._build_path(memory)
            if not self._check_containment(path):
                return False
            if not path.exists():
                log.warning(
                    "Memory file not found for deletion: %s", path,
                )
                return False
            path.unlink()
            log.info(
                "Deleted memory %s at %s", memory.memory_id, path,
            )
            return True
        except Exception:
            log.warning(
                "Failed to delete memory %s",
                memory.memory_id,
                exc_info=True,
            )
            return False

    def overwrite(self, memory: Memory) -> Path | None:
        """Overwrite (update) a memory's markdown file.

        Recalculates the content hash from new content.
        Returns the path written, or None on failure.
        """
        return self.write(memory)

    # -- internal helpers --------------------------------------------

    def _build_path(self, memory: Memory) -> Path:
        """Derive file path from memory metadata.

        Format: {memories_dir}/{entity_type}/{YYYY-MM}/{uuid}.md
        """
        entity = memory.entity_type or "observation"
        # Extract YYYY-MM from created_at (format: YYYY-MM-DD ...)
        month = memory.created_at[:7] if memory.created_at else "unknown"
        mid = memory.uuid or str(memory.memory_id)
        filename = f"{mid}.md"
        return self.memories_dir / entity / month / filename

    def _render_frontmatter(
        self,
        memory: Memory,
        content_hash: str,
    ) -> str:
        """Render YAML frontmatter block for the memory."""
        title = memory.content.strip().replace("\n", " ")
        if len(title) > 60:
            title = title[:57] + "..."

        # Escape any YAML-problematic chars in title
        title = title.replace('"', '\\"')

        tags_list = memory.tags or []
        tags_str = (
            "[" + ", ".join(str(t) for t in tags_list) + "]"
        )

        workspace = memory.workspace or "null"
        if workspace != "null":
            workspace = f'"{workspace}"'

        source = memory.source_agent or "null"
        if source != "null":
            source = f'"{source}"'

        updated = memory.updated_at or "null"
        if updated != "null":
            updated = f'"{updated}"'

        lines = [
            "---",
            f'title: "{title}"',
            f"neurostack_id: {memory.uuid or memory.memory_id}",
            f"entity_type: {memory.entity_type}",
            f"tags: {tags_str}",
            f"workspace: {workspace}",
            f"source_agent: {source}",
            f'created_at: "{memory.created_at}"',
            f"updated_at: {updated}",
            f"neurostack_hash: {content_hash}",
            "---",
        ]
        return "\n".join(lines)

    def _compute_hash(self, content: str) -> str:
        """SHA256 hash of content, prefixed with 'sha256:'."""
        digest = hashlib.sha256(
            content.encode("utf-8"),
        ).hexdigest()
        return f"sha256:{digest}"

    def _ensure_dir(self, dir_path: Path) -> None:
        """Create directory if needed, with caching."""
        key = str(dir_path)
        if key in self._created_dirs:
            return
        try:
            dir_path.mkdir(parents=True, exist_ok=True)
            self._created_dirs.add(key)
        except Exception:
            log.warning(
                "Failed to create directory %s",
                dir_path,
                exc_info=True,
            )
            raise

    def _check_containment(self, path: Path) -> bool:
        """Verify resolved path is under vault_root.

        Prevents path traversal via symlinks or '..'.
        """
        real = Path(os.path.realpath(path))
        root = str(self.vault_root)
        if not str(real).startswith(root + os.sep) and str(real) != root:
            log.warning(
                "Security: path %s resolves outside vault root %s",
                path,
                self.vault_root,
            )
            return False
        return True

    def _check_vault_root(self) -> bool:
        """Validate vault_root has >= 3 path components.

        Prevents accidental writes to / or /home/user.
        Raises ValueError on failure.
        """
        parts = self.vault_root.parts
        if len(parts) < 3:
            raise ValueError(
                f"vault_root too shallow ({self.vault_root}). "
                f"Must have >= 3 path components to prevent "
                f"accidental writes to system directories."
            )
        return True
