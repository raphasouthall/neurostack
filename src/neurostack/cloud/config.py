# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Cloud configuration for NeuroStack.

All settings are loaded from environment variables with the NEUROSTACK_CLOUD_ prefix.
"""

import os
from dataclasses import dataclass


@dataclass
class CloudConfig:
    """Cloud infrastructure settings for R2 storage and Fireworks AI."""

    # R2 settings
    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket_name: str = "neurostack-prod"

    # Fireworks AI settings
    fireworks_api_key: str = ""
    fireworks_embed_model: str = "nomic-ai/nomic-embed-text-v1.5"
    fireworks_llm_model: str = "accounts/fireworks/models/qwen2p5-7b-instruct"

    # Cloud API settings
    cloud_api_url: str = ""
    cloud_api_key: str = ""

    @property
    def r2_endpoint_url(self) -> str:
        """Return the R2 S3-compatible endpoint URL."""
        return f"https://{self.r2_account_id}.r2.cloudflarestorage.com"


def load_cloud_config() -> CloudConfig:
    """Load cloud config from environment variables with NEUROSTACK_CLOUD_ prefix.

    Example: NEUROSTACK_CLOUD_R2_ACCOUNT_ID -> r2_account_id
    """
    cfg = CloudConfig()

    env_map = {
        "NEUROSTACK_CLOUD_R2_ACCOUNT_ID": "r2_account_id",
        "NEUROSTACK_CLOUD_R2_ACCESS_KEY_ID": "r2_access_key_id",
        "NEUROSTACK_CLOUD_R2_SECRET_ACCESS_KEY": "r2_secret_access_key",
        "NEUROSTACK_CLOUD_R2_BUCKET_NAME": "r2_bucket_name",
        "NEUROSTACK_CLOUD_FIREWORKS_API_KEY": "fireworks_api_key",
        "NEUROSTACK_CLOUD_FIREWORKS_EMBED_MODEL": "fireworks_embed_model",
        "NEUROSTACK_CLOUD_FIREWORKS_LLM_MODEL": "fireworks_llm_model",
        "NEUROSTACK_CLOUD_API_URL": "cloud_api_url",
        "NEUROSTACK_CLOUD_API_KEY": "cloud_api_key",
    }

    for env_key, attr in env_map.items():
        val = os.environ.get(env_key)
        if val is not None:
            setattr(cfg, attr, val)

    return cfg
