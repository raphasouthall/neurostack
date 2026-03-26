# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Content-hash manifest for incremental vault sync.

Tracks SHA-256 hashes of vault markdown files so only changed content
is uploaded to the cloud indexer.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

import pathspec


@dataclass
class SyncDiff:
    """Result of comparing two manifests."""

    added: list[str] = field(default_factory=list)
    """New files not in previous manifest."""

    changed: list[str] = field(default_factory=list)
    """Files whose content hash changed."""

    removed: list[str] = field(default_factory=list)
    """Files no longer in vault."""

    @property
    def has_changes(self) -> bool:
        """True if any files were added, changed, or removed."""
        return bool(self.added or self.changed or self.removed)

    @property
    def upload_files(self) -> list[str]:
        """Files that need uploading (added + changed)."""
        return self.added + self.changed


class Manifest:
    """Content-hash manifest for vault files.

    Stores {relative_path: sha256_hex} mappings and supports diffing
    two manifests to determine what changed.
    """

    def __init__(self, entries: dict[str, str] | None = None) -> None:
        self.entries: dict[str, str] = entries or {}

    @staticmethod
    def scan_vault(vault_root: Path, ignore_file: Path | None = None) -> Manifest:
        """Walk vault_root, compute SHA-256 for each .md file.

        Skips directories starting with '.' (.obsidian, .git, .neurostack).
        Uses forward slashes for cross-platform consistency.

        If *ignore_file* is provided and exists, patterns are parsed using
        gitignore syntax (via ``pathspec``) and matching files are excluded.
        """
        entries: dict[str, str] = {}
        root = str(vault_root)

        # Build ignore spec from .neurostackignore if available
        spec: pathspec.PathSpec | None = None
        if ignore_file is not None and ignore_file.exists():
            patterns = ignore_file.read_text().splitlines()
            patterns = [p for p in patterns if p.strip() and not p.strip().startswith("#")]
            if patterns:
                spec = pathspec.PathSpec.from_lines("gitignore", patterns)

        for dirpath, dirnames, filenames in os.walk(root):
            # Filter out dot-directories in-place (prevents os.walk from descending)
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]

            for fname in filenames:
                if not fname.endswith(".md"):
                    continue

                full_path = os.path.join(dirpath, fname)
                # Relative path with forward slashes
                rel_path = os.path.relpath(full_path, root).replace(os.sep, "/")

                if spec and spec.match_file(rel_path):
                    continue  # Skip ignored files

                sha = hashlib.sha256()
                with open(full_path, "rb") as f:
                    while chunk := f.read(65536):
                        sha.update(chunk)

                entries[rel_path] = sha.hexdigest()

        return Manifest(entries)

    @staticmethod
    def load(path: Path) -> Manifest:
        """Load manifest from JSON file. Returns empty Manifest if not found."""
        if not path.exists():
            return Manifest()

        with open(path) as f:
            data = json.load(f)

        return Manifest(data)

    def save(self, path: Path) -> None:
        """Save manifest to JSON file. Creates parent directories."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(self.entries, f, indent=2, sort_keys=True)

    @staticmethod
    def diff(old: Manifest, new: Manifest) -> SyncDiff:
        """Compute what changed between two manifests."""
        old_keys = set(old.entries)
        new_keys = set(new.entries)

        added = sorted(new_keys - old_keys)
        removed = sorted(old_keys - new_keys)
        changed = sorted(
            k for k in old_keys & new_keys if old.entries[k] != new.entries[k]
        )

        return SyncDiff(added=added, changed=changed, removed=removed)
