# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Cloud backend dispatch — replaces local tool functions with cloud proxies.

When ``mode=cloud``, each registered tool is re-pointed to a CloudClient
method that forwards the call to the cloud REST API. The registry stays
protocol-agnostic: MCP, OpenAI, and REST adapters all pick up the change
automatically.

Usage (called once at startup):
    from neurostack.cloud.dispatch import enable_cloud_dispatch
    enable_cloud_dispatch(registry, cloud_client)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from neurostack.cloud.client import CloudClient
    from neurostack.tools.registry import ToolRegistry

log = logging.getLogger("neurostack.cloud.dispatch")

# Map: registry tool name -> CloudClient method name.
# Most are 1:1, but a few differ (e.g. query -> vault_search).
_TOOL_TO_METHOD = {
    "vault_search": "vault_search",
    "vault_triples": "vault_triples",
    "vault_summary": "vault_summary",
    "vault_stats": "vault_stats",
    "vault_graph": "vault_graph",
    "vault_related": "vault_related",
    "vault_ask": "vault_ask",
    "vault_communities": "vault_communities",
    "vault_context": "vault_context",
    "session_brief": "session_brief",
    "vault_record_usage": "vault_record_usage",
    "vault_prediction_errors": "vault_prediction_errors",
    "vault_remember": "vault_remember",
    "vault_forget": "vault_forget",
    "vault_update_memory": "vault_update_memory",
    "vault_merge": "vault_merge",
    "vault_memories": "vault_memories",
    "vault_capture": "vault_capture",
    "vault_session_start": "vault_session_start",
    "vault_session_end": "vault_session_end",
    "vault_harvest": "vault_harvest",
}


def enable_cloud_dispatch(registry: ToolRegistry, client: CloudClient) -> int:
    """Replace local tool functions with cloud-proxied versions.

    For each tool in the registry that has a corresponding CloudClient method,
    swaps the ``fn`` on the frozen ToolDef with a lambda that calls the client.

    Args:
        registry: The populated tool registry (after ensure_registered()).
        client: A configured CloudClient instance.

    Returns:
        Number of tools successfully re-pointed to cloud.
    """
    count = 0
    for tool_name, method_name in _TOOL_TO_METHOD.items():
        tool_def = registry.get(tool_name)
        if tool_def is None:
            log.debug("Tool %r not in registry — skipping cloud dispatch", tool_name)
            continue

        cloud_method = getattr(client, method_name, None)
        if cloud_method is None:
            log.warning(
                "CloudClient missing method %r for tool %r", method_name, tool_name,
            )
            continue

        # ToolDef is frozen, so we replace via object.__setattr__
        object.__setattr__(tool_def, "fn", cloud_method)
        count += 1
        log.debug("Cloud dispatch: %s -> CloudClient.%s", tool_name, method_name)

    log.info("Cloud dispatch enabled for %d/%d tools", count, len(_TOOL_TO_METHOD))
    return count
