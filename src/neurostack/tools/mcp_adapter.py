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
from typing import Any, Protocol, cast

from mcp.server.mcpserver import Context, MCPServer
from mcp.types import ToolAnnotations

from ..client import CLIENT_NAME
from . import ensure_registered
from .render import RENDERERS, render

log = logging.getLogger("neurostack.tools.mcp_adapter")


class _StampedTool(Protocol):
    """An async wrapper carrying the signature MCP introspects it with."""

    __name__: str
    __doc__: str | None
    __signature__: inspect.Signature

    async def __call__(self, **kwargs: Any) -> Any: ...


def _wants_json(ctx: Context | None) -> bool:
    """Whether the caller is the hook client, which parses replies as JSON (#318).

    Hooks already deployed send this name, so a newer server keeps answering
    them in JSON, and a ``vault_remember`` they cannot parse would cost a
    checkpoint its receipts and save the item again on the next try.
    """
    try:
        params = ctx.request_context.session.client_params if ctx else None
    except ValueError:  # no request behind the call, e.g. server.call_tool
        return False
    return params is not None and params.client_info.name == CLIENT_NAME


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
        async def _wrapper(_td=tool_def, mcp_ctx=None, **kwargs):
            result = await asyncio.to_thread(_td.call, **kwargs)
            # Replies a model reads go out as Markdown, about a third of the
            # characters of indented JSON (#318). Every other tool, and every
            # reply to the hook client, stays JSON for machine consumers.
            if _td.name in RENDERERS and not _wants_json(mcp_ctx):
                return render(_td.name, result)
            return result

        # functools.wraps returns an opaque wrapper; the runtime object is a
        # plain coroutine function that inspect reads __signature__ off.
        wrapper = cast(_StampedTool, _wrapper)
        sig = inspect.signature(tool_def.fn)
        if tool_def.name in RENDERERS:
            # MCPServer injects a parameter annotated Context and leaves it out
            # of the input schema; it names the client for _wants_json.
            sig = sig.replace(parameters=[
                *sig.parameters.values(),
                inspect.Parameter("mcp_ctx", inspect.Parameter.KEYWORD_ONLY,
                                  default=None, annotation=Context),
            ])
            wrapper.__annotations__ = {**tool_def.fn.__annotations__, "mcp_ctx": Context}
        wrapper.__signature__ = sig
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

        # Tools are annotated `-> dict`, so MCPServer would also publish an
        # output schema and echo every reply as structuredContent next to the
        # JSON text block, and clients render both copies (issue #310).
        mcp.add_tool(wrapper, annotations=mcp_annotations, structured_output=False)

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
