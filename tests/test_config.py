"""Tests for neurostack.config — TOML loading and env var overrides."""

import os
from pathlib import Path
from unittest.mock import patch

from neurostack.config import Config, RankingWeights, load_config


class TestConfig:
    def test_defaults(self):
        cfg = Config()
        assert cfg.embed_model == "nomic-embed-text"
        assert cfg.embed_dim == 768
        assert cfg.llm_model == "phi3.5"
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


class TestRankingWeights:
    """Ranking-signal weights (issue #66): config plumbing + RankingWeights."""

    def test_config_defaults_reproduce_prod_constants(self):
        cfg = Config()
        assert cfg.convergence_weight == 0.3
        assert cfg.hotness_weight == 0.2
        assert cfg.inhibition_threshold == 0.65
        assert cfg.inhibition_strength == 0.30

    def test_weights_defaults_match_config_defaults(self):
        # A default RankingWeights and one built from a default Config must agree,
        # or hybrid_search(weights=None) and hybrid_search(weights=RankingWeights())
        # would diverge.
        assert RankingWeights() == RankingWeights.from_config(Config())

    def test_from_config_reads_fields(self):
        cfg = Config(
            convergence_weight=0.5,
            hotness_weight=0.05,
            inhibition_threshold=0.8,
            inhibition_strength=0.15,
            cooccurrence_boost_weight=0.2,
            link_section_penalty=0.7,
            link_density_threshold=0.6,
        )
        w = RankingWeights.from_config(cfg)
        assert w.convergence_weight == 0.5
        assert w.hotness_weight == 0.05
        assert w.inhibition_threshold == 0.8
        assert w.inhibition_strength == 0.15
        assert w.cooccurrence_boost_weight == 0.2
        assert w.link_section_penalty == 0.7
        assert w.link_density_threshold == 0.6

    def test_weights_are_frozen(self):
        import dataclasses

        import pytest
        w = RankingWeights()
        with pytest.raises(dataclasses.FrozenInstanceError):
            w.convergence_weight = 0.9  # type: ignore[misc]

    def test_env_overrides(self):
        env = {
            "NEUROSTACK_CONVERGENCE_WEIGHT": "0.42",
            "NEUROSTACK_HOTNESS_WEIGHT": "0.11",
            "NEUROSTACK_INHIBITION_THRESHOLD": "0.7",
            "NEUROSTACK_INHIBITION_STRENGTH": "0.2",
        }
        with patch.dict(os.environ, env):
            cfg = load_config()
        assert cfg.convergence_weight == 0.42
        assert cfg.hotness_weight == 0.11
        assert cfg.inhibition_threshold == 0.7
        assert cfg.inhibition_strength == 0.2

    def test_toml_config(self, tmp_path):
        config_file = tmp_path / "config.toml"
        config_file.write_text(
            "convergence_weight = 0.25\ninhibition_strength = 0.15\n"
        )
        with patch("neurostack.config.CONFIG_PATH", config_file):
            cfg = load_config()
        assert cfg.convergence_weight == 0.25
        assert cfg.inhibition_strength == 0.15
        assert cfg.hotness_weight == 0.2  # untouched key keeps default
