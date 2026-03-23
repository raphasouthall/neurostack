# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Tests for the dual-auth dependency (require_auth).

Tests all three authentication paths:
1. Firebase ID tokens (>200 chars)
2. User-generated nsk-* API keys (Firestore lookup)
3. Legacy sk-* Bearer tokens (env var)
"""

from __future__ import annotations

import hashlib
import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient

from tests.conftest import MockFirestoreCollection


# ---------------------------------------------------------------------------
# Shared test app factory
# ---------------------------------------------------------------------------


def _make_test_app():
    """Create a minimal FastAPI app with require_auth dependency."""
    from neurostack.cloud.auth import require_auth

    app = FastAPI()

    @app.get("/protected")
    async def protected(user: dict = Depends(require_auth)):
        return {"user_id": user["user_id"], "tier": user["tier"]}

    # Give app a tier_store stub
    app.state.tier_store = None
    return app


# ---------------------------------------------------------------------------
# Firebase ID token path tests
# ---------------------------------------------------------------------------


class TestRequireAuthFirebase:
    """Tests for require_auth() with Firebase ID tokens."""

    def test_firebase_token_authenticates(self, mock_firebase_admin, mock_firestore):
        """Firebase ID token (>200 chars) verifies and returns user info."""
        from neurostack.cloud import auth as auth_mod
        auth_mod._API_KEYS = None

        # Seed user in Firestore
        mock_firestore._collections["users"] = MockFirestoreCollection({
            "firebase-user-123": {"email": "test@example.com", "tier": "pro"}
        })

        app = _make_test_app()
        with TestClient(app) as client:
            # Firebase ID tokens are JWTs, typically >200 chars
            long_token = "x" * 250
            resp = client.get("/protected", headers={"Authorization": f"Bearer {long_token}"})
            assert resp.status_code == 200
            data = resp.json()
            assert data["user_id"] == "firebase-user-123"
            assert data["tier"] == "pro"

    def test_firebase_token_defaults_to_free_tier(self, mock_firebase_admin, mock_firestore):
        """Firebase user without Firestore doc defaults to free tier."""
        from neurostack.cloud import auth as auth_mod
        auth_mod._API_KEYS = None

        app = _make_test_app()
        with TestClient(app) as client:
            long_token = "y" * 250
            resp = client.get("/protected", headers={"Authorization": f"Bearer {long_token}"})
            assert resp.status_code == 200
            data = resp.json()
            assert data["user_id"] == "firebase-user-123"
            assert data["tier"] == "free"


# ---------------------------------------------------------------------------
# nsk-* user key path tests
# ---------------------------------------------------------------------------


class TestRequireAuthNskKey:
    """Tests for require_auth() with user-generated nsk-* API keys."""

    def test_nsk_key_authenticates(self, mock_firestore):
        """Valid nsk-* key authenticates via Firestore lookup."""
        from neurostack.cloud import auth as auth_mod
        auth_mod._API_KEYS = None

        raw_key = "nsk-my-user-key-abc"
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

        mock_firestore._collections["users"] = MockFirestoreCollection({
            "nsk-user-1": {
                "email": "nsk@example.com",
                "tier": "team",
                "_sub_api_keys": {
                    "key-1": {"key_hash": key_hash, "name": "CLI Key"},
                },
            }
        })

        app = _make_test_app()
        with TestClient(app) as client:
            resp = client.get(
                "/protected",
                headers={"Authorization": f"Bearer {raw_key}"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["user_id"] == "nsk-user-1"
            assert data["tier"] == "team"

    def test_invalid_nsk_key_returns_401(self, mock_firestore):
        """Invalid nsk-* key returns 401."""
        from neurostack.cloud import auth as auth_mod
        auth_mod._API_KEYS = None

        app = _make_test_app()
        with TestClient(app) as client:
            resp = client.get(
                "/protected",
                headers={"Authorization": "Bearer nsk-nonexistent-key"},
            )
            assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Legacy sk-* key path tests
# ---------------------------------------------------------------------------


class TestRequireAuthLegacySk:
    """Tests for require_auth() with legacy sk-* Bearer tokens."""

    def test_legacy_sk_key_still_works(self):
        """Legacy sk-* key authenticates through require_auth fallback."""
        keys = {"sk-legacy-123": {"user_id": "legacy-user", "tier": "free"}}

        with patch.dict(os.environ, {"NEUROSTACK_CLOUD_API_KEYS": json.dumps(keys)}):
            from neurostack.cloud import auth as auth_mod
            auth_mod._API_KEYS = None

            app = _make_test_app()
            with TestClient(app) as client:
                resp = client.get(
                    "/protected",
                    headers={"Authorization": "Bearer sk-legacy-123"},
                )
                assert resp.status_code == 200
                data = resp.json()
                assert data["user_id"] == "legacy-user"
                assert data["tier"] == "free"

    def test_invalid_sk_key_returns_401(self):
        """Invalid sk-* key returns 401."""
        with patch.dict(os.environ, {"NEUROSTACK_CLOUD_API_KEYS": json.dumps({})}):
            from neurostack.cloud import auth as auth_mod
            auth_mod._API_KEYS = None

            app = _make_test_app()
            with TestClient(app) as client:
                resp = client.get(
                    "/protected",
                    headers={"Authorization": "Bearer sk-wrong-key"},
                )
                assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


class TestRequireAuthErrors:
    """Tests for require_auth() error handling."""

    def test_no_auth_header_returns_401(self):
        """Missing Authorization header returns 401."""
        from neurostack.cloud import auth as auth_mod
        auth_mod._API_KEYS = None

        app = _make_test_app()
        with TestClient(app) as client:
            resp = client.get("/protected")
            assert resp.status_code == 401

    def test_malformed_auth_header_returns_401(self):
        """Auth header without 'Bearer ' prefix returns 401."""
        from neurostack.cloud import auth as auth_mod
        auth_mod._API_KEYS = None

        app = _make_test_app()
        with TestClient(app) as client:
            resp = client.get(
                "/protected",
                headers={"Authorization": "Token some-token"},
            )
            assert resp.status_code == 401

    def test_empty_token_returns_401(self):
        """Bearer token that is empty returns 401."""
        from neurostack.cloud import auth as auth_mod
        auth_mod._API_KEYS = None

        app = _make_test_app()
        with TestClient(app) as client:
            resp = client.get(
                "/protected",
                headers={"Authorization": "Bearer "},
            )
            assert resp.status_code == 401
