# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""MCP adapter — wraps registry tools for the mcp 2.x MCPServer.

Usage:
    from neurostack.tools.mcp_adapter import create_mcp_server
    mcp = create_mcp_server()
    mcp.run(transport="stdio")
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import logging

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from . import ensure_registered

log = logging.getLogger("neurostack.tools.mcp_adapter")


def create_mcp_server(name: str = "neurostack", **server_kwargs) -> MCPServer:
    """Create an MCPServer with all registry tools auto-registered.

    Tools named in ``disabled_tools`` are left off the surface. Every registered
    tool's schema is injected into every client session, so one nobody calls
    costs tokens on every turn and lengthens the menu the model picks from.

    Args:
        name: MCP server name
        **server_kwargs: Passed through to the MCPServer constructor
    """
    from ..config import get_config

    mcp = MCPServer(name, **server_kwargs)
    registry = ensure_registered()
    disabled = set(get_config().disabled_tools)
    skipped: list[str] = []

    for tool_def in registry.list_tools():
        if tool_def.name in disabled:
            skipped.append(tool_def.name)
            continue

        @functools.wraps(tool_def.fn)
        async def wrapper(_td=tool_def, **kwargs):
            return await asyncio.to_thread(_td.call, **kwargs)

        wrapper.__signature__ = inspect.signature(tool_def.fn)
        wrapper.__doc__ = tool_def.fn.__doc__

        # Build MCP ToolAnnotations from registry hints
        mcp_annotations = None
        if tool_def.annotations:
            hints = tool_def.annotations
            mcp_annotations = ToolAnnotations(
                read_only_hint=hints.read_only,
                destructive_hint=hints.destructive,
                idempotent_hint=hints.idempotent,
                open_world_hint=hints.open_world,
            )

        mcp.add_tool(wrapper, annotations=mcp_annotations)

    log.debug(
        "Registered %d of %d tools on MCP server %r",
        len(registry) - len(skipped), len(registry), name,
    )
    if skipped:
        log.info("Tools disabled by config: %s", ", ".join(sorted(skipped)))
    unknown = disabled - {t.name for t in registry.list_tools()}
    if unknown:
        log.warning(
            "disabled_tools names no such tool: %s", ", ".join(sorted(unknown))
        )
    return mcp
