# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Firestore-backed user storage for NeuroStack Cloud.

Manages user documents and API key lookups in Firestore.
User documents live at ``users/{uid}`` and API keys live in
``users/{uid}/api_keys/{key_id}`` subcollections.
"""

from __future__ import annotations

import hashlib
import os
import secrets

import stripe
from google.cloud import firestore
from google.cloud.firestore_v1 import AsyncClient

_db: AsyncClient | None = None


def _get_db() -> AsyncClient:
    """Return the singleton async Firestore client."""
    global _db
    if _db is None:
        _db = AsyncClient()
    return _db


async def get_user(uid: str, db: AsyncClient | None = None) -> dict | None:
    """Read user document from ``users/{uid}``.

    Returns the user dict or None if the document does not exist.
    """
    client = db or _get_db()
    doc = await client.collection("users").document(uid).get()
    if doc.exists:
        return doc.to_dict()
    return None


async def create_user(
    uid: str,
    email: str,
    name: str,
    provider: str,
    db: AsyncClient | None = None,
) -> dict:
    """Create a new user document at ``users/{uid}``.

    Returns the written user dict (with server timestamps replaced by sentinels).
    """
    client = db or _get_db()
    user_data = {
        "email": email,
        "display_name": name,
        "provider": provider,
        "tier": "free",
        "stripe_customer_id": None,
        "created_at": firestore.SERVER_TIMESTAMP,
        "last_login": firestore.SERVER_TIMESTAMP,
    }
    await client.collection("users").document(uid).set(user_data)
    return {**user_data, "uid": uid}


async def update_last_login(uid: str, db: AsyncClient | None = None) -> None:
    """Update the last_login timestamp for a user."""
    client = db or _get_db()
    await client.collection("users").document(uid).update(
        {"last_login": firestore.SERVER_TIMESTAMP}
    )


async def lookup_api_key(raw_key: str, db: AsyncClient | None = None) -> dict | None:
    """Look up a user-generated ``nsk-*`` API key by its SHA-256 hash.

    Searches the ``api_keys`` collection group across all users.
    Returns ``{"user_id": str, "tier": str, "key_name": str}`` or None.
    """
    client = db or _get_db()
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

    query = client.collection_group("api_keys").where("key_hash", "==", key_hash)
    docs = query.stream()

    async for doc in docs:
        data = doc.to_dict()
        # Parent path: users/{uid}/api_keys/{key_id}
        parent_ref = doc.reference.parent.parent
        uid = parent_ref.id

        # Fetch parent user to get tier
        user_doc = await client.collection("users").document(uid).get()
        tier = "free"
        if user_doc.exists:
            tier = user_doc.to_dict().get("tier", "free")

        return {
            "user_id": uid,
            "tier": tier,
            "key_name": data.get("name", "unnamed"),
        }

    return None


async def ensure_stripe_customer(
    uid: str, email: str, name: str, db: AsyncClient | None = None
) -> str:
    """Create Stripe customer on first login if not exists. Returns customer_id."""
    client = db or _get_db()
    user_ref = client.collection("users").document(uid)
    user_doc = await user_ref.get()
    user_data = user_doc.to_dict()

    if user_data and user_data.get("stripe_customer_id"):
        return user_data["stripe_customer_id"]

    stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
    customer = stripe.Customer.create(
        email=email,
        name=name,
        metadata={"firebase_uid": uid},
    )

    await user_ref.update({"stripe_customer_id": customer.id})
    return customer.id


def generate_api_key() -> tuple[str, str]:
    """Generate an API key. Returns (plaintext, SHA-256 hash)."""
    raw = f"nsk-{secrets.token_urlsafe(32)}"
    key_hash = hashlib.sha256(raw.encode()).hexdigest()
    return raw, key_hash


async def create_api_key(
    uid: str, name: str, db: AsyncClient | None = None
) -> dict:
    """Create a new API key for a user. Returns {key, key_id, name, prefix}."""
    client = db or _get_db()
    plaintext, key_hash = generate_api_key()
    key_ref = client.collection("users").document(uid).collection("api_keys").document()
    key_data = {
        "name": name,
        "key_hash": key_hash,
        "prefix": plaintext[:12],  # "nsk-XXXXXXXX" for display
        "created_at": firestore.SERVER_TIMESTAMP,
        "last_used": None,
    }
    await key_ref.set(key_data)
    return {
        "key": plaintext,  # Shown once, never stored in plaintext
        "key_id": key_ref.id,
        "name": name,
        "prefix": plaintext[:12],
    }


async def list_api_keys(
    uid: str, db: AsyncClient | None = None
) -> list[dict]:
    """List all API keys for a user (prefix + name, never hash)."""
    client = db or _get_db()
    keys_ref = client.collection("users").document(uid).collection("api_keys")
    keys = []
    async for doc in keys_ref.stream():
        data = doc.to_dict()
        keys.append({
            "key_id": doc.id,
            "name": data.get("name", ""),
            "prefix": data.get("prefix", ""),
            "created_at": data.get("created_at"),
            "last_used": data.get("last_used"),
        })
    return keys


async def revoke_api_key(
    uid: str, key_id: str, db: AsyncClient | None = None
) -> bool:
    """Delete an API key. Returns True if deleted, False if not found."""
    client = db or _get_db()
    key_ref = client.collection("users").document(uid).collection("api_keys").document(key_id)
    doc = await key_ref.get()
    if not doc.exists:
        return False
    await key_ref.delete()
    return True
