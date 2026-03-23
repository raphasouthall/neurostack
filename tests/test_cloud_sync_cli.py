# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Tests for cloud sync CLI subcommands (push, pull, query)."""

from __future__ import annotations

import json
import sys
from argparse import Namespace
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

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
    }
    defaults.update(kwargs)
    return Namespace(**defaults)


def _authed_config(url: str = "https://api.test", key: str = "test-key") -> CloudConfig:
    return CloudConfig(cloud_api_url=url, cloud_api_key=key)


def _empty_config() -> CloudConfig:
    return CloudConfig(cloud_api_url="", cloud_api_key="")


def _mock_get_config(tmp_path):
    """Return a mock Config with vault_root and db_dir set to tmp_path."""
    cfg = MagicMock()
    cfg.vault_root = tmp_path
    cfg.db_dir = tmp_path / "db"
    return cfg


# ---------------------------------------------------------------------------
# Test 1: push with no credentials prints auth error and exits 1
# ---------------------------------------------------------------------------

class TestCloudPushNoAuth:
    @patch("neurostack.cloud.config.load_cloud_config")
    @patch("neurostack.cli.get_config")
    def test_push_no_credentials_exits_1(self, mock_cfg, mock_cloud_cfg, tmp_path, capsys):
        """Push without credentials prints auth error and exits 1."""
        mock_cfg.return_value = _mock_get_config(tmp_path)
        mock_cloud_cfg.return_value = _empty_config()

        from neurostack.cli import cmd_cloud_push
        args = _make_args(cloud_command="push")
        with pytest.raises(SystemExit, match="1"):
            cmd_cloud_push(args)

        err = capsys.readouterr().err
        assert "Not authenticated" in err


# ---------------------------------------------------------------------------
# Test 2: push with valid credentials calls VaultSyncEngine.push()
# ---------------------------------------------------------------------------

class TestCloudPushSuccess:
    @patch("neurostack.cloud.sync.VaultSyncEngine")
    @patch("neurostack.cloud.config.load_cloud_config")
    @patch("neurostack.cli.get_config")
    def test_push_success(self, mock_cfg, mock_cloud_cfg, mock_engine_cls, tmp_path, capsys):
        """Push with valid credentials calls engine.push and prints result."""
        mock_cfg.return_value = _mock_get_config(tmp_path)
        mock_cloud_cfg.return_value = _authed_config()

        mock_engine = MagicMock()
        mock_engine.push.return_value = {
            "status": "complete",
            "message": "Pushed 5 files",
            "note_count": 5,
        }
        mock_engine_cls.return_value = mock_engine

        from neurostack.cli import cmd_cloud_push
        args = _make_args(cloud_command="push")
        cmd_cloud_push(args)

        mock_engine.push.assert_called_once()
        out = capsys.readouterr().out
        assert "Pushed 5 files" in out


# ---------------------------------------------------------------------------
# Test 3: push --json outputs JSON result
# ---------------------------------------------------------------------------

class TestCloudPushJson:
    @patch("neurostack.cloud.sync.VaultSyncEngine")
    @patch("neurostack.cloud.config.load_cloud_config")
    @patch("neurostack.cli.get_config")
    def test_push_json(self, mock_cfg, mock_cloud_cfg, mock_engine_cls, tmp_path, capsys):
        """Push with --json outputs JSON."""
        mock_cfg.return_value = _mock_get_config(tmp_path)
        mock_cloud_cfg.return_value = _authed_config()

        result_dict = {"status": "complete", "message": "Pushed 5 files", "note_count": 5}
        mock_engine = MagicMock()
        mock_engine.push.return_value = result_dict
        mock_engine_cls.return_value = mock_engine

        from neurostack.cli import cmd_cloud_push
        args = _make_args(cloud_command="push", json=True)
        cmd_cloud_push(args)

        out = capsys.readouterr().out
        parsed = json.loads(out)
        assert parsed["status"] == "complete"
        assert parsed["note_count"] == 5


# ---------------------------------------------------------------------------
# Test 4: pull with valid credentials calls engine.pull() and prints path
# ---------------------------------------------------------------------------

class TestCloudPullSuccess:
    @patch("neurostack.cloud.sync.VaultSyncEngine")
    @patch("neurostack.cloud.config.load_cloud_config")
    @patch("neurostack.cli.get_config")
    def test_pull_success(self, mock_cfg, mock_cloud_cfg, mock_engine_cls, tmp_path, capsys):
        """Pull calls engine.pull and prints download path."""
        mock_cfg.return_value = _mock_get_config(tmp_path)
        mock_cloud_cfg.return_value = _authed_config()

        # Create a fake DB file so stat() works
        db_path = tmp_path / "db" / "neurostack.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        db_path.write_bytes(b"x" * 1024 * 1024)  # 1 MB

        mock_engine = MagicMock()
        mock_engine.pull.return_value = db_path
        mock_engine_cls.return_value = mock_engine

        from neurostack.cli import cmd_cloud_pull
        args = _make_args(cloud_command="pull")
        cmd_cloud_pull(args)

        mock_engine.pull.assert_called_once()
        out = capsys.readouterr().out
        assert "Downloaded database" in out
        assert "1.0 MB" in out


