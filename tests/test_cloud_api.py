# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Tests for the NeuroStack Cloud API gateway, auth module, and wired endpoints."""

import json
import os
import time
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Test API keys fixture
# ---------------------------------------------------------------------------

TEST_API_KEYS = {
    "sk-valid-key-123": {"user_id": "user-1", "tier": "free"},
    "sk-pro-key-456": {"user_id": "user-2", "tier": "pro"},
}

TEST_API_KEYS_JSON = json.dumps(TEST_API_KEYS)


@pytest.fixture(autouse=True)
def _reset_api_keys_cache():
    """Reset the cached API keys between tests."""
    from neurostack.cloud import auth

    auth._API_KEYS = None
    yield
    auth._API_KEYS = None


@pytest.fixture
def mock_storage():
    """Mocked GCSStorageClient."""
    storage = MagicMock()
    storage.upload_vault_files.return_value = ["uploads/user-1/test.md"]
    storage.generate_download_url.return_value = "https://storage.googleapis.com/signed-url/neurostack.db"
    return storage


@pytest.fixture
def mock_indexer():
    """Mocked CloudIndexer."""
    indexer = MagicMock()
    indexer.index_vault.return_value = {
        "status": "complete",
        "db_size": 4096,
        "note_count": 1,
    }
    return indexer


@pytest.fixture
def client(mock_storage, mock_indexer):
    """FastAPI TestClient with mocked cloud services."""
    with patch.dict(os.environ, {"NEUROSTACK_CLOUD_API_KEYS": TEST_API_KEYS_JSON}):
        # Patch GCSStorageClient and CloudIndexer to avoid real cloud calls
        with (
            patch("neurostack.cloud.api.GCSStorageClient", return_value=mock_storage),
            patch("neurostack.cloud.api.CloudIndexer", return_value=mock_indexer),
        ):
            from neurostack.cloud.api import app

            with TestClient(app) as tc:
                yield tc


def auth_header(key: str = "sk-valid-key-123") -> dict[str, str]:
    """Helper to build Authorization header."""
    return {"Authorization": f"Bearer {key}"}


# ---------------------------------------------------------------------------
# Auth module tests
# ---------------------------------------------------------------------------


