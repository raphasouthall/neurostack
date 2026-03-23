# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Tests for cloud config persistence and CloudClient HTTP wrapper."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

try:
    import tomllib
except ImportError:
    import tomli as tomllib


# ---------------------------------------------------------------------------
# Config persistence tests
# ---------------------------------------------------------------------------


class TestSaveCloudConfig:
    """Tests for save_cloud_config() TOML persistence."""

    def test_save_writes_cloud_section(self, tmp_path, monkeypatch):
        """save_cloud_config(url, key) writes [cloud] section to config.toml."""
        config_path = tmp_path / "config.toml"
        monkeypatch.setattr("neurostack.cloud.config.CONFIG_PATH", config_path)

        from neurostack.cloud.config import save_cloud_config

        save_cloud_config(
            cloud_api_url="https://api.neurostack.sh",
            cloud_api_key="ns_test_key_123",
        )

        assert config_path.exists()
        with open(config_path, "rb") as f:
            data = tomllib.load(f)
        assert data["cloud"]["cloud_api_url"] == "https://api.neurostack.sh"
        assert data["cloud"]["cloud_api_key"] == "ns_test_key_123"

    def test_save_preserves_existing_sections(self, tmp_path, monkeypatch):
        """save_cloud_config() preserves existing non-cloud config sections."""
        config_path = tmp_path / "config.toml"
        config_path.write_text('vault_root = "~/my-vault"\nembed_url = "http://gpu:11435"\n')
        monkeypatch.setattr("neurostack.cloud.config.CONFIG_PATH", config_path)

        from neurostack.cloud.config import save_cloud_config

        save_cloud_config(
            cloud_api_url="https://api.neurostack.sh",
            cloud_api_key="ns_key",
        )

        with open(config_path, "rb") as f:
            data = tomllib.load(f)
        assert data["vault_root"] == "~/my-vault"
        assert data["embed_url"] == "http://gpu:11435"
        assert data["cloud"]["cloud_api_url"] == "https://api.neurostack.sh"

    def test_save_creates_directory(self, tmp_path, monkeypatch):
        """save_cloud_config() creates ~/.config/neurostack/ directory if missing."""
        config_path = tmp_path / "subdir" / "nested" / "config.toml"
        monkeypatch.setattr("neurostack.cloud.config.CONFIG_PATH", config_path)

        from neurostack.cloud.config import save_cloud_config

        save_cloud_config(cloud_api_url="https://api.neurostack.sh", cloud_api_key="key")

        assert config_path.exists()


class TestClearCloudCredentials:
    """Tests for clear_cloud_credentials()."""

    def test_clear_removes_key_preserves_url(self, tmp_path, monkeypatch):
        """clear_cloud_credentials() removes cloud_api_key but preserves cloud_api_url."""
        config_path = tmp_path / "config.toml"
        config_path.write_text(
            '[cloud]\ncloud_api_url = "https://api.neurostack.sh"\n'
            'cloud_api_key = "ns_secret"\n'
        )
        monkeypatch.setattr("neurostack.cloud.config.CONFIG_PATH", config_path)

        from neurostack.cloud.config import clear_cloud_credentials

        clear_cloud_credentials()

        with open(config_path, "rb") as f:
            data = tomllib.load(f)
        assert data["cloud"]["cloud_api_url"] == "https://api.neurostack.sh"
        assert data["cloud"]["cloud_api_key"] == ""


class TestLoadCloudConfigToml:
    """Tests for load_cloud_config() TOML integration."""

    def test_load_reads_from_toml(self, tmp_path, monkeypatch):
        """load_cloud_config() reads cloud_api_url and cloud_api_key from config.toml [cloud]."""
        config_path = tmp_path / "config.toml"
        config_path.write_text(
            '[cloud]\ncloud_api_url = "https://api.neurostack.sh"\n'
            'cloud_api_key = "ns_toml_key"\n'
        )
        monkeypatch.setattr("neurostack.cloud.config.CONFIG_PATH", config_path)
        # Clear env vars that would override
        monkeypatch.delenv("NEUROSTACK_CLOUD_API_URL", raising=False)
        monkeypatch.delenv("NEUROSTACK_CLOUD_API_KEY", raising=False)

        from neurostack.cloud.config import load_cloud_config

        cfg = load_cloud_config()
        assert cfg.cloud_api_url == "https://api.neurostack.sh"
        assert cfg.cloud_api_key == "ns_toml_key"

    def test_env_vars_override_toml(self, tmp_path, monkeypatch):
        """Env vars NEUROSTACK_CLOUD_API_URL/KEY override TOML values."""
        config_path = tmp_path / "config.toml"
        config_path.write_text(
            '[cloud]\ncloud_api_url = "https://toml.example.com"\n'
            'cloud_api_key = "toml_key"\n'
        )
        monkeypatch.setattr("neurostack.cloud.config.CONFIG_PATH", config_path)
        monkeypatch.setenv("NEUROSTACK_CLOUD_API_URL", "https://env.example.com")
        monkeypatch.setenv("NEUROSTACK_CLOUD_API_KEY", "env_key")

        from neurostack.cloud.config import load_cloud_config

        cfg = load_cloud_config()
        assert cfg.cloud_api_url == "https://env.example.com"
        assert cfg.cloud_api_key == "env_key"