# ---------------------------------------------------------------------------
# Test 5: pull --json outputs JSON with db_path and size
# ---------------------------------------------------------------------------

class TestCloudPullJson:
    @patch("neurostack.cloud.sync.VaultSyncEngine")
    @patch("neurostack.cloud.config.load_cloud_config")
    @patch("neurostack.cli.get_config")
    def test_pull_json(self, mock_cfg, mock_cloud_cfg, mock_engine_cls, tmp_path, capsys):
        """Pull with --json outputs JSON with db_path and size."""
        mock_cfg.return_value = _mock_get_config(tmp_path)
        mock_cloud_cfg.return_value = _authed_config()

        db_path = tmp_path / "db" / "neurostack.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        db_path.write_bytes(b"x" * 2048)

        mock_engine = MagicMock()
        mock_engine.pull.return_value = db_path
        mock_engine_cls.return_value = mock_engine

        from neurostack.cli import cmd_cloud_pull
        args = _make_args(cloud_command="pull", json=True)
        cmd_cloud_pull(args)

        out = capsys.readouterr().out
        parsed = json.loads(out)
        assert parsed["db_path"] == str(db_path)
        assert parsed["size"] == 2048


# ---------------------------------------------------------------------------
# Test 6: query calls engine.query() and prints formatted results
# ---------------------------------------------------------------------------

class TestCloudQuerySuccess:
    @patch("neurostack.cloud.sync.VaultSyncEngine")
    @patch("neurostack.cloud.config.load_cloud_config")
    @patch("neurostack.cli.get_config")
    def test_query_success(self, mock_cfg, mock_cloud_cfg, mock_engine_cls, tmp_path, capsys):
        """Query prints formatted results."""
        mock_cfg.return_value = _mock_get_config(tmp_path)
        mock_cloud_cfg.return_value = _authed_config()

        mock_engine = MagicMock()
        mock_engine.query.return_value = [
            {"title": "Note A", "score": 0.95, "snippet": "This is about testing"},
            {"title": "Note B", "score": 0.82, "snippet": "Another result"},
        ]
        mock_engine_cls.return_value = mock_engine

        from neurostack.cli import cmd_cloud_query
        args = _make_args(cloud_command="query", query="test", top_k=10, mode="hybrid")
        cmd_cloud_query(args)

        mock_engine.query.assert_called_once_with("test", top_k=10, mode="hybrid")
        out = capsys.readouterr().out
        assert "Note A" in out
        assert "0.950" in out
        assert "Note B" in out

    @patch("neurostack.cloud.sync.VaultSyncEngine")
    @patch("neurostack.cloud.config.load_cloud_config")
    @patch("neurostack.cli.get_config")
    def test_query_no_results(self, mock_cfg, mock_cloud_cfg, mock_engine_cls, tmp_path, capsys):
        """Query with no results prints 'No results found.'."""
        mock_cfg.return_value = _mock_get_config(tmp_path)
        mock_cloud_cfg.return_value = _authed_config()

        mock_engine = MagicMock()
        mock_engine.query.return_value = []
        mock_engine_cls.return_value = mock_engine

        from neurostack.cli import cmd_cloud_query
        args = _make_args(cloud_command="query", query="nonexistent", top_k=10, mode="hybrid")
        cmd_cloud_query(args)

        out = capsys.readouterr().out
        assert "No results found" in out


# ---------------------------------------------------------------------------
# Test 7: query --json outputs JSON results
# ---------------------------------------------------------------------------

class TestCloudQueryJson:
    @patch("neurostack.cloud.sync.VaultSyncEngine")
    @patch("neurostack.cloud.config.load_cloud_config")
    @patch("neurostack.cli.get_config")
    def test_query_json(self, mock_cfg, mock_cloud_cfg, mock_engine_cls, tmp_path, capsys):
        """Query with --json outputs JSON array."""
        mock_cfg.return_value = _mock_get_config(tmp_path)
        mock_cloud_cfg.return_value = _authed_config()

        results = [{"title": "Note A", "score": 0.95}]
        mock_engine = MagicMock()
        mock_engine.query.return_value = results
        mock_engine_cls.return_value = mock_engine

        from neurostack.cli import cmd_cloud_query
        args = _make_args(cloud_command="query", query="test", top_k=10, mode="hybrid", json=True)
        cmd_cloud_query(args)

        out = capsys.readouterr().out
        parsed = json.loads(out)
        assert len(parsed) == 1
        assert parsed[0]["title"] == "Note A"


# ---------------------------------------------------------------------------
# Test 8: query --top-k 5 --mode semantic passes args correctly
# ---------------------------------------------------------------------------

