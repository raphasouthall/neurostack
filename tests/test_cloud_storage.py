# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Unit tests for cloud storage client and config (GCP: Cloud Storage + Gemini API)."""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from neurostack.cloud.config import GEMINI_BASE_URL, CloudConfig, load_cloud_config
from neurostack.cloud.storage import GCSStorageClient, _validate_user_id


# ---------------------------------------------------------------------------
# CloudConfig tests
# ---------------------------------------------------------------------------


class TestCloudConfig:
    """Tests for CloudConfig dataclass and loader."""

    def test_loads_gcp_settings_from_env(self):
        """CloudConfig loads GCP_PROJECT, GCP_REGION, GCS_BUCKET_NAME."""
        env = {
            "NEUROSTACK_CLOUD_GCP_PROJECT": "my-gcp-project",
            "NEUROSTACK_CLOUD_GCP_REGION": "europe-west1",
            "NEUROSTACK_CLOUD_GCS_BUCKET_NAME": "my-bucket",
        }
        with patch.dict(os.environ, env, clear=False):
            cfg = load_cloud_config()

        assert cfg.gcp_project == "my-gcp-project"
        assert cfg.gcp_region == "europe-west1"
        assert cfg.gcs_bucket_name == "my-bucket"

    def test_loads_gemini_settings_from_env(self):
        """CloudConfig loads GEMINI_API_KEY, GEMINI_EMBED_MODEL, and GEMINI_LLM_MODEL."""
        env = {
            "NEUROSTACK_CLOUD_GEMINI_API_KEY": "test-api-key-xyz",
            "NEUROSTACK_CLOUD_GEMINI_EMBED_MODEL": "custom-embed-model",
            "NEUROSTACK_CLOUD_GEMINI_LLM_MODEL": "custom-llm-model",
        }
        with patch.dict(os.environ, env, clear=False):
            cfg = load_cloud_config()

        assert cfg.gemini_api_key == "test-api-key-xyz"
        assert cfg.gemini_embed_model == "custom-embed-model"
        assert cfg.gemini_llm_model == "custom-llm-model"

    def test_loads_gemini_embed_dim_from_env(self):
        """CloudConfig loads GEMINI_EMBED_DIM as an integer."""
        env = {
            "NEUROSTACK_CLOUD_GEMINI_EMBED_DIM": "1024",
        }
        with patch.dict(os.environ, env, clear=False):
            cfg = load_cloud_config()

        assert cfg.gemini_embed_dim == 1024

    def test_gemini_base_url_constant(self):
        """GEMINI_BASE_URL constant equals the Gemini API OpenAI-compatible URL."""
        assert GEMINI_BASE_URL == "https://generativelanguage.googleapis.com/v1beta/openai"

    def test_defaults(self):
        """CloudConfig has sensible defaults."""
        cfg = CloudConfig()
        assert cfg.gcs_bucket_name == "neurostack-prod"
        assert cfg.gemini_embed_model == "gemini-embedding-001"
        assert cfg.gemini_llm_model == "gemini-2.5-flash"
        assert cfg.gemini_embed_dim == 768
        assert cfg.gemini_api_key == ""
        assert cfg.gcp_project == ""
        assert cfg.gcp_region == "us-central1"
        assert cfg.cloud_api_url == ""
        assert cfg.cloud_api_key == ""


# ---------------------------------------------------------------------------
# GCSStorageClient tests
# ---------------------------------------------------------------------------


