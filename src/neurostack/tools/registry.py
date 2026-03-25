# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Protocol-agnostic tool registry for NeuroStack.

Tools register once via @registry.tool() and return Python dicts.
Adapters (MCP, OpenAI, REST) serialize to their wire format.

Usage:
    from neurostack.tools.registry import registry

    @registry.tool(tags=["search"])
    def vault_search(query: str, top_k: int = 5) -> dict:
        '''Search the vault.'''
        return {"results": [...]}

    # List all tools:
    registry.tools  # dict[str, ToolDef]

    # Call a tool:
    result = registry.call("vault_search", query="foo")
"""

from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass
from typing import Any, Callable, get_type_hints

log = logging.getLogger("neurostack.tools")


@dataclass(frozen=True)
class ToolParam:
    """Describes a single tool parameter."""

    name: str
    type: type | str
    default: Any = inspect.Parameter.empty
    description: str = ""

    @property
    def required(self) -> bool:
        return self.default is inspect.Parameter.empty


@dataclass(frozen=True)
class ToolDef:
    """Complete definition of a registered tool."""

    name: str
    description: str
    fn: Callable[..., dict]
    params: list[ToolParam]
    tags: tuple[str, ...] = ()

    def call(self, **kwargs: Any) -> dict:
        """Invoke the tool function with the given kwargs."""
        return self.fn(**kwargs)


def _extract_params(fn: Callable) -> list[ToolParam]:
    """Extract parameter metadata from a function signature + type hints."""
    sig = inspect.signature(fn)
    try:
        hints = get_type_hints(fn)
    except Exception:
        hints = {}

    params = []
    for name, param in sig.parameters.items():
        if name in ("self", "cls"):
            continue
        ptype = hints.get(name, str)
        # Strip Optional wrapper for display
        origin = getattr(ptype, "__origin__", None)
        if origin is not None:
            import types
            if origin is types.UnionType or str(origin) == "typing.Union":
                args = [a for a in ptype.__args__ if a is not type(None)]
                if len(args) == 1:
                    ptype = args[0]

        params.append(ToolParam(
            name=name,
            type=ptype,
            default=(
                param.default
                if param.default is not inspect.Parameter.empty
                else inspect.Parameter.empty
            ),
            description="",  # Extracted from docstring by adapters if needed
        ))
    return params


def _extract_description(fn: Callable) -> str:
    """Extract the first paragraph of a function's docstring."""
    doc = inspect.getdoc(fn)
    if not doc:
        return fn.__name__
    # First paragraph (up to blank line)
    lines = []
    for line in doc.split("\n"):
        if not line.strip():
            if lines:
                break
            continue
        lines.append(line.strip())
    return " ".join(lines) if lines else fn.__name__


class ToolRegistry:
    """Central registry of protocol-agnostic tools."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDef] = {}

    @property
    def tools(self) -> dict[str, ToolDef]:
        return dict(self._tools)

    def tool(
        self,
        *,
        name: str | None = None,
        tags: list[str] | None = None,
    ) -> Callable:
        """Decorator to register a tool function.

        The decorated function must return a dict (not a JSON string).

        Args:
            name: Override the tool name (defaults to function name)
            tags: Categorisation tags like ["search", "retrieval"]
        """
        def decorator(fn: Callable) -> Callable:
            tool_name = name or fn.__name__
            if tool_name in self._tools:
                log.warning("Tool %r registered twice — overwriting", tool_name)

            tool_def = ToolDef(
                name=tool_name,
                description=_extract_description(fn),
                fn=fn,
                params=_extract_params(fn),
                tags=tuple(tags or []),
            )
            self._tools[tool_name] = tool_def
            # Preserve the original function for direct imports
            fn._tool_def = tool_def
            return fn

        return decorator

    def call(self, tool_name: str, **kwargs: Any) -> dict:
        """Invoke a registered tool by name."""
        tool = self._tools.get(tool_name)
        if tool is None:
            raise KeyError(f"Unknown tool: {tool_name!r}")
        return tool.call(**kwargs)

    def get(self, tool_name: str) -> ToolDef | None:
        """Get a tool definition by name."""
        return self._tools.get(tool_name)

    def list_tools(self, tag: str | None = None) -> list[ToolDef]:
        """List all tools, optionally filtered by tag."""
        tools = list(self._tools.values())
        if tag:
            tools = [t for t in tools if tag in t.tags]
        return tools

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools


# Singleton registry — all tool modules register against this instance
registry = ToolRegistry()
