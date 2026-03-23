# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Cloud configuration for NeuroStack.

All settings are loaded from defaults -> config.toml [cloud] section -> environment
variables with the NEUROSTACK_CLOUD_ prefix (highest priority).
GCP-only stack: Cloud Run + Gemini API + Cloud Storage.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # Python 3.10 fallback

import tomli_w

from neurostack.config import CONFIG_PATH

# Gemini API OpenAI-compatible base URL.
# NeuroStack's embedder appends /v1/embeddings and summarizer appends
# /v1/chat/completions — but this base already includes /v1beta/openai,
# so we set embed_url/llm_url to the full path with /v1 stripped
# (the embedder/summarizer prepend /v1/ themselves).
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"


@dataclass
class CloudConfig:
    """Cloud infrastructure settings for GCP (Cloud Storage + Gemini API)."""

    # GCP settings
    gcp_project: str = ""
    gcp_region: str = "us-central1"

    # Cloud Storage settings
    gcs_bucket_name: str = "neurostack-prod"

    # Gemini API settings
    gemini_api_key: str = ""
    gemini_embed_model: str = "gemini-embedding-001"
    gemini_llm_model: str = "gemini-2.5-flash"
    gemini_embed_dim: int = 768

    # Cloud API settings (for CLI client)
    cloud_api_url: str = ""
    cloud_api_key: str = ""


def _read_toml() -> dict:
    """Read existing config.toml or return empty dict."""
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "rb") as f:
            return tomllib.load(f)
    return {}


def _write_toml(data: dict) -> None:
    """Write config dict to config.toml, creating parent dirs if needed."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "wb") as f:
        tomli_w.dump(data, f)


def save_cloud_config(cloud_api_url: str, cloud_api_key: str) -> None:
    """Persist cloud API URL and key to config.toml [cloud] section.

    Preserves all existing config sections. Creates the config directory
    if it does not exist.
    """
    data = _read_toml()
    cloud = data.get("cloud", {})
    cloud["cloud_api_url"] = cloud_api_url
    cloud["cloud_api_key"] = cloud_api_key
    data["cloud"] = cloud
    _write_toml(data)


def clear_cloud_credentials() -> None:
    """Remove cloud_api_key from config.toml but preserve cloud_api_url.

    This allows the user to log out without losing their endpoint configuration.
    """
    data = _read_toml()
    cloud = data.get("cloud", {})
    cloud["cloud_api_key"] = ""
    data["cloud"] = cloud
    _write_toml(data)


def load_cloud_config() -> CloudConfig:
    """Load cloud config: defaults -> config.toml [cloud] -> env vars.

    Priority (highest wins):
      1. Environment variables with NEUROSTACK_CLOUD_ prefix
      2. config.toml [cloud] section
      3. Dataclass defaults
    """
    cfg = CloudConfig()

    # Layer 2: TOML [cloud] section
    data = _read_toml()
    cloud_data = data.get("cloud", {})

    str_fields = (
        "gcp_project", "gcp_region", "gcs_bucket_name",
        "gemini_api_key", "gemini_embed_model", "gemini_llm_model",
        "cloud_api_url", "cloud_api_key",
    )
    for key in str_fields:
        if key in cloud_data:
            setattr(cfg, key, cloud_data[key])

    if "gemini_embed_dim" in cloud_data:
        cfg.gemini_embed_dim = int(cloud_data["gemini_embed_dim"])

    # Layer 3: env var overrides (highest priority)
    env_map = {
        "NEUROSTACK_CLOUD_GCP_PROJECT": "gcp_project",
        "NEUROSTACK_CLOUD_GCP_REGION": "gcp_region",
        "NEUROSTACK_CLOUD_GCS_BUCKET_NAME": "gcs_bucket_name",
        "NEUROSTACK_CLOUD_GEMINI_API_KEY": "gemini_api_key",
        "NEUROSTACK_CLOUD_GEMINI_EMBED_MODEL": "gemini_embed_model",
        "NEUROSTACK_CLOUD_GEMINI_LLM_MODEL": "gemini_llm_model",
        "NEUROSTACK_CLOUD_API_URL": "cloud_api_url",
        "NEUROSTACK_CLOUD_API_KEY": "cloud_api_key",
    }

    for env_key, attr in env_map.items():
        val = os.environ.get(env_key)
        if val is not None:
            setattr(cfg, attr, val)

    # Integer fields
    dim = os.environ.get("NEUROSTACK_CLOUD_GEMINI_EMBED_DIM")
    if dim is not None:
        cfg.gemini_embed_dim = int(dim)

    return cfg
