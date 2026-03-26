# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Tests for upload progress reporting in push() and sync()."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture()
def vault_env(tmp_path):
    """Set up vault dir, db dir, and sample .md files for progress tests."""
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    db_dir = tmp_path / "db"
    db_dir.mkdir()
    manifest_path = tmp_path / "manifest" / "cloud-manifest.json"

    # Create sample vault files with known content
    (vault_root / "note1.md").write_text("first note content")
    (vault_root / "sub").mkdir()
    (vault_root / "sub" / "note2.md").write_text("second note content")

    return {
        "vault_root": vault_root,
        "db_dir": db_dir,
        "manifest_path": manifest_path,
        "api_url": "https://api.neurostack.sh",
        "api_key": "ns_test_key_123",
    }


def _make_engine(vault_env, **overrides):
    """Create a VaultSyncEngine from vault_env fixture."""
    from neurostack.cloud.sync import VaultSyncEngine

    kwargs = {
        "cloud_api_url": vault_env["api_url"],
        "cloud_api_key": vault_env["api_key"],
        "vault_root": vault_env["vault_root"],
        "db_dir": vault_env["db_dir"],
        "manifest_path": vault_env["manifest_path"],
        "poll_interval": 0.01,
        "poll_timeout": 1.0,
    }
    kwargs.update(overrides)
    return VaultSyncEngine(**kwargs)


def _mock_http_client():
    """Build a mock httpx.Client that accepts upload and returns complete."""
    mock_upload_resp = MagicMock()
    mock_upload_resp.status_code = 202
    mock_upload_resp.json.return_value = {
        "job_id": "job-progress",
        "status": "queued",
        "message": "Upload received",
    }
    mock_upload_resp.raise_for_status = MagicMock()

    mock_status_resp = MagicMock()
    mock_status_resp.status_code = 200
    mock_status_resp.json.return_value = {
        "job_id": "job-progress",
        "status": "complete",
        "progress": 1.0,
    }
    mock_status_resp.raise_for_status = MagicMock()

    mock_client = MagicMock()
    mock_client.post.return_value = mock_upload_resp
    mock_client.get.return_value = mock_status_resp
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    return mock_client


class TestPushProgressReporting:
    """Tests for progress reporting in push()."""

    def test_push_reports_file_count(self, vault_env):
        """progress_callback receives message with file count."""
        engine = _make_engine(vault_env)
        mock_client = _mock_http_client()
        messages: list[str] = []

        with patch("neurostack.cloud.sync.httpx.Client", return_value=mock_client):
            engine.push(progress_callback=messages.append)

        # Find the uploading message that includes file count
        upload_msgs = [m for m in messages if "Uploading 2 files" in m]
        assert len(upload_msgs) >= 1, f"Expected 'Uploading 2 files' in messages: {messages}"

    def test_push_reports_compression_ratio(self, vault_env):
        """progress_callback receives message with compression percentage."""
        engine = _make_engine(vault_env)
        mock_client = _mock_http_client()
        messages: list[str] = []

        with patch("neurostack.cloud.sync.httpx.Client", return_value=mock_client):
            engine.push(progress_callback=messages.append)

        # Find messages with compression info
        compression_msgs = [m for m in messages if "compression" in m.lower()]
        assert len(compression_msgs) >= 1, f"Expected compression info in messages: {messages}"
        # Should contain a percentage
        msg = compression_msgs[0]
        assert "%" in msg, f"Expected percentage in compression message: {msg}"

    def test_push_result_includes_upload_stats(self, vault_env):
        """push() return dict has upload_stats key with correct fields."""
        engine = _make_engine(vault_env)
        mock_client = _mock_http_client()

        with patch("neurostack.cloud.sync.httpx.Client", return_value=mock_client):
            result = engine.push()

        assert "upload_stats" in result
        stats = result["upload_stats"]
        assert stats["files_uploaded"] == 2
        assert stats["raw_bytes"] > 0
        assert stats["compressed_bytes"] > 0
        assert isinstance(stats["compression_ratio"], float)

    def test_push_no_changes_reports_zero_stats(self, vault_env):
        """When no changes, upload_stats has all zeros."""
        engine = _make_engine(vault_env)
        mock_client = _mock_http_client()

        # First push to establish manifest
        with patch("neurostack.cloud.sync.httpx.Client", return_value=mock_client):
            engine.push()

        # Second push should detect no changes
        result = engine.push()

        assert result["status"] == "no_changes"
        assert "upload_stats" in result
        stats = result["upload_stats"]
        assert stats["files_uploaded"] == 0
        assert stats["raw_bytes"] == 0
        assert stats["compressed_bytes"] == 0
        assert stats["compression_ratio"] == 0.0
