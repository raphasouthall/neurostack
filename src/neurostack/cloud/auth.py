# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Bearer token authentication for NeuroStack Cloud API.

API keys are loaded from the NEUROSTACK_CLOUD_API_KEYS environment variable,
which contains a JSON object mapping keys to user metadata:

    {"sk-abc123": {"user_id": "user-1", "tier": "free"}}

At runtime, GCP Secret Manager injects this value.
"""

from __future__ import annotations

import hmac
import json
import os

from fastapi import HTTPException, Request


def _load_api_keys() -> dict[str, dict]:
    """Load API keys from NEUROSTACK_CLOUD_API_KEYS env var.

    Format: JSON object mapping key -> {user_id, tier}
    Example: {"sk-abc123": {"user_id": "user-1", "tier": "free"}}
    """
    raw = os.environ.get("NEUROSTACK_CLOUD_API_KEYS", "{}")
    return json.loads(raw)


_API_KEYS: dict[str, dict] | None = None


def _get_api_keys() -> dict[str, dict]:
    """Return cached API keys, loading from env on first call."""
    global _API_KEYS
    if _API_KEYS is None:
        _API_KEYS = _load_api_keys()
    return _API_KEYS


async def require_api_key(request: Request) -> dict:
    """FastAPI dependency that validates Bearer token and returns user info.

    Uses constant-time comparison to prevent timing side-channels.
    Raises HTTPException(401) if the Authorization header is missing,
    malformed, or contains an invalid key.
    """
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(
            status_code=401, detail="Missing or invalid Authorization header"
        )
    token = auth[7:]
    keys = _get_api_keys()

    # Constant-time comparison against all keys to prevent timing attacks.
    matched_user: dict | None = None
    for stored_key, user_info in keys.items():
        if hmac.compare_digest(stored_key.encode(), token.encode()):
            matched_user = user_info
            break

    if matched_user is None:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return matched_user
