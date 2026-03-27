# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""REST adapter — auto-generates /v1/tools/* endpoints from registry tools.

Creates a FastAPI router with:
- POST /v1/tools/{tool_name} — invoke any tool
- GET  /v1/tools — list all tools with schemas (OpenAPI-ready)

Usage:
    from fastapi import FastAPI
    from neurostack.tools.rest_adapter import create_tools_router

    app = FastAPI()
    app.include_router(create_tools_router())
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from . import ensure_registered
from .schema_utils import param_to_json_schema as _param_to_json_schema

log = logging.getLogger("neurostack.tools.rest_adapter")


def create_tools_router(prefix: str = "/v1/tools") -> APIRouter:
    """Create a FastAPI router exposing all registry tools as REST endpoints.

    Args:
        prefix: URL prefix for the tools router
    """
    router = APIRouter(prefix=prefix, tags=["tools"])
    registry = ensure_registered()

    @router.get("", summary="List all available tools")
    async def list_tools() -> JSONResponse:
        """List all tools with their parameter schemas."""
        tools = []
        for tool in registry.list_tools():
            properties: dict[str, Any] = {}
            required: list[str] = []
            for param in tool.params:
                properties[param.name] = _param_to_json_schema(param)
                if param.required:
                    required.append(param.name)

            schema: dict[str, Any] = {
                "type": "object",
                "properties": properties,
            }
            if required:
                schema["required"] = required

            tools.append({
                "name": tool.name,
                "description": tool.description,
                "tags": list(tool.tags),
                "parameters": schema,
            })

        return JSONResponse({"tools": tools, "count": len(tools)})

    @router.post(
        "/{tool_name}",
        summary="Invoke a tool by name",
    )
    async def invoke_tool(tool_name: str, request: Request) -> JSONResponse:
        """Invoke a registry tool with the given parameters.

        Pass tool arguments as a JSON body.
        """
        tool = registry.get(tool_name)
        if tool is None:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown tool: {tool_name}",
            )

        try:
            body = await request.json()
        except Exception:
            body = {}

        try:
            result = await asyncio.to_thread(tool.call, **body)
            return JSONResponse(result if isinstance(result, dict) else {"result": result})
        except TypeError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid parameters: {exc}",
            ) from exc
        except Exception as exc:
            log.exception("Tool %s failed", tool_name)
            raise HTTPException(
                status_code=500,
                detail=f"Tool execution failed: {exc}",
            ) from exc

    return router
