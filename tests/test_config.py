"""Tests for neurostack.config — TOML loading and env var overrides."""

import os
from pathlib import Path
from unittest.mock import patch

from neurostack.config import Config, load_config


class TestConfig:
    def test_defaults(self):
        cfg = Config()
        assert cfg.embed_model == "nomic-embed-text"
        assert cfg.embed_dim == 768
        assert cfg.llm_model == "qwen2.5:3b"
        assert isinstance(cfg.vault_root, Path)
        assert isinstance(cfg.db_dir, Path)

    def test_db_path_property(self):
        cfg = Config()
        assert cfg.db_path == cfg.db_dir / "neurostack.db"

    def test_session_db_property(self):
        cfg = Config()
        assert cfg.session_db == cfg.db_dir / "sessions.db"


class TestLoadConfig:
    def test_env_var_override(self):
        with patch.dict(os.environ, {"NEUROSTACK_EMBED_DIM": "384"}):
            cfg = load_config()
            assert cfg.embed_dim == 384

    def test_env_var_path_override(self, tmp_path):
        with patch.dict(os.environ, {"NEUROSTACK_VAULT_ROOT": str(tmp_path)}):
            cfg = load_config()
            assert cfg.vault_root == tmp_path

    def test_env_var_string_override(self):
        with patch.dict(os.environ, {"NEUROSTACK_LLM_MODEL": "llama3.2:3b"}):
            cfg = load_config()
            assert cfg.llm_model == "llama3.2:3b"

    def test_toml_config(self, tmp_path):
        config_file = tmp_path / "config.toml"
        config_file.write_text(
            'embed_model = "custom-model"\nembed_dim = 512\n'
        )
        with patch("neurostack.config.CONFIG_PATH", config_file):
            cfg = load_config()
            assert cfg.embed_model == "custom-model"
            assert cfg.embed_dim == 512

    def test_env_overrides_toml(self, tmp_path):
        config_file = tmp_path / "config.toml"
        config_file.write_text('embed_dim = 512\n')
        with patch("neurostack.config.CONFIG_PATH", config_file), \
             patch.dict(os.environ, {"NEUROSTACK_EMBED_DIM": "256"}):
            cfg = load_config()
            assert cfg.embed_dim == 256

    def test_missing_toml(self, tmp_path):
        config_file = tmp_path / "nonexistent.toml"
        with patch("neurostack.config.CONFIG_PATH", config_file):
            cfg = load_config()
            assert cfg.embed_model == "nomic-embed-text"  # defaults
