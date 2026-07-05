"""Tests for neurostack.tools.file_tools — vault file CRUD over MCP."""

from __future__ import annotations

import os
import subprocess
import threading
import time
from pathlib import Path

import pytest

from neurostack import config as nsconfig
from neurostack.tools.file_tools import (
    PathSafetyError,
    _safe_dir,
    _safe_path,
    vault_delete_file,
    vault_list_files,
    vault_read_file,
    vault_write_file,
)

# --------------------------- fixtures ----------------------------------------


VALID_FRONTMATTER = (
    "---\n"
    "date: 2026-05-11\n"
    "tags: [test]\n"
    "type: project\n"
    "---\n\n"
    "# Test Note\n\nBody.\n"
)


def _git(args: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), check=check,
        capture_output=True, text=True,
    )


@pytest.fixture
def tmp_vault_repo(tmp_path, monkeypatch):
    """tmp_path/vault → working tree, tmp_path/remote.git → bare remote."""
    bare = tmp_path / "remote.git"
    _git(["init", "--bare", "--initial-branch=main", str(bare)], cwd=tmp_path)

    vault = tmp_path / "vault"
    vault.mkdir()
    _git(["init", "--initial-branch=main"], cwd=vault)
    _git(["config", "user.email", "test@example.com"], cwd=vault)
    _git(["config", "user.name", "test"], cwd=vault)
    _git(["config", "commit.gpgsign", "false"], cwd=vault)
    _git(["remote", "add", "origin", str(bare)], cwd=vault)
    (vault / "README.md").write_text("# vault\n")
    _git(["add", "README.md"], cwd=vault)
    _git(["commit", "-m", "init"], cwd=vault)
    _git(["push", "origin", "main"], cwd=vault)

    monkeypatch.setenv("NEUROSTACK_VAULT_ROOT", str(vault))
    nsconfig._config = None
    yield vault
    nsconfig._config = None


def _head(vault: Path) -> str:
    return _git(["rev-parse", "HEAD"], cwd=vault).stdout.strip()


def _remote_head(bare: Path) -> str:
    return _git(["rev-parse", "main"], cwd=bare).stdout.strip()


# --------------------------- path safety -------------------------------------


class TestPathSafety:
    def test_traversal_rejected(self, tmp_vault_repo):
        with pytest.raises(PathSafetyError, match="'..'"):
            _safe_path("../etc/passwd", tmp_vault_repo)

    def test_absolute_rejected(self, tmp_vault_repo):
        with pytest.raises(PathSafetyError, match="relative"):
            _safe_path("/etc/passwd", tmp_vault_repo)

    def test_dot_segment_rejected(self, tmp_vault_repo):
        with pytest.raises(PathSafetyError, match="hidden"):
            _safe_path(".git/config", tmp_vault_repo)

    def test_dot_prefix_filename_rejected(self, tmp_vault_repo):
        with pytest.raises(PathSafetyError, match="hidden|.md"):
            _safe_path(".secret.md", tmp_vault_repo)

    def test_non_md_rejected(self, tmp_vault_repo):
        with pytest.raises(PathSafetyError, match=".md"):
            _safe_path("home/foo.txt", tmp_vault_repo)

    def test_empty_rejected(self, tmp_vault_repo):
        with pytest.raises(PathSafetyError, match="empty"):
            _safe_path("", tmp_vault_repo)

    def test_symlink_outside_rejected(self, tmp_path, tmp_vault_repo):
        outside = tmp_path / "outside.md"
        outside.write_text("---\ndate: x\ntags: []\ntype: x\n---\nbad\n")
        link = tmp_vault_repo / "evil.md"
        os.symlink(outside, link)
        with pytest.raises(PathSafetyError, match="outside"):
            _safe_path("evil.md", tmp_vault_repo)

    def test_valid_path_accepted(self, tmp_vault_repo):
        p = _safe_path("home/projects/note.md", tmp_vault_repo)
        assert p == (tmp_vault_repo / "home" / "projects" / "note.md").resolve()

    def test_safe_dir_empty_is_root(self, tmp_vault_repo):
        assert _safe_dir("", tmp_vault_repo) == tmp_vault_repo

    def test_safe_dir_traversal_rejected(self, tmp_vault_repo):
        with pytest.raises(PathSafetyError):
            _safe_dir("..", tmp_vault_repo)


