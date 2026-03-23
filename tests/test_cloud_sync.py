# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Tests for cloud manifest tracking and vault sync engine."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest


# ---------------------------------------------------------------------------
# Manifest tests
# ---------------------------------------------------------------------------


class TestManifestScanVault:
    """Tests for Manifest.scan_vault() SHA-256 hashing."""

    def test_scan_returns_hashes_for_md_files(self, tmp_path):
        """scan_vault returns {relative_path: sha256_hex} for all .md files."""
        from neurostack.cloud.manifest import Manifest

        (tmp_path / "note1.md").write_text("hello world")
        (tmp_path / "subdir").mkdir()
        (tmp_path / "subdir" / "note2.md").write_text("second note")

        manifest = Manifest.scan_vault(tmp_path)

        assert "note1.md" in manifest.entries
        assert "subdir/note2.md" in manifest.entries
        assert len(manifest.entries) == 2

        # Verify actual SHA-256
        expected = hashlib.sha256(b"hello world").hexdigest()
        assert manifest.entries["note1.md"] == expected

    def test_scan_skips_non_md_files(self, tmp_path):
        """scan_vault skips non-.md files (images, .obsidian, etc.)."""
        from neurostack.cloud.manifest import Manifest

        (tmp_path / "note.md").write_text("content")
        (tmp_path / "image.png").write_bytes(b"\x89PNG")
        (tmp_path / "data.json").write_text("{}")

        manifest = Manifest.scan_vault(tmp_path)

        assert "note.md" in manifest.entries
        assert "image.png" not in manifest.entries
        assert "data.json" not in manifest.entries
        assert len(manifest.entries) == 1

    def test_scan_skips_dot_directories(self, tmp_path):
        """scan_vault skips directories starting with . (.obsidian, .git, .neurostack)."""
        from neurostack.cloud.manifest import Manifest

        (tmp_path / "note.md").write_text("content")
        (tmp_path / ".obsidian").mkdir()
        (tmp_path / ".obsidian" / "config.md").write_text("obsidian config")
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "HEAD.md").write_text("ref")
        (tmp_path / ".neurostack").mkdir()
        (tmp_path / ".neurostack" / "manifest.md").write_text("data")

        manifest = Manifest.scan_vault(tmp_path)

        assert len(manifest.entries) == 1
        assert "note.md" in manifest.entries

    def test_content_hash_is_deterministic(self, tmp_path):
        """Same file content always produces the same hash."""
        from neurostack.cloud.manifest import Manifest

        content = "deterministic content test"
        (tmp_path / "a.md").write_text(content)

        m1 = Manifest.scan_vault(tmp_path)
        m2 = Manifest.scan_vault(tmp_path)

        assert m1.entries["a.md"] == m2.entries["a.md"]
        assert m1.entries["a.md"] == hashlib.sha256(content.encode()).hexdigest()


class TestManifestLoadSave:
    """Tests for Manifest.load() and Manifest.save() JSON persistence."""

    def test_load_returns_empty_if_no_file(self, tmp_path):
        """load() returns empty Manifest if file does not exist."""
        from neurostack.cloud.manifest import Manifest

        manifest = Manifest.load(tmp_path / "nonexistent.json")
        assert manifest.entries == {}

    def test_load_reads_saved_manifest(self, tmp_path):
        """load() loads previously saved manifest from JSON."""
        from neurostack.cloud.manifest import Manifest

        path = tmp_path / "manifest.json"
        data = {"note.md": "abc123", "sub/note2.md": "def456"}
        path.write_text(json.dumps(data))

        manifest = Manifest.load(path)
        assert manifest.entries == data

    def test_save_writes_json(self, tmp_path):
        """save() writes {filename: hash} JSON to disk."""
        from neurostack.cloud.manifest import Manifest

        path = tmp_path / "manifest.json"
        manifest = Manifest({"note.md": "abc123"})
        manifest.save(path)

        data = json.loads(path.read_text())
        assert data == {"note.md": "abc123"}

    def test_save_creates_parent_dirs(self, tmp_path):
        """save() creates parent directories if needed."""
        from neurostack.cloud.manifest import Manifest

        path = tmp_path / "deep" / "nested" / "manifest.json"
        manifest = Manifest({"note.md": "abc123"})
        manifest.save(path)

        assert path.exists()
        data = json.loads(path.read_text())
        assert data == {"note.md": "abc123"}


