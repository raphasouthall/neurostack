# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Cloud client configuration for NeuroStack.

Client-side settings for connecting to NeuroStack Cloud.
Loaded from defaults -> config.toml [cloud] section -> environment variables.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # Python 3.10 fallback

import tomli_w


def _get_config_path():
    """Get CONFIG_PATH lazily to avoid circular import with neurostack.config."""
    from neurostack.config import CONFIG_PATH
    return CONFIG_PATH


@dataclass
class CloudConfig:
    """Client-side cloud settings for connecting to NeuroStack Cloud."""

    cloud_api_url: str = ""
    cloud_api_key: str = ""
    consent_given: bool = False
    consent_date: str = ""


def _read_toml() -> dict:
    """Read existing config.toml or return empty dict."""
    config_path = _get_config_path()
    if config_path.exists():
        with open(config_path, "rb") as f:
            return tomllib.load(f)
    return {}


def _write_toml(data: dict) -> None:
    """Write config dict to config.toml, creating parent dirs if needed."""
    config_path = _get_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "wb") as f:
        tomli_w.dump(data, f)


def save_cloud_config(cloud_api_url: str, cloud_api_key: str) -> None:
    """Persist cloud API URL and key to config.toml [cloud] section."""
    data = _read_toml()
    cloud = data.get("cloud", {})
    cloud["cloud_api_url"] = cloud_api_url
    cloud["cloud_api_key"] = cloud_api_key
    data["cloud"] = cloud
    _write_toml(data)


def save_consent() -> None:
    """Record that the user has granted cloud consent in config.toml."""
    from datetime import datetime, timezone

    data = _read_toml()
    cloud = data.get("cloud", {})
    cloud["consent_given"] = True
    cloud["consent_date"] = datetime.now(timezone.utc).isoformat()
    data["cloud"] = cloud
    _write_toml(data)


def clear_cloud_credentials() -> None:
    """Remove cloud_api_key from config.toml but preserve cloud_api_url."""
    data = _read_toml()
    cloud = data.get("cloud", {})
    cloud["cloud_api_key"] = ""
    data["cloud"] = cloud
    _write_toml(data)


def load_cloud_config() -> CloudConfig:
    """Load cloud client config: defaults -> config.toml [cloud] -> env vars."""
    cfg = CloudConfig()

    # Layer 2: TOML [cloud] section
    data = _read_toml()
    cloud_data = data.get("cloud", {})

    for key in ("cloud_api_url", "cloud_api_key", "consent_date"):
        if key in cloud_data:
            setattr(cfg, key, cloud_data[key])

    if "consent_given" in cloud_data:
        cfg.consent_given = bool(cloud_data["consent_given"])

    # Layer 3: env var overrides (highest priority)
    env_map = {
        "NEUROSTACK_CLOUD_API_URL": "cloud_api_url",
        "NEUROSTACK_CLOUD_API_KEY": "cloud_api_key",
    }

    for env_key, attr in env_map.items():
        val = os.environ.get(env_key)
        if val is not None:
            setattr(cfg, attr, val)

    return cfg
