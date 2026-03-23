# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Singleton Firebase Admin SDK initialization.

On Cloud Run, Application Default Credentials (ADC) are used
automatically. In development, set GOOGLE_APPLICATION_CREDENTIALS
to a service account key file.
"""

from __future__ import annotations

import firebase_admin

_app: firebase_admin.App | None = None


def get_firebase_app() -> firebase_admin.App:
    """Return the singleton Firebase Admin app, initializing on first call."""
    global _app
    if _app is None:
        _app = firebase_admin.initialize_app()  # Uses ADC
    return _app
