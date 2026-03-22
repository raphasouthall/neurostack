# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Cloud configuration for NeuroStack.

All settings are loaded from environment variables with the NEUROSTACK_CLOUD_ prefix.
GCP-only stack: Cloud Run + Vertex AI + Cloud Storage.
"""

import os
from dataclasses import dataclass


@dataclass
class CloudConfig:
    """Cloud infrastructure settings for GCP (Cloud Storage + Vertex AI)."""

    # GCP settings
    gcp_project: str = ""
    gcp_region: str = "us-central1"

    # Cloud Storage settings
    gcs_bucket_name: str = "neurostack-prod"

    # Vertex AI settings
    vertex_embed_model: str = "text-embedding-005"
    vertex_llm_model: str = "gemini-2.0-flash"

    # Cloud API settings (for CLI client)
    cloud_api_url: str = ""
    cloud_api_key: str = ""

    @property
    def vertex_base_url(self) -> str:
        """Return the Vertex AI OpenAI-compatible base URL.

        Vertex AI exposes an OpenAI-compatible endpoint at this path.
        NeuroStack's embedder appends /v1/embeddings and summarizer
        appends /v1/chat/completions, so this must NOT include /v1.
        """
        return (
            f"https://{self.gcp_region}-aiplatform.googleapis.com/"
            f"v1beta1/projects/{self.gcp_project}/locations/{self.gcp_region}/"
            f"endpoints/openapi"
        )


def load_cloud_config() -> CloudConfig:
    """Load cloud config from environment variables with NEUROSTACK_CLOUD_ prefix.

    Example: NEUROSTACK_CLOUD_GCP_PROJECT -> gcp_project
    """
    cfg = CloudConfig()

    env_map = {
        "NEUROSTACK_CLOUD_GCP_PROJECT": "gcp_project",
        "NEUROSTACK_CLOUD_GCP_REGION": "gcp_region",
        "NEUROSTACK_CLOUD_GCS_BUCKET_NAME": "gcs_bucket_name",
        "NEUROSTACK_CLOUD_VERTEX_EMBED_MODEL": "vertex_embed_model",
        "NEUROSTACK_CLOUD_VERTEX_LLM_MODEL": "vertex_llm_model",
        "NEUROSTACK_CLOUD_API_URL": "cloud_api_url",
        "NEUROSTACK_CLOUD_API_KEY": "cloud_api_key",
    }

    for env_key, attr in env_map.items():
        val = os.environ.get(env_key)
        if val is not None:
            setattr(cfg, attr, val)

    return cfg
