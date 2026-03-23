# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Tests for Firebase token verification and Firestore user store."""

from __future__ import annotations

import hashlib
from unittest.mock import MagicMock, patch

import pytest

from tests.conftest import MOCK_FIREBASE_DECODED_TOKEN


# ---------------------------------------------------------------------------
# verify_firebase_token tests
# ---------------------------------------------------------------------------


class TestVerifyFirebaseToken:
    """Tests for firebase_auth.verify_firebase_token()."""

    def test_valid_token_returns_user_info(self, mock_firebase_admin):
        """verify_firebase_token with valid token returns uid, email, provider."""
        from neurostack.cloud.firebase_auth import verify_firebase_token

        result = verify_firebase_token("valid-firebase-token-string")
        assert result["uid"] == "firebase-user-123"
        assert result["email"] == "test@example.com"
        assert result["provider"] == "google.com"

    def test_invalid_token_raises_value_error(self):
        """verify_firebase_token with invalid token raises ValueError."""
        from firebase_admin import auth as firebase_auth

        with (
            patch(
                "firebase_admin.auth.verify_id_token",
                side_effect=firebase_auth.InvalidIdTokenError("bad token"),
            ),
            patch("firebase_admin.initialize_app", return_value=MagicMock()),
        ):
            import neurostack.cloud.firebase_init as fi
            old_app = fi._app
            fi._app = None
            try:
                from neurostack.cloud.firebase_auth import verify_firebase_token
                with pytest.raises(ValueError, match="Invalid Firebase ID token"):
                    verify_firebase_token("bad-token")
            finally:
                fi._app = old_app


# ---------------------------------------------------------------------------
# Firestore user store tests
# ---------------------------------------------------------------------------


class TestGetUser:
    """Tests for user_store.get_user()."""

    @pytest.mark.asyncio
    async def test_get_existing_user(self, mock_firestore):
        """get_user returns user dict for existing user."""
        from neurostack.cloud.user_store import get_user

        # Seed user data
        mock_firestore._collections["users"] = type(mock_firestore.collection("users"))(
            {"user-1": {"email": "alice@example.com", "tier": "free", "display_name": "Alice"}}
        )

        result = await get_user("user-1")
        assert result is not None
        assert result["email"] == "alice@example.com"
        assert result["tier"] == "free"

    @pytest.mark.asyncio
    async def test_get_nonexistent_user_returns_none(self, mock_firestore):
        """get_user returns None for nonexistent user."""
        from neurostack.cloud.user_store import get_user

        result = await get_user("nonexistent-uid")
        assert result is None


class TestCreateUser:
    """Tests for user_store.create_user()."""

    @pytest.mark.asyncio
    async def test_create_user_returns_user_dict(self, mock_firestore):
        """create_user writes to Firestore and returns user dict."""
        from neurostack.cloud.user_store import create_user

        result = await create_user("new-uid", "bob@example.com", "Bob", "github.com")
        assert result["email"] == "bob@example.com"
        assert result["display_name"] == "Bob"
        assert result["provider"] == "github.com"
        assert result["tier"] == "free"
        assert result["uid"] == "new-uid"

    @pytest.mark.asyncio
    async def test_create_user_persists_in_firestore(self, mock_firestore):
        """create_user data can be read back via get_user."""
        from neurostack.cloud.user_store import create_user, get_user

        await create_user("persist-uid", "persist@example.com", "Persist", "google.com")
        user = await get_user("persist-uid")
        assert user is not None
        assert user["email"] == "persist@example.com"


class TestLookupApiKey:
    """Tests for user_store.lookup_api_key()."""

    @pytest.mark.asyncio
    async def test_lookup_valid_nsk_key(self, mock_firestore):
        """lookup_api_key finds key by SHA-256 hash."""
        from neurostack.cloud.user_store import lookup_api_key

        raw_key = "nsk-test-key-12345"
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

        # Seed: users collection with a user that has api_keys subcollection
        from tests.conftest import MockFirestoreCollection
        users_col = MockFirestoreCollection({
            "user-abc": {
                "email": "abc@example.com",
                "tier": "pro",
                "_sub_api_keys": {
                    "key-1": {
                        "key_hash": key_hash,
                        "name": "My CLI Key",
                    }
                },
            }
        })
        mock_firestore._collections["users"] = users_col

        result = await lookup_api_key(raw_key)
        assert result is not None
        assert result["user_id"] == "user-abc"
        assert result["tier"] == "pro"
        assert result["key_name"] == "My CLI Key"

    @pytest.mark.asyncio
    async def test_lookup_invalid_nsk_key_returns_none(self, mock_firestore):
        """lookup_api_key returns None for non-matching key."""
        from neurostack.cloud.user_store import lookup_api_key

        result = await lookup_api_key("nsk-invalid-key")
        assert result is None
