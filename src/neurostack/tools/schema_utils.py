# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Shared JSON Schema utilities for tool adapters."""

from __future__ import annotations

from typing import Any

from .registry import ToolParam

# Python type -> JSON Schema type mapping
_TYPE_MAP: dict[type | str, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}


def param_to_json_schema(param: ToolParam) -> dict[str, Any]:
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
