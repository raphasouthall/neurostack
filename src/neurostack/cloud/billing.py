# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Stripe billing integration for NeuroStack Cloud.

Handles Checkout session creation, Customer Portal access, and webhook
event processing for subscription lifecycle (provisioning/deprovisioning).
"""

from __future__ import annotations

import logging
import os

import stripe

log = logging.getLogger("neurostack.cloud.billing")


def _get_stripe_config() -> dict:
    """Load Stripe config from environment variables."""
    return {
        "secret_key": os.environ.get("STRIPE_SECRET_KEY", ""),
        "webhook_secret": os.environ.get("STRIPE_WEBHOOK_SECRET", ""),
        "price_pro": os.environ.get("STRIPE_PRICE_PRO", ""),
        "price_team": os.environ.get("STRIPE_PRICE_TEAM", ""),
    }


def get_tier_for_price(price_id: str) -> str:
    """Map a Stripe price ID to a NeuroStack tier name."""
    cfg = _get_stripe_config()
    if price_id and price_id == cfg["price_pro"]:
        return "pro"
    if price_id and price_id == cfg["price_team"]:
        return "team"
    return "free"


def create_checkout_session(
    user_id: str,
    price_id: str,
    success_url: str = "https://neurostack.sh/billing/success",
    cancel_url: str = "https://neurostack.sh/billing/cancel",
) -> str:
    """Create a Stripe Checkout session. Returns the checkout URL."""
    cfg = _get_stripe_config()
    stripe.api_key = cfg["secret_key"]

    session = stripe.checkout.Session.create(
        mode="subscription",
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=success_url,
        cancel_url=cancel_url,
        metadata={"user_id": user_id},
        client_reference_id=user_id,
    )
    return session.url


def create_portal_session(
    customer_id: str,
    return_url: str = "https://neurostack.sh/billing",
) -> str:
    """Create a Stripe Customer Portal session. Returns the portal URL."""
    cfg = _get_stripe_config()
    stripe.api_key = cfg["secret_key"]

    session = stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=return_url,
    )
    return session.url


def verify_webhook_signature(payload: bytes, sig_header: str) -> dict:
    """Verify Stripe webhook signature. Returns parsed event or raises ValueError."""
    cfg = _get_stripe_config()
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, cfg["webhook_secret"]
        )
        return event
    except stripe.SignatureVerificationError as exc:
        raise ValueError(f"Invalid webhook signature: {exc}")


def handle_webhook_event(event: dict, update_tier_fn) -> dict:
    """Process a Stripe webhook event.

    Args:
        event: Parsed Stripe event dict.
        update_tier_fn: Callable(user_id, new_tier) to update user's tier.

    Returns:
        dict with {handled: bool, action: str}
    """
    event_type = event.get("type", "")
    data = event.get("data", {}).get("object", {})

    if event_type == "checkout.session.completed":
        user_id = (
            data.get("metadata", {}).get("user_id")
            or data.get("client_reference_id")
        )
        subscription_id = data.get("subscription")

        if user_id and subscription_id:
            cfg = _get_stripe_config()
            stripe.api_key = cfg["secret_key"]
            sub = stripe.Subscription.retrieve(subscription_id)
            price_id = sub["items"]["data"][0]["price"]["id"]
            new_tier = get_tier_for_price(price_id)
            update_tier_fn(user_id, new_tier)
            log.info("Provisioned %s to tier %s", user_id, new_tier)
            return {
                "handled": True,
                "action": f"provisioned {user_id} to {new_tier}",
            }

    elif event_type == "customer.subscription.updated":
        items = data.get("items", {}).get("data", [])
        if items:
            price_id = items[0].get("price", {}).get("id", "")
            new_tier = get_tier_for_price(price_id)
            metadata = data.get("metadata", {})
            user_id = metadata.get("user_id")
            if user_id:
                update_tier_fn(user_id, new_tier)
                log.info("Updated %s to tier %s", user_id, new_tier)
                return {
                    "handled": True,
                    "action": f"updated {user_id} to {new_tier}",
                }

    elif event_type == "customer.subscription.deleted":
        metadata = data.get("metadata", {})
        user_id = metadata.get("user_id")
        if user_id:
            update_tier_fn(user_id, "free")
            log.info("Downgraded %s to free", user_id)
            return {
                "handled": True,
                "action": f"downgraded {user_id} to free",
            }

    return {"handled": False, "action": "unhandled event type"}
