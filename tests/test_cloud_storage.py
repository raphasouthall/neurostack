# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Unit tests for cloud storage client and config."""

import os
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from neurostack.cloud.config import CloudConfig, load_cloud_config
from neurostack.cloud.storage import R2StorageClient


# ---------------------------------------------------------------------------
# CloudConfig tests
# ---------------------------------------------------------------------------


class TestCloudConfig:
    """Tests for CloudConfig dataclass and loader."""

    def test_loads_r2_settings_from_env(self):
        """CloudConfig loads R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME."""
        env = {
            "NEUROSTACK_CLOUD_R2_ACCOUNT_ID": "abc123",
            "NEUROSTACK_CLOUD_R2_ACCESS_KEY_ID": "key-id",
            "NEUROSTACK_CLOUD_R2_SECRET_ACCESS_KEY": "secret-key",
            "NEUROSTACK_CLOUD_R2_BUCKET_NAME": "my-bucket",
        }
        with patch.dict(os.environ, env, clear=False):
            cfg = load_cloud_config()

        assert cfg.r2_account_id == "abc123"
        assert cfg.r2_access_key_id == "key-id"
        assert cfg.r2_secret_access_key == "secret-key"
        assert cfg.r2_bucket_name == "my-bucket"

    def test_loads_fireworks_settings_from_env(self):
        """CloudConfig loads FIREWORKS_API_KEY, FIREWORKS_EMBED_MODEL, FIREWORKS_LLM_MODEL."""
        env = {
            "NEUROSTACK_CLOUD_FIREWORKS_API_KEY": "fw-key-123",
            "NEUROSTACK_CLOUD_FIREWORKS_EMBED_MODEL": "custom-embed",
            "NEUROSTACK_CLOUD_FIREWORKS_LLM_MODEL": "custom-llm",
        }
        with patch.dict(os.environ, env, clear=False):
            cfg = load_cloud_config()

        assert cfg.fireworks_api_key == "fw-key-123"
        assert cfg.fireworks_embed_model == "custom-embed"
        assert cfg.fireworks_llm_model == "custom-llm"

    def test_r2_endpoint_url_property(self):
        """CloudConfig.r2_endpoint_url returns https://{account_id}.r2.cloudflarestorage.com."""
        cfg = CloudConfig(r2_account_id="myaccount")
        assert cfg.r2_endpoint_url == "https://myaccount.r2.cloudflarestorage.com"

    def test_defaults(self):
        """CloudConfig has sensible defaults."""
        cfg = CloudConfig()
        assert cfg.r2_bucket_name == "neurostack-prod"
        assert cfg.fireworks_embed_model == "nomic-ai/nomic-embed-text-v1.5"
        assert cfg.fireworks_llm_model == "accounts/fireworks/models/qwen2p5-7b-instruct"
        assert cfg.r2_account_id == ""
        assert cfg.fireworks_api_key == ""


# ---------------------------------------------------------------------------
# R2StorageClient tests
# ---------------------------------------------------------------------------