# ---------------------------------------------------------------------------
# CloudClient tests
# ---------------------------------------------------------------------------


class TestCloudClientInit:
    """Tests for CloudClient initialization."""

    def test_init_stores_config_no_network(self):
        """CloudClient.__init__ stores config and does not make network calls."""
        from neurostack.cloud.client import CloudClient
        from neurostack.cloud.config import CloudConfig

        cfg = CloudConfig(
            cloud_api_url="https://api.neurostack.sh",
            cloud_api_key="ns_key_123",
        )
        client = CloudClient(cfg)
        assert client._config is cfg
        assert client._base_url == "https://api.neurostack.sh"

    def test_init_strips_trailing_slash(self):
        """CloudClient strips trailing slash from base URL."""
        from neurostack.cloud.client import CloudClient
        from neurostack.cloud.config import CloudConfig

        cfg = CloudConfig(cloud_api_url="https://api.neurostack.sh/")
        client = CloudClient(cfg)
        assert client._base_url == "https://api.neurostack.sh"

    def test_is_configured_true(self):
        """is_configured returns True when both url and key are set."""
        from neurostack.cloud.client import CloudClient
        from neurostack.cloud.config import CloudConfig

        cfg = CloudConfig(
            cloud_api_url="https://api.neurostack.sh",
            cloud_api_key="ns_key",
        )
        assert CloudClient(cfg).is_configured is True

    def test_is_configured_false_missing_key(self):
        """is_configured returns False when api_key is empty."""
        from neurostack.cloud.client import CloudClient
        from neurostack.cloud.config import CloudConfig

        cfg = CloudConfig(cloud_api_url="https://api.neurostack.sh", cloud_api_key="")
        assert CloudClient(cfg).is_configured is False

    def test_is_configured_false_missing_url(self):
        """is_configured returns False when cloud_api_url is empty."""
        from neurostack.cloud.client import CloudClient
        from neurostack.cloud.config import CloudConfig

        cfg = CloudConfig(cloud_api_url="", cloud_api_key="ns_key")
        assert CloudClient(cfg).is_configured is False


class TestCloudClientHealth:
    """Tests for CloudClient.health() — no auth required."""

    def test_health_returns_status(self):
        """health() calls GET /health and returns server status dict."""
        from neurostack.cloud.client import CloudClient
        from neurostack.cloud.config import CloudConfig

        cfg = CloudConfig(cloud_api_url="https://api.neurostack.sh")
        client = CloudClient(cfg)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "ok", "version": "0.8.0"}
        mock_response.raise_for_status = MagicMock()

        with patch("neurostack.cloud.client.httpx") as mock_httpx:
            mock_httpx.get.return_value = mock_response
            result = client.health()

        assert result == {"status": "ok", "version": "0.8.0"}
        mock_httpx.get.assert_called_once_with(
            "https://api.neurostack.sh/health",
            timeout=10.0,
        )

    def test_health_no_auth_header(self):
        """health() does not send Authorization header."""
        from neurostack.cloud.client import CloudClient
        from neurostack.cloud.config import CloudConfig

        cfg = CloudConfig(
            cloud_api_url="https://api.neurostack.sh",
            cloud_api_key="ns_secret",
        )
        client = CloudClient(cfg)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "ok"}
        mock_response.raise_for_status = MagicMock()

        with patch("neurostack.cloud.client.httpx") as mock_httpx:
            mock_httpx.get.return_value = mock_response
            client.health()

        # Verify no headers kwarg (no auth)
        call_kwargs = mock_httpx.get.call_args
        assert "headers" not in call_kwargs.kwargs

    def test_health_connection_error(self):
        """health() raises ConnectionError when server unreachable."""
        import httpx as real_httpx

        from neurostack.cloud.client import CloudClient
        from neurostack.cloud.config import CloudConfig

        cfg = CloudConfig(cloud_api_url="https://api.neurostack.sh")
        client = CloudClient(cfg)

        with patch("neurostack.cloud.client.httpx") as mock_httpx:
            mock_httpx.ConnectError = real_httpx.ConnectError
            mock_httpx.TimeoutException = real_httpx.TimeoutException
            mock_httpx.get.side_effect = real_httpx.ConnectError("Connection refused")
            with pytest.raises(ConnectionError, match="Cannot reach cloud API"):
                client.health()


