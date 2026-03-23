# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Tests for Firebase token verification, Firestore user store, and API endpoints."""

from __future__ import annotations

import hashlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

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


# ---------------------------------------------------------------------------
# ensure_stripe_customer tests
# ---------------------------------------------------------------------------


class TestEnsureStripeCustomer:
    """Tests for user_store.ensure_stripe_customer()."""

    @pytest.mark.asyncio
    async def test_creates_stripe_customer_for_new_user(self, mock_firestore):
        """ensure_stripe_customer creates a Stripe customer if user has no stripe_customer_id."""
        from neurostack.cloud.user_store import create_user, ensure_stripe_customer

        await create_user("uid-1", "alice@example.com", "Alice", "google.com")

        with patch("stripe.Customer") as mock_stripe:
            mock_stripe.create.return_value = MagicMock(id="cus_test123")
            with patch.dict("os.environ", {"STRIPE_SECRET_KEY": "sk_test_xxx"}):
                result = await ensure_stripe_customer("uid-1", "alice@example.com", "Alice")

        assert result == "cus_test123"
        mock_stripe.create.assert_called_once_with(
            email="alice@example.com",
            name="Alice",
            metadata={"firebase_uid": "uid-1"},
        )

    @pytest.mark.asyncio
    async def test_skips_stripe_if_customer_exists(self, mock_firestore):
        """ensure_stripe_customer returns existing customer_id without calling Stripe."""
        from neurostack.cloud.user_store import create_user, ensure_stripe_customer

        await create_user("uid-2", "bob@example.com", "Bob", "github.com")
        # Manually set stripe_customer_id
        mock_firestore.collection("users")._data["uid-2"]["stripe_customer_id"] = "cus_existing"

        with patch("stripe.Customer") as mock_stripe:
            result = await ensure_stripe_customer("uid-2", "bob@example.com", "Bob")

        assert result == "cus_existing"
        mock_stripe.create.assert_not_called()


# ---------------------------------------------------------------------------
# API key CRUD tests
# ---------------------------------------------------------------------------


class TestGenerateApiKey:
    """Tests for user_store.generate_api_key()."""

    def test_key_starts_with_nsk_prefix(self):
        """generate_api_key produces keys starting with nsk-."""
        from neurostack.cloud.user_store import generate_api_key

        plaintext, key_hash = generate_api_key()
        assert plaintext.startswith("nsk-")
        assert len(plaintext) > 12  # nsk- plus token
        assert key_hash == hashlib.sha256(plaintext.encode()).hexdigest()


class TestCreateApiKey:
    """Tests for user_store.create_api_key()."""

    @pytest.mark.asyncio
    async def test_create_api_key_returns_plaintext(self, mock_firestore):
        """create_api_key returns dict with key, key_id, name, prefix."""
        from neurostack.cloud.user_store import create_api_key, create_user

        await create_user("uid-key", "key@example.com", "Key User", "google.com")
        result = await create_api_key("uid-key", "my-cli-key")

        assert result["key"].startswith("nsk-")
        assert result["name"] == "my-cli-key"
        assert result["prefix"] == result["key"][:12]
        assert "key_id" in result


class TestListApiKeys:
    """Tests for user_store.list_api_keys()."""

    @pytest.mark.asyncio
    async def test_list_returns_key_info_without_hash(self, mock_firestore):
        """list_api_keys returns key_id, name, prefix for each key."""
        from neurostack.cloud.user_store import create_api_key, create_user, list_api_keys

        await create_user("uid-list", "list@example.com", "List User", "google.com")
        await create_api_key("uid-list", "key-one")
        await create_api_key("uid-list", "key-two")

        keys = await list_api_keys("uid-list")
        assert len(keys) == 2
        names = {k["name"] for k in keys}
        assert names == {"key-one", "key-two"}
        for k in keys:
            assert "key_id" in k
            assert "prefix" in k
            assert "key_hash" not in k  # Never expose hash


