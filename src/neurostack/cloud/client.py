# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""HTTP client for NeuroStack Cloud API with Bearer token authentication."""

from __future__ import annotations

import httpx

from .config import CloudConfig


class CloudClient:
    """HTTP client for NeuroStack Cloud API with Bearer token authentication.

    Wraps httpx for synchronous HTTP calls (CLI is synchronous).
    All authenticated requests include ``Authorization: Bearer {api_key}``.
    """

    def __init__(self, config: CloudConfig) -> None:
        self._config = config
        self._base_url = config.cloud_api_url.rstrip("/")

    @property
    def is_configured(self) -> bool:
        """True if both cloud URL and API key are set."""
        return bool(self._config.cloud_api_url and self._config.cloud_api_key)

    def _auth_headers(self) -> dict[str, str]:
        """Build Bearer auth header from stored API key."""
        if self._config.cloud_api_key:
            return {"Authorization": f"Bearer {self._config.cloud_api_key}"}
        return {}

    def health(self) -> dict:
        """Check cloud API health. No auth required.

        Returns:
            Server status dict, e.g. ``{"status": "ok", "version": "0.8.0"}``.

        Raises:
            ConnectionError: If the server is unreachable or times out.
        """
        url = f"{self._base_url}/health"
        try:
            resp = httpx.get(url, timeout=10.0)
            resp.raise_for_status()
            return resp.json()
        except httpx.ConnectError:
            raise ConnectionError(
                f"Cannot reach cloud API at {self._base_url}. "
                "Check your cloud_api_url setting."
            )
        except httpx.TimeoutException:
            raise ConnectionError(
                f"Cloud API at {self._base_url} timed out."
            )

    def validate_key(self) -> bool:
        """Validate stored API key against the cloud API.

        Calls ``GET /health`` with the Bearer token. Returns True on 200,
        False on 401. Other errors propagate as ConnectionError.
        """
        url = f"{self._base_url}/health"
        try:
            resp = httpx.get(url, headers=self._auth_headers(), timeout=10.0)
        except httpx.ConnectError:
            raise ConnectionError(
                f"Cannot reach cloud API at {self._base_url}. "
                "Check your cloud_api_url setting."
            )
        except httpx.TimeoutException:
            raise ConnectionError(
                f"Cloud API at {self._base_url} timed out."
            )

        if resp.status_code == 401:
            return False
        return resp.status_code == 200

    def status(self) -> dict:
        """Get authenticated status including tier and usage.

        Returns:
            Dict with ``authenticated`` (bool), ``tier`` (str or None),
            and ``cloud_url`` (str). Full tier/usage comes from Phase 7
            billing endpoints.
        """
        is_valid = self.validate_key()
        return {
            "authenticated": is_valid,
            "tier": "free" if is_valid else None,
            "cloud_url": self._base_url,
        }
