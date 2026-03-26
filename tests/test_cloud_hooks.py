"""Tests for git hooks installer (neurostack cloud install-hooks)."""
from __future__ import annotations

import stat

import pytest

from neurostack.cloud.hooks import (
    HOOK_MARKER,
    hooks_status,
    install_hooks,
    uninstall_hooks,
)


@pytest.fixture
def git_vault(tmp_path):
    """Create a tmp_path that looks like a git repo."""
    (tmp_path / ".git").mkdir()
    return tmp_path


def test_install_hooks_creates_post_commit(git_vault):
    result = install_hooks(git_vault)
    hook = git_vault / ".git" / "hooks" / "post-commit"
    assert hook.exists()
    assert HOOK_MARKER in hook.read_text()
    assert "post-commit" in result["installed"]


def test_install_hooks_creates_post_merge(git_vault):
    result = install_hooks(git_vault)
    hook = git_vault / ".git" / "hooks" / "post-merge"
    assert hook.exists()
    assert HOOK_MARKER in hook.read_text()
    assert "post-merge" in result["installed"]


def test_hooks_are_executable(git_vault):
    install_hooks(git_vault)
    for name in ("post-commit", "post-merge"):
        hook = git_vault / ".git" / "hooks" / name
        mode = hook.stat().st_mode
        assert mode & stat.S_IXUSR, f"{name} should be user-executable"
        assert mode & stat.S_IXGRP, f"{name} should be group-executable"
        assert mode & stat.S_IXOTH, f"{name} should be other-executable"


def test_install_hooks_skips_existing(git_vault):
    first = install_hooks(git_vault)
    assert len(first["installed"]) == 2
    assert len(first["skipped"]) == 0

    second = install_hooks(git_vault)
    assert len(second["installed"]) == 0
    assert set(second["skipped"]) == {"post-commit", "post-merge"}


def test_install_hooks_not_git_repo(tmp_path):
    with pytest.raises(ValueError, match="Not a git repository"):
        install_hooks(tmp_path)


def test_uninstall_hooks_removes(git_vault):
    install_hooks(git_vault)
    result = uninstall_hooks(git_vault)
    assert set(result["removed"]) == {"post-commit", "post-merge"}
    assert not (git_vault / ".git" / "hooks" / "post-commit").exists()
    assert not (git_vault / ".git" / "hooks" / "post-merge").exists()


def test_hooks_status_reports_correctly(git_vault):
    # Before install
    status = hooks_status(git_vault)
    assert status["git_repo"] is True
    assert status["post_commit"] is False
    assert status["post_merge"] is False

    # After install
    install_hooks(git_vault)
    status = hooks_status(git_vault)
    assert status["post_commit"] is True
    assert status["post_merge"] is True

    # Not a git repo
    from pathlib import Path
    status = hooks_status(Path("/tmp/not-a-repo-12345"))
    assert status["git_repo"] is False


def test_hooks_append_to_existing(git_vault):
    hooks_dir = git_vault / ".git" / "hooks"
    hooks_dir.mkdir(exist_ok=True)

    # Write a pre-existing post-commit hook without the marker
    existing_content = "#!/bin/sh\n# my custom hook\necho 'custom action'\n"
    (hooks_dir / "post-commit").write_text(existing_content)

    install_hooks(git_vault)

    final = (hooks_dir / "post-commit").read_text()
    # Original content preserved
    assert "my custom hook" in final
    assert "echo 'custom action'" in final
    # Neurostack content appended
    assert HOOK_MARKER in final
    assert "neurostack cloud sync" in final
