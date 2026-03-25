# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""NeuroStack tool registry — protocol-agnostic tool definitions.

Import `registry` and the tool modules to get a populated registry:

    from neurostack.tools import registry, ensure_registered
    ensure_registered()
    result = registry.call("vault_search", query="foo")
"""

from .registry import ToolDef, ToolParam, ToolRegistry, registry

_registered = False


def ensure_registered() -> ToolRegistry:
    """Import all tool modules so they register with the singleton registry."""
    global _registered
    if not _registered:
        from . import (
            insight_tools,  # noqa: F401
            memory_tools,  # noqa: F401
            search_tools,  # noqa: F401
            session_tools,  # noqa: F401
        )
        _registered = True
    return registry


__all__ = [
    "ToolDef",
    "ToolParam",
    "ToolRegistry",
    "ensure_registered",
    "registry",
]
