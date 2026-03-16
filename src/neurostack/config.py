# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Unified configuration for NeuroStack."""

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # Python 3.10 fallback


CONFIG_PATH = Path.home() / ".config" / "neurostack" / "config.toml"


@dataclass
class Config:
    """NeuroStack configuration with env var overrides."""

    vault_root: Path = field(default_factory=lambda: Path.home() / "brain")
    db_dir: Path = field(default_factory=lambda: Path.home() / ".local" / "share" / "neurostack")
    embed_url: str = "http://localhost:11435"
    embed_model: str = "nomic-embed-text"
    embed_dim: int = 768
    llm_url: str = "http://localhost:11434"
    # NOTE: Verify the license of any model you configure here.
    # phi3.5 is MIT licensed.
    llm_model: str = "phi3.5"
    session_dir: Path = field(default_factory=lambda: Path.home() / ".claude" / "projects")
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    api_key: str = ""

    @property
    def db_path(self) -> Path:
        return self.db_dir / "neurostack.db"

    @property
    def session_db(self) -> Path:
        return self.db_dir / "sessions.db"


def load_config() -> Config:
    """Load config from TOML file, then apply env var overrides."""
    cfg = Config()

    # Load TOML if exists
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "rb") as f:
            data = tomllib.load(f)

        for key in ("vault_root", "db_dir", "session_dir"):
            if key in data:
                setattr(cfg, key, Path(os.path.expanduser(data[key])))
        for key in ("embed_url", "embed_model", "llm_url", "llm_model",
                    "api_host", "api_key"):
            if key in data:
                setattr(cfg, key, data[key])
        if "embed_dim" in data:
            cfg.embed_dim = int(data["embed_dim"])
        if "api_port" in data:
            cfg.api_port = int(data["api_port"])

    # Env var overrides (NEUROSTACK_ prefix)
    env_map = {
        "NEUROSTACK_VAULT_ROOT": ("vault_root", Path),
        "NEUROSTACK_DB_DIR": ("db_dir", Path),
        "NEUROSTACK_EMBED_URL": ("embed_url", str),
        "NEUROSTACK_EMBED_MODEL": ("embed_model", str),
        "NEUROSTACK_EMBED_DIM": ("embed_dim", int),
        "NEUROSTACK_LLM_URL": ("llm_url", str),
        "NEUROSTACK_LLM_MODEL": ("llm_model", str),
        "NEUROSTACK_SESSION_DIR": ("session_dir", Path),
        "NEUROSTACK_API_HOST": ("api_host", str),
        "NEUROSTACK_API_PORT": ("api_port", int),
        "NEUROSTACK_API_KEY": ("api_key", str),
    }

    for env_key, (attr, typ) in env_map.items():
        val = os.environ.get(env_key)
        if val is not None:
            if typ == Path:
                setattr(cfg, attr, Path(os.path.expanduser(val)))
            else:
                setattr(cfg, attr, typ(val))

    return cfg


# Module-level singleton
_config: Config | None = None


def get_config() -> Config:
    """Get or create the singleton config instance."""
    global _config
    if _config is None:
        _config = load_config()
    return _config