class TestCloudClientValidateKey:
    """Tests for CloudClient.validate_key()."""

    def test_validate_key_returns_true_on_200(self):
        """validate_key() returns True when server responds 200."""
        from neurostack.cloud.client import CloudClient
        from neurostack.cloud.config import CloudConfig

        cfg = CloudConfig(
            cloud_api_url="https://api.neurostack.sh",
            cloud_api_key="ns_valid_key",
        )
        client = CloudClient(cfg)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "ok"}

        with patch("neurostack.cloud.client.httpx") as mock_httpx:
            mock_httpx.get.return_value = mock_response
            result = client.validate_key()

        assert result is True
        call_kwargs = mock_httpx.get.call_args
        assert call_kwargs.kwargs["headers"]["Authorization"] == "Bearer ns_valid_key"

    def test_validate_key_returns_false_on_401(self):
        """validate_key() returns False on 401 Unauthorized."""
        from neurostack.cloud.client import CloudClient
        from neurostack.cloud.config import CloudConfig

        cfg = CloudConfig(
            cloud_api_url="https://api.neurostack.sh",
            cloud_api_key="ns_bad_key",
        )
        client = CloudClient(cfg)

        mock_response = MagicMock()
        mock_response.status_code = 401

        with patch("neurostack.cloud.client.httpx") as mock_httpx:
            mock_httpx.get.return_value = mock_response
            result = client.validate_key()

        assert result is False

    def test_validate_key_connection_error(self):
        """validate_key() raises ConnectionError when server unreachable."""
        import httpx as real_httpx

        from neurostack.cloud.client import CloudClient
        from neurostack.cloud.config import CloudConfig

        cfg = CloudConfig(
            cloud_api_url="https://api.neurostack.sh",
            cloud_api_key="ns_key",
        )
        client = CloudClient(cfg)

        with patch("neurostack.cloud.client.httpx") as mock_httpx:
            mock_httpx.ConnectError = real_httpx.ConnectError
            mock_httpx.TimeoutException = real_httpx.TimeoutException
            mock_httpx.get.side_effect = real_httpx.ConnectError("Connection refused")
            with pytest.raises(ConnectionError):
                client.validate_key()


class TestCloudClientStatus:
    """Tests for CloudClient.status()."""

    def test_status_authenticated(self):
        """status() returns auth state and tier when key is valid."""
        from neurostack.cloud.client import CloudClient
        from neurostack.cloud.config import CloudConfig

        cfg = CloudConfig(
            cloud_api_url="https://api.neurostack.sh",
            cloud_api_key="ns_valid_key",
        )
        client = CloudClient(cfg)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "ok", "version": "0.8.0"}

        with patch("neurostack.cloud.client.httpx") as mock_httpx:
            mock_httpx.get.return_value = mock_response
            result = client.status()

        assert result["authenticated"] is True
        assert result["cloud_url"] == "https://api.neurostack.sh"

    def test_status_unauthenticated(self):
        """status() returns authenticated=False when key is invalid."""
        from neurostack.cloud.client import CloudClient
        from neurostack.cloud.config import CloudConfig

        cfg = CloudConfig(
            cloud_api_url="https://api.neurostack.sh",
            cloud_api_key="ns_bad_key",
        )
        client = CloudClient(cfg)

        mock_response = MagicMock()
        mock_response.status_code = 401

        with patch("neurostack.cloud.client.httpx") as mock_httpx:
            mock_httpx.get.return_value = mock_response
            result = client.status()

        assert result["authenticated"] is False
        assert result["tier"] is None


class TestCloudClientAuthHeaders:
    """Tests for Bearer auth header construction."""

    def test_auth_headers_set_on_authenticated_requests(self):
        """CloudClient sets Authorization: Bearer {api_key} on authenticated requests."""
        from neurostack.cloud.client import CloudClient
        from neurostack.cloud.config import CloudConfig

        cfg = CloudConfig(
            cloud_api_url="https://api.neurostack.sh",
            cloud_api_key="ns_my_secret_key",
        )
        client = CloudClient(cfg)
        headers = client._auth_headers()
        assert headers == {"Authorization": "Bearer ns_my_secret_key"}

    def test_auth_headers_empty_when_no_key(self):
        """_auth_headers() returns empty dict when no API key configured."""
        from neurostack.cloud.client import CloudClient
        from neurostack.cloud.config import CloudConfig

        cfg = CloudConfig(cloud_api_url="https://api.neurostack.sh", cloud_api_key="")
        client = CloudClient(cfg)
        assert client._auth_headers() == {}
