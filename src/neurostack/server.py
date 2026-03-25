#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""NeuroStack MCP server — thin adapter over the protocol-agnostic tool registry.

All tool logic lives in neurostack.tools.*_tools modules. This file
creates a FastMCP server with all tools auto-registered.
"""

from .tools.mcp_adapter import create_mcp_server

mcp = create_mcp_server()

if __name__ == "__main__":
    mcp.run(transport="stdio")