class TestManifestDiff:
    """Tests for Manifest.diff() computing SyncDiff."""

    def test_diff_detects_added_files(self):
        """diff() identifies new files not in old manifest."""
        from neurostack.cloud.manifest import Manifest

        old = Manifest({})
        new = Manifest({"note.md": "abc123"})

        diff = Manifest.diff(old, new)
        assert "note.md" in diff.added
        assert diff.changed == []
        assert diff.removed == []

    def test_diff_detects_changed_files(self):
        """diff() identifies files whose content hash changed."""
        from neurostack.cloud.manifest import Manifest

        old = Manifest({"note.md": "old_hash"})
        new = Manifest({"note.md": "new_hash"})

        diff = Manifest.diff(old, new)
        assert diff.added == []
        assert "note.md" in diff.changed
        assert diff.removed == []

    def test_diff_detects_removed_files(self):
        """diff() identifies files no longer in vault."""
        from neurostack.cloud.manifest import Manifest

        old = Manifest({"note.md": "abc123"})
        new = Manifest({})

        diff = Manifest.diff(old, new)
        assert diff.added == []
        assert diff.changed == []
        assert "note.md" in diff.removed

    def test_diff_returns_empty_when_identical(self):
        """diff() returns empty SyncDiff when old and new are identical."""
        from neurostack.cloud.manifest import Manifest, SyncDiff

        entries = {"note.md": "abc123", "sub/note2.md": "def456"}
        old = Manifest(dict(entries))
        new = Manifest(dict(entries))

        diff = Manifest.diff(old, new)
        assert diff.added == []
        assert diff.changed == []
        assert diff.removed == []
        assert not diff.has_changes

    def test_diff_has_changes_property(self):
        """has_changes is True when diff is non-empty."""
        from neurostack.cloud.manifest import Manifest

        old = Manifest({})
        new = Manifest({"note.md": "abc123"})

        diff = Manifest.diff(old, new)
        assert diff.has_changes is True

    def test_diff_upload_files_property(self):
        """upload_files returns added + changed files."""
        from neurostack.cloud.manifest import Manifest

        old = Manifest({"existing.md": "old_hash"})
        new = Manifest({"existing.md": "new_hash", "new.md": "abc123"})

        diff = Manifest.diff(old, new)
        assert set(diff.upload_files) == {"existing.md", "new.md"}


# ---------------------------------------------------------------------------
# VaultSyncEngine tests
# ---------------------------------------------------------------------------


@pytest.fixture
def vault_env(tmp_path):
    """Set up vault dir, db dir, and sample .md files for sync tests."""
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    db_dir = tmp_path / "db"
    db_dir.mkdir()
    manifest_path = tmp_path / "manifest" / "cloud-manifest.json"

    # Create sample vault files
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
        "poll_interval": 0.01,  # fast polling for tests
        "poll_timeout": 1.0,  # short timeout for tests
    }
    kwargs.update(overrides)
    return VaultSyncEngine(**kwargs)


