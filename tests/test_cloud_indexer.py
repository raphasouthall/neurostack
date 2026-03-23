# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Unit tests for the CloudIndexer cloud indexing pipeline (GCP: Gemini API + GCS).

The CloudIndexer runs indexing via an in-process async pipeline for tenant
isolation. Tests mock cloud_index_vault to verify the correct arguments,
error handling, and GCS upload without invoking real indexing or GCP credentials.
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from neurostack.cloud.config import GEMINI_BASE_URL, CloudConfig
from neurostack.cloud.indexer import CloudIndexer


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def cloud_config() -> CloudConfig:
    """CloudConfig with Gemini API settings."""
    return CloudConfig(
        gcp_project="test-project",
        gcp_region="us-central1",
        gcs_bucket_name="test-bucket",
        gemini_api_key="test-gemini-key-123",
        gemini_embed_model="gemini-embedding-001",
        gemini_llm_model="gemini-2.5-flash",
        gemini_embed_dim=768,
    )


@pytest.fixture()
def mock_storage() -> MagicMock:
    """Mocked GCSStorageClient."""
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


# ---------------------------------------------------------------------------
# Test: construction
# ---------------------------------------------------------------------------


class TestCloudIndexerInit:
    """Tests for CloudIndexer construction."""

    def test_accepts_config_and_storage(self, cloud_config, mock_storage):
        """CloudIndexer.__init__ accepts CloudConfig and GCSStorageClient."""
        indexer = CloudIndexer(cloud_config, mock_storage)
        assert indexer._config is cloud_config
        assert indexer._storage is mock_storage


# ---------------------------------------------------------------------------
# Test: async pipeline invocation and isolation
# ---------------------------------------------------------------------------


class TestCloudIndexerAsyncPipeline:
    """Tests for async pipeline invocation with proper tenant isolation."""

    @patch("neurostack.cloud.indexer.cloud_index_vault")
    def test_passes_config_to_async_pipeline(self, mock_pipeline, indexer, cloud_config):
        """Async pipeline receives the CloudConfig."""
        mock_pipeline.return_value = {"status": "complete", "db_size": 1000, "note_count": 2}

        indexer.index_vault("user-1", SAMPLE_FILES)

        mock_pipeline.assert_called_once()
        call_args = mock_pipeline.call_args
        # Third positional arg is the config
        assert call_args[0][2] is cloud_config

    @patch("neurostack.cloud.indexer.cloud_index_vault")
    def test_passes_vault_files_to_async_pipeline(self, mock_pipeline, indexer):
        """Async pipeline receives the vault files dict."""
        mock_pipeline.return_value = {"status": "complete", "db_size": 1000, "note_count": 2}

        indexer.index_vault("user-1", SAMPLE_FILES)

        call_args = mock_pipeline.call_args
        assert call_args[0][0] == SAMPLE_FILES

    @patch("neurostack.cloud.indexer.cloud_index_vault")
    def test_passes_temp_db_path(self, mock_pipeline, indexer):
        """Async pipeline receives a temp db_path, not the host's DB."""
        mock_pipeline.return_value = {"status": "complete", "db_size": 1000, "note_count": 2}

        indexer.index_vault("user-1", SAMPLE_FILES)

        call_args = mock_pipeline.call_args
        db_path = call_args[0][1]
        assert isinstance(db_path, Path)
        assert str(db_path).endswith("neurostack.db")
        # Must be in a temp directory, not the user's home
        assert str(db_path) != str(Path.home() / ".local" / "share" / "neurostack" / "neurostack.db")

    @patch("neurostack.cloud.indexer.cloud_index_vault")
    def test_parent_env_not_mutated(self, mock_pipeline, indexer):
        """Parent process env vars are never modified."""
        import os

        original_embed_key = os.environ.get("NEUROSTACK_EMBED_API_KEY")
        original_db_dir = os.environ.get("NEUROSTACK_DB_DIR")

        mock_pipeline.return_value = {"status": "complete", "db_size": 1000, "note_count": 2}
        indexer.index_vault("user-1", SAMPLE_FILES)

        assert os.environ.get("NEUROSTACK_EMBED_API_KEY") == original_embed_key
        assert os.environ.get("NEUROSTACK_DB_DIR") == original_db_dir


# ---------------------------------------------------------------------------
# Test: uploads DB to GCS after indexing
# ---------------------------------------------------------------------------


class TestCloudIndexerUpload:
    """Tests for GCS upload after indexing."""

    @patch("neurostack.cloud.indexer.cloud_index_vault")
    def test_uploads_db_to_gcs_on_success(self, mock_pipeline, indexer, mock_storage, tmp_path):
        """After indexing, uploads the resulting DB to GCS via storage.upload_db."""
        # Create a fake DB file at the path the pipeline would use
        def fake_pipeline(vault_files, db_path, config):
            db_path.parent.mkdir(parents=True, exist_ok=True)
            db_path.write_bytes(b"SQLite format 3\x00" + b"\x00" * 100)
            return {"status": "complete", "db_size": 116, "note_count": 2}

        mock_pipeline.side_effect = fake_pipeline

        result = indexer.index_vault("user-1", SAMPLE_FILES)

        assert result["status"] == "complete"
        mock_storage.upload_db.assert_called_once()
        call_args = mock_storage.upload_db.call_args
        assert call_args[0][0] == "user-1"


# ---------------------------------------------------------------------------
# Test: return value and error handling
# ---------------------------------------------------------------------------


class TestCloudIndexerResult:
    """Tests for index_vault return dict."""

    @patch("neurostack.cloud.indexer.cloud_index_vault")
    def test_returns_status_db_size_note_count(self, mock_pipeline, indexer):
        """index_vault returns dict with status, db_size, and note_count."""
        def fake_pipeline(vault_files, db_path, config):
            db_path.parent.mkdir(parents=True, exist_ok=True)
            db_path.write_bytes(b"SQLite format 3\x00" + b"\x00" * 100)
            return {"status": "complete", "db_size": 116, "note_count": 2}

        mock_pipeline.side_effect = fake_pipeline

        result = indexer.index_vault("user-1", SAMPLE_FILES)

        assert result["status"] == "complete"
        assert result["db_size"] == 116
        assert result["note_count"] == 2

    @patch("neurostack.cloud.indexer.cloud_index_vault")
    def test_returns_failed_on_pipeline_exception(self, mock_pipeline, indexer):
        """index_vault returns status=failed when pipeline raises."""
        mock_pipeline.side_effect = RuntimeError("Gemini API unreachable")

        result = indexer.index_vault("user-1", SAMPLE_FILES)

        assert result["status"] == "failed"
        assert "Gemini API unreachable" in result["error"]

    @patch("neurostack.cloud.indexer.cloud_index_vault")
    def test_returns_failed_on_no_db(self, mock_pipeline, indexer):
        """index_vault returns failed when pipeline succeeds but no DB file."""
        mock_pipeline.return_value = {"status": "complete", "db_size": 0, "note_count": 2}

        result = indexer.index_vault("user-1", SAMPLE_FILES)

        assert result["status"] == "failed"
        assert "No database produced" in result["error"]

    @patch("neurostack.cloud.indexer.cloud_index_vault")
    def test_does_not_upload_on_failure(self, mock_pipeline, indexer, mock_storage):
        """Storage.upload_db is NOT called when indexing fails."""
        mock_pipeline.side_effect = RuntimeError("Failed")

        indexer.index_vault("user-1", SAMPLE_FILES)

        mock_storage.upload_db.assert_not_called()
