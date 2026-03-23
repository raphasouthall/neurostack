# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Tests for neurostack cloud CLI subcommands (login, logout, status, setup)."""

from __future__ import annotations

import json
import sys
from argparse import Namespace
from unittest.mock import MagicMock, patch

import pytest

from neurostack.cloud.config import CloudConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_args(**kwargs) -> Namespace:
    """Build a minimal argparse Namespace for cmd_cloud."""
    defaults = {
        "command": "cloud",
        "cloud_command": None,
        "json": False,
        "key": None,
    }
    defaults.update(kwargs)
    return Namespace(**defaults)


def _mock_cloud_config(url: str = "", key: str = "") -> CloudConfig:
    return CloudConfig(cloud_api_url=url, cloud_api_key=key)


# ---------------------------------------------------------------------------
# Test 1: login --key with valid key saves config
# ---------------------------------------------------------------------------

class TestCloudLogin:
    @patch("neurostack.cli.CloudClient")
    @patch("neurostack.cli.save_cloud_config")
    @patch("neurostack.cli.load_cloud_config")
    def test_login_valid_key_saves(self, mock_load, mock_save, mock_client_cls, capsys):
        """Login with --key and valid key prints success and saves."""
        mock_load.return_value = _mock_cloud_config(
            url="https://neurostack-api-911077737485.us-central1.run.app"
        )
        mock_client = MagicMock()
        mock_client.validate_key.return_value = True
        mock_client_cls.return_value = mock_client

        from neurostack.cli import cmd_cloud
        args = _make_args(cloud_command="login", key="sk-test123")
        cmd_cloud(args)

        out = capsys.readouterr().out
        assert "Logged in" in out
        mock_save.assert_called_once()
        call_kwargs = mock_save.call_args
        assert call_kwargs[1]["cloud_api_key"] == "sk-test123"

    # Test 2: login --key with invalid key does NOT save
    @patch("neurostack.cli.CloudClient")
    @patch("neurostack.cli.save_cloud_config")
    @patch("neurostack.cli.load_cloud_config")
    def test_login_invalid_key_errors(self, mock_load, mock_save, mock_client_cls, capsys):
        """Login with invalid key prints error, does not save, exits 1."""
        mock_load.return_value = _mock_cloud_config(
            url="https://neurostack-api-911077737485.us-central1.run.app"
        )
        mock_client = MagicMock()
        mock_client.validate_key.return_value = False
        mock_client_cls.return_value = mock_client

        from neurostack.cli import cmd_cloud
        args = _make_args(cloud_command="login", key="sk-bad")
        with pytest.raises(SystemExit, match="1"):
            cmd_cloud(args)

        out = capsys.readouterr().out
        assert "Invalid API key" in out
        mock_save.assert_not_called()

    # Test 3: login without --key prompts interactively
    @patch("neurostack.cli.CloudClient")
    @patch("neurostack.cli.save_cloud_config")
    @patch("neurostack.cli.load_cloud_config")
    @patch("builtins.input", return_value="sk-interactive")
    def test_login_interactive_prompt(self, mock_input, mock_load, mock_save, mock_client_cls, capsys):
        """Login without --key prompts for input."""
        mock_load.return_value = _mock_cloud_config(
            url="https://neurostack-api-911077737485.us-central1.run.app"
        )
        mock_client = MagicMock()
        mock_client.validate_key.return_value = True
        mock_client_cls.return_value = mock_client

        from neurostack.cli import cmd_cloud
        args = _make_args(cloud_command="login", key=None)
        cmd_cloud(args)

        mock_input.assert_called_once()
        out = capsys.readouterr().out
        assert "Logged in" in out
        mock_save.assert_called_once()


# ---------------------------------------------------------------------------
# Test 4: logout clears credentials
# ---------------------------------------------------------------------------

class TestCloudLogout:
    @patch("neurostack.cli.clear_cloud_credentials")
    def test_logout_clears_and_confirms(self, mock_clear, capsys):
        """Logout calls clear_cloud_credentials and prints confirmation."""
        from neurostack.cli import cmd_cloud
        args = _make_args(cloud_command="logout")
        cmd_cloud(args)

        mock_clear.assert_called_once()
        out = capsys.readouterr().out
        assert "Logged out" in out
        assert "credentials cleared" in out.lower()


