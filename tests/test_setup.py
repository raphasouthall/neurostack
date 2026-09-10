"""Tests for neurostack.setup — platform detection, MCP config merging, client setup."""

import json
from unittest.mock import patch

import pytest

from neurostack.setup import (
    _detect_platform,
    _merge_mcp_entry,
    _read_json,
    _write_json,
    setup_client,
    setup_desktop,
)


class TestDetectPlatform:
    def test_macos(self):
        with patch("neurostack.setup.platform.system", return_value="Darwin"):
            assert _detect_platform() == "macos"

    def test_windows(self):
        with patch("neurostack.setup.platform.system", return_value="Windows"):
            assert _detect_platform() == "windows"

    def test_linux(self):
        with patch("neurostack.setup.platform.system", return_value="Linux"):
            assert _detect_platform() == "linux"

    def test_unknown_falls_back_to_linux(self):
        with patch("neurostack.setup.platform.system", return_value="FreeBSD"):
            assert _detect_platform() == "linux"


class TestReadJson:
    def test_reads_valid_json(self, tmp_path):
        p = tmp_path / "config.json"
        p.write_text('{"key": "value"}', encoding="utf-8")
        assert _read_json(p) == {"key": "value"}

    def test_missing_file_returns_empty_dict(self, tmp_path):
        p = tmp_path / "nonexistent.json"
        assert _read_json(p) == {}

    def test_invalid_json_returns_empty_dict(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("not valid json {{{", encoding="utf-8")
        assert _read_json(p) == {}

    def test_empty_file_returns_empty_dict(self, tmp_path):
        p = tmp_path / "empty.json"
        p.write_text("", encoding="utf-8")
        assert _read_json(p) == {}


class TestWriteJson:
    def test_writes_json_with_newline(self, tmp_path):
        p = tmp_path / "out.json"
        _write_json(p, {"hello": "world"})
        raw = p.read_text(encoding="utf-8")
        assert raw.endswith("\n")
        assert json.loads(raw) == {"hello": "world"}

    def test_creates_parent_dirs(self, tmp_path):
        p = tmp_path / "deep" / "nested" / "config.json"
        _write_json(p, {"a": 1})
        assert p.exists()
        assert json.loads(p.read_text(encoding="utf-8")) == {"a": 1}

    def test_pretty_printed(self, tmp_path):
        p = tmp_path / "out.json"
        _write_json(p, {"a": 1})
        raw = p.read_text(encoding="utf-8")
        assert "\n" in raw.rstrip("\n")  # multi-line = indented


class TestMergeMcpEntry:
    def test_new_entry_into_empty_config(self):
        config = {}
        entry = {"command": "neurostack", "args": ["serve"], "env": {}}
        result, already = _merge_mcp_entry(config, "mcpServers", "neurostack", entry)
        assert not already
        assert result["mcpServers"]["neurostack"] == entry

    def test_new_entry_preserves_existing_servers(self):
        config = {"mcpServers": {"other-server": {"command": "other"}}}
        entry = {"command": "neurostack", "args": ["serve"], "env": {}}
        result, already = _merge_mcp_entry(config, "mcpServers", "neurostack", entry)
        assert not already
        assert "other-server" in result["mcpServers"]
        assert result["mcpServers"]["other-server"]["command"] == "other"
        assert "neurostack" in result["mcpServers"]

    def test_update_existing_entry(self):
        config = {
            "mcpServers": {
                "neurostack": {
                    "command": "/old/path",
                    "args": ["old"],
                    "env": {"CUSTOM_VAR": "keep-me"},
                }
            }
        }
        entry = {"command": "/new/path", "args": ["serve"], "env": {}}
        result, already = _merge_mcp_entry(config, "mcpServers", "neurostack", entry)
        assert already
        ns = result["mcpServers"]["neurostack"]
        assert ns["command"] == "/new/path"
        assert ns["args"] == ["serve"]
        # User env customizations preserved
        assert ns["env"] == {"CUSTOM_VAR": "keep-me"}

    def test_update_adds_env_if_missing(self):
        config = {
            "mcpServers": {
                "neurostack": {"command": "/old/path", "args": ["old"]}
            }
        }
        entry = {"command": "/new/path", "args": ["serve"], "env": {"A": "B"}}
        result, already = _merge_mcp_entry(config, "mcpServers", "neurostack", entry)
        assert already
        assert result["mcpServers"]["neurostack"]["env"] == {"A": "B"}

    def test_different_key(self):
        config = {}
        entry = {"command": "neurostack", "args": ["serve"]}
        result, already = _merge_mcp_entry(config, "servers", "neurostack", entry)
        assert not already
        assert "servers" in result
        assert result["servers"]["neurostack"] == entry


class TestSetupDesktop:
    def test_dry_run_does_not_write(self, tmp_path, capsys):
        config_path = tmp_path / "claude_desktop_config.json"
        config_path.write_text('{"mcpServers": {}}', encoding="utf-8")

        with patch("neurostack.setup._claude_desktop_config_path", return_value=config_path), \
             patch("neurostack.setup._neurostack_command", return_value="/usr/bin/neurostack"):
            setup_desktop(dry_run=True)

        captured = capsys.readouterr()
        assert "[dry-run]" in captured.out
        # File should be unchanged
        assert json.loads(config_path.read_text()) == {"mcpServers": {}}

    def test_dry_run_shows_merged_config(self, tmp_path, capsys):
        config_path = tmp_path / "claude_desktop_config.json"
        config_path.write_text('{}', encoding="utf-8")

        with patch("neurostack.setup._claude_desktop_config_path", return_value=config_path), \
             patch("neurostack.setup._neurostack_command", return_value="neurostack"):
            setup_desktop(dry_run=True)

        captured = capsys.readouterr()
        # The dry-run output should include the merged config as JSON
        assert "neurostack" in captured.out
        assert "serve" in captured.out

    def test_writes_config_on_real_run(self, tmp_path, capsys):
        config_path = tmp_path / "claude_desktop_config.json"

        with patch("neurostack.setup._claude_desktop_config_path", return_value=config_path), \
             patch("neurostack.setup._neurostack_command", return_value="neurostack"):
            setup_desktop(dry_run=False)

        data = json.loads(config_path.read_text())
        assert "mcpServers" in data
        assert "neurostack" in data["mcpServers"]
        assert data["mcpServers"]["neurostack"]["args"] == ["serve"]


class TestSetupClient:
    @pytest.mark.parametrize("client_name", ["cursor", "windsurf", "gemini", "claude-code"])
    def test_known_clients_dry_run(self, client_name, tmp_path, capsys):
        config_path = tmp_path / "mcp.json"
        config_path.write_text('{}', encoding="utf-8")

        from neurostack.setup import CLIENT_CONFIGS as _cfgs

        override = {
            client_name: {**_cfgs[client_name], "path": lambda p=config_path: p},
        }
        with (
            patch.dict("neurostack.setup.CLIENT_CONFIGS", override),
            patch("neurostack.setup._neurostack_command", return_value="neurostack"),
        ):
            setup_client(client_name, dry_run=True)

        captured = capsys.readouterr()
        assert "[dry-run]" in captured.out

    def test_vscode_entry_has_type_stdio(self, tmp_path, capsys):
        config_path = tmp_path / "mcp.json"
        config_path.write_text('{}', encoding="utf-8")

        from neurostack.setup import CLIENT_CONFIGS as _cfgs

        override = {
            "vscode": {**_cfgs["vscode"], "path": lambda p=config_path: p},
        }
        with (
            patch.dict("neurostack.setup.CLIENT_CONFIGS", override),
            patch("neurostack.setup._neurostack_command", return_value="neurostack"),
        ):
            setup_client("vscode", dry_run=True)

        captured = capsys.readouterr()
        # VS Code entry should have "type": "stdio"
        assert '"type": "stdio"' in captured.out

    def test_unknown_client_exits(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            setup_client("not-a-real-client")
        assert exc_info.value.code == 1

    def test_unknown_client_prints_supported(self, capsys):
        with pytest.raises(SystemExit):
            setup_client("bogus-editor")
        captured = capsys.readouterr()
        assert "Unknown client" in captured.err
        assert "Supported clients" in captured.err

    def test_client_name_normalisation(self, tmp_path, capsys):
        """Client names are lowercased and spaces become hyphens."""
        config_path = tmp_path / "mcp.json"
        config_path.write_text('{}', encoding="utf-8")

        from neurostack.setup import CLIENT_CONFIGS as _cfgs

        override = {
            "claude-code": {
                **_cfgs["claude-code"],
                "path": lambda p=config_path: p,
            },
        }
        with (
            patch.dict("neurostack.setup.CLIENT_CONFIGS", override),
            patch("neurostack.setup._neurostack_command", return_value="neurostack"),
        ):
            setup_client("Claude Code", dry_run=True)

        captured = capsys.readouterr()
        assert "[dry-run]" in captured.out
