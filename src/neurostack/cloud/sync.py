# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Vault sync engine for push, pull, and cloud query operations.

Orchestrates all cloud API interactions: uploading vault files,
polling indexing status, downloading the indexed DB, and sending
remote queries.
"""

from __future__ import annotations

import logging
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

import httpx

from .manifest import Manifest

logger = logging.getLogger(__name__)


class SyncError(Exception):
    """Raised when a sync operation fails."""


class VaultSyncEngine:
    """Orchestrates vault push, DB pull, and cloud query.

    Uses httpx directly for multipart upload, polling, and streaming
    download. All HTTP calls include Bearer auth headers.
    """

    def __init__(
        self,
        cloud_api_url: str,
        cloud_api_key: str,
        vault_root: Path,
        db_dir: Path,
        manifest_path: Path | None = None,
        poll_interval: float = 5.0,
        poll_timeout: float = 3600.0,
    ) -> None:
        self._api_url = cloud_api_url.rstrip("/")
        self._api_key = cloud_api_key
        self._vault_root = vault_root
        self._db_dir = db_dir
        self._manifest_path = manifest_path or (
            vault_root / ".neurostack" / "cloud-manifest.json"
        )
        self._poll_interval = poll_interval
        self._poll_timeout = poll_timeout

    def _headers(self) -> dict[str, str]:
        """Build Bearer auth header."""
        return {"Authorization": f"Bearer {self._api_key}"}

    def push(
        self, *, progress_callback: Callable[[str], None] | None = None
    ) -> dict:
        """Upload changed vault files and wait for indexing.

        Steps:
        1. Scan vault -> new manifest
        2. Load saved manifest -> old manifest
        3. Compute diff
        4. If no changes, return early
        5. Upload changed files via multipart POST
        6. Poll status until complete or failed
        7. Save new manifest on success
        8. Return job result dict
        """
        # 1-3: Scan and diff
        new_manifest = Manifest.scan_vault(self._vault_root)
        old_manifest = Manifest.load(self._manifest_path)
        diff = Manifest.diff(old_manifest, new_manifest)

        if not diff.has_changes:
            logger.info("No changes detected, skipping upload")
            if progress_callback:
                progress_callback("No changes detected")
            return {"status": "no_changes", "message": "Vault is up to date"}

        upload_files = diff.upload_files
        logger.info(
            "Uploading %d files (%d added, %d changed, %d removed)",
            len(upload_files),
            len(diff.added),
            len(diff.changed),
            len(diff.removed),
        )

        if progress_callback:
            progress_callback(f"Uploading {len(upload_files)} files...")

        # 5-7: Upload and poll
        with httpx.Client(headers=self._headers(), timeout=300.0) as client:
            # Build multipart file list
            files = []
            for rel_path in upload_files:
                full_path = self._vault_root / rel_path
                content = full_path.read_bytes()
                files.append(("files", (rel_path, content, "text/markdown")))

            # POST upload
            resp = client.post(f"{self._api_url}/v1/vault/upload", files=files)
            resp.raise_for_status()
            upload_data = resp.json()

            job_id = upload_data["job_id"]
            logger.info("Upload accepted, job_id=%s", job_id)

            if progress_callback:
                progress_callback(f"Upload accepted, polling job {job_id}...")

            # Poll for completion
            result = self._poll_job(client, job_id, progress_callback)

        # 8: Save manifest on success
        new_manifest.save(self._manifest_path)
        logger.info("Manifest saved to %s", self._manifest_path)

        return result

    def _poll_job(
        self,
        client: httpx.Client,
        job_id: str,
        progress_callback: Callable[[str], None] | None = None,
    ) -> dict:
        """Poll job status until terminal state.

        Raises SyncError on failure or timeout.
        """
        start = time.monotonic()
        url = f"{self._api_url}/v1/vault/status/{job_id}"

        while True:
            elapsed = time.monotonic() - start
            if elapsed >= self._poll_timeout:
                raise SyncError(
                    f"Indexing timed out after {self._poll_timeout}s "
                    f"for job {job_id}"
                )

            resp = client.get(url)
            resp.raise_for_status()
            data = resp.json()

            status = data.get("status", "unknown")
            logger.info(
                "Job %s: status=%s, progress=%s",
                job_id,
                status,
                data.get("progress"),
            )

            if progress_callback:
                progress = data.get("progress")
                msg = f"Job {job_id}: {status}"
                if progress is not None:
                    msg += f" ({progress:.0%})"
                progress_callback(msg)

            if status == "complete":
                return data

            if status == "failed":
                error = data.get("error", "Unknown indexing error")
                raise SyncError(f"Indexing failed for job {job_id}: {error}")

            time.sleep(self._poll_interval)

    def pull(self, *, db_path: Path | None = None) -> Path:
        """Download indexed DB from cloud.

        Steps:
        1. GET /v1/vault/download -> presigned URL
        2. Stream download to temp file
        3. Atomic rename to db_dir/neurostack.db
        4. Return path to downloaded DB
        """
        target = db_path or (self._db_dir / "neurostack.db")
        target.parent.mkdir(parents=True, exist_ok=True)

        with httpx.Client(headers=self._headers(), timeout=60.0) as client:
            # Get presigned download URL
            resp = client.get(f"{self._api_url}/v1/vault/download")
            resp.raise_for_status()
            download_info = resp.json()
            download_url = download_info["download_url"]

            logger.info("Downloading DB from presigned URL...")

            # Stream to temp file, then atomic rename
            with tempfile.NamedTemporaryFile(
                dir=str(target.parent), delete=False, suffix=".tmp"
            ) as tmp_file:
                tmp_path = Path(tmp_file.name)
                with client.stream("GET", download_url) as stream:
                    stream.raise_for_status()
                    for chunk in stream.iter_bytes(chunk_size=65536):
                        tmp_file.write(chunk)

            # Atomic rename
            tmp_path.rename(target)
            logger.info("DB downloaded to %s", target)

        return target

    def query(
        self,
        search_text: str,
        *,
        top_k: int = 10,
        mode: str = "hybrid",
    ) -> list[dict]:
        """Query the cloud-indexed vault.

        Sends POST /v1/vault/query with search params.
        Handles 501 (not implemented) gracefully.
        """
        with httpx.Client(headers=self._headers(), timeout=30.0) as client:
            body = {"query": search_text, "top_k": top_k, "mode": mode}
            resp = client.post(f"{self._api_url}/v1/vault/query", json=body)

            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError:
                if resp.status_code == 501:
                    raise SyncError(
                        "Cloud query API not yet available. "
                        "This feature is coming in a future release."
                    )
                raise

            data = resp.json()
            return data.get("results", [])