# --------------------------- vault_read_file ---------------------------------


class TestReadFile:
    def test_read_existing(self, tmp_vault_repo):
        target = tmp_vault_repo / "home" / "note.md"
        target.parent.mkdir(parents=True)
        target.write_text("hello\n")
        result = vault_read_file(path="home/note.md")
        assert result["exists"] is True
        assert result["content"] == "hello\n"
        assert result["size_bytes"] == len("hello\n")
        assert result["path"] == "home/note.md"

    def test_read_nonexistent(self, tmp_vault_repo):
        result = vault_read_file(path="home/missing.md")
        assert result["exists"] is False
        assert result["content"] == ""

    def test_read_rejected_path(self, tmp_vault_repo):
        result = vault_read_file(path="../etc/passwd")
        assert result["exists"] is False
        assert "error" in result

    def test_unbounded_read_has_no_paging_keys(self, tmp_vault_repo):
        # Issue #62: the default call must stay byte-for-byte unchanged.
        target = tmp_vault_repo / "home" / "note.md"
        target.parent.mkdir(parents=True)
        target.write_text("hello world\n")
        result = vault_read_file(path="home/note.md")
        assert set(result) == {"path", "exists", "size_bytes", "content"}

    def test_bounded_read_offset_and_limit(self, tmp_vault_repo):
        target = tmp_vault_repo / "home" / "big.md"
        target.parent.mkdir(parents=True)
        target.write_text("0123456789")
        result = vault_read_file(path="home/big.md", offset=2, limit=3)
        assert result["content"] == "234"
        assert result["offset"] == 2
        assert result["size_chars"] == 10
        assert result["size_bytes"] == 10
        assert result["truncated"] is True

    def test_bounded_read_to_end_not_truncated(self, tmp_vault_repo):
        target = tmp_vault_repo / "home" / "big.md"
        target.parent.mkdir(parents=True)
        target.write_text("0123456789")
        result = vault_read_file(path="home/big.md", offset=7, limit=100)
        assert result["content"] == "789"
        assert result["truncated"] is False

    def test_bounded_read_pages_reassemble_to_whole(self, tmp_vault_repo):
        body = "".join(str(i % 10) for i in range(250))
        target = tmp_vault_repo / "home" / "long.md"
        target.parent.mkdir(parents=True)
        target.write_text(body)
        pages, offset = [], 0
        while True:
            page = vault_read_file(path="home/long.md", offset=offset, limit=100)
            pages.append(page["content"])
            if not page["truncated"]:
                break
            offset += len(page["content"])
        assert "".join(pages) == body

    def test_negative_params_rejected(self, tmp_vault_repo):
        target = tmp_vault_repo / "home" / "note.md"
        target.parent.mkdir(parents=True)
        target.write_text("hello")
        assert "error" in vault_read_file(path="home/note.md", offset=-1)
        assert "error" in vault_read_file(path="home/note.md", limit=-5)

    def test_offset_past_end_returns_empty(self, tmp_vault_repo):
        target = tmp_vault_repo / "home" / "note.md"
        target.parent.mkdir(parents=True)
        target.write_text("short")
        result = vault_read_file(path="home/note.md", offset=999)
        assert result["content"] == ""
        assert result["truncated"] is False


# --------------------------- vault_list_files --------------------------------


