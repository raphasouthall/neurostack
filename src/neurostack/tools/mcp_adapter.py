# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""MCP adapter — wraps registry tools for FastMCP.

Usage:
    from neurostack.tools.mcp_adapter import create_mcp_server
    mcp = create_mcp_server()
    mcp.run(transport="stdio")
"""

from __future__ import annotations

import functools
import inspect
import logging

from mcp.server.fastmcp import FastMCP

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
        def wrapper(_td=tool_def, **kwargs):
            return _td.call(**kwargs)

        wrapper.__signature__ = inspect.signature(tool_def.fn)
        wrapper.__doc__ = tool_def.fn.__doc__
        mcp.tool()(wrapper)

    log.debug("Registered %d tools on MCP server %r", len(registry), name)
    return mcp
