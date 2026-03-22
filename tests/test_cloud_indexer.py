# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Unit tests for the CloudIndexer cloud indexing pipeline.

The CloudIndexer runs indexing in a subprocess for tenant isolation.
Tests mock subprocess.run to verify the correct env vars, arguments,
and error handling without invoking real indexing.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from neurostack.cloud.config import CloudConfig
from neurostack.cloud.indexer import FIREWORKS_BASE_URL, CloudIndexer


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def cloud_config() -> CloudConfig:
    """CloudConfig with Fireworks AI credentials."""
    return CloudConfig(
        fireworks_api_key="fw-test-key-123",
        fireworks_embed_model="nomic-ai/nomic-embed-text-v1.5",
        fireworks_llm_model="accounts/fireworks/models/qwen2p5-7b-instruct",
        r2_account_id="testaccount",
        r2_access_key_id="test-key-id",
        r2_secret_access_key="test-secret",
        r2_bucket_name="test-bucket",
    )


@pytest.fixture()
def mock_storage() -> MagicMock:
    """Mocked R2StorageClient."""
    storage = MagicMock()
    storage.upload_db.return_value = "vaults/user-1/neurostack.db"
    return storage


@pytest.fixture()
def indexer(cloud_config, mock_storage) -> CloudIndexer:
    """CloudIndexer with mocked storage."""
    return CloudIndexer(cloud_config, mock_storage)


SAMPLE_FILES = {
    "note1.md": b"# Hello\n\nSome content here.",
    "subfolder/note2.md": b"# World\n\nMore content.",
}


def _make_successful_run(tmp_path_factory=None):
    """Create a mock subprocess.run that simulates successful indexing.

    Creates a fake DB file in the temp directory that the indexer expects.
    """

    def _run(args, *, env=None, capture_output=False, text=False, timeout=None):
        # The vault_root is passed as the last arg
        vault_root = Path(args[-1])
        # DB dir is sibling to vault dir
        db_dir = vault_root.parent / "db"
        db_dir.mkdir(parents=True, exist_ok=True)
        db_path = db_dir / "neurostack.db"
        db_path.write_bytes(b"SQLite format 3\x00" + b"\x00" * 100)

        result = MagicMock()
        result.returncode = 0
        result.stdout = json.dumps({"db_exists": True, "db_size": db_path.stat().st_size})
        result.stderr = ""
        return result

    return _run


def _make_failed_run(stderr="Error: something broke"):
    """Create a mock subprocess.run that simulates failed indexing."""

    def _run(args, *, env=None, capture_output=False, text=False, timeout=None):
        result = MagicMock()
        result.returncode = 1
        result.stdout = ""
        result.stderr = stderr
        return result

    return _run


# ---------------------------------------------------------------------------
# Test: construction
# ---------------------------------------------------------------------------


class TestCloudIndexerInit:
    """Tests for CloudIndexer construction."""

    def test_accepts_config_and_storage(self, cloud_config, mock_storage):
        """CloudIndexer.__init__ accepts CloudConfig and R2StorageClient."""
        indexer = CloudIndexer(cloud_config, mock_storage)
        assert indexer._config is cloud_config
        assert indexer._storage is mock_storage


# ---------------------------------------------------------------------------
# Test: subprocess env vars and isolation
# ---------------------------------------------------------------------------


