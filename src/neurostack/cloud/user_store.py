# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Firestore-backed user storage for NeuroStack Cloud.

Manages user documents and API key lookups in Firestore.
User documents live at ``users/{uid}`` and API keys live in
``users/{uid}/api_keys/{key_id}`` subcollections.
"""

from __future__ import annotations

import hashlib

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