class TestRevokeApiKey:
    """Tests for user_store.revoke_api_key()."""

    @pytest.mark.asyncio
    async def test_revoke_existing_key_returns_true(self, mock_firestore):
        """revoke_api_key deletes key and returns True."""
        from neurostack.cloud.user_store import create_api_key, create_user, list_api_keys, revoke_api_key

        await create_user("uid-rev", "rev@example.com", "Rev User", "google.com")
        created = await create_api_key("uid-rev", "to-revoke")
        key_id = created["key_id"]

        result = await revoke_api_key("uid-rev", key_id)
        assert result is True

        # Verify key is gone
        keys = await list_api_keys("uid-rev")
        assert len(keys) == 0

    @pytest.mark.asyncio
    async def test_revoke_nonexistent_key_returns_false(self, mock_firestore):
        """revoke_api_key returns False for nonexistent key."""
        from neurostack.cloud.user_store import create_user, revoke_api_key

        await create_user("uid-rev2", "rev2@example.com", "Rev User 2", "google.com")
        result = await revoke_api_key("uid-rev2", "nonexistent-key-id")
        assert result is False


# ---------------------------------------------------------------------------
# Registration endpoint tests
# ---------------------------------------------------------------------------


class TestRegisterEndpoint:
    """Tests for POST /api/v1/user/register."""

    @pytest.fixture
    def app_client(self, mock_firestore, mock_firebase_admin):
        """Create a test client with mocked auth and Firestore."""
        from neurostack.cloud.api import app

        # Set up minimal app state
        app.state.meter = MagicMock()
        app.state.meter.check_query_limit = AsyncMock(return_value=(True, ""))
        app.state.meter.check_note_limit = AsyncMock(return_value=(True, ""))
        app.state.tier_store = None

        return app

    @pytest.mark.asyncio
    async def test_register_new_user_creates_user_and_stripe(self, app_client, mock_firestore):
        """POST /api/v1/user/register for new user creates Firestore doc and Stripe customer."""
        with patch("stripe.Customer") as mock_stripe:
            mock_stripe.create.return_value = MagicMock(id="cus_new123")
            with patch.dict("os.environ", {"STRIPE_SECRET_KEY": "sk_test_xxx"}):
                async with AsyncClient(
                    transport=ASGITransport(app=app_client),
                    base_url="http://test",
                ) as client:
                    # Use a long token to trigger Firebase path (>200 chars)
                    long_token = "x" * 250
                    resp = await client.post(
                        "/api/v1/user/register",
                        headers={"Authorization": f"Bearer {long_token}"},
                    )

        assert resp.status_code == 200
        data = resp.json()
        assert data["uid"] == "firebase-user-123"
        assert data["email"] == "test@example.com"
        assert data["tier"] == "free"
        assert data["provider"] == "google.com"
        assert data["stripe_customer_id"] == "cus_new123"

    @pytest.mark.asyncio
    async def test_register_existing_user_is_idempotent(self, app_client, mock_firestore):
        """POST /api/v1/user/register for existing user updates last_login, returns profile."""
        from neurostack.cloud.user_store import create_user

        # Pre-create user
        await create_user("firebase-user-123", "test@example.com", "Test User", "google.com")
        mock_firestore.collection("users")._data["firebase-user-123"]["stripe_customer_id"] = "cus_existing"

        async with AsyncClient(
            transport=ASGITransport(app=app_client),
            base_url="http://test",
        ) as client:
            long_token = "x" * 250
            resp = await client.post(
                "/api/v1/user/register",
                headers={"Authorization": f"Bearer {long_token}"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["uid"] == "firebase-user-123"
        assert data["stripe_customer_id"] == "cus_existing"

    @pytest.mark.asyncio
    async def test_register_requires_auth(self, app_client):
        """POST /api/v1/user/register without token returns 401."""
        async with AsyncClient(
            transport=ASGITransport(app=app_client),
            base_url="http://test",
        ) as client:
            resp = await client.post("/api/v1/user/register")

        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# API key endpoint tests
# ---------------------------------------------------------------------------


class TestApiKeyEndpoints:
    """Tests for /api/v1/user/keys endpoints."""

    @pytest.fixture
    def app_client(self, mock_firestore, mock_firebase_admin):
        """Create a test client with mocked auth and Firestore."""
        from neurostack.cloud.api import app

        app.state.meter = MagicMock()
        app.state.tier_store = None
        return app

    def _auth_headers(self):
        """Return auth headers with a long Firebase-style token."""
        return {"Authorization": f"Bearer {'x' * 250}"}

    @pytest.mark.asyncio
    async def test_create_key_returns_nsk_plaintext(self, app_client, mock_firestore):
        """POST /api/v1/user/keys returns plaintext key starting with nsk-."""
        from neurostack.cloud.user_store import create_user

        await create_user("firebase-user-123", "test@example.com", "Test", "google.com")

        async with AsyncClient(
            transport=ASGITransport(app=app_client),
            base_url="http://test",
        ) as client:
            resp = await client.post(
                "/api/v1/user/keys",
                json={"name": "my-cli-key"},
                headers=self._auth_headers(),
            )

        assert resp.status_code == 201
        data = resp.json()
        assert data["key"].startswith("nsk-")
        assert data["name"] == "my-cli-key"
        assert data["prefix"] == data["key"][:12]

    @pytest.mark.asyncio
    async def test_list_keys_returns_info_without_hash(self, app_client, mock_firestore):
        """GET /api/v1/user/keys returns key info without hash."""
        from neurostack.cloud.user_store import create_api_key, create_user

        await create_user("firebase-user-123", "test@example.com", "Test", "google.com")
        await create_api_key("firebase-user-123", "key-alpha")

        async with AsyncClient(
            transport=ASGITransport(app=app_client),
            base_url="http://test",
        ) as client:
            resp = await client.get(
                "/api/v1/user/keys",
                headers=self._auth_headers(),
            )

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        assert data[0]["name"] == "key-alpha"
        assert "prefix" in data[0]

    @pytest.mark.asyncio
    async def test_delete_key_returns_204(self, app_client, mock_firestore):
        """DELETE /api/v1/user/keys/{key_id} returns 204."""
        from neurostack.cloud.user_store import create_api_key, create_user

        await create_user("firebase-user-123", "test@example.com", "Test", "google.com")
        created = await create_api_key("firebase-user-123", "to-delete")

        async with AsyncClient(
            transport=ASGITransport(app=app_client),
            base_url="http://test",
        ) as client:
            resp = await client.delete(
                f"/api/v1/user/keys/{created['key_id']}",
                headers=self._auth_headers(),
            )

        assert resp.status_code == 204

    @pytest.mark.asyncio
    async def test_delete_nonexistent_key_returns_404(self, app_client, mock_firestore):
        """DELETE /api/v1/user/keys/{key_id} for nonexistent key returns 404."""
        from neurostack.cloud.user_store import create_user

        await create_user("firebase-user-123", "test@example.com", "Test", "google.com")

        async with AsyncClient(
            transport=ASGITransport(app=app_client),
            base_url="http://test",
        ) as client:
            resp = await client.delete(
                "/api/v1/user/keys/nonexistent-id",
                headers=self._auth_headers(),
            )

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_keys_require_auth(self, app_client):
        """API key endpoints require authentication."""
        async with AsyncClient(
            transport=ASGITransport(app=app_client),
            base_url="http://test",
        ) as client:
            resp = await client.post("/api/v1/user/keys", json={"name": "test"})
            assert resp.status_code == 401

            resp = await client.get("/api/v1/user/keys")
            assert resp.status_code == 401

            resp = await client.delete("/api/v1/user/keys/some-id")
            assert resp.status_code == 401