class TestListFiles:
    def _seed_notes(self, vault: Path) -> None:
        (vault / "home" / "a").mkdir(parents=True)
        (vault / "home" / "a" / "one.md").write_text("a")
        (vault / "home" / "a" / "two.md").write_text("b")
        (vault / "home" / "b.md").write_text("c")
        (vault / ".obsidian").mkdir()
        (vault / ".obsidian" / "workspace.md").write_text("hidden")

    def test_empty_dir(self, tmp_vault_repo):
        (tmp_vault_repo / "empty").mkdir()
        result = vault_list_files(directory="empty")
        assert result["files"] == []

    def test_recursive(self, tmp_vault_repo):
        self._seed_notes(tmp_vault_repo)
        result = vault_list_files(directory="home", recursive=True)
        paths = sorted(f["path"] for f in result["files"])
        assert paths == ["home/a/one.md", "home/a/two.md", "home/b.md"]

    def test_non_recursive(self, tmp_vault_repo):
        self._seed_notes(tmp_vault_repo)
        result = vault_list_files(directory="home", recursive=False)
        paths = sorted(f["path"] for f in result["files"])
        assert paths == ["home/b.md"]

    def test_excludes_hidden(self, tmp_vault_repo):
        self._seed_notes(tmp_vault_repo)
        result = vault_list_files(directory="", recursive=True)
        paths = [f["path"] for f in result["files"]]
        for p in paths:
            assert not any(seg.startswith(".") for seg in Path(p).parts)
        # README.md from fixture is the only root-level .md
        assert "README.md" in paths
        assert ".obsidian/workspace.md" not in paths

    def test_pattern(self, tmp_vault_repo):
        self._seed_notes(tmp_vault_repo)
        result = vault_list_files(
            directory="home/a", pattern="one*.md", recursive=False,
        )
        paths = [f["path"] for f in result["files"]]
        assert paths == ["home/a/one.md"]

    def test_rejected_directory(self, tmp_vault_repo):
        result = vault_list_files(directory="../etc")
        assert result["files"] == []
        assert "error" in result


# --------------------------- vault_write_file --------------------------------


class TestWriteFile:
    def test_create_new(self, tmp_vault_repo):
        result = vault_write_file(
            path="home/new.md", content=VALID_FRONTMATTER,
        )
        assert result["written"] is True
        assert result["created"] is True
        assert result["pushed"] is True
        assert result["commit_sha"]
        assert result["index_update_needed"] is True
        assert result["index_hint"]
        assert (tmp_vault_repo / "home" / "new.md").is_file()
        # commit exists
        log = _git(["log", "--oneline", "-2"], cwd=tmp_vault_repo).stdout
        assert "vault_write_file: home/new.md" in log
        # remote has the new HEAD
        bare = tmp_vault_repo.parent / "remote.git"
        assert _remote_head(bare) == _head(tmp_vault_repo)

    def test_overwrite_existing(self, tmp_vault_repo):
        # seed
        vault_write_file(path="home/x.md", content=VALID_FRONTMATTER)
        new_content = VALID_FRONTMATTER + "Extra line.\n"
        result = vault_write_file(path="home/x.md", content=new_content)
        assert result["written"] is True
        assert result["created"] is False
        assert result["pushed"] is True
        assert (tmp_vault_repo / "home" / "x.md").read_text() == new_content

    def test_missing_frontmatter_rejected(self, tmp_vault_repo):
        result = vault_write_file(
            path="home/bad.md", content="# Just a heading, no frontmatter\n",
        )
        assert result["written"] is False
        assert "frontmatter" in result["error"]
        assert not (tmp_vault_repo / "home" / "bad.md").exists()

    def test_missing_required_field_rejected(self, tmp_vault_repo):
        content = (
            "---\n"
            "date: 2026-05-11\n"
            "tags: [test]\n"
            # missing 'type'
            "---\n"
            "body\n"
        )
        result = vault_write_file(path="home/bad.md", content=content)
        assert result["written"] is False
        assert "type" in result["missing_fields"]
        assert not (tmp_vault_repo / "home" / "bad.md").exists()

    def test_custom_commit_message(self, tmp_vault_repo):
        result = vault_write_file(
            path="home/cm.md",
            content=VALID_FRONTMATTER,
            commit_message="custom: write home/cm.md",
        )
        assert result["pushed"] is True
        msg = _git(
            ["log", "-1", "--pretty=%s"], cwd=tmp_vault_repo,
        ).stdout.strip()
        assert msg == "custom: write home/cm.md"

    def test_idempotent_no_change(self, tmp_vault_repo):
        first = vault_write_file(path="home/i.md", content=VALID_FRONTMATTER)
        assert first["pushed"] is True
        head_before = _head(tmp_vault_repo)
        # same content again
        second = vault_write_file(path="home/i.md", content=VALID_FRONTMATTER)
        assert second["written"] is True
        assert second["no_changes"] is True
        assert second["pushed"] is False
        assert second["commit_sha"] is None
        assert _head(tmp_vault_repo) == head_before

    def test_rollback_on_push_failure_create(self, tmp_vault_repo):
        head_before = _head(tmp_vault_repo)
        _git(
            ["remote", "set-url", "origin", "/nonexistent/repo.git"],
            cwd=tmp_vault_repo,
        )
        result = vault_write_file(
            path="home/lost.md", content=VALID_FRONTMATTER,
        )
        assert result["written"] is True
        assert result["pushed"] is False
        assert result["rolled_back"] is True
        assert "git_error" in result and result["git_error"]
        # HEAD restored
        assert _head(tmp_vault_repo) == head_before
        # File gone
        assert not (tmp_vault_repo / "home" / "lost.md").exists()

    def test_rollback_on_push_failure_overwrite(self, tmp_vault_repo):
        seed = vault_write_file(
            path="home/o.md", content=VALID_FRONTMATTER,
        )
        assert seed["pushed"] is True
        head_after_seed = _head(tmp_vault_repo)
        original_content = (tmp_vault_repo / "home" / "o.md").read_text()

        _git(
            ["remote", "set-url", "origin", "/nonexistent/repo.git"],
            cwd=tmp_vault_repo,
        )
        new_content = VALID_FRONTMATTER + "added\n"
        result = vault_write_file(path="home/o.md", content=new_content)
        assert result["pushed"] is False
        assert result["rolled_back"] is True
        assert _head(tmp_vault_repo) == head_after_seed
        # original content restored by git reset --hard HEAD~1
        assert (tmp_vault_repo / "home" / "o.md").read_text() == original_content


