# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Tests for cloud privacy consent and .neurostackignore."""

from __future__ import annotations

from unittest.mock import patch

import pytest


class TestSaveConsent:
    """Tests for save_consent() writing to config.toml."""

    def test_save_consent_writes_to_config(self, tmp_path):
        """save_consent() writes consent_given=true and consent_date to config."""
        config_path = tmp_path / "config.toml"

        with patch("neurostack.cloud.config.CONFIG_PATH", config_path):
            from neurostack.cloud.config import save_consent

            save_consent()

            # Read back the file and verify
            import tomllib

            with open(config_path, "rb") as f:
                data = tomllib.load(f)

            assert data["cloud"]["consent_given"] is True
            assert "consent_date" in data["cloud"]
            assert len(data["cloud"]["consent_date"]) > 0

    def test_load_consent_from_config(self, tmp_path):
        """load_cloud_config() reads consent fields from config.toml."""
        config_path = tmp_path / "config.toml"

        import tomli_w

        data = {
            "cloud": {
                "cloud_api_url": "https://example.com",
                "cloud_api_key": "test-key",
                "consent_given": True,
                "consent_date": "2026-03-26T12:00:00+00:00",
            }
        }
        with open(config_path, "wb") as f:
            tomli_w.dump(data, f)

        with patch("neurostack.cloud.config.CONFIG_PATH", config_path):
            from neurostack.cloud.config import load_cloud_config

            cfg = load_cloud_config()

        assert cfg.consent_given is True
        assert cfg.consent_date == "2026-03-26T12:00:00+00:00"


class TestConsentCheck:
    """Tests for consent enforcement in push/sync."""

    def test_push_raises_consent_error_when_not_given(self, tmp_path):
        """push() raises ConsentError when consent_given=False."""
        from neurostack.cloud.sync import ConsentError, VaultSyncEngine

        vault = tmp_path / "vault"
        vault.mkdir()
        (vault / "note.md").write_text("hello")
        db_dir = tmp_path / "db"
        db_dir.mkdir()

        engine = VaultSyncEngine(
            cloud_api_url="https://example.com",
            cloud_api_key="test-key",
            vault_root=vault,
            db_dir=db_dir,
            consent_given=False,
        )

        with pytest.raises(ConsentError, match="Cloud consent not given"):
            engine.push()

    def test_push_succeeds_with_consent(self, tmp_path):
        """push() proceeds normally when consent_given=True (no ConsentError)."""
        from unittest.mock import MagicMock

        import httpx

        from neurostack.cloud.sync import VaultSyncEngine

        vault = tmp_path / "vault"
        vault.mkdir()
        (vault / "note.md").write_text("hello world")
        db_dir = tmp_path / "db"
        db_dir.mkdir()

        engine = VaultSyncEngine(
            cloud_api_url="https://example.com",
            cloud_api_key="test-key",
            vault_root=vault,
            db_dir=db_dir,
            consent_given=True,
        )

        # Mock httpx.Client to avoid real HTTP calls
        mock_response = MagicMock()
        mock_response.json.return_value = {"job_id": "test-job-123"}
        mock_response.raise_for_status = MagicMock()

        mock_status_response = MagicMock()
        mock_status_response.json.return_value = {
            "status": "complete",
            "message": "Indexing complete",
        }
        mock_status_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.post.return_value = mock_response
        mock_client.get.return_value = mock_status_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch("httpx.Client", return_value=mock_client):
            result = engine.push()

        assert result["status"] == "complete"

    def test_sync_raises_consent_error_when_not_given(self, tmp_path):
        """sync() raises ConsentError when consent_given=False."""
        from neurostack.cloud.sync import ConsentError, VaultSyncEngine

        vault = tmp_path / "vault"
        vault.mkdir()
        (vault / "note.md").write_text("hello")
        db_dir = tmp_path / "db"
        db_dir.mkdir()

        engine = VaultSyncEngine(
            cloud_api_url="https://example.com",
            cloud_api_key="test-key",
            vault_root=vault,
            db_dir=db_dir,
            consent_given=False,
        )

        with pytest.raises(ConsentError, match="Cloud consent not given"):
            engine.sync()


class TestNeurostackIgnore:
    """Tests for .neurostackignore loading."""

    def test_neurostackignore_load_patterns(self, tmp_path):
        """_load_ignore_patterns() reads patterns from .neurostackignore file."""
        from neurostack.cloud.sync import VaultSyncEngine

        vault = tmp_path / "vault"
        vault.mkdir()
        db_dir = tmp_path / "db"
        db_dir.mkdir()

        # Write a .neurostackignore file with patterns, comments, and blank lines
        ignore_file = vault / ".neurostackignore"
        ignore_file.write_text(
            "# Ignore private notes\n"
            "private/\n"
            "\n"
            "*.draft.md\n"
            "# Another comment\n"
            "journal/personal/*\n"
        )

        engine = VaultSyncEngine(
            cloud_api_url="https://example.com",
            cloud_api_key="test-key",
            vault_root=vault,
            db_dir=db_dir,
        )

        patterns = engine._load_ignore_patterns()

        assert patterns == ["private/", "*.draft.md", "journal/personal/*"]
        assert engine._check_neurostackignore_exists() is True

    def test_neurostackignore_returns_empty_when_missing(self, tmp_path):
        """_load_ignore_patterns() returns empty list when file doesn't exist."""
        from neurostack.cloud.sync import VaultSyncEngine

        vault = tmp_path / "vault"
        vault.mkdir()
        db_dir = tmp_path / "db"
        db_dir.mkdir()

        engine = VaultSyncEngine(
            cloud_api_url="https://example.com",
            cloud_api_key="test-key",
            vault_root=vault,
            db_dir=db_dir,
        )

        assert engine._load_ignore_patterns() == []
        assert engine._check_neurostackignore_exists() is False
