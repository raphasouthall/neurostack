# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Tests for .neurostackignore support in manifest scanning and sync."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from neurostack.cloud.manifest import Manifest


class TestNeurostackIgnore:
    """Tests for .neurostackignore pattern exclusion in Manifest.scan_vault()."""

    def test_scan_excludes_ignored_file(self, tmp_path):
        """Files listed in .neurostackignore are excluded from the manifest."""
        (tmp_path / "normal.md").write_text("visible note")
        (tmp_path / "secret.md").write_text("hidden note")
        (tmp_path / ".neurostackignore").write_text("secret.md\n")

        ignore_file = tmp_path / ".neurostackignore"
        manifest = Manifest.scan_vault(tmp_path, ignore_file=ignore_file)

        assert "normal.md" in manifest.entries
        assert "secret.md" not in manifest.entries
        assert len(manifest.entries) == 1

    def test_scan_excludes_glob_pattern(self, tmp_path):
        """Glob patterns like 'private/*.md' exclude matching subdirectory files."""
        (tmp_path / "note.md").write_text("public note")
        (tmp_path / "private").mkdir()
        (tmp_path / "private" / "diary.md").write_text("private diary")
        (tmp_path / "private" / "journal.md").write_text("private journal")
        (tmp_path / ".neurostackignore").write_text("private/*.md\n")

        ignore_file = tmp_path / ".neurostackignore"
        manifest = Manifest.scan_vault(tmp_path, ignore_file=ignore_file)

        assert "note.md" in manifest.entries
        assert "private/diary.md" not in manifest.entries
        assert "private/journal.md" not in manifest.entries
        assert len(manifest.entries) == 1

    def test_scan_ignores_comments_and_blank_lines(self, tmp_path):
        """Comments (#) and blank lines in .neurostackignore are ignored."""
        (tmp_path / "keep.md").write_text("keep this")
        (tmp_path / "drop.md").write_text("drop this")
        ignore_content = "# This is a comment\n\n  # Indented comment\n\ndrop.md\n\n"
        (tmp_path / ".neurostackignore").write_text(ignore_content)

        ignore_file = tmp_path / ".neurostackignore"
        manifest = Manifest.scan_vault(tmp_path, ignore_file=ignore_file)

        assert "keep.md" in manifest.entries
        assert "drop.md" not in manifest.entries
        assert len(manifest.entries) == 1

    def test_scan_without_ignore_file_includes_all(self, tmp_path):
        """Without an ignore_file, all .md files are included (backwards compatible)."""
        (tmp_path / "a.md").write_text("alpha")
        (tmp_path / "b.md").write_text("beta")

        manifest = Manifest.scan_vault(tmp_path)

        assert "a.md" in manifest.entries
        assert "b.md" in manifest.entries
        assert len(manifest.entries) == 2

    def test_push_uses_ignore_file(self, tmp_path):
        """VaultSyncEngine.push() skips files matching .neurostackignore patterns."""
        from neurostack.cloud.sync import VaultSyncEngine

        # Set up vault with ignore file
        (tmp_path / "public.md").write_text("public content")
        (tmp_path / "ignored.md").write_text("ignored content")
        (tmp_path / ".neurostackignore").write_text("ignored.md\n")

        manifest_path = tmp_path / ".neurostack" / "cloud-manifest.json"

        engine = VaultSyncEngine(
            cloud_api_url="https://fake.api",
            cloud_api_key="fake-key",
            vault_root=tmp_path,
            db_dir=tmp_path,
            manifest_path=manifest_path,
            consent_given=True,
        )

        # Mock the HTTP calls so push doesn't actually contact a server
        mock_response = MagicMock()
        mock_response.json.return_value = {"job_id": "test-job"}
        mock_response.raise_for_status = MagicMock()

        mock_poll_result = {"status": "complete"}

        with (
            patch.object(engine, "_build_tar_archive", return_value=b"fake") as mock_tar,
            patch.object(engine, "_poll_job", return_value=mock_poll_result),
            patch("httpx.Client") as mock_client_cls,
        ):
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.post.return_value = mock_response
            mock_client_cls.return_value = mock_client

            engine.push()

            # Verify _build_tar_archive was called with only "public.md"
            call_args = mock_tar.call_args
            upload_files = call_args[0][0]
            assert "public.md" in upload_files
            assert "ignored.md" not in upload_files
