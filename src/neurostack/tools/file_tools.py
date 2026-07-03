# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Vault file CRUD tools — read/list/write/delete .md files in the brain vault.

Designed for MCP clients (e.g. Microsoft Copilot Studio) that need to author
vault notes without ssh access. Writes commit + push to origin/main under an
flock, with rebase-on-conflict and rollback on push failure.
"""

from __future__ import annotations

import fcntl
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .registry import ToolAnnotationHints as Hints
from .registry import registry

_READ_ONLY = Hints(read_only=True, open_world=False)
_WRITE_IDEMPOTENT = Hints(
    read_only=False, destructive=False, idempotent=True, open_world=False,
)
_WRITE_DESTRUCTIVE = Hints(
    read_only=False, destructive=True, idempotent=True, open_world=False,
)

REQUIRED_FRONTMATTER_FIELDS = ("date", "tags", "type")
LOCK_FILENAME = ".neurostack-write.lock"

_FRONTMATTER_RE = re.compile(r"^---\r?\n(.*?)\r?\n---(\r?\n|$)", re.DOTALL)


def _vault_root() -> Path:
    from ..config import get_config
    return get_config().vault_root.resolve()


# --------------------------- path safety -------------------------------------


class PathSafetyError(ValueError):
    """Raised when a caller-supplied path violates the safety rules."""


def _check_segments(relative: str, parts: tuple[str, ...]) -> None:
    for part in parts:
        if part in ("", "."):
            raise PathSafetyError(f"empty or '.' segment in {relative!r}")
        if part == "..":
            raise PathSafetyError(f"'..' segment not allowed in {relative!r}")
        if part.startswith("."):
            raise PathSafetyError(
                f"hidden segment {part!r} not allowed in {relative!r}"
            )


def _check_symlinks_inside(vault_root: Path, parts: tuple[str, ...]) -> None:
    current = vault_root
    for part in parts:
        current = current / part
        if current.is_symlink():
            target = current.resolve()
            try:
                target.relative_to(vault_root)
            except ValueError as exc:
                raise PathSafetyError(
                    f"symlink {part!r} points outside vault"
                ) from exc


def _safe_path(relative: str, vault_root: Path) -> Path:
    """Resolve a relative .md path inside vault_root, rejecting unsafe inputs."""
    if not relative or not relative.strip():
        raise PathSafetyError("path is empty")
    p = Path(relative)
    if p.is_absolute():
        raise PathSafetyError(f"path must be relative, got {relative!r}")

    _check_segments(relative, p.parts)

    if p.suffix != ".md":
        raise PathSafetyError(
            f"only .md files allowed, got {p.suffix!r} in {relative!r}"
        )

    _check_symlinks_inside(vault_root, p.parts)

    abs_path = (vault_root / p).resolve()
    try:
        abs_path.relative_to(vault_root)
    except ValueError as exc:
        raise PathSafetyError(
            f"path escapes vault root: {relative!r}"
        ) from exc
    return abs_path


def _safe_dir(relative: str, vault_root: Path) -> Path:
    """Resolve a relative directory inside vault_root. Empty string = vault root."""
    if not relative:
        return vault_root
    p = Path(relative)
    if p.is_absolute():
        raise PathSafetyError(f"directory must be relative, got {relative!r}")

    _check_segments(relative, p.parts)
    _check_symlinks_inside(vault_root, p.parts)

    abs_path = (vault_root / p).resolve()
    try:
        abs_path.relative_to(vault_root)
    except ValueError as exc:
        raise PathSafetyError(
            f"directory escapes vault root: {relative!r}"
        ) from exc
    return abs_path


# --------------------------- frontmatter -------------------------------------


def _parse_frontmatter(content: str) -> tuple[dict | None, list[str]]:
    """Return (frontmatter_dict_or_none, list_of_errors)."""
    m = _FRONTMATTER_RE.match(content)
    if not m:
        return None, [
            "missing frontmatter block (expected leading --- YAML --- at start of file)",
        ]
    try:
        data = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as exc:
        return None, [f"frontmatter YAML parse error: {exc}"]
    if not isinstance(data, dict):
        return None, [
            f"frontmatter is not a YAML mapping (got {type(data).__name__})",
        ]
    return data, []


def _missing_required_fields(fm: dict) -> list[str]:
    """Return required fields that are absent or None. Empty list/string is allowed."""
    missing = []
    for field in REQUIRED_FRONTMATTER_FIELDS:
        if field not in fm or fm[field] is None:
            missing.append(field)
    return missing


# --------------------------- git helpers -------------------------------------


def _run_git(
    args: list[str], cwd: Path, *, check: bool = True,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), check=check,
        capture_output=True, text=True,
    )


def _git_head(cwd: Path) -> str | None:
    """Return current HEAD sha or None on empty repo."""
    r = _run_git(["rev-parse", "HEAD"], cwd, check=False)
    if r.returncode != 0:
        return None
    return r.stdout.strip() or None


def _stage_and_diff(vault_root: Path, relative_path: str) -> bool:
    """Stage the path; return True if anything actually changed in the index."""
    _run_git(["add", "--", relative_path], vault_root)
    diff_check = _run_git(
        ["diff", "--cached", "--quiet"], vault_root, check=False,
    )
    return diff_check.returncode != 0


def _try_push_with_rebase(vault_root: Path) -> str | None:
    """Push origin main. Return None on success, error string on failure."""
    try:
        _run_git(["push", "origin", "main"], vault_root)
        return None
    except subprocess.CalledProcessError as first:
        stderr1 = (first.stderr or "").strip()
        try:
            _run_git(
                ["pull", "--rebase", "--autostash", "origin", "main"],
                vault_root,
            )
        except subprocess.CalledProcessError as rebase_err:
            _run_git(["rebase", "--abort"], vault_root, check=False)
            return (
                f"push failed and rebase failed: "
                f"push={stderr1}; rebase={(rebase_err.stderr or '').strip()}"
            )
        try:
            _run_git(["push", "origin", "main"], vault_root)
            return None
        except subprocess.CalledProcessError as second:
            return (
                f"push failed twice: first={stderr1}; "
                f"after-rebase={(second.stderr or '').strip()}"
            )


def _rollback_commit(vault_root: Path, our_commit_sha: str | None) -> None:
    """Reset HEAD by one commit if our commit is still on top. Best-effort."""
    if not our_commit_sha:
        return
    current = _git_head(vault_root)
    if current == our_commit_sha:
        _run_git(["reset", "--hard", "HEAD~1"], vault_root, check=False)


def _commit_and_push(
    vault_root: Path, relative_path: str, commit_message: str,
) -> dict:
    """Stage + commit + push. Returns dict with commit_sha/pushed/error fields."""
    try:
        changed = _stage_and_diff(vault_root, relative_path)
    except subprocess.CalledProcessError as exc:
        return {
            "committed": False, "pushed": False,
            "error": f"git add failed: {(exc.stderr or str(exc)).strip()}",
        }
    if not changed:
        return {
            "committed": False, "pushed": False, "no_changes": True,
            "commit_sha": None,
        }

    try:
        _run_git(["commit", "-m", commit_message], vault_root)
    except subprocess.CalledProcessError as exc:
        return {
            "committed": False, "pushed": False,
            "error": f"git commit failed: {(exc.stderr or str(exc)).strip()}",
        }
    commit_sha = _git_head(vault_root)

    push_err = _try_push_with_rebase(vault_root)
    if push_err is None:
        return {
            "committed": True, "pushed": True,
            "commit_sha": commit_sha,
        }

    _rollback_commit(vault_root, commit_sha)
    return {
        "committed": True, "pushed": False, "rolled_back": True,
        "commit_sha": None, "error": push_err,
    }


# --------------------------- locking -----------------------------------------


def _acquire_vault_lock(vault_root: Path):
    """Acquire an exclusive flock on the vault write lock. Returns file handle."""
    lock_path = vault_root / LOCK_FILENAME
    fh = open(lock_path, "a+")
    fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
    return fh


def _release_vault_lock(fh) -> None:
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    finally:
        fh.close()


# --------------------------- tools -------------------------------------------


@registry.tool(tags=["vault-files", "read"], annotations=_READ_ONLY)
def vault_read_file(path: str) -> dict:
    """Read a markdown file from the vault.

    Args:
        path: Relative path under vault_root (e.g. "home/projects/foo.md").
              Must end in .md. Absolute paths, '..', and dot-prefixed
              segments (.git, .obsidian, .trash, etc.) are rejected.
    """
    vault_root = _vault_root()
    try:
        abs_path = _safe_path(path, vault_root)
    except PathSafetyError as exc:
        return {"path": path, "exists": False, "error": str(exc)}

    if not abs_path.is_file():
        return {"path": path, "exists": False, "size_bytes": 0, "content": ""}

    data = abs_path.read_bytes()

    # Implicit-feedback loop (issue #66): opening a note is a deliberate use, so
    # attribute it back to the search that surfaced it. Opt-in, non-blocking, and
    # writes only to the index DB (not the vault) — the read stays read-only.
    from ..feedback import capture_use
    capture_use([path])

    return {
        "path": path,
        "exists": True,
        "size_bytes": len(data),
        "content": data.decode("utf-8"),
    }


@registry.tool(tags=["vault-files", "read"], annotations=_READ_ONLY)
def vault_list_files(
    directory: str = "",
    pattern: str = "*.md",
    recursive: bool = True,
) -> dict:
    """List markdown files under a vault directory.

    Hidden segments (.git, .obsidian, .trash, .neurostack, .claude, etc.) are
    always excluded from results.

    Args:
        directory: Relative directory under vault_root. "" = vault root.
        pattern: Glob pattern (default "*.md"). Only .md files are returned
                 regardless of pattern.
        recursive: If True (default), walk subdirectories.
    """
    vault_root = _vault_root()
    try:
        abs_dir = _safe_dir(directory, vault_root)
    except PathSafetyError as exc:
        return {"directory": directory, "files": [], "error": str(exc)}

    if not abs_dir.is_dir():
        return {
            "directory": directory, "files": [],
            "error": f"not a directory: {directory!r}",
        }

    iterator = abs_dir.rglob(pattern) if recursive else abs_dir.glob(pattern)
    files = []
    for fp in sorted(iterator):
        if not fp.is_file():
            continue
        if fp.suffix != ".md":
            continue
        try:
            rel = fp.relative_to(vault_root)
        except ValueError:
            continue
        if any(part.startswith(".") for part in rel.parts):
            continue
        stat = fp.stat()
        modified = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
        files.append({
            "path": str(rel),
            "size_bytes": stat.st_size,
            "modified_iso": modified.isoformat(),
        })
    return {"directory": directory, "files": files}


@registry.tool(tags=["vault-files", "write"], annotations=_WRITE_IDEMPOTENT)
def vault_write_file(
    path: str,
    content: str,
    commit_message: str = None,
) -> dict:
    """Create or overwrite a markdown file in the vault. Commits + pushes to origin/main.

    Requires a YAML frontmatter block with required fields date, tags, type;
    hard-rejects writes that lack any of them. On push conflict, attempts
    `git pull --rebase --autostash` and retries once; on second failure,
    rolls back the local commit and returns pushed=false.

    Args:
        path: Relative .md path under vault_root.
        content: Full file content. Must start with `---\\n...\\n---\\n` YAML.
        commit_message: Optional. Default: "vault_write_file: <path> (via MCP)".
    """
    vault_root = _vault_root()
    try:
        abs_path = _safe_path(path, vault_root)
    except PathSafetyError as exc:
        return {"path": path, "written": False, "error": str(exc)}

    fm, fm_errors = _parse_frontmatter(content)
    if fm is None:
        return {
            "path": path, "written": False,
            "error": "frontmatter validation failed",
            "frontmatter_errors": fm_errors,
        }
    missing = _missing_required_fields(fm)
    if missing:
        return {
            "path": path, "written": False,
            "error": (
                f"missing required frontmatter fields: {', '.join(missing)} "
                f"(required: {', '.join(REQUIRED_FRONTMATTER_FIELDS)})"
            ),
            "missing_fields": missing,
        }

    msg = commit_message or f"vault_write_file: {path} (via MCP)"
    fh = _acquire_vault_lock(vault_root)
    try:
        created = not abs_path.exists()
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        encoded = content.encode("utf-8")
        abs_path.write_bytes(encoded)
        git_result = _commit_and_push(vault_root, path, msg)
    finally:
        _release_vault_lock(fh)

    rel_parent = abs_path.parent.relative_to(vault_root)
    index_hint = None
    if created:
        index_hint = (
            f"- [[{abs_path.stem}]] — <one-line description> "
            f"(add to {rel_parent / 'index.md'})"
        )

    return {
        "path": path,
        "written": True,
        "created": created,
        "bytes_written": len(encoded),
        "commit_sha": git_result.get("commit_sha"),
        "pushed": git_result.get("pushed", False),
        "rolled_back": git_result.get("rolled_back", False),
        "no_changes": git_result.get("no_changes", False),
        "git_error": git_result.get("error"),
        "index_update_needed": created,
        "index_hint": index_hint,
    }


@registry.tool(tags=["vault-files", "write"], annotations=_WRITE_DESTRUCTIVE)
def vault_delete_file(
    path: str,
    commit_message: str = None,
) -> dict:
    """Delete a markdown file from the vault. Commits + pushes to origin/main.

    Same path-safety rules as the write/read tools. Returns deleted=False
    with an error if the file does not exist. Conflict and rollback behaviour
    matches vault_write_file.

    Args:
        path: Relative .md path under vault_root.
        commit_message: Optional. Default: "vault_delete_file: <path> (via MCP)".
    """
    vault_root = _vault_root()
    try:
        abs_path = _safe_path(path, vault_root)
    except PathSafetyError as exc:
        return {"path": path, "deleted": False, "error": str(exc)}

    if not abs_path.is_file():
        return {
            "path": path, "deleted": False,
            "error": f"file does not exist: {path}",
        }

    msg = commit_message or f"vault_delete_file: {path} (via MCP)"
    fh = _acquire_vault_lock(vault_root)
    try:
        abs_path.unlink()
        git_result = _commit_and_push(vault_root, path, msg)
    finally:
        _release_vault_lock(fh)

    rel_parent = abs_path.parent.relative_to(vault_root)
    return {
        "path": path,
        "deleted": True,
        "commit_sha": git_result.get("commit_sha"),
        "pushed": git_result.get("pushed", False),
        "rolled_back": git_result.get("rolled_back", False),
        "no_changes": git_result.get("no_changes", False),
        "git_error": git_result.get("error"),
        "index_update_needed": True,
        "index_hint": (
            f"remove the [[{abs_path.stem}]] entry from {rel_parent / 'index.md'}"
        ),
    }
