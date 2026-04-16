# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Server and API CLI commands."""

import sys


def cmd_serve(args):
    """Start the NeuroStack MCP server."""
    from ..server import mcp
    transport = args.transport
    if transport == "http":
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        if args.host not in ("127.0.0.1", "localhost", "::1"):
            from mcp.server.transport_security import TransportSecuritySettings
            mcp.settings.transport_security = TransportSecuritySettings(
                enable_dns_rebinding_protection=False,
                allowed_hosts=["*"],
                allowed_origins=["*"],
            )
        print(f"Starting NeuroStack MCP (Streamable HTTP) on {args.host}:{args.port}")
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport=transport)


def cmd_bundle(args):
    """Build a .mcpb bundle for Claude Desktop."""
    from ..bundle import build_mcpb
    output = build_mcpb(output_dir=args.output)
    print(f"\n  Built: {output}")
    print(f"  Size:  {output.stat().st_size / 1024:.0f} KB")
    print("\n  Install: double-click the .mcpb file in Claude Desktop")
    print("  Or distribute via GitHub Releases.\n")


def cmd_api(args):
    """Start the OpenAI-compatible HTTP API server."""
    try:
        from ..api import run_server
    except ImportError:
        print(
            "API dependencies not installed. "
            "Install with: pip install neurostack[api]",
            file=sys.stderr,
        )
        sys.exit(1)
    print(f"Starting NeuroStack API on {args.host}:{args.port}")
    run_server(host=args.host, port=args.port)