class TestSyncEnginePush:
    """Tests for VaultSyncEngine.push() — upload changed files."""

    def test_push_uploads_changed_files(self, vault_env):
        """push() scans vault, diffs, uploads only changed files via multipart POST."""
        engine = _make_engine(vault_env)

        mock_upload_resp = MagicMock()
        mock_upload_resp.status_code = 202
        mock_upload_resp.json.return_value = {
            "job_id": "job-abc",
            "status": "queued",
            "message": "Upload received",
        }
        mock_upload_resp.raise_for_status = MagicMock()

        mock_status_resp = MagicMock()
        mock_status_resp.status_code = 200
        mock_status_resp.json.return_value = {
            "job_id": "job-abc",
            "status": "complete",
            "progress": 1.0,
            "note_count": 2,
        }
        mock_status_resp.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.post.return_value = mock_upload_resp
        mock_client.get.return_value = mock_status_resp
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch("neurostack.cloud.sync.httpx.Client", return_value=mock_client):
            result = engine.push()

        # Verify upload was called
        mock_client.post.assert_called_once()
        post_call = mock_client.post.call_args
        assert "/v1/vault/upload" in post_call.args[0]

        # Verify result contains job info
        assert result["status"] == "complete"
        assert result["job_id"] == "job-abc"

    def test_push_polls_until_complete(self, vault_env):
        """push() polls status endpoint until status='complete'."""
        engine = _make_engine(vault_env)

        mock_upload_resp = MagicMock()
        mock_upload_resp.status_code = 202
        mock_upload_resp.json.return_value = {
            "job_id": "job-abc",
            "status": "queued",
            "message": "Upload received",
        }
        mock_upload_resp.raise_for_status = MagicMock()

        # First poll returns indexing, second returns complete
        mock_indexing_resp = MagicMock()
        mock_indexing_resp.status_code = 200
        mock_indexing_resp.json.return_value = {
            "job_id": "job-abc",
            "status": "indexing",
            "progress": 0.5,
        }
        mock_indexing_resp.raise_for_status = MagicMock()

        mock_complete_resp = MagicMock()
        mock_complete_resp.status_code = 200
        mock_complete_resp.json.return_value = {
            "job_id": "job-abc",
            "status": "complete",
            "progress": 1.0,
            "note_count": 2,
        }
        mock_complete_resp.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.post.return_value = mock_upload_resp
        mock_client.get.side_effect = [mock_indexing_resp, mock_complete_resp]
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch("neurostack.cloud.sync.httpx.Client", return_value=mock_client):
            result = engine.push()

        # Should have polled twice
        assert mock_client.get.call_count == 2
        assert result["status"] == "complete"

    def test_push_saves_manifest_on_success(self, vault_env):
        """push() saves updated manifest to disk after successful upload + indexing."""
        engine = _make_engine(vault_env)

        mock_upload_resp = MagicMock()
        mock_upload_resp.status_code = 202
        mock_upload_resp.json.return_value = {
            "job_id": "job-abc",
            "status": "queued",
            "message": "OK",
        }
        mock_upload_resp.raise_for_status = MagicMock()

        mock_status_resp = MagicMock()
        mock_status_resp.status_code = 200
        mock_status_resp.json.return_value = {
            "job_id": "job-abc",
            "status": "complete",
            "progress": 1.0,
        }
        mock_status_resp.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.post.return_value = mock_upload_resp
        mock_client.get.return_value = mock_status_resp
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch("neurostack.cloud.sync.httpx.Client", return_value=mock_client):
            engine.push()

        # Manifest should be saved
        assert vault_env["manifest_path"].exists()
        data = json.loads(vault_env["manifest_path"].read_text())
        assert "note1.md" in data
        assert "sub/note2.md" in data

    def test_push_no_changes_skips_upload(self, vault_env):
        """push() with no changes skips upload and returns early."""
        from neurostack.cloud.manifest import Manifest

        engine = _make_engine(vault_env)

        # Pre-save a manifest matching current vault state
        current = Manifest.scan_vault(vault_env["vault_root"])
        current.save(vault_env["manifest_path"])

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch("neurostack.cloud.sync.httpx.Client", return_value=mock_client):
            result = engine.push()

        # No HTTP calls should have been made
        mock_client.post.assert_not_called()
        assert result["status"] == "no_changes"

    def test_push_raises_on_indexing_failure(self, vault_env):
        """push() raises SyncError if indexing fails (status='failed')."""
        from neurostack.cloud.sync import SyncError

        engine = _make_engine(vault_env)

        mock_upload_resp = MagicMock()
        mock_upload_resp.status_code = 202
        mock_upload_resp.json.return_value = {
            "job_id": "job-abc",
            "status": "queued",
            "message": "OK",
        }
        mock_upload_resp.raise_for_status = MagicMock()

        mock_failed_resp = MagicMock()
        mock_failed_resp.status_code = 200
        mock_failed_resp.json.return_value = {
            "job_id": "job-abc",
            "status": "failed",
            "error": "Indexing error: out of memory",
        }
        mock_failed_resp.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.post.return_value = mock_upload_resp
        mock_client.get.return_value = mock_failed_resp
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch("neurostack.cloud.sync.httpx.Client", return_value=mock_client):
            with pytest.raises(SyncError, match="Indexing error"):
                engine.push()

    def test_push_raises_on_poll_timeout(self, vault_env):
        """push() raises SyncError when poll timeout is exceeded."""
        from neurostack.cloud.sync import SyncError

        engine = _make_engine(vault_env, poll_timeout=0.05, poll_interval=0.01)

        mock_upload_resp = MagicMock()
        mock_upload_resp.status_code = 202
        mock_upload_resp.json.return_value = {
            "job_id": "job-abc",
            "status": "queued",
            "message": "OK",
        }
        mock_upload_resp.raise_for_status = MagicMock()

        # Always return "indexing" to trigger timeout
        mock_indexing_resp = MagicMock()
        mock_indexing_resp.status_code = 200
        mock_indexing_resp.json.return_value = {
            "job_id": "job-abc",
            "status": "indexing",
            "progress": 0.5,
        }
        mock_indexing_resp.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.post.return_value = mock_upload_resp
        mock_client.get.return_value = mock_indexing_resp
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch("neurostack.cloud.sync.httpx.Client", return_value=mock_client):
            with pytest.raises(SyncError, match="timed out"):
                engine.push()


