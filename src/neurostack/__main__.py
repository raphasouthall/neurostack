# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Allow running as python -m neurostack."""
from .cli import main  # noqa: E402 — cli is now a package

if __name__ == "__main__":
    main()