class TestGCSStorageClient:
    """Tests for GCSStorageClient with mocked google.cloud.storage."""

    @pytest.fixture()
    def config(self):
        return CloudConfig(
            gcp_project="test-project",
            gcp_region="us-central1",
            gcs_bucket_name="test-bucket",
        )

    @pytest.fixture()
    def mock_gcs(self):
        with patch("neurostack.cloud.storage.gcs") as mock_gcs_module:
            mock_client_instance = MagicMock()
            mock_bucket = MagicMock()
            mock_gcs_module.Client.return_value = mock_client_instance
            mock_client_instance.bucket.return_value = mock_bucket
            yield mock_client_instance, mock_bucket, mock_gcs_module

    @pytest.fixture()
    def storage(self, config, mock_gcs):
        return GCSStorageClient(config)

    def test_creates_gcs_client_with_project(self, config, mock_gcs):
        """GCSStorageClient creates google.cloud.storage.Client with project."""
        _, _, mock_gcs_module = mock_gcs
        GCSStorageClient(config)

        mock_gcs_module.Client.assert_called_once_with(project="test-project")

    def test_selects_correct_bucket(self, config, mock_gcs):
        """GCSStorageClient selects the configured bucket."""
        mock_client_instance, _, _ = mock_gcs
        GCSStorageClient(config)

        mock_client_instance.bucket.assert_called_once_with("test-bucket")

    def test_upload_db(self, storage, mock_gcs):
        """upload_db calls blob.upload_from_filename with correct path."""
        _, mock_bucket, _ = mock_gcs
        mock_blob = MagicMock()
        mock_bucket.blob.return_value = mock_blob
        db_path = Path("/tmp/neurostack.db")

        key = storage.upload_db("user-42", db_path)

        assert key == "vaults/user-42/neurostack.db"
        mock_bucket.blob.assert_called_once_with("vaults/user-42/neurostack.db")
        mock_blob.upload_from_filename.assert_called_once_with(str(db_path))

    @patch("google.auth.transport.requests.Request")
    @patch("google.auth.default")
    def test_generate_download_url(self, mock_auth_default, mock_request, storage, mock_gcs):
        """generate_download_url calls blob.generate_signed_url with v4, IAM signing."""
        import datetime

        mock_creds = MagicMock()
        mock_creds.service_account_email = "sa@test.iam.gserviceaccount.com"
        mock_creds.token = "fake-token"
        mock_auth_default.return_value = (mock_creds, "test-project")

        _, mock_bucket, _ = mock_gcs
        mock_blob = MagicMock()
        mock_blob.generate_signed_url.return_value = "https://storage.googleapis.com/signed-url"
        mock_bucket.blob.return_value = mock_blob

        url = storage.generate_download_url("user-42")

        assert url == "https://storage.googleapis.com/signed-url"
        mock_bucket.blob.assert_called_once_with("vaults/user-42/neurostack.db")
        mock_blob.generate_signed_url.assert_called_once_with(
            version="v4",
            expiration=datetime.timedelta(seconds=3600),
            method="GET",
            service_account_email="sa@test.iam.gserviceaccount.com",
            access_token="fake-token",
        )

    @patch("google.auth.transport.requests.Request")
    @patch("google.auth.default")
    def test_generate_download_url_custom_expiry(self, mock_auth_default, mock_request, storage, mock_gcs):
        """generate_download_url respects custom expires_in."""
        import datetime

        mock_creds = MagicMock()
        mock_creds.service_account_email = "sa@test.iam.gserviceaccount.com"
        mock_creds.token = "fake-token"
        mock_auth_default.return_value = (mock_creds, "test-project")

        _, mock_bucket, _ = mock_gcs
        mock_blob = MagicMock()
        mock_blob.generate_signed_url.return_value = "https://example.com"
        mock_bucket.blob.return_value = mock_blob

        storage.generate_download_url("user-42", expires_in=7200)

        mock_blob.generate_signed_url.assert_called_once_with(
            version="v4",
            expiration=datetime.timedelta(seconds=7200),
            method="GET",
            service_account_email="sa@test.iam.gserviceaccount.com",
            access_token="fake-token",
        )

    def test_upload_vault_files(self, storage, mock_gcs):
        """upload_vault_files calls blob.upload_from_string for each file."""
        _, mock_bucket, _ = mock_gcs
        mock_blob = MagicMock()
        mock_bucket.blob.return_value = mock_blob
        files = {"note1.md": b"# Hello", "note2.md": b"# World"}

        keys = storage.upload_vault_files("user-42", files)

        assert set(keys) == {"uploads/user-42/note1.md", "uploads/user-42/note2.md"}
        assert mock_blob.upload_from_string.call_count == 2

    def test_download_vault_files(self, storage, mock_gcs):
        """download_vault_files lists blobs and downloads each one."""
        mock_client_instance, _, _ = mock_gcs

        blob1 = MagicMock()
        blob1.name = "uploads/user-42/note1.md"
        blob1.download_as_bytes.return_value = b"# Hello"

        blob2 = MagicMock()
        blob2.name = "uploads/user-42/note2.md"
        blob2.download_as_bytes.return_value = b"# World"

        mock_client_instance.list_blobs.return_value = [blob1, blob2]

        files = storage.download_vault_files("user-42")

        assert files == {"note1.md": b"# Hello", "note2.md": b"# World"}
        mock_client_instance.list_blobs.assert_called_once_with(
            "test-bucket", prefix="uploads/user-42/"
        )

    def test_delete_user_data(self, storage, mock_gcs):
        """delete_user_data deletes blobs under both vaults/ and uploads/ prefixes."""
        mock_client_instance, _, _ = mock_gcs

        vault_blob = MagicMock()
        upload_blob1 = MagicMock()
        upload_blob2 = MagicMock()

        def list_blobs_side_effect(bucket_name, prefix=""):
            if prefix == "vaults/user-42/":
                return [vault_blob]
            elif prefix == "uploads/user-42/":
                return [upload_blob1, upload_blob2]
            return []

        mock_client_instance.list_blobs.side_effect = list_blobs_side_effect

        count = storage.delete_user_data("user-42")

        assert count == 3
        vault_blob.delete.assert_called_once()
        upload_blob1.delete.assert_called_once()
        upload_blob2.delete.assert_called_once()


# ---------------------------------------------------------------------------
# _validate_user_id tests
# ---------------------------------------------------------------------------


class TestValidateUserId:
    """Tests for _validate_user_id preventing prefix traversal."""

    def test_rejects_traversal_user_id(self):
        with pytest.raises(ValueError, match="Invalid user_id"):
            _validate_user_id("../other-user")

    def test_rejects_slash_in_user_id(self):
        with pytest.raises(ValueError, match="Invalid user_id"):
            _validate_user_id("user/evil")

    def test_rejects_empty_user_id(self):
        with pytest.raises(ValueError, match="Invalid user_id"):
            _validate_user_id("")

    def test_accepts_valid_user_id(self):
        assert _validate_user_id("user-1") == "user-1"
        assert _validate_user_id("user_2") == "user_2"
        assert _validate_user_id("abc123") == "abc123"
