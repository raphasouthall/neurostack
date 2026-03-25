# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Build .mcpb bundle for Claude Desktop extensions.

Creates a ZIP archive with manifest.json, pyproject.toml, icon, and source
code. Respects .mcpbignore for file exclusion.
"""

from __future__ import annotations

import fnmatch
import json
import zipfile
from pathlib import Path


def _load_ignore_patterns(repo_root: Path) -> list[str]:
    """Load exclusion patterns from .mcpbignore."""
    ignore_file = repo_root / ".mcpbignore"
    if not ignore_file.exists():
        return []
    patterns = []
    for line in ignore_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            patterns.append(line)
    return patterns


def _is_ignored(rel_path: str, patterns: list[str]) -> bool:
    """Check if a relative path matches any ignore pattern."""
    parts = rel_path.split("/")
    for pattern in patterns:
        # Directory pattern (ends with /)
        if pattern.endswith("/"):
            dir_name = pattern.rstrip("/")
            if any(part == dir_name for part in parts[:-1]):
                return True
            # Also match if the path starts with the directory
            if rel_path.startswith(dir_name + "/") or rel_path == dir_name:
                return True
        # File pattern
        elif fnmatch.fnmatch(rel_path, pattern):
            return True
        elif fnmatch.fnmatch(parts[-1], pattern):
            return True
    return False


def _sync_version(repo_root: Path) -> str:
    """Read version from pyproject.toml and sync to manifest.json."""
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib

    pyproject = repo_root / "pyproject.toml"
    with open(pyproject, "rb") as f:
        data = tomllib.load(f)
    version = data["project"]["version"]

    # Update manifest.json version
    manifest_path = repo_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("version") != version:
        manifest["version"] = version
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")

    return version


def build_mcpb(output_dir: str = "dist", repo_root: Path | None = None) -> Path:
    """Build the .mcpb bundle ZIP file.

    Args:
        output_dir: Directory to write the .mcpb file to.
        repo_root: Root of the neurostack repo. Defaults to this file's repo.

    Returns:
        Path to the created .mcpb file.
    """
    if repo_root is None:
        repo_root = Path(__file__).resolve().parent.parent.parent

    version = _sync_version(repo_root)
    patterns = _load_ignore_patterns(repo_root)

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    mcpb_path = out_dir / f"neurostack-{version}.mcpb"

    # Required files that must be included
    required = ["manifest.json", "pyproject.toml", "icon.png"]

    with zipfile.ZipFile(mcpb_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # Add required files
        for name in required:
            fpath = repo_root / name
            if fpath.exists():
                zf.write(fpath, name)

        # Add source package
        src_dir = repo_root / "src"
        if src_dir.exists():
            for fpath in sorted(src_dir.rglob("*")):
                if fpath.is_dir():
                    continue
                rel = str(fpath.relative_to(repo_root))
                if _is_ignored(rel, patterns):
                    continue
                zf.write(fpath, rel)

        # Add vault-template (needed for init)
        tmpl_dir = repo_root / "vault-template"
        if tmpl_dir.exists():
            for fpath in sorted(tmpl_dir.rglob("*")):
                if fpath.is_dir():
                    continue
                rel = str(fpath.relative_to(repo_root))
                if _is_ignored(rel, patterns):
                    continue
                zf.write(fpath, rel)

    return mcpb_path
