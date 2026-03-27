# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Vault sync engine for push, pull, and cloud query operations.

Orchestrates all cloud API interactions: uploading vault files,
polling indexing status, downloading the indexed DB, and sending
remote queries.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import sqlite3
import tarfile
import tempfile
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

import httpx

from .manifest import Manifest

logger = logging.getLogger(__name__)


NEUROSTACKIGNORE_FILE = ".neurostackignore"


class SyncError(Exception):
    """Raised when a sync operation fails."""


class ConsentError(SyncError):
    """Raised when cloud consent has not been given."""


class VaultSyncEngine:
    """Orchestrates vault push, DB pull, and cloud query.

    Uses httpx directly for tar.gz upload, polling, and streaming
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
        consent_given: bool = True,
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
        self._consent_given = consent_given

    def _headers(self) -> dict[str, str]:
        """Build Bearer auth header."""
        return {"Authorization": f"Bearer {self._api_key}"}

    def _build_tar_archive(
        self, upload_files: list[str], diff: object
    ) -> bytes:
        """Pack upload files and manifest into a tar.gz archive.

        Creates a tar.gz containing:
        - ``_manifest.json`` with format_version, removed list, and file_hashes
        - Each .md file from *upload_files*

        Args:
            upload_files: Relative paths of files to include.
            diff: A ``SyncDiff`` instance (uses ``.removed``).

        Returns:
            The tar.gz archive as raw bytes.
        """
        buf = io.BytesIO()
        file_hashes: dict[str, str] = {}

        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            # Add each vault file
            for rel_path in upload_files:
                full_path = self._vault_root / rel_path
                content = full_path.read_bytes()
                file_hashes[rel_path] = (
                    "sha256:" + hashlib.sha256(content).hexdigest()
                )
                info = tarfile.TarInfo(name=rel_path)
                info.size = len(content)
                tar.addfile(info, io.BytesIO(content))

            # Build and add _manifest.json
            manifest_data = {
                "format_version": 1,
                "removed": list(getattr(diff, "removed", [])),
                "file_hashes": file_hashes,
            }
            manifest_bytes = json.dumps(manifest_data).encode()
            info = tarfile.TarInfo(name="_manifest.json")
            info.size = len(manifest_bytes)
            tar.addfile(info, io.BytesIO(manifest_bytes))

        return buf.getvalue()

    def push(
        self, *, progress_callback: Callable[[str], None] | None = None
    ) -> dict:
        """Upload changed vault files and wait for indexing.

        Steps:
        1. Check consent
        2. Scan vault -> new manifest
        3. Load saved manifest -> old manifest
        4. Compute diff
        5. If no changes, return early
        6. Upload changed files via tar.gz POST
        7. Poll status until complete or failed
        8. Save new manifest on success
        9. Return job result dict
        """
        # 1: Consent check
        if not self._consent_given:
            raise ConsentError(
                "Cloud consent not given. Run `neurostack cloud consent` "
                "or `neurostack init --cloud` to grant consent."
            )

        # 2-4: Scan and diff
        ignore_path = self._vault_root / NEUROSTACKIGNORE_FILE
        new_manifest = Manifest.scan_vault(
            self._vault_root,
            ignore_file=ignore_path if ignore_path.exists() else None,
        )
        old_manifest = Manifest.load(self._manifest_path)
        diff = Manifest.diff(old_manifest, new_manifest)

        if not diff.has_changes:
            logger.info("No changes detected, skipping upload")
            if progress_callback:
                progress_callback("No changes detected")
            return {
                "status": "no_changes",
                "message": "Vault is up to date",
                "upload_stats": {
                    "files_uploaded": 0,
                    "raw_bytes": 0,
                    "compressed_bytes": 0,
                    "compression_ratio": 0.0,
                },
            }

        upload_files = diff.upload_files
        logger.info(
            "Uploading %d files (%d added, %d changed, %d removed)",
            len(upload_files),
            len(diff.added),
            len(diff.changed),
            len(diff.removed),
        )

        # 5-7: Upload via tar.gz and poll
        archive_data = self._build_tar_archive(upload_files, diff)

        # Calculate upload stats
        total_raw_bytes = sum(
            (self._vault_root / rel_path).stat().st_size for rel_path in upload_files
        )
        archive_bytes = len(archive_data)
        compression_ratio = (
            (1 - archive_bytes / total_raw_bytes) * 100 if total_raw_bytes > 0 else 0
        )

        if progress_callback:
            progress_callback(
                f"Uploading {len(upload_files)} files "
                f"({archive_bytes / 1024:.1f} KB, "
                f"{compression_ratio:.0f}% compression)"
            )

        with httpx.Client(headers=self._headers(), timeout=300.0) as client:
            headers = {
                "Content-Type": "application/gzip",
                "X-Upload-Format": "tar.gz",
            }
            resp = client.post(
                f"{self._api_url}/v1/vault/upload",
                content=archive_data,
                headers=headers,
            )
            resp.raise_for_status()
            upload_data = resp.json()

            job_id = upload_data["job_id"]
            logger.info("Upload accepted, job_id=%s", job_id)

            if progress_callback:
                progress_callback(f"Upload complete ({archive_bytes / 1024:.1f} KB sent)")

            if progress_callback:
                progress_callback(f"Upload accepted, polling job {job_id}...")

            # Poll for completion
            result = self._poll_job(client, job_id, progress_callback)

        # 8: Save manifest on success
        new_manifest.save(self._manifest_path)
        logger.info("Manifest saved to %s", self._manifest_path)

        result["upload_stats"] = {
            "files_uploaded": len(upload_files),
            "raw_bytes": total_raw_bytes,
            "compressed_bytes": archive_bytes,
            "compression_ratio": round(compression_ratio, 1),
        }

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
        2. Stream download to temp file (separate client, no auth headers)
        3. Verify downloaded size matches Content-Length
        4. Atomic rename to db_dir/neurostack.db
        5. Return path to downloaded DB
        """
        target = db_path or (self._db_dir / "neurostack.db")
        target.parent.mkdir(parents=True, exist_ok=True)

        # Step 1: Get presigned download URL (authenticated)
        with httpx.Client(headers=self._headers(), timeout=60.0) as client:
            resp = client.get(f"{self._api_url}/v1/vault/download")
            resp.raise_for_status()
            download_info = resp.json()
            download_url = download_info["download_url"]

        logger.info("Downloading DB from presigned URL...")

        # Step 2: Stream download with a SEPARATE client -- no auth headers
        # (GCS signed URLs reject extra Authorization headers) and a longer
        # timeout suitable for large files (72MB+).
        download_timeout = httpx.Timeout(
            connect=30.0, read=300.0, write=30.0, pool=30.0
        )
        bytes_written = 0
        with tempfile.NamedTemporaryFile(
            dir=str(target.parent), delete=False, suffix=".tmp"
        ) as tmp_file:
            tmp_path = Path(tmp_file.name)
            try:
                with httpx.Client(timeout=download_timeout) as dl_client:
                    with dl_client.stream("GET", download_url) as stream:
                        stream.raise_for_status()
                        expected_size = stream.headers.get("content-length")
                        for chunk in stream.iter_bytes(chunk_size=131072):
                            tmp_file.write(chunk)
                            bytes_written += len(chunk)
            except Exception:
                # Clean up temp file on failure
                tmp_path.unlink(missing_ok=True)
                raise

        # Step 3: Verify download integrity
        if expected_size is not None:
            expected = int(expected_size)
            if bytes_written != expected:
                tmp_path.unlink(missing_ok=True)
                raise SyncError(
                    f"Download incomplete: got {bytes_written} bytes, "
                    f"expected {expected} bytes"
                )

        logger.info(
            "Downloaded %d bytes to temp file", bytes_written
        )

        # Step 4: Remove stale WAL/SHM from previous DB before replacing
        for suffix in ("-wal", "-shm"):
            stale = target.with_name(target.name + suffix)
            if stale.exists():
                stale.unlink()

        # Step 5: Atomic rename
        tmp_path.rename(target)
        logger.info("DB saved to %s (%d bytes)", target, bytes_written)

        return target

    def query(
        self,
        search_text: str,
        *,
        top_k: int = 10,
        depth: str = "auto",
        mode: str = "hybrid",
        workspace: str | None = None,
    ) -> dict:
        """Query the cloud-indexed vault.

        Sends POST /v1/vault/query with search params.
        Returns dict with triples, summaries, chunks, and depth_used.
        """
        with httpx.Client(headers=self._headers(), timeout=30.0) as client:
            body: dict = {
                "query": search_text,
                "top_k": top_k,
                "depth": depth,
                "mode": mode,
            }
            if workspace:
                body["workspace"] = workspace

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

            return resp.json()

    def sync(
        self,
        *,
        progress_callback: Callable[[str], None] | None = None,
    ) -> dict:
        """Push vault changes and fetch new memories from cloud.

        Steps:
        1. Check consent
        2. Scan vault and compute diff (reuses push logic)
        3. Upload changed files if any (reuses push upload + poll)
        4. Save manifest on success
        5. Fetch new memories from cloud since last sync
        6. Merge memories into local SQLite (INSERT OR REPLACE, dedup by UUID)
        7. Store last_sync_time from server response
        8. Return combined result dict
        """
        # 1: Consent check
        if not self._consent_given:
            raise ConsentError(
                "Cloud consent not given. Run `neurostack cloud consent` "
                "or `neurostack init --cloud` to grant consent."
            )

        # --- Push phase (reuse push logic inline) ---
        from .manifest import Manifest  # noqa: F811

        ignore_path = self._vault_root / NEUROSTACKIGNORE_FILE
        new_manifest = Manifest.scan_vault(
            self._vault_root,
            ignore_file=ignore_path if ignore_path.exists() else None,
        )
        old_manifest = Manifest.load(self._manifest_path)
        diff = Manifest.diff(old_manifest, new_manifest)

        push_result: dict
        if not diff.has_changes:
            logger.info("No changes detected, skipping upload")
            if progress_callback:
                progress_callback("No changes detected")
            push_result = {
                "status": "no_changes",
                "message": "Vault is up to date",
                "upload_stats": {
                    "files_uploaded": 0,
                    "raw_bytes": 0,
                    "compressed_bytes": 0,
                    "compression_ratio": 0.0,
                },
            }
        else:
            upload_files = diff.upload_files
            logger.info(
                "Uploading %d files (%d added, %d changed, %d removed)",
                len(upload_files),
                len(diff.added),
                len(diff.changed),
                len(diff.removed),
            )

            archive_data = self._build_tar_archive(upload_files, diff)

            # Calculate upload stats
            total_raw_bytes = sum(
                (self._vault_root / rel_path).stat().st_size for rel_path in upload_files
            )
            archive_bytes = len(archive_data)
            compression_ratio = (
            (1 - archive_bytes / total_raw_bytes) * 100 if total_raw_bytes > 0 else 0
        )

            if progress_callback:
                progress_callback(
                    f"Uploading {len(upload_files)} files "
                    f"({archive_bytes / 1024:.1f} KB, "
                    f"{compression_ratio:.0f}% compression)"
                )

            with httpx.Client(headers=self._headers(), timeout=300.0) as client:
                headers = {
                    "Content-Type": "application/gzip",
                    "X-Upload-Format": "tar.gz",
                }
                resp = client.post(
                    f"{self._api_url}/v1/vault/upload",
                    content=archive_data,
                    headers=headers,
                )
                resp.raise_for_status()
                upload_data = resp.json()

                job_id = upload_data["job_id"]
                logger.info("Upload accepted, job_id=%s", job_id)

                if progress_callback:
                    progress_callback(f"Upload complete ({archive_bytes / 1024:.1f} KB sent)")

                if progress_callback:
                    progress_callback(f"Upload accepted, polling job {job_id}...")

                push_result = self._poll_job(client, job_id, progress_callback)

            new_manifest.save(self._manifest_path)
            logger.info("Manifest saved to %s", self._manifest_path)

            push_result["upload_stats"] = {
                "files_uploaded": len(upload_files),
                "raw_bytes": total_raw_bytes,
                "compressed_bytes": archive_bytes,
                "compression_ratio": round(compression_ratio, 1),
            }

        # --- Memory fetch phase ---
        if progress_callback:
            progress_callback("Fetching new memories from cloud...")

        last_sync_time = self._load_last_sync_time()
        memories_fetched = 0
        server_time: str | None = None

        try:
            with httpx.Client(headers=self._headers(), timeout=30.0) as client:
                params: dict[str, str | int] = {"limit": 100}
                if last_sync_time:
                    params["after"] = last_sync_time

                resp = client.get(
                    f"{self._api_url}/v1/vault/memories/since",
                    params=params,
                )
                resp.raise_for_status()
                mem_data = resp.json()

            memories = mem_data.get("memories", [])
            server_time = mem_data.get("server_time")
            memories_fetched = len(memories)

            if memories:
                self._merge_memories(memories)
                logger.info("Merged %d memories into local DB", memories_fetched)
            else:
                logger.info("No new memories from cloud")

            if progress_callback:
                progress_callback(f"Fetched {memories_fetched} memories")

        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                logger.warning("Memories endpoint not available (404), skipping")
                if progress_callback:
                    progress_callback("Memories endpoint not available, skipped")
            else:
                raise

        # Save sync time
        if server_time:
            self._save_last_sync_time(server_time)

        return {
            **push_result,
            "memories_fetched": memories_fetched,
        }

    def _sync_meta_path(self) -> Path:
        """Path to the cloud sync metadata file."""
        return Path.home() / ".local" / "share" / "neurostack" / "cloud-sync-meta.json"

    def _load_last_sync_time(self) -> str | None:
        """Load last_sync_time from sync metadata file."""
        meta_path = self._sync_meta_path()
        if not meta_path.exists():
            return None
        try:
            data = json.loads(meta_path.read_text())
            return data.get("last_sync_time")
        except (json.JSONDecodeError, OSError):
            return None

    def _save_last_sync_time(self, server_time: str) -> None:
        """Save last_sync_time to sync metadata file."""
        meta_path = self._sync_meta_path()
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(json.dumps({"last_sync_time": server_time}))

    def get_staleness(self) -> dict:
        """Compute staleness between local vault and last cloud sync.

        Compares the latest modification time of any .md file in the vault
        against the last_sync_time stored in cloud-sync-meta.json. Uses
        stat-only checks (no file reads) for performance.

        Returns:
            Dict with is_stale, local_latest, last_sync, stale_since,
            stale_files_count, and behind_hours fields.
        """
        # Find the latest mtime of any .md file in the vault
        local_latest_dt: datetime | None = None
        stale_files_count = 0
        stale_since_dt: datetime | None = None

        last_sync_str = self._load_last_sync_time()
        last_sync_dt: datetime | None = None
        if last_sync_str:
            try:
                last_sync_dt = datetime.fromisoformat(last_sync_str)
                if last_sync_dt.tzinfo is None:
                    last_sync_dt = last_sync_dt.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                last_sync_dt = None

        for md_file in self._vault_root.rglob("*.md"):
            # Skip dot-directories (.obsidian, .git, .neurostack)
            if any(part.startswith(".") for part in md_file.relative_to(self._vault_root).parts):
                continue
            mtime = datetime.fromtimestamp(md_file.stat().st_mtime, tz=timezone.utc)
            if local_latest_dt is None or mtime > local_latest_dt:
                local_latest_dt = mtime

            if last_sync_dt is not None and mtime > last_sync_dt:
                stale_files_count += 1
                if stale_since_dt is None or mtime < stale_since_dt:
                    stale_since_dt = mtime

        # No sync meta at all => stale (never synced)
        if last_sync_dt is None:
            return {
                "is_stale": True,
                "local_latest": local_latest_dt.isoformat() if local_latest_dt else None,
                "last_sync": None,
                "stale_since": None,
                "stale_files_count": 0,
                "behind_hours": None,
            }

        is_stale = local_latest_dt is not None and local_latest_dt > last_sync_dt

        behind_hours: float | None = None
        if is_stale and local_latest_dt is not None:
            behind_hours = round(
                (local_latest_dt - last_sync_dt).total_seconds() / 3600, 1
            )

        return {
            "is_stale": is_stale,
            "local_latest": local_latest_dt.isoformat() if local_latest_dt else None,
            "last_sync": last_sync_str,
            "stale_since": stale_since_dt.isoformat() if stale_since_dt else None,
            "stale_files_count": stale_files_count,
            "behind_hours": behind_hours,
        }

    def _check_neurostackignore_exists(self) -> bool:
        """Check whether a .neurostackignore file exists in the vault root."""
        return (self._vault_root / NEUROSTACKIGNORE_FILE).is_file()

    def _load_ignore_patterns(self) -> list[str]:
        """Load ignore patterns from .neurostackignore in vault root.

        Returns a list of pattern strings (one per non-empty, non-comment line).
        """
        ignore_path = self._vault_root / NEUROSTACKIGNORE_FILE
        if not ignore_path.is_file():
            return []

        patterns: list[str] = []
        for line in ignore_path.read_text().splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                patterns.append(stripped)
        return patterns

    def _merge_memories(self, memories: list[dict]) -> None:
        """Merge fetched memories into local SQLite DB.

        Uses INSERT ... ON CONFLICT to upsert by UUID, preserving
        existing fields (embedding, revision_count, merge_count,
        merged_from) not present in the cloud response.
        Deletes memories marked with deleted=true.
        """
        from ..schema import get_db

        db_path = self._db_dir / "neurostack.db"
        if not db_path.exists():
            logger.warning("Local DB not found at %s, skipping memory merge", db_path)
            return

        conn = get_db(db_path)
        try:
            for mem in memories:
                if mem.get("deleted"):
                    conn.execute(
                        "DELETE FROM memories WHERE uuid = ?",
                        (mem["uuid"],),
                    )
                else:
                    tags = mem.get("tags")
                    if isinstance(tags, list):
                        tags = json.dumps(tags)
                    conn.execute(
                        "INSERT INTO memories "
                        "(uuid, content, entity_type, tags, workspace, "
                        "source_agent, session_id, expires_at, "
                        "created_at, updated_at, file_path) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                        "ON CONFLICT(uuid) DO UPDATE SET "
                        "content = excluded.content, "
                        "entity_type = excluded.entity_type, "
                        "tags = excluded.tags, "
                        "workspace = excluded.workspace, "
                        "source_agent = excluded.source_agent, "
                        "session_id = excluded.session_id, "
                        "expires_at = excluded.expires_at, "
                        "updated_at = excluded.updated_at, "
                        "file_path = excluded.file_path",
                        (
                            mem["uuid"],
                            mem.get("content", ""),
                            mem.get("entity_type", "observation"),
                            tags,
                            mem.get("workspace"),
                            mem.get("source_agent"),
                            mem.get("session_id"),
                            mem.get("expires_at"),
                            mem.get("created_at"),
                            mem.get("updated_at"),
                            mem.get("file_path"),
                        ),
                    )
            conn.commit()
        finally:
            conn.close()
