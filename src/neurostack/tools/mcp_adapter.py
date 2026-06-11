# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""MCP adapter — wraps registry tools for FastMCP.

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

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from . import ensure_registered

log = logging.getLogger("neurostack.tools.mcp_adapter")


def create_mcp_server(name: str = "neurostack", **fastmcp_kwargs) -> FastMCP:
    """Create a FastMCP server with all registry tools auto-registered.

    Args:
        name: MCP server name
        **fastmcp_kwargs: Passed through to FastMCP constructor
    """
    mcp = FastMCP(name, **fastmcp_kwargs)
    registry = ensure_registered()

    for tool_def in registry.list_tools():
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
                readOnlyHint=hints.read_only,
                destructiveHint=hints.destructive,
                idempotentHint=hints.idempotent,
                openWorldHint=hints.open_world,
            )

        mcp.tool(annotations=mcp_annotations)(wrapper)

    log.debug("Registered %d tools on MCP server %r", len(registry), name)
    return mcp