# ---------------------------------------------------------------------------
# Tests 5-7: status command
# ---------------------------------------------------------------------------

class TestCloudStatus:
    # Test 5: status when authenticated
    @patch("neurostack.cli.CloudClient")
    @patch("neurostack.cli.load_cloud_config")
    def test_status_authenticated(self, mock_load, mock_client_cls, capsys):
        """Status shows Authenticated, cloud URL, and tier when configured."""
        mock_load.return_value = _mock_cloud_config(
            url="https://neurostack-api-911077737485.us-central1.run.app",
            key="sk-valid",
        )
        mock_client = MagicMock()
        mock_client.is_configured = True
        mock_client.status.return_value = {
            "authenticated": True,
            "tier": "free",
            "cloud_url": "https://neurostack-api-911077737485.us-central1.run.app",
        }
        mock_client_cls.return_value = mock_client

        from neurostack.cli import cmd_cloud
        args = _make_args(cloud_command="status")
        cmd_cloud(args)

        out = capsys.readouterr().out
        assert "Authenticated" in out
        assert "neurostack-api" in out
        assert "free" in out

    # Test 6: status when NOT authenticated
    @patch("neurostack.cli.CloudClient")
    @patch("neurostack.cli.load_cloud_config")
    def test_status_not_authenticated(self, mock_load, mock_client_cls, capsys):
        """Status shows 'Not authenticated' when no key is stored."""
        mock_load.return_value = _mock_cloud_config(url="", key="")
        mock_client = MagicMock()
        mock_client.is_configured = False
        mock_client_cls.return_value = mock_client

        from neurostack.cli import cmd_cloud
        args = _make_args(cloud_command="status")
        cmd_cloud(args)

        out = capsys.readouterr().out
        assert "Not authenticated" in out

    # Test 7: status --json returns machine-readable JSON
    @patch("neurostack.cli.CloudClient")
    @patch("neurostack.cli.load_cloud_config")
    def test_status_json_output(self, mock_load, mock_client_cls, capsys):
        """status --json returns JSON with authenticated, cloud_url, tier."""
        mock_load.return_value = _mock_cloud_config(
            url="https://neurostack-api-911077737485.us-central1.run.app",
            key="sk-valid",
        )
        mock_client = MagicMock()
        mock_client.is_configured = True
        mock_client.status.return_value = {
            "authenticated": True,
            "tier": "free",
            "cloud_url": "https://neurostack-api-911077737485.us-central1.run.app",
        }
        mock_client_cls.return_value = mock_client

        from neurostack.cli import cmd_cloud
        args = _make_args(cloud_command="status", json=True)
        cmd_cloud(args)

        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["authenticated"] is True
        assert "cloud_url" in data
        assert data["tier"] == "free"


# ---------------------------------------------------------------------------
# Test 8: setup prompts for URL and key, validates, saves
# ---------------------------------------------------------------------------

class TestCloudSetup:
    @patch("neurostack.cli.CloudClient")
    @patch("neurostack.cli.save_cloud_config")
    @patch("neurostack.cli.load_cloud_config")
    @patch("builtins.input", side_effect=["https://custom.api.dev", "sk-setup-key"])
    def test_setup_interactive(self, mock_input, mock_load, mock_save, mock_client_cls, capsys):
        """Setup prompts for URL and key, validates, saves both."""
        mock_load.return_value = _mock_cloud_config()
        mock_client = MagicMock()
        mock_client.validate_key.return_value = True
        mock_client_cls.return_value = mock_client

        from neurostack.cli import cmd_cloud
        args = _make_args(cloud_command="setup")
        cmd_cloud(args)

        out = capsys.readouterr().out
        assert "configured" in out.lower() or "Authenticated" in out
        mock_save.assert_called_once_with(
            cloud_api_url="https://custom.api.dev",
            cloud_api_key="sk-setup-key",
        )


# ---------------------------------------------------------------------------
# Test 9: no subcommand prints usage
# ---------------------------------------------------------------------------

class TestCloudNoSubcommand:
    def test_no_subcommand_prints_usage(self, capsys):
        """cloud with no subcommand prints usage help."""
        from neurostack.cli import cmd_cloud
        args = _make_args(cloud_command=None)
        cmd_cloud(args)

        out = capsys.readouterr().out
        assert "login" in out
        assert "logout" in out
        assert "status" in out
        assert "setup" in out
