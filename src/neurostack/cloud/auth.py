# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Dual-auth for NeuroStack Cloud API.

Supports three authentication methods (in priority order):
1. Firebase ID tokens (>200 chars) -- from frontend OAuth login
2. User-generated nsk-* API keys -- looked up via Firestore hash
3. Legacy sk-* Bearer tokens -- from env var (Secret Manager)

The ``require_auth`` dependency implements the triple-fallback.
The ``require_api_key`` dependency is preserved for backward compat.
"""

from __future__ import annotations

import hmac
import json
import logging
import os

from fastapi import HTTPException, Request

from .firebase_auth import verify_firebase_token
from .user_store import get_user, lookup_api_key

log = logging.getLogger("neurostack.cloud.auth")


# ---------------------------------------------------------------------------
# Legacy sk-* key auth (unchanged)
# ---------------------------------------------------------------------------


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

    If the app has a ``tier_store`` on its state (GCS-backed tier
    overrides from Stripe webhooks), the returned tier reflects the
    latest persistent value rather than the static Secret Manager default.
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
            matched_user = dict(user_info)  # Copy to avoid mutating cache
            break

    if matched_user is None:
        raise HTTPException(status_code=401, detail="Invalid API key")

    # Apply persistent tier override from Stripe webhooks (if available)
    tier_store = getattr(request.app.state, "tier_store", None)
    if tier_store is not None:
        override = tier_store.get(matched_user["user_id"])
        if override is not None:
            matched_user["tier"] = override

    return matched_user


# ---------------------------------------------------------------------------
# Dual-auth dependency (new)
# ---------------------------------------------------------------------------


async def require_auth(request: Request) -> dict:
    """FastAPI dependency implementing triple-fallback authentication.

    Priority:
    1. Firebase ID token (len > 200) -> verify via Firebase Admin SDK
    2. nsk-* user key -> look up via Firestore hash
    3. sk-* legacy key -> fall back to require_api_key

    Returns: {"user_id": str, "tier": str}
    Raises: HTTPException(401) if all paths fail.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=401, detail="Missing or invalid Authorization header"
        )
    token = auth_header[7:]

    if not token:
        raise HTTPException(
            status_code=401, detail="Missing or invalid Authorization header"
        )

    # Path 1: Firebase ID token (JWT, typically >200 chars)
    if len(token) > 200:
        try:
            firebase_user = verify_firebase_token(token)
            uid = firebase_user["uid"]
            user_doc = await get_user(uid)
            tier = user_doc.get("tier", "free") if user_doc else "free"

            result = {"user_id": uid, "tier": tier}

            # Apply tier_store override
            tier_store = getattr(request.app.state, "tier_store", None)
            if tier_store is not None:
                override = tier_store.get(uid)
                if override is not None:
                    result["tier"] = override

            return result
        except ValueError:
            log.debug("Firebase token verification failed, trying other methods")

    # Path 2: User-generated nsk-* API key
    if token.startswith("nsk-"):
        key_info = await lookup_api_key(token)
        if key_info is not None:
            result = {"user_id": key_info["user_id"], "tier": key_info["tier"]}

            # Apply tier_store override
            tier_store = getattr(request.app.state, "tier_store", None)
            if tier_store is not None:
                override = tier_store.get(key_info["user_id"])
                if override is not None:
                    result["tier"] = override

            return result
        raise HTTPException(status_code=401, detail="Invalid API key")

    # Path 3: Legacy sk-* key (falls through to existing logic)
    return await require_api_key(request)