class TestR2StorageClient:
    """Tests for R2StorageClient with mocked boto3."""

    @pytest.fixture()
    def config(self):
        return CloudConfig(
            r2_account_id="testaccount",
            r2_access_key_id="test-key-id",
            r2_secret_access_key="test-secret",
            r2_bucket_name="test-bucket",
        )

    @pytest.fixture()
    def mock_s3(self):
        with patch("neurostack.cloud.storage.boto3") as mock_boto3:
            mock_client = MagicMock()
            mock_boto3.client.return_value = mock_client
            yield mock_client, mock_boto3

    @pytest.fixture()
    def client(self, config, mock_s3):
        mock_client, _ = mock_s3
        return R2StorageClient(config)

    def test_creates_s3_client_with_r2_endpoint(self, config, mock_s3):
        """R2StorageClient creates boto3 S3 client with R2 endpoint and s3v4 signing."""
        mock_client, mock_boto3 = mock_s3
        storage = R2StorageClient(config)

        mock_boto3.client.assert_called_once()
        call_kwargs = mock_boto3.client.call_args
        assert call_kwargs[0][0] == "s3"
        assert call_kwargs[1]["endpoint_url"] == "https://testaccount.r2.cloudflarestorage.com"
        assert call_kwargs[1]["aws_access_key_id"] == "test-key-id"
        assert call_kwargs[1]["aws_secret_access_key"] == "test-secret"

    def test_upload_db(self, client, mock_s3):
        """upload_db calls s3.upload_file with key 'vaults/{user_id}/neurostack.db'."""
        mock_client, _ = mock_s3
        db_path = Path("/tmp/neurostack.db")

        key = client.upload_db("user-42", db_path)

        assert key == "vaults/user-42/neurostack.db"
        mock_client.upload_file.assert_called_once_with(
            str(db_path), "test-bucket", "vaults/user-42/neurostack.db"
        )

    def test_generate_download_url(self, client, mock_s3):
        """generate_download_url returns presigned URL with 1-hour default expiry."""
        mock_client, _ = mock_s3
        mock_client.generate_presigned_url.return_value = "https://presigned.example.com/db"

        url = client.generate_download_url("user-42")

        assert url == "https://presigned.example.com/db"
        mock_client.generate_presigned_url.assert_called_once_with(
            "get_object",
            Params={"Bucket": "test-bucket", "Key": "vaults/user-42/neurostack.db"},
            ExpiresIn=3600,
        )

    def test_generate_download_url_custom_expiry(self, client, mock_s3):
        """generate_download_url respects custom expires_in."""
        mock_client, _ = mock_s3
        mock_client.generate_presigned_url.return_value = "https://example.com"

        client.generate_download_url("user-42", expires_in=7200)

        mock_client.generate_presigned_url.assert_called_once_with(
            "get_object",
            Params={"Bucket": "test-bucket", "Key": "vaults/user-42/neurostack.db"},
            ExpiresIn=7200,
        )

    def test_upload_vault_files(self, client, mock_s3):
        """upload_vault_files uploads to 'uploads/{user_id}/{filename}'."""
        mock_client, _ = mock_s3
        files = {"note1.md": b"# Hello", "note2.md": b"# World"}

        keys = client.upload_vault_files("user-42", files)

        assert set(keys) == {"uploads/user-42/note1.md", "uploads/user-42/note2.md"}
        assert mock_client.put_object.call_count == 2

    def test_delete_user_data(self, client, mock_s3):
        """delete_user_data deletes all objects under vaults/{user_id}/ and uploads/{user_id}/."""
        mock_client, _ = mock_s3

        # Mock list_objects_v2 to return objects for both prefixes
        def list_side_effect(**kwargs):
            prefix = kwargs.get("Prefix", "")
            if prefix == "vaults/user-42/":
                return {
                    "Contents": [{"Key": "vaults/user-42/neurostack.db"}],
                    "IsTruncated": False,
                }
            elif prefix == "uploads/user-42/":
                return {
                    "Contents": [
                        {"Key": "uploads/user-42/note1.md"},
                        {"Key": "uploads/user-42/note2.md"},
                    ],
                    "IsTruncated": False,
                }
            return {"IsTruncated": False}

        mock_client.list_objects_v2.side_effect = list_side_effect

        count = client.delete_user_data("user-42")

        assert count == 3
        assert mock_client.delete_objects.call_count == 2

    def test_download_vault_files(self, client, mock_s3):
        """download_vault_files retrieves all files under uploads/{user_id}/."""
        mock_client, _ = mock_s3
        mock_client.list_objects_v2.return_value = {
            "Contents": [
                {"Key": "uploads/user-42/note1.md"},
                {"Key": "uploads/user-42/note2.md"},
            ],
            "IsTruncated": False,
        }

        body1 = MagicMock()
        body1.read.return_value = b"# Hello"
        body2 = MagicMock()
        body2.read.return_value = b"# World"

        mock_client.get_object.side_effect = [
            {"Body": body1},
            {"Body": body2},
        ]

        files = client.download_vault_files("user-42")

        assert files == {"note1.md": b"# Hello", "note2.md": b"# World"}
        assert mock_client.get_object.call_count == 2