class TestSyncEnginePull:
    """Tests for VaultSyncEngine.pull() — download indexed DB."""

    def test_pull_downloads_db(self, vault_env):
        """pull() downloads DB from presigned URL and saves to db_dir."""
        engine = _make_engine(vault_env)

        mock_download_info_resp = MagicMock()
        mock_download_info_resp.status_code = 200
        mock_download_info_resp.json.return_value = {
            "download_url": "https://storage.example.com/db.sqlite?sig=abc",
            "expires_in": 3600,
        }
        mock_download_info_resp.raise_for_status = MagicMock()

        db_content = b"SQLite format 3\x00fake-db-content"
        mock_db_resp = MagicMock()
        mock_db_resp.status_code = 200
        mock_db_resp.content = db_content
        mock_db_resp.raise_for_status = MagicMock()

        # iter_bytes for streaming
        mock_db_resp.iter_bytes = MagicMock(return_value=iter([db_content]))
        mock_db_resp.__enter__ = MagicMock(return_value=mock_db_resp)
        mock_db_resp.__exit__ = MagicMock(return_value=False)

        mock_client = MagicMock()
        mock_client.get.return_value = mock_download_info_resp
        mock_client.stream.return_value = mock_db_resp
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch("neurostack.cloud.sync.httpx.Client", return_value=mock_client):
            result_path = engine.pull()

        expected_db = vault_env["db_dir"] / "neurostack.db"
        assert result_path == expected_db
        assert expected_db.exists()
        assert expected_db.read_bytes() == db_content

    def test_pull_creates_db_dir_if_missing(self, vault_env):
        """pull() creates db_dir if it does not exist."""
        import shutil

        # Remove db_dir
        new_db_dir = vault_env["db_dir"] / "new_subdir"
        engine = _make_engine(vault_env, db_dir=new_db_dir)

        mock_download_info_resp = MagicMock()
        mock_download_info_resp.status_code = 200
        mock_download_info_resp.json.return_value = {
            "download_url": "https://storage.example.com/db.sqlite?sig=abc",
            "expires_in": 3600,
        }
        mock_download_info_resp.raise_for_status = MagicMock()

        db_content = b"SQLite format 3\x00fake-db"
        mock_db_resp = MagicMock()
        mock_db_resp.status_code = 200
        mock_db_resp.iter_bytes = MagicMock(return_value=iter([db_content]))
        mock_db_resp.__enter__ = MagicMock(return_value=mock_db_resp)
        mock_db_resp.__exit__ = MagicMock(return_value=False)
        mock_db_resp.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.get.return_value = mock_download_info_resp
        mock_client.stream.return_value = mock_db_resp
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch("neurostack.cloud.sync.httpx.Client", return_value=mock_client):
            result_path = engine.pull()

        assert new_db_dir.exists()
        assert result_path.exists()


class TestSyncEngineQuery:
    """Tests for VaultSyncEngine.query() — cloud search."""

    def test_query_sends_search_request(self, vault_env):
        """query() sends POST /v1/vault/query with search params."""
        engine = _make_engine(vault_env)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "results": [
                {"title": "note1.md", "score": 0.95, "snippet": "hello"},
            ]
        }
        mock_resp.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.post.return_value = mock_resp
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch("neurostack.cloud.sync.httpx.Client", return_value=mock_client):
            results = engine.query("hello world")

        mock_client.post.assert_called_once()
        post_call = mock_client.post.call_args
        assert "/v1/vault/query" in post_call.args[0]
        body = post_call.kwargs.get("json", {})
        assert body["query"] == "hello world"
        assert body["top_k"] == 10
        assert body["mode"] == "hybrid"

    def test_query_handles_501_not_implemented(self, vault_env):
        """query() handles 501 gracefully with clear error message."""
        import httpx as real_httpx

        from neurostack.cloud.sync import SyncError

        engine = _make_engine(vault_env)

        mock_resp = MagicMock()
        mock_resp.status_code = 501
        mock_resp.raise_for_status.side_effect = real_httpx.HTTPStatusError(
            "501 Not Implemented",
            request=MagicMock(),
            response=mock_resp,
        )

        mock_client = MagicMock()
        mock_client.post.return_value = mock_resp
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch("neurostack.cloud.sync.httpx.Client", return_value=mock_client):
            with pytest.raises(SyncError, match="not yet available"):
                engine.query("test query")


class TestSyncEngineAuth:
    """Tests for Authorization header on all HTTP calls."""

    def test_all_requests_include_bearer_auth(self, vault_env):
        """All HTTP calls include Authorization: Bearer {api_key} header."""
        engine = _make_engine(vault_env)

        mock_upload_resp = MagicMock()
        mock_upload_resp.status_code = 202
        mock_upload_resp.json.return_value = {
            "job_id": "job-abc",
            "status": "queued",
            "message": "OK",
        }
        mock_upload_resp.raise_for_status = MagicMock()

        mock_status_resp = MagicMock()
        mock_status_resp.status_code = 200
        mock_status_resp.json.return_value = {
            "job_id": "job-abc",
            "status": "complete",
            "progress": 1.0,
        }
        mock_status_resp.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.post.return_value = mock_upload_resp
        mock_client.get.return_value = mock_status_resp
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch("neurostack.cloud.sync.httpx.Client", return_value=mock_client) as mock_cls:
            engine.push()

        # Check that Client was created with auth headers
        client_call = mock_cls.call_args
        headers = client_call.kwargs.get("headers", {})
        assert headers.get("Authorization") == "Bearer ns_test_key_123"