class TestCloudIndexerSubprocess:
    """Tests for subprocess-based indexing with proper tenant isolation."""

    @patch("neurostack.cloud.indexer.subprocess.run")
    def test_passes_fireworks_env_vars_to_subprocess(self, mock_run, indexer):
        """Subprocess receives Fireworks AI URLs and API keys in env."""
        mock_run.side_effect = _make_successful_run()
        indexer.index_vault("user-1", SAMPLE_FILES)

        mock_run.assert_called_once()
        env = mock_run.call_args.kwargs["env"]
        assert env["NEUROSTACK_EMBED_URL"] == FIREWORKS_BASE_URL
        assert env["NEUROSTACK_LLM_URL"] == FIREWORKS_BASE_URL
        assert env["NEUROSTACK_EMBED_API_KEY"] == "fw-test-key-123"
        assert env["NEUROSTACK_LLM_API_KEY"] == "fw-test-key-123"
        assert env["NEUROSTACK_EMBED_MODEL"] == "nomic-ai/nomic-embed-text-v1.5"
        assert env["NEUROSTACK_LLM_MODEL"] == "accounts/fireworks/models/qwen2p5-7b-instruct"

    @patch("neurostack.cloud.indexer.subprocess.run")
    def test_passes_isolated_db_dir_to_subprocess(self, mock_run, indexer):
        """Subprocess gets a unique temp DB dir, not the host's DB."""
        mock_run.side_effect = _make_successful_run()
        indexer.index_vault("user-1", SAMPLE_FILES)

        env = mock_run.call_args.kwargs["env"]
        db_dir = env["NEUROSTACK_DB_DIR"]
        # Must be in a temp directory, not the user's home
        assert "ns-cloud-user-1-" in db_dir or "/tmp" in db_dir
        assert db_dir != str(Path.home() / ".local" / "share" / "neurostack")

    @patch("neurostack.cloud.indexer.subprocess.run")
    def test_passes_isolated_vault_root_to_subprocess(self, mock_run, indexer):
        """Subprocess gets a temp vault dir, not the host's vault."""
        mock_run.side_effect = _make_successful_run()
        indexer.index_vault("user-1", SAMPLE_FILES)

        env = mock_run.call_args.kwargs["env"]
        vault_root = env["NEUROSTACK_VAULT_ROOT"]
        assert "ns-cloud-user-1-" in vault_root or "/tmp" in vault_root
        assert vault_root != str(Path.home() / "brain")

    @patch("neurostack.cloud.indexer.subprocess.run")
    def test_parent_env_not_mutated(self, mock_run, indexer):
        """Parent process env vars are never modified."""
        import os

        original_embed_key = os.environ.get("NEUROSTACK_EMBED_API_KEY")
        original_db_dir = os.environ.get("NEUROSTACK_DB_DIR")

        mock_run.side_effect = _make_successful_run()
        indexer.index_vault("user-1", SAMPLE_FILES)

        assert os.environ.get("NEUROSTACK_EMBED_API_KEY") == original_embed_key
        assert os.environ.get("NEUROSTACK_DB_DIR") == original_db_dir

    @patch("neurostack.cloud.indexer.subprocess.run")
    def test_subprocess_has_timeout(self, mock_run, indexer):
        """Subprocess has a timeout to prevent runaway indexing."""
        mock_run.side_effect = _make_successful_run()
        indexer.index_vault("user-1", SAMPLE_FILES)

        assert mock_run.call_args.kwargs["timeout"] == 600

    def test_fireworks_base_url_does_not_include_v1(self):
        """Base URL must NOT include /v1 -- embedder/summarizer append it."""
        assert FIREWORKS_BASE_URL == "https://api.fireworks.ai/inference"
        assert not FIREWORKS_BASE_URL.endswith("/v1")


# ---------------------------------------------------------------------------
# Test: file writing to temp directory
# ---------------------------------------------------------------------------


class TestCloudIndexerFileWriting:
    """Tests for writing vault files to isolated temp directory."""

    @patch("neurostack.cloud.indexer.subprocess.run")
    def test_writes_files_to_temp_vault_dir(self, mock_run, indexer):
        """Vault files are written to a temp directory before subprocess starts."""
        written_files = {}

        def _check_files(args, *, env=None, **kw):
            vault_root = Path(args[-1])
            for f in vault_root.rglob("*.md"):
                rel = str(f.relative_to(vault_root))
                written_files[rel] = f.read_bytes()
            result = MagicMock()
            result.returncode = 1
            result.stdout = ""
            result.stderr = "check only"
            return result

        mock_run.side_effect = _check_files
        indexer.index_vault("user-1", SAMPLE_FILES)

        assert "note1.md" in written_files
        assert "subfolder/note2.md" in written_files
        assert written_files["note1.md"] == b"# Hello\n\nSome content here."

    @patch("neurostack.cloud.indexer.subprocess.run")
    def test_creates_subdirectories_for_nested_files(self, mock_run, indexer):
        """Subdirectories are created for nested vault files."""
        checked = {}

        def _check(args, *, env=None, **kw):
            vault_root = Path(args[-1])
            checked["subdir_exists"] = (vault_root / "subfolder" / "note2.md").exists()
            result = MagicMock()
            result.returncode = 1
            result.stdout = ""
            result.stderr = ""
            return result

        mock_run.side_effect = _check
        indexer.index_vault("user-1", SAMPLE_FILES)

        assert checked["subdir_exists"] is True


