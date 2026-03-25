# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""OpenAI function-calling adapter — exposes all registry tools as OpenAI tools.

Generates OpenAI-compatible function definitions from registry metadata
and handles tool_calls in chat completion requests.

Usage:
    from neurostack.tools.openai_adapter import (
        get_openai_tools,
        execute_tool_call,
    )

    # Get function definitions for the API
    tools = get_openai_tools()

    # Execute a tool call from the model
    result = execute_tool_call("vault_search", {"query": "foo"})
"""

from __future__ import annotations

import inspect
import json
import logging
from typing import Any

from . import ensure_registered
from .registry import ToolDef, ToolParam

log = logging.getLogger("neurostack.tools.openai_adapter")

# Python type -> JSON Schema type mapping
_TYPE_MAP: dict[type | str, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}


def _param_to_json_schema(param: ToolParam) -> dict[str, Any]:
    """Convert a ToolParam to a JSON Schema property."""
    ptype = param.type
    schema: dict[str, Any] = {}

    # Handle generic types like list[str]
    origin = getattr(ptype, "__origin__", None)
    if origin is list:
        schema["type"] = "array"
        args = getattr(ptype, "__args__", ())
        if args:
            item_type = _TYPE_MAP.get(args[0], "string")
            schema["items"] = {"type": item_type}
    elif isinstance(ptype, type):
        schema["type"] = _TYPE_MAP.get(ptype, "string")
    else:
        schema["type"] = "string"

    if param.description:
        schema["description"] = param.description

    return schema


def _tool_to_openai_function(tool: ToolDef) -> dict[str, Any]:
    """Convert a ToolDef to an OpenAI function definition."""
    properties: dict[str, Any] = {}
    required: list[str] = []

    for param in tool.params:
        properties[param.name] = _param_to_json_schema(param)
        if param.required:
            required.append(param.name)

    parameters: dict[str, Any] = {
        "type": "object",
        "properties": properties,
    }
    if required:
        parameters["required"] = required

    # Extract full docstring for the description
    doc = inspect.getdoc(tool.fn) or tool.description
    # Truncate to OpenAI's 1024 char limit for descriptions
    if len(doc) > 1024:
        doc = doc[:1021] + "..."

    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": doc,
            "parameters": parameters,
        },
    }


def get_openai_tools(tag: str | None = None) -> list[dict[str, Any]]:
    """Get all registry tools as OpenAI function definitions.

    Args:
        tag: Optional tag to filter tools (e.g. "search", "memory")

    Returns:
        List of OpenAI tool definitions ready for the tools parameter
    """
    registry = ensure_registered()
    return [
        _tool_to_openai_function(tool)
        for tool in registry.list_tools(tag=tag)
    ]


def execute_tool_call(
    name: str,
    arguments: dict[str, Any] | str,
) -> str:
    """Execute a tool call from an OpenAI function calling response.

    Args:
        name: Tool name from the function call
        arguments: Tool arguments (dict or JSON string)

    Returns:
        JSON string result for the tool_call response
    """
    registry = ensure_registered()

    if isinstance(arguments, str):
        arguments = json.loads(arguments)

    try:
        result = registry.call(name, **arguments)
        return json.dumps(result, default=str)
    except KeyError:
        return json.dumps({"error": f"Unknown tool: {name}"})
    except Exception as exc:
        log.exception("Tool %s failed", name)
        return json.dumps({"error": str(exc)})


def get_openai_tools_map() -> dict[str, ToolDef]:
    """Get a name -> ToolDef mapping for direct access."""
    registry = ensure_registered()
    return registry.tools
