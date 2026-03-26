# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Tests for tar.gz upload format in the vault sync engine."""

from __future__ import annotations

import hashlib
import io
import json
import tarfile
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import MagicMock, patch


@dataclass
class _FakeDiff:
    """Minimal stand-in for SyncDiff used by _build_tar_archive."""

    added: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)

    @property
    def upload_files(self) -> list[str]:
        return self.added + self.changed

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.changed or self.removed)


def _make_engine(tmp_path: Path):
    """Create a VaultSyncEngine pointed at *tmp_path*."""
    from neurostack.cloud.sync import VaultSyncEngine

    return VaultSyncEngine(
        cloud_api_url="https://api.example.com",
        cloud_api_key="sk-test",
        vault_root=tmp_path,
        db_dir=tmp_path / "db",
    )


class TestBuildTarArchive:
    """Tests for VaultSyncEngine._build_tar_archive."""

    def test_build_tar_archive_contains_manifest(self, tmp_path):
        """_build_tar_archive creates a valid tar.gz with _manifest.json."""
        (tmp_path / "note.md").write_text("# Hello")
        engine = _make_engine(tmp_path)
        diff = _FakeDiff(added=["note.md"])

        archive = engine._build_tar_archive(diff.upload_files, diff)

        tar = tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz")
        names = tar.getnames()
        assert "_manifest.json" in names
        tar.close()

    def test_build_tar_archive_contains_files(self, tmp_path):
        """tar contains all upload files with correct content."""
        (tmp_path / "a.md").write_text("alpha")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "b.md").write_text("beta")
        engine = _make_engine(tmp_path)
        diff = _FakeDiff(added=["a.md", "sub/b.md"])

        archive = engine._build_tar_archive(diff.upload_files, diff)

        tar = tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz")
        assert "a.md" in tar.getnames()
        assert "sub/b.md" in tar.getnames()

        a_content = tar.extractfile("a.md").read()
        assert a_content == b"alpha"

        b_content = tar.extractfile("sub/b.md").read()
        assert b_content == b"beta"
        tar.close()

    def test_manifest_has_correct_format(self, tmp_path):
        """_manifest.json has format_version=1, removed list, file_hashes with sha256 prefix."""
        (tmp_path / "note.md").write_text("content")
        engine = _make_engine(tmp_path)
        diff = _FakeDiff(added=["note.md"], removed=["old.md"])

        archive = engine._build_tar_archive(diff.upload_files, diff)

        tar = tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz")
        manifest = json.loads(tar.extractfile("_manifest.json").read())
        tar.close()

        assert manifest["format_version"] == 1
        assert manifest["removed"] == ["old.md"]
        assert "note.md" in manifest["file_hashes"]

        # Hash should have sha256: prefix
        h = manifest["file_hashes"]["note.md"]
        assert h.startswith("sha256:")

        # Verify the actual hash value
        expected = "sha256:" + hashlib.sha256(b"content").hexdigest()
        assert h == expected

    def test_push_sends_tar_format(self, tmp_path):
        """push() sends Content-Type: application/gzip with tar.gz body."""
        (tmp_path / "note.md").write_text("# Test note")
        engine = _make_engine(tmp_path)

        # Mock manifest load/save so diff shows the file as added
        mock_manifest = MagicMock()
        mock_manifest.entries = {}

        # Mock the HTTP response chain
        mock_upload_resp = MagicMock()
        mock_upload_resp.json.return_value = {"job_id": "job-123", "status": "queued"}
        mock_upload_resp.raise_for_status = MagicMock()

        mock_status_resp = MagicMock()
        mock_status_resp.json.return_value = {"status": "complete"}
        mock_status_resp.raise_for_status = MagicMock()

        captured_kwargs = {}

        def fake_post(url, **kwargs):
            captured_kwargs.update(kwargs)
            return mock_upload_resp

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post = fake_post
        mock_client.get = MagicMock(return_value=mock_status_resp)

        with (
            patch("neurostack.cloud.sync.Manifest.load", return_value=mock_manifest),
            patch("neurostack.cloud.sync.Manifest.save"),
            patch("httpx.Client", return_value=mock_client),
        ):
            engine.push()

        # Verify Content-Type header was set
        assert "headers" in captured_kwargs
        assert captured_kwargs["headers"]["Content-Type"] == "application/gzip"
        assert captured_kwargs["headers"]["X-Upload-Format"] == "tar.gz"

        # Verify content is valid tar.gz
        body = captured_kwargs["content"]
        tar = tarfile.open(fileobj=io.BytesIO(body), mode="r:gz")
        assert "_manifest.json" in tar.getnames()
        tar.close()
