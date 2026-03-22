# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""FastAPI cloud gateway for NeuroStack Cloud.

Provides authenticated endpoints for vault upload, indexing status,
database download, and query. Hosted on GCP Cloud Run.

Tenant isolation guarantees:
- Every job, upload, and download is scoped to the authenticated user_id.
- Job status is only visible to the user who created the job.
- Filenames are sanitised to prevent path traversal across tenant prefixes.
- Upload size and count are bounded to prevent resource abuse.
"""

from __future__ import annotations

import logging
import threading
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, UploadFile, File
from pydantic import BaseModel

from .auth import require_api_key
from .config import CloudConfig, load_cloud_config
from .indexer import CloudIndexer
from .storage import GCSStorageClient

log = logging.getLogger("neurostack.cloud.api")

# ---------------------------------------------------------------------------
# Tenant isolation limits
# ---------------------------------------------------------------------------

MAX_FILES_PER_UPLOAD = 5000
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB per file
MAX_TOTAL_UPLOAD_BYTES = 500 * 1024 * 1024  # 500 MB per upload


# ---------------------------------------------------------------------------
# Filename sanitisation
# ---------------------------------------------------------------------------


def _sanitise_filename(filename: str | None) -> str:
    """Sanitise an uploaded filename to prevent path traversal.

    Rejects any filename that could escape the tenant prefix:
    - Strips leading/trailing whitespace
    - Rejects absolute paths, .., and empty names
    - Normalises path separators
    - Only allows .md files
    """
    if not filename:
        raise HTTPException(status_code=400, detail="Filename is required")

    name = filename.strip()

    # Reject absolute paths (Unix and Windows)
    if name.startswith("/") or name.startswith("\\") or (len(name) >= 2 and name[1] == ":"):
        raise HTTPException(status_code=400, detail=f"Absolute path not allowed: {name}")

    # Normalise separators
    name = name.replace("\\", "/")

    # Reject path traversal components
    parts = name.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise HTTPException(
            status_code=400,
            detail=f"Path traversal not allowed: {filename}",
        )

    # Only allow markdown files
    if not name.endswith(".md"):
        raise HTTPException(
            status_code=400,
            detail=f"Only .md files accepted, got: {name}",
        )

    return name


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class HealthResponse(BaseModel):
    status: str
    version: str


class UploadResponse(BaseModel):
    job_id: str
    status: str
    message: str


class JobStatusResponse(BaseModel):
    job_id: str
    status: str  # "queued" | "indexing" | "complete" | "failed"
    progress: float | None = None
    download_url: str | None = None
    error: str | None = None
    db_size: int | None = None
    note_count: int | None = None


class DownloadResponse(BaseModel):
    download_url: str
    expires_in: int


# ---------------------------------------------------------------------------
# App lifecycle
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize cloud infrastructure on startup."""
    config = load_cloud_config()
    storage = GCSStorageClient(config)
    indexer = CloudIndexer(config, storage)

    app.state.config = config
    app.state.storage = storage
    app.state.indexer = indexer
    app.state.jobs = {}
    app.state.jobs_lock = threading.Lock()

    yield


app = FastAPI(title="NeuroStack Cloud", version="0.8.0", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Background indexing
# ---------------------------------------------------------------------------


def _run_indexing(
    app_state, job_id: str, user_id: str, vault_files: dict[str, bytes]
) -> None:
    """Run indexing in a background thread.

    Updates app_state.jobs[job_id] with progress and results.
    """
    try:
        with app_state.jobs_lock:
            app_state.jobs[job_id]["status"] = "indexing"
        result = app_state.indexer.index_vault(user_id, vault_files)
        with app_state.jobs_lock:
            app_state.jobs[job_id].update(result)
    except Exception as exc:
        log.exception("Background indexing failed for job %s", job_id)
        with app_state.jobs_lock:
            app_state.jobs[job_id]["status"] = "failed"
            app_state.jobs[job_id]["error"] = str(exc)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/health", response_model=HealthResponse)
async def health():
    """Health check -- no authentication required."""
    return HealthResponse(status="ok", version="0.8.0")


@app.post("/v1/vault/upload", response_model=UploadResponse, status_code=202)
async def upload_vault(
    files: list[UploadFile] = File(...),
    user: dict = Depends(require_api_key),
):
    """Accept vault files for cloud indexing.

    Enforces per-tenant limits on file count, individual file size, and
    total upload size. Filenames are sanitised to prevent path traversal.
    """
    user_id = user["user_id"]

    # Enforce file count limit
    if len(files) > MAX_FILES_PER_UPLOAD:
        raise HTTPException(
            status_code=400,
            detail=f"Too many files: {len(files)} exceeds limit of {MAX_FILES_PER_UPLOAD}",
        )

    # Read and validate uploaded files
    vault_files: dict[str, bytes] = {}
    total_size = 0

    for f in files:
        safe_name = _sanitise_filename(f.filename)
        content = await f.read()

        if len(content) > MAX_FILE_SIZE_BYTES:
            raise HTTPException(
                status_code=400,
                detail=f"File too large: {safe_name} is {len(content)} bytes "
                f"(limit {MAX_FILE_SIZE_BYTES})",
            )

        total_size += len(content)
        if total_size > MAX_TOTAL_UPLOAD_BYTES:
            raise HTTPException(
                status_code=400,
                detail=f"Total upload size exceeds {MAX_TOTAL_UPLOAD_BYTES} bytes",
            )

        vault_files[safe_name] = content

    # Store raw vault files in R2 under tenant prefix
    app.state.storage.upload_vault_files(user_id, vault_files)

    # Create job scoped to this user and start background indexing
    job_id = str(uuid.uuid4())
    with app.state.jobs_lock:
        app.state.jobs[job_id] = {
            "status": "queued",
            "user_id": user_id,
            "note_count": len(vault_files),
        }

    thread = threading.Thread(
        target=_run_indexing,
        args=(app.state, job_id, user_id, vault_files),
        daemon=True,
    )
    thread.start()

    return UploadResponse(
        job_id=job_id,
        status="queued",
        message=f"Received {len(files)} files for indexing",
    )


@app.get("/v1/vault/status/{job_id}", response_model=JobStatusResponse)
async def vault_status(
    job_id: str,
    user: dict = Depends(require_api_key),
):
    """Check indexing job status. Only the owning user can see their jobs."""
    with app.state.jobs_lock:
        job = app.state.jobs.get(job_id)

    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    # Tenant isolation: job must belong to the requesting user
    if job.get("user_id") != user["user_id"]:
        raise HTTPException(status_code=404, detail="Job not found")

    return JobStatusResponse(
        job_id=job_id,
        status=job.get("status", "unknown"),
        db_size=job.get("db_size"),
        note_count=job.get("note_count"),
        error=job.get("error"),
    )


@app.get("/v1/vault/download", response_model=DownloadResponse)
async def download_db(
    user: dict = Depends(require_api_key),
):
    """Generate a presigned URL scoped to the authenticated user's database."""
    user_id = user["user_id"]
    url = app.state.storage.generate_download_url(user_id)
    return DownloadResponse(
        download_url=url,
        expires_in=3600,
    )


@app.post("/v1/vault/query")
async def query_vault(
    user: dict = Depends(require_api_key),
):
    """Query the cloud-indexed vault. Not yet implemented."""
    raise HTTPException(status_code=501, detail="Query API not yet implemented")
