# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Firebase ID token verification for NeuroStack Cloud.

Verifies Firebase ID tokens sent by the frontend (SvelteKit app)
and returns decoded user information.
"""

from __future__ import annotations

from firebase_admin import auth as firebase_auth

from .firebase_init import get_firebase_app


def verify_firebase_token(token: str) -> dict:
    """Verify a Firebase ID token and return user info.

    Returns:
        {"uid": str, "email": str, "provider": str}

    Raises:
        ValueError: If the token is invalid, expired, or revoked.
    """
    try:
        decoded = firebase_auth.verify_id_token(token, app=get_firebase_app())
    except (
        firebase_auth.InvalidIdTokenError,
        firebase_auth.ExpiredIdTokenError,
        firebase_auth.RevokedIdTokenError,
    ) as exc:
        raise ValueError(f"Invalid Firebase ID token: {exc}") from exc

    return {
        "uid": decoded["uid"],
        "email": decoded.get("email", ""),
        "provider": decoded.get("firebase", {}).get("sign_in_provider", "unknown"),
    }
