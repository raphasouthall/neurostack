# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Git hooks installer for automatic cloud sync.

Installs post-commit and post-merge hooks in the vault's git repository
that run `neurostack cloud sync` after each commit/merge.
"""
from __future__ import annotations

import stat
from pathlib import Path

HOOK_MARKER = "# neurostack-cloud-sync"

POST_COMMIT_HOOK = f"""\
#!/bin/sh
{HOOK_MARKER}
# Auto-sync vault to NeuroStack Cloud after commit
neurostack cloud sync --quiet 2>/dev/null &
"""

POST_MERGE_HOOK = f"""\
#!/bin/sh
{HOOK_MARKER}
# Auto-sync vault to NeuroStack Cloud after merge
neurostack cloud sync --quiet 2>/dev/null &
"""


def find_git_dir(vault_root: Path) -> Path | None:
    """Find the .git directory for the vault. Returns None if not a git repo."""
    git_dir = vault_root / ".git"
    if git_dir.is_dir():
        return git_dir
    # Could be a git worktree — .git is a file with "gitdir: <path>"
    if git_dir.is_file():
        content = git_dir.read_text().strip()
        if content.startswith("gitdir:"):
            return Path(content.split(":", 1)[1].strip())
    return None


def install_hooks(vault_root: Path) -> dict:
    """Install post-commit and post-merge hooks.

    Returns dict with results:
    {
        "installed": ["post-commit", "post-merge"],
        "skipped": [],  # already installed
        "git_dir": str,
    }
    """
    git_dir = find_git_dir(vault_root)
    if git_dir is None:
        raise ValueError(f"Not a git repository: {vault_root}")

    hooks_dir = git_dir / "hooks"
    hooks_dir.mkdir(exist_ok=True)

    installed = []
    skipped = []

    for hook_name, hook_content in [
        ("post-commit", POST_COMMIT_HOOK),
        ("post-merge", POST_MERGE_HOOK),
    ]:
        hook_path = hooks_dir / hook_name

        if hook_path.exists():
            existing = hook_path.read_text()
            if HOOK_MARKER in existing:
                skipped.append(hook_name)
                continue
            # Append to existing hook
            hook_path.write_text(existing.rstrip() + "\n\n" + hook_content)
        else:
            hook_path.write_text(hook_content)

        # Make executable
        hook_path.chmod(hook_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        installed.append(hook_name)

    return {
        "installed": installed,
        "skipped": skipped,
        "git_dir": str(git_dir),
    }


def uninstall_hooks(vault_root: Path) -> dict:
    """Remove neurostack sync hooks.

    Returns dict with results:
    {
        "removed": ["post-commit", "post-merge"],
        "not_found": [],
    }
    """
    git_dir = find_git_dir(vault_root)
    if git_dir is None:
        raise ValueError(f"Not a git repository: {vault_root}")

    hooks_dir = git_dir / "hooks"
    removed = []
    not_found = []

    for hook_name in ("post-commit", "post-merge"):
        hook_path = hooks_dir / hook_name

        if not hook_path.exists():
            not_found.append(hook_name)
            continue

        content = hook_path.read_text()
        if HOOK_MARKER not in content:
            not_found.append(hook_name)
            continue

        # Remove the neurostack section
        lines = content.split("\n")
        new_lines = []
        skip = False
        for line in lines:
            if HOOK_MARKER in line:
                skip = True
                continue
            if skip and line.startswith("#"):
                continue
            if skip and line.strip().startswith("neurostack"):
                skip = False
                continue
            skip = False
            new_lines.append(line)

        remaining = "\n".join(new_lines).strip()
        if remaining and remaining != "#!/bin/sh":
            hook_path.write_text(remaining + "\n")
        else:
            hook_path.unlink()

        removed.append(hook_name)

    return {
        "removed": removed,
        "not_found": not_found,
    }


def hooks_status(vault_root: Path) -> dict:
    """Check if hooks are installed.

    Returns:
    {
        "git_repo": bool,
        "post_commit": bool,
        "post_merge": bool,
    }
    """
    git_dir = find_git_dir(vault_root)
    if git_dir is None:
        return {"git_repo": False, "post_commit": False, "post_merge": False}

    hooks_dir = git_dir / "hooks"
    result = {"git_repo": True, "post_commit": False, "post_merge": False}

    for hook_name in ("post_commit", "post_merge"):
        file_name = hook_name.replace("_", "-")
        hook_path = hooks_dir / file_name
        if hook_path.exists() and HOOK_MARKER in hook_path.read_text():
            result[hook_name] = True

    return result
