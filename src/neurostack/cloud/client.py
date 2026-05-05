# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""HTTP client for NeuroStack Cloud API with Bearer token authentication.

Covers all 21 MCP tools. Methods with dedicated REST endpoints use them
directly; the rest route through ``POST /v1/vault/tools/{name}``.
"""

from __future__ import annotations

from typing import Any

import httpx

from .config import CloudConfig


class CloudClient:
    """HTTP client for NeuroStack Cloud API with Bearer token authentication.

    Wraps httpx for synchronous HTTP calls (CLI is synchronous).
    All authenticated requests include ``Authorization: Bearer {api_key}``.
    """

    def __init__(self, config: CloudConfig) -> None:
        self._config = config
        self._base_url = config.cloud_api_url.rstrip("/")

    @property
    def is_configured(self) -> bool:
        """True if both cloud URL and API key are set."""
        return bool(self._config.cloud_api_url and self._config.cloud_api_key)

    def _auth_headers(self) -> dict[str, str]:
        """Build Bearer auth header from stored API key."""
        if self._config.cloud_api_key:
            return {"Authorization": f"Bearer {self._config.cloud_api_key}"}
        return {}

    def _post(self, path: str, body: dict, *, timeout: float = 60.0) -> httpx.Response:
        """Authenticated POST request."""
        return httpx.post(
            f"{self._base_url}{path}",
            json=body,
            headers=self._auth_headers(),
            timeout=timeout,
        )

    def _get(self, path: str, *, timeout: float = 30.0) -> httpx.Response:
        """Authenticated GET request."""
        return httpx.get(
            f"{self._base_url}{path}",
            headers=self._auth_headers(),
            timeout=timeout,
        )

    def _handle_response(self, resp: httpx.Response) -> dict:
        """Common response handling: 404 -> FileNotFoundError, else raise."""
        if resp.status_code == 404:
            detail = "No database found"
            try:
                detail = resp.json().get("detail", detail)
            except Exception:
                pass
            raise FileNotFoundError(detail)
        resp.raise_for_status()
        return resp.json()

    def _tool_call(self, tool_name: str, **kwargs: Any) -> dict:
        """Generic tool invocation via POST /v1/vault/tools/{name}.

        Used for tools that don't have a dedicated REST endpoint.
        The cloud API dispatches to the same tool implementation.
        """
        body = {k: v for k, v in kwargs.items() if v is not None}
        resp = self._post(f"/v1/vault/tools/{tool_name}", body)
        return self._handle_response(resp)

    # -----------------------------------------------------------------
    # Infrastructure
    # -----------------------------------------------------------------

    def health(self) -> dict:
        """Check cloud API health. No auth required."""
        url = f"{self._base_url}/health"
        try:
            resp = httpx.get(url, timeout=10.0)
            resp.raise_for_status()
            return resp.json()
        except httpx.ConnectError:
            raise ConnectionError(
                f"Cannot reach cloud API at {self._base_url}. "
                "Check your cloud_api_url setting."
            )
        except httpx.TimeoutException:
            raise ConnectionError(
                f"Cloud API at {self._base_url} timed out."
            )

    def validate_key(self) -> bool:
        """Validate stored API key. Returns True on 200, False on 401."""
        url = f"{self._base_url}/v1/usage"
        try:
            resp = httpx.get(url, headers=self._auth_headers(), timeout=10.0)
        except httpx.ConnectError:
            raise ConnectionError(
                f"Cannot reach cloud API at {self._base_url}. "
                "Check your cloud_api_url setting."
            )
        except httpx.TimeoutException:
            raise ConnectionError(
                f"Cloud API at {self._base_url} timed out."
            )
        if resp.status_code == 401:
            return False
        return resp.status_code == 200

    def status(self) -> dict:
        """Get authenticated status including tier and usage."""
        url = f"{self._base_url}/v1/usage"
        try:
            resp = httpx.get(url, headers=self._auth_headers(), timeout=10.0)
        except (httpx.ConnectError, httpx.TimeoutException):
            return {
                "authenticated": False, "tier": None,
                "cloud_url": self._base_url, "usage": None,
            }
        if resp.status_code == 401:
            return {
                "authenticated": False, "tier": None,
                "cloud_url": self._base_url, "usage": None,
            }
        if resp.status_code == 200:
            data = resp.json()
            return {
                "authenticated": True,
                "tier": data.get("tier", "free"),
                "cloud_url": self._base_url,
                "usage": data.get("usage"),
            }
        return {
            "authenticated": False, "tier": None,
            "cloud_url": self._base_url, "usage": None,
        }

    # -----------------------------------------------------------------
    # Search & Retrieval (dedicated endpoints)
    # -----------------------------------------------------------------

    def vault_search(
        self,
        query: str,
        *,
        top_k: int = 5,
        mode: str = "hybrid",
        depth: str = "auto",
        context: str | None = None,
        workspace: str | None = None,
    ) -> dict:
        """Hybrid search with tiered retrieval depth."""
        body: dict = {"query": query, "top_k": top_k, "depth": depth, "mode": mode}
        if workspace:
            body["workspace"] = workspace
        if context:
            body["context"] = context
        resp = self._post("/v1/vault/query", body)
        return self._handle_response(resp)

    def vault_triples(
        self,
        query: str,
        *,
        top_k: int = 10,
        mode: str = "hybrid",
        workspace: str | None = None,
    ) -> dict:
        """Search knowledge graph triples."""
        body: dict = {"query": query, "top_k": top_k}
        if mode != "hybrid":
            body["mode"] = mode
        if workspace:
            body["workspace"] = workspace
        resp = self._post("/v1/vault/triples", body)
        data = self._handle_response(resp)
        # Normalize: REST returns {"triples": [...]}, tool expects dict
        if "triples" in data and not any(
            k for k in data if k != "triples"
        ):
            return data
        return data

    def vault_summary(self, path_or_query: str) -> dict:
        """Get pre-computed note summary."""
        resp = self._post("/v1/vault/summary", {"note_path": path_or_query})
        if resp.status_code == 404:
            return {"error": f"No summary found for: {path_or_query}"}
        resp.raise_for_status()
        return resp.json()

    def vault_stats(self) -> dict:
        """Get vault index health statistics."""
        resp = self._get("/v1/vault/stats")
        stats = self._handle_response(resp)
        # Also fetch health metrics
        try:
            health_resp = self._get("/v1/vault/health")
            if health_resp.status_code == 200:
                stats.update(health_resp.json())
        except Exception:
            pass
        return stats

    def vault_graph(
        self,
        note: str,
        *,
        depth: int = 1,
        workspace: str | None = None,
    ) -> dict:
        """Get wiki-link neighborhood of a note."""
        return self._tool_call(
            "vault_graph", note=note, depth=depth, workspace=workspace,
        )

    def vault_related(
        self,
        note: str,
        *,
        top_k: int = 10,
        workspace: str | None = None,
    ) -> dict:
        """Find semantically similar notes."""
        return self._tool_call(
            "vault_related", note=note, top_k=top_k, workspace=workspace,
        )

    def vault_ask(
        self,
        question: str,
        *,
        top_k: int = 8,
        workspace: str | None = None,
    ) -> dict:
        """RAG Q&A with inline citations."""
        return self._tool_call(
            "vault_ask", question=question, top_k=top_k, workspace=workspace,
        )

    def vault_communities(
        self,
        query: str,
        *,
        top_k: int = 6,
        level: int = 0,
        map_reduce: bool = True,
        workspace: str | None = None,
    ) -> dict:
        """GraphRAG global queries across topic clusters."""
        return self._tool_call(
            "vault_communities",
            query=query, top_k=top_k, level=level,
            map_reduce=map_reduce, workspace=workspace,
        )

    def vault_context(
        self,
        task: str,
        *,
        token_budget: int = 2000,
        workspace: str | None = None,
        include_memories: bool = True,
        include_triples: bool = True,
    ) -> dict:
        """Task-scoped context recovery."""
        return self._tool_call(
            "vault_context",
            task=task, token_budget=token_budget, workspace=workspace,
            include_memories=include_memories, include_triples=include_triples,
        )

    def session_brief(self, *, workspace: str | None = None) -> dict:
        """Compact session briefing."""
        return self._tool_call("session_brief", workspace=workspace)

    def vault_record_usage(self, note_paths: list[str]) -> dict:
        """Record note usage for hotness scoring."""
        return self._tool_call("vault_record_usage", note_paths=note_paths)

    def vault_prediction_errors(
        self,
        *,
        error_type: str | None = None,
        limit: int = 20,
        resolve: list[str] | None = None,
        workspace: str | None = None,
    ) -> dict:
        """Find notes flagged as poor retrieval fit."""
        return self._tool_call(
            "vault_prediction_errors",
            error_type=error_type, limit=limit,
            resolve=resolve, workspace=workspace,
        )

    # -----------------------------------------------------------------
    # Memories (write operations — cloud stores in Firestore)
    # -----------------------------------------------------------------

    def vault_remember(
        self,
        content: str,
        *,
        tags: list[str] | None = None,
        entity_type: str = "observation",
        source_agent: str | None = None,
        workspace: str | None = None,
        ttl_hours: float | None = None,
        session_id: int | None = None,
    ) -> dict:
        """Save a memory."""
        return self._tool_call(
            "vault_remember",
            content=content, tags=tags, entity_type=entity_type,
            source_agent=source_agent, workspace=workspace,
            ttl_hours=ttl_hours, session_id=session_id,
        )

    def vault_forget(self, memory_id: int) -> dict:
        """Delete a memory."""
        return self._tool_call("vault_forget", memory_id=memory_id)

    def vault_update_memory(
        self,
        memory_id: int,
        *,
        content: str | None = None,
        tags: list[str] | None = None,
        add_tags: list[str] | None = None,
        remove_tags: list[str] | None = None,
        entity_type: str | None = None,
        workspace: str | None = None,
        ttl_hours: float | None = None,
    ) -> dict:
        """Update a memory."""
        return self._tool_call(
            "vault_update_memory",
            memory_id=memory_id, content=content, tags=tags,
            add_tags=add_tags, remove_tags=remove_tags,
            entity_type=entity_type, workspace=workspace,
            ttl_hours=ttl_hours,
        )

    def vault_merge(self, target_id: int, source_id: int) -> dict:
        """Merge two memories."""
        return self._tool_call(
            "vault_merge", target_id=target_id, source_id=source_id,
        )

    def vault_memories(
        self,
        *,
        query: str | None = None,
        entity_type: str | None = None,
        workspace: str | None = None,
        limit: int = 20,
    ) -> dict:
        """Search or list memories."""
        return self._tool_call(
            "vault_memories",
            query=query, entity_type=entity_type,
            workspace=workspace, limit=limit,
        )

    # -----------------------------------------------------------------
    # Sessions
    # -----------------------------------------------------------------

    def vault_session_start(
        self,
        *,
        source_agent: str | None = None,
        workspace: str | None = None,
    ) -> dict:
        """Begin a memory session."""
        return self._tool_call(
            "vault_session_start",
            source_agent=source_agent, workspace=workspace,
        )

    def vault_session_end(
        self,
        session_id: int,
        *,
        summarize: bool = True,
        auto_harvest: bool = True,
    ) -> dict:
        """End a memory session."""
        return self._tool_call(
            "vault_session_end",
            session_id=session_id, summarize=summarize,
            auto_harvest=auto_harvest,
        )

    def vault_harvest(
        self,
        *,
        sessions: int = 1,
        dry_run: bool = False,
        provider: str | None = None,
    ) -> dict:
        """Extract insights from Claude Code sessions."""
        return self._tool_call(
            "vault_harvest",
            sessions=sessions, dry_run=dry_run, provider=provider,
        )

    # -----------------------------------------------------------------
    # Backwards compatibility aliases
    # -----------------------------------------------------------------

    def query(
        self,
        query: str,
        *,
        top_k: int = 10,
        depth: str = "auto",
        mode: str = "hybrid",
        workspace: str | None = None,
    ) -> dict:
        """Alias for vault_search (backwards compat with existing callers)."""
        return self.vault_search(
            query, top_k=top_k, depth=depth, mode=mode, workspace=workspace,
        )

    def triples(
        self,
        query: str,
        *,
        top_k: int = 10,
        workspace: str | None = None,
    ) -> list[dict]:
        """Alias for vault_triples (backwards compat)."""
        result = self.vault_triples(query, top_k=top_k, workspace=workspace)
        return result.get("triples", []) if isinstance(result, dict) else result

    def summary(self, note_path: str) -> dict | None:
        """Alias for vault_summary (backwards compat)."""
        result = self.vault_summary(note_path)
        if isinstance(result, dict) and "error" in result:
            return None
        return result