class TestAuth:
    """Tests for require_api_key dependency."""

    def test_missing_auth_header_returns_401(self, client):
        resp = client.post("/v1/vault/upload", files=[("files", ("test.md", b"# Test", "text/markdown"))])
        assert resp.status_code == 401

    def test_invalid_bearer_token_returns_401(self, client):
        resp = client.post(
            "/v1/vault/upload",
            headers=auth_header("invalid-key"),
            files=[("files", ("test.md", b"# Test", "text/markdown"))],
        )
        assert resp.status_code == 401

    def test_valid_key_returns_user_dict(self, client):
        """A valid key should allow the request through and return user info."""
        resp = client.post(
            "/v1/vault/upload",
            headers=auth_header("sk-valid-key-123"),
            files=[("files", ("test.md", b"# Test", "text/markdown"))],
        )
        assert resp.status_code == 202
        data = resp.json()
        assert "job_id" in data

    def test_api_keys_loaded_from_env_var(self):
        """API keys are loaded from NEUROSTACK_CLOUD_API_KEYS env var."""
        with patch.dict(
            os.environ,
            {"NEUROSTACK_CLOUD_API_KEYS": json.dumps({"sk-test": {"user_id": "u1", "tier": "free"}})},
        ):
            from neurostack.cloud.auth import _load_api_keys

            keys = _load_api_keys()
            assert "sk-test" in keys
            assert keys["sk-test"]["user_id"] == "u1"
            assert keys["sk-test"]["tier"] == "free"

    def test_malformed_auth_header_returns_401(self, client):
        """Auth header without 'Bearer ' prefix should fail."""
        resp = client.post(
            "/v1/vault/upload",
            headers={"Authorization": "Token sk-valid-key-123"},
            files=[("files", ("test.md", b"# Test", "text/markdown"))],
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Health endpoint tests
# ---------------------------------------------------------------------------


class TestHealth:
    """Tests for GET /health (no auth required)."""

    def test_health_returns_200(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "version" in data

    def test_health_returns_version(self, client):
        resp = client.get("/health")
        data = resp.json()
        assert data["version"] == "0.8.0"


# ---------------------------------------------------------------------------
# Upload endpoint tests
# ---------------------------------------------------------------------------


class TestUpload:
    """Tests for POST /v1/vault/upload."""

    def test_upload_without_auth_returns_401(self, client):
        resp = client.post("/v1/vault/upload", files=[("files", ("test.md", b"# Test", "text/markdown"))])
        assert resp.status_code == 401

    def test_upload_with_auth_returns_202(self, client):
        resp = client.post(
            "/v1/vault/upload",
            headers=auth_header(),
            files=[("files", ("test.md", b"# Test", "text/markdown"))],
        )
        assert resp.status_code == 202
        data = resp.json()
        assert "job_id" in data
        assert data["status"] == "queued"
        assert "1 files" in data["message"]

    def test_upload_multiple_files(self, client):
        resp = client.post(
            "/v1/vault/upload",
            headers=auth_header(),
            files=[
                ("files", ("a.md", b"# A", "text/markdown")),
                ("files", ("b.md", b"# B", "text/markdown")),
            ],
        )
        assert resp.status_code == 202
        assert "2 files" in resp.json()["message"]

    def test_upload_stores_files_in_gcs(self, client, mock_storage):
        """Upload stores vault files in GCS via storage.upload_vault_files."""
        client.post(
            "/v1/vault/upload",
            headers=auth_header(),
            files=[("files", ("test.md", b"# Test", "text/markdown"))],
        )
        mock_storage.upload_vault_files.assert_called_once()
        call_args = mock_storage.upload_vault_files.call_args
        assert call_args[0][0] == "user-1"  # user_id
        assert "test.md" in call_args[0][1]  # vault_files dict

    def test_upload_returns_job_id(self, client):
        """Upload returns a valid UUID job_id."""
        resp = client.post(
            "/v1/vault/upload",
            headers=auth_header(),
            files=[("files", ("test.md", b"# Test", "text/markdown"))],
        )
        data = resp.json()
        # Should be a valid UUID
        import uuid as uuid_mod

        uuid_mod.UUID(data["job_id"])  # Raises ValueError if invalid

    def test_upload_triggers_background_indexing(self, client, mock_indexer):
        """Upload triggers background indexing via CloudIndexer."""
        resp = client.post(
            "/v1/vault/upload",
            headers=auth_header(),
            files=[("files", ("test.md", b"# Test", "text/markdown"))],
        )
        job_id = resp.json()["job_id"]

        # Give background thread time to run
        time.sleep(0.2)

        mock_indexer.index_vault.assert_called_once()
        call_args = mock_indexer.index_vault.call_args
        assert call_args[0][0] == "user-1"
        assert "test.md" in call_args[0][1]


# ---------------------------------------------------------------------------
# Status endpoint tests
# ---------------------------------------------------------------------------


class TestVaultStatus:
    """Tests for GET /v1/vault/status/{job_id}."""

    def test_status_without_auth_returns_401(self, client):
        resp = client.get("/v1/vault/status/some-job-id")
        assert resp.status_code == 401

    def test_status_returns_job_info(self, client):
        """Status endpoint returns real job status after upload."""
        # Upload a file to create a job
        resp = client.post(
            "/v1/vault/upload",
            headers=auth_header(),
            files=[("files", ("test.md", b"# Test", "text/markdown"))],
        )
        job_id = resp.json()["job_id"]

        # Give background thread time to run
        time.sleep(0.2)

        resp = client.get(
            f"/v1/vault/status/{job_id}",
            headers=auth_header(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["job_id"] == job_id
        assert data["status"] in ("queued", "indexing", "complete")

    def test_status_unknown_job_returns_404(self, client):
        """Requesting status for a nonexistent job returns 404."""
        resp = client.get(
            "/v1/vault/status/nonexistent-job",
            headers=auth_header(),
        )
        assert resp.status_code == 404

    def test_status_includes_result_fields(self, client):
        """Completed job status includes db_size and note_count."""
        resp = client.post(
            "/v1/vault/upload",
            headers=auth_header(),
            files=[("files", ("test.md", b"# Test", "text/markdown"))],
        )
        job_id = resp.json()["job_id"]

        # Wait for background indexing
        time.sleep(0.3)

        resp = client.get(
            f"/v1/vault/status/{job_id}",
            headers=auth_header(),
        )
        data = resp.json()
        if data["status"] == "complete":
            assert data["db_size"] is not None
            assert data["note_count"] is not None


# ---------------------------------------------------------------------------
# Download endpoint tests
# ---------------------------------------------------------------------------


class TestDownload:
    """Tests for GET /v1/vault/download."""

    def test_download_without_auth_returns_401(self, client):
        resp = client.get("/v1/vault/download")
        assert resp.status_code == 401

    def test_download_with_auth_returns_presigned_url(self, client, mock_storage):
        """Download endpoint returns a signed GCS URL."""
        resp = client.get("/v1/vault/download", headers=auth_header())
        assert resp.status_code == 200
        data = resp.json()
        assert data["download_url"] == "https://storage.googleapis.com/signed-url/neurostack.db"
        assert data["expires_in"] == 3600

    def test_download_calls_storage_with_user_id(self, client, mock_storage):
        """Download endpoint calls storage.generate_download_url with the user's ID."""
        client.get("/v1/vault/download", headers=auth_header())
        mock_storage.generate_download_url.assert_called_once_with("user-1")


# ---------------------------------------------------------------------------
# Query endpoint tests
# ---------------------------------------------------------------------------


class TestQuery:
    """Tests for POST /v1/vault/query."""

    def test_query_without_auth_returns_401(self, client):
        resp = client.post("/v1/vault/query")
        assert resp.status_code == 401

    def test_query_returns_501_not_implemented(self, client):
        resp = client.post("/v1/vault/query", headers=auth_header())
        assert resp.status_code == 501


# ---------------------------------------------------------------------------
# Tenant isolation tests
# ---------------------------------------------------------------------------


class TestTenantIsolation:
    """Tests for cross-tenant isolation guarantees."""

    def test_user_cannot_see_other_users_jobs(self, client):
        """User A cannot see User B's job status (returns 404, not 403)."""
        # User 1 uploads
        resp = client.post(
            "/v1/vault/upload",
            headers=auth_header("sk-valid-key-123"),  # user-1
            files=[("files", ("test.md", b"# Test", "text/markdown"))],
        )
        job_id = resp.json()["job_id"]

        # User 2 tries to check User 1's job — must get 404
        resp = client.get(
            f"/v1/vault/status/{job_id}",
            headers=auth_header("sk-pro-key-456"),  # user-2
        )
        assert resp.status_code == 404

    def test_user_can_see_own_jobs(self, client):
        """User can see their own job status."""
        resp = client.post(
            "/v1/vault/upload",
            headers=auth_header("sk-valid-key-123"),
            files=[("files", ("test.md", b"# Test", "text/markdown"))],
        )
        job_id = resp.json()["job_id"]

        resp = client.get(
            f"/v1/vault/status/{job_id}",
            headers=auth_header("sk-valid-key-123"),
        )
        assert resp.status_code == 200

    def test_download_scoped_to_user(self, client, mock_storage):
        """Download URL is generated for the authenticated user only."""
        client.get("/v1/vault/download", headers=auth_header("sk-pro-key-456"))
        mock_storage.generate_download_url.assert_called_once_with("user-2")


# ---------------------------------------------------------------------------
# Path traversal protection tests
# ---------------------------------------------------------------------------


class TestPathTraversal:
    """Tests for filename sanitisation preventing path traversal."""

    def test_rejects_path_traversal_dotdot(self, client):
        """Filenames with .. are rejected."""
        resp = client.post(
            "/v1/vault/upload",
            headers=auth_header(),
            files=[("files", ("../../../etc/passwd", b"bad", "text/markdown"))],
        )
        assert resp.status_code == 400
        assert "traversal" in resp.json()["detail"].lower() or "not allowed" in resp.json()["detail"].lower()

    def test_rejects_absolute_path(self, client):
        """Absolute paths are rejected."""
        resp = client.post(
            "/v1/vault/upload",
            headers=auth_header(),
            files=[("files", ("/etc/passwd.md", b"bad", "text/markdown"))],
        )
        assert resp.status_code == 400

    def test_rejects_non_markdown_files(self, client):
        """Only .md files are accepted."""
        resp = client.post(
            "/v1/vault/upload",
            headers=auth_header(),
            files=[("files", ("script.py", b"import os", "text/plain"))],
        )
        assert resp.status_code == 400
        assert ".md" in resp.json()["detail"]

    def test_rejects_backslash_traversal(self, client):
        """Windows-style backslash traversal is rejected."""
        resp = client.post(
            "/v1/vault/upload",
            headers=auth_header(),
            files=[("files", ("..\\..\\etc\\passwd.md", b"bad", "text/markdown"))],
        )
        assert resp.status_code == 400

    def test_accepts_nested_markdown(self, client):
        """Nested subdirectory paths with .md extension are accepted."""
        resp = client.post(
            "/v1/vault/upload",
            headers=auth_header(),
            files=[("files", ("work/projects/note.md", b"# OK", "text/markdown"))],
        )
        assert resp.status_code == 202

    def test_rejects_empty_filename(self, client):
        """Empty filenames are rejected (FastAPI returns 422 or our code returns 400)."""
        resp = client.post(
            "/v1/vault/upload",
            headers=auth_header(),
            files=[("files", ("", b"# Empty", "text/markdown"))],
        )
        assert resp.status_code in (400, 422)


# ---------------------------------------------------------------------------
# Upload limit tests
# ---------------------------------------------------------------------------


class TestUploadLimits:
    """Tests for upload size and count limits."""

    def test_rejects_oversized_file(self, client):
        """Files exceeding MAX_FILE_SIZE_BYTES are rejected."""
        big_content = b"# Big\n" + b"x" * (10 * 1024 * 1024 + 1)  # 10MB + 1
        resp = client.post(
            "/v1/vault/upload",
            headers=auth_header(),
            files=[("files", ("big.md", big_content, "text/markdown"))],
        )
        assert resp.status_code == 400
        assert "too large" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Storage user_id validation tests
# ---------------------------------------------------------------------------


class TestStorageUserIdValidation:
    """Tests for GCS storage user_id validation."""

    def test_rejects_traversal_user_id(self):
        """user_id with path traversal characters is rejected."""
        from neurostack.cloud.storage import _validate_user_id

        with pytest.raises(ValueError, match="Invalid user_id"):
            _validate_user_id("../other-user")

    def test_rejects_slash_in_user_id(self):
        from neurostack.cloud.storage import _validate_user_id

        with pytest.raises(ValueError, match="Invalid user_id"):
            _validate_user_id("user/evil")

    def test_rejects_empty_user_id(self):
        from neurostack.cloud.storage import _validate_user_id

        with pytest.raises(ValueError, match="Invalid user_id"):
            _validate_user_id("")

    def test_accepts_valid_user_id(self):
        from neurostack.cloud.storage import _validate_user_id

        assert _validate_user_id("user-1") == "user-1"
        assert _validate_user_id("user_2") == "user_2"
        assert _validate_user_id("abc123") == "abc123"