class TestCloudQueryArgs:
    @patch("neurostack.cloud.sync.VaultSyncEngine")
    @patch("neurostack.cloud.config.load_cloud_config")
    @patch("neurostack.cli.get_config")
    def test_query_custom_args(self, mock_cfg, mock_cloud_cfg, mock_engine_cls, tmp_path):
        """Query passes top_k and mode to engine correctly."""
        mock_cfg.return_value = _mock_get_config(tmp_path)
        mock_cloud_cfg.return_value = _authed_config()

        mock_engine = MagicMock()
        mock_engine.query.return_value = []
        mock_engine_cls.return_value = mock_engine

        from neurostack.cli import cmd_cloud_query
        args = _make_args(cloud_command="query", query="hello", top_k=5, mode="semantic")
        cmd_cloud_query(args)

        mock_engine.query.assert_called_once_with("hello", top_k=5, mode="semantic")


# ---------------------------------------------------------------------------
# Test 9: All commands exit 1 with SyncError message on failure
# ---------------------------------------------------------------------------

class TestCloudSyncErrors:
    @patch("neurostack.cloud.sync.VaultSyncEngine")
    @patch("neurostack.cloud.config.load_cloud_config")
    @patch("neurostack.cli.get_config")
    def test_push_sync_error(self, mock_cfg, mock_cloud_cfg, mock_engine_cls, tmp_path, capsys):
        """Push exits 1 and prints error on SyncError."""
        from neurostack.cloud.sync import SyncError

        mock_cfg.return_value = _mock_get_config(tmp_path)
        mock_cloud_cfg.return_value = _authed_config()

        mock_engine = MagicMock()
        mock_engine.push.side_effect = SyncError("Upload failed: server error")
        mock_engine_cls.return_value = mock_engine

        from neurostack.cli import cmd_cloud_push
        args = _make_args(cloud_command="push")
        with pytest.raises(SystemExit, match="1"):
            cmd_cloud_push(args)

        err = capsys.readouterr().err
        assert "Upload failed: server error" in err

    @patch("neurostack.cloud.sync.VaultSyncEngine")
    @patch("neurostack.cloud.config.load_cloud_config")
    @patch("neurostack.cli.get_config")
    def test_pull_sync_error(self, mock_cfg, mock_cloud_cfg, mock_engine_cls, tmp_path, capsys):
        """Pull exits 1 and prints error on SyncError."""
        from neurostack.cloud.sync import SyncError

        mock_cfg.return_value = _mock_get_config(tmp_path)
        mock_cloud_cfg.return_value = _authed_config()

        mock_engine = MagicMock()
        mock_engine.pull.side_effect = SyncError("Download failed")
        mock_engine_cls.return_value = mock_engine

        from neurostack.cli import cmd_cloud_pull
        args = _make_args(cloud_command="pull")
        with pytest.raises(SystemExit, match="1"):
            cmd_cloud_pull(args)

        err = capsys.readouterr().err
        assert "Download failed" in err

    @patch("neurostack.cloud.sync.VaultSyncEngine")
    @patch("neurostack.cloud.config.load_cloud_config")
    @patch("neurostack.cli.get_config")
    def test_query_sync_error(self, mock_cfg, mock_cloud_cfg, mock_engine_cls, tmp_path, capsys):
        """Query exits 1 and prints error on SyncError."""
        from neurostack.cloud.sync import SyncError

        mock_cfg.return_value = _mock_get_config(tmp_path)
        mock_cloud_cfg.return_value = _authed_config()

        mock_engine = MagicMock()
        mock_engine.query.side_effect = SyncError("Query API not available")
        mock_engine_cls.return_value = mock_engine

        from neurostack.cli import cmd_cloud_query
        args = _make_args(cloud_command="query", query="test", top_k=10, mode="hybrid")
        with pytest.raises(SystemExit, match="1"):
            cmd_cloud_query(args)

        err = capsys.readouterr().err
        assert "Query API not available" in err

    @patch("neurostack.cloud.config.load_cloud_config")
    @patch("neurostack.cli.get_config")
    def test_pull_no_credentials_exits_1(self, mock_cfg, mock_cloud_cfg, tmp_path, capsys):
        """Pull without credentials prints auth error and exits 1."""
        mock_cfg.return_value = _mock_get_config(tmp_path)
        mock_cloud_cfg.return_value = _empty_config()

        from neurostack.cli import cmd_cloud_pull
        args = _make_args(cloud_command="pull")
        with pytest.raises(SystemExit, match="1"):
            cmd_cloud_pull(args)

        err = capsys.readouterr().err
        assert "Not authenticated" in err

    @patch("neurostack.cloud.config.load_cloud_config")
    @patch("neurostack.cli.get_config")
    def test_query_no_credentials_exits_1(self, mock_cfg, mock_cloud_cfg, tmp_path, capsys):
        """Query without credentials prints auth error and exits 1."""
        mock_cfg.return_value = _mock_get_config(tmp_path)
        mock_cloud_cfg.return_value = _empty_config()

        from neurostack.cli import cmd_cloud_query
        args = _make_args(cloud_command="query", query="test", top_k=10, mode="hybrid")
        with pytest.raises(SystemExit, match="1"):
            cmd_cloud_query(args)

        err = capsys.readouterr().err
        assert "Not authenticated" in err
