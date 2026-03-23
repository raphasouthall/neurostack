# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Cloud indexing pipeline for NeuroStack.

Accepts uploaded vault files, delegates AI work (embeddings + LLM
extraction) to the Gemini API via its OpenAI-compatible endpoint, and
produces indexed SQLite databases stored in Google Cloud Storage.

Uses an in-process async pipeline (cloud_index_vault) with 20-note
concurrency instead of a sequential subprocess, reducing indexing time
from 8+ hours to ~5 minutes for 500 notes.

Tenant isolation guarantees:
- Each indexing job uses its own temp directory and explicit db_path.
- The parent process's module-level globals are never mutated.
- Vault files are written to a per-job temp directory, isolated from
  other tenants and the host filesystem.
- Filenames must be pre-sanitised by the API layer before reaching here.
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from pathlib import Path

from .async_indexer import cloud_index_vault
from .config import CloudConfig
from .storage import GCSStorageClient

log = logging.getLogger("neurostack.cloud.indexer")


class CloudIndexer:
    """Orchestrates cloud indexing via Gemini API and GCS."""

    def __init__(self, config: CloudConfig, storage: GCSStorageClient) -> None:
        self._config = config
        self._storage = storage

    def index_vault(self, user_id: str, vault_files: dict[str, bytes]) -> dict:
        """Index vault files using async Gemini API pipeline and store result in GCS.

        Runs the two-phase async pipeline in-process:
          Phase 1: Parse + FTS5 + batch embed (~45s)
          Phase 2: 20-concurrent summarize + triples (~5min)

        Args:
            user_id: Tenant identifier for GCS key prefix.
            vault_files: Mapping of filename -> file content bytes.
                         Filenames must already be sanitised by the caller.

        Returns:
            Dict with keys: status, db_size, note_count (on success)
            or status, error (on failure).
        """
        with tempfile.TemporaryDirectory(prefix=f"ns-cloud-{user_id}-") as tmpdir:
            db_path = Path(tmpdir) / "neurostack.db"

            try:
                result = asyncio.run(
                    cloud_index_vault(vault_files, db_path, self._config)
                )

                if result.get("status") == "complete" and db_path.exists():
                    self._storage.upload_db(user_id, db_path)
                    return result
                elif result.get("status") == "complete":
                    # Pipeline said complete but no DB file
                    return {"status": "failed", "error": "No database produced"}
                else:
                    return result

            except Exception as exc:
                log.exception("Cloud indexing failed for user %s", user_id)
                return {"status": "failed", "error": str(exc)}