# --------------------------- vault_delete_file -------------------------------


class TestDeleteFile:
    def test_delete_existing(self, tmp_vault_repo):
        vault_write_file(path="home/d.md", content=VALID_FRONTMATTER)
        result = vault_delete_file(path="home/d.md")
        assert result["deleted"] is True
        assert result["pushed"] is True
        assert result["commit_sha"]
        assert result["index_update_needed"] is True
        assert not (tmp_vault_repo / "home" / "d.md").exists()
        msg = _git(
            ["log", "-1", "--pretty=%s"], cwd=tmp_vault_repo,
        ).stdout.strip()
        assert msg == "vault_delete_file: home/d.md (via MCP)"

    def test_delete_nonexistent(self, tmp_vault_repo):
        result = vault_delete_file(path="home/never.md")
        assert result["deleted"] is False
        assert "error" in result

    def test_delete_rejected_path(self, tmp_vault_repo):
        result = vault_delete_file(path="../etc/passwd")
        assert result["deleted"] is False
        assert "error" in result


# --------------------------- concurrency -------------------------------------


class TestConcurrency:
    def test_two_writers_serialize(self, tmp_vault_repo):
        """Two threads writing different files must both succeed without git collision."""
        errors = []

        def writer(name: str, delay: float) -> None:
            try:
                content = VALID_FRONTMATTER.replace(
                    "# Test Note", f"# Note {name}",
                )
                if delay:
                    time.sleep(delay)
                result = vault_write_file(
                    path=f"home/{name}.md", content=content,
                )
                if not result.get("pushed"):
                    errors.append((name, result))
            except Exception as exc:  # noqa: BLE001
                errors.append((name, exc))

        t1 = threading.Thread(target=writer, args=("alpha", 0.0))
        t2 = threading.Thread(target=writer, args=("bravo", 0.05))
        t1.start()
        t2.start()
        t1.join(timeout=30)
        t2.join(timeout=30)

        assert not errors, f"writer errors: {errors}"
        assert (tmp_vault_repo / "home" / "alpha.md").is_file()
        assert (tmp_vault_repo / "home" / "bravo.md").is_file()
        # both commits made it
        log = _git(["log", "--oneline"], cwd=tmp_vault_repo).stdout
        assert "home/alpha.md" in log
        assert "home/bravo.md" in log