# ---------------------------------------------------------------------------
# Test: uploads DB to R2 after indexing
# ---------------------------------------------------------------------------


class TestCloudIndexerUpload:
    """Tests for R2 upload after indexing."""

    @patch("neurostack.cloud.indexer.subprocess.run")
    def test_uploads_db_to_r2_on_success(self, mock_run, indexer, mock_storage):
        """After indexing, uploads the resulting DB to R2 via storage.upload_db."""
        mock_run.side_effect = _make_successful_run()

        result = indexer.index_vault("user-1", SAMPLE_FILES)

        assert result["status"] == "complete"
        mock_storage.upload_db.assert_called_once()
        call_args = mock_storage.upload_db.call_args
        assert call_args[0][0] == "user-1"
        assert str(call_args[0][1]).endswith("neurostack.db")


# ---------------------------------------------------------------------------
# Test: return value and error handling
# ---------------------------------------------------------------------------


class TestCloudIndexerResult:
    """Tests for index_vault return dict."""

    @patch("neurostack.cloud.indexer.subprocess.run")
    def test_returns_status_db_size_note_count(self, mock_run, indexer):
        """index_vault returns dict with status, db_size, and note_count."""
        mock_run.side_effect = _make_successful_run()

        result = indexer.index_vault("user-1", SAMPLE_FILES)

        assert result["status"] == "complete"
        assert result["db_size"] > 0
        assert result["note_count"] == 2

    @patch("neurostack.cloud.indexer.subprocess.run")
    def test_returns_failed_on_subprocess_error(self, mock_run, indexer):
        """index_vault returns status=failed when subprocess exits non-zero."""
        mock_run.side_effect = _make_failed_run("Fireworks AI unreachable")

        result = indexer.index_vault("user-1", SAMPLE_FILES)

        assert result["status"] == "failed"
        assert "Fireworks AI unreachable" in result["error"]

    @patch("neurostack.cloud.indexer.subprocess.run")
    def test_returns_failed_on_timeout(self, mock_run, indexer):
        """index_vault returns status=failed on subprocess timeout."""
        import subprocess

        mock_run.side_effect = subprocess.TimeoutExpired(cmd="python", timeout=600)

        result = indexer.index_vault("user-1", SAMPLE_FILES)

        assert result["status"] == "failed"
        assert "timed out" in result["error"]

    @patch("neurostack.cloud.indexer.subprocess.run")
    def test_returns_failed_on_no_db(self, mock_run, indexer):
        """index_vault returns failed when subprocess succeeds but no DB."""

        def _no_db(args, *, env=None, **kw):
            result = MagicMock()
            result.returncode = 0
            result.stdout = json.dumps({"db_exists": False, "db_size": 0})
            result.stderr = ""
            return result

        mock_run.side_effect = _no_db

        result = indexer.index_vault("user-1", SAMPLE_FILES)

        assert result["status"] == "failed"
        assert "No database produced" in result["error"]

    @patch("neurostack.cloud.indexer.subprocess.run")
    def test_does_not_upload_on_failure(self, mock_run, indexer, mock_storage):
        """Storage.upload_db is NOT called when indexing fails."""
        mock_run.side_effect = _make_failed_run()

        indexer.index_vault("user-1", SAMPLE_FILES)

        mock_storage.upload_db.assert_not_called()
