# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Cloud configuration for NeuroStack.

All settings are loaded from environment variables with the NEUROSTACK_CLOUD_ prefix.
GCP-only stack: Cloud Run + Gemini API + Cloud Storage.
"""

import os
from dataclasses import dataclass

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


def load_cloud_config() -> CloudConfig:
    """Load cloud config from environment variables with NEUROSTACK_CLOUD_ prefix.

    Example: NEUROSTACK_CLOUD_GCP_PROJECT -> gcp_project
    """
    cfg = CloudConfig()

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
