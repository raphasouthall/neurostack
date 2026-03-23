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

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from pydantic import BaseModel

from .auth import require_api_key, require_auth
from .billing import (
    create_checkout_session,
    create_portal_session,
    handle_webhook_event,
    verify_webhook_signature,
)
from .config import load_cloud_config
from .indexer import CloudIndexer
from .job_store import JobStore
from .metering import TIER_LIMITS, UsageMeter
from .query import CloudQueryEngine
from .storage import GCSStorageClient
from .tier_store import TierStore

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
    status: str  # "queued" | "indexing" | "search_ready" | "complete" | "failed"
    progress: float | None = None
    download_url: str | None = None
    error: str | None = None
    db_size: int | None = None
    note_count: int | None = None


class DownloadResponse(BaseModel):
    download_url: str
    expires_in: int


class UsageResponse(BaseModel):
    queries: int
    index_jobs: int
    notes_indexed: int
    period: str
    tier: str
    limits: dict


class CheckoutRequest(BaseModel):
    price_id: str
    success_url: str = "https://neurostack.sh/billing/success"
    cancel_url: str = "https://neurostack.sh/billing/cancel"


class CheckoutResponse(BaseModel):
    checkout_url: str


class PortalRequest(BaseModel):
    customer_id: str
    return_url: str = "https://neurostack.sh/billing"


class PortalResponse(BaseModel):
    portal_url: str


class QueryRequest(BaseModel):
    query: str
    top_k: int = 10
    mode: str = "hybrid"
    depth: str = "auto"
    workspace: str | None = None


class QueryResponse(BaseModel):
    triples: list = []
    summaries: list = []
    chunks: list = []
    depth_used: str = ""


class TriplesRequest(BaseModel):
    query: str
    top_k: int = 10
    workspace: str | None = None


class SummaryRequest(BaseModel):
    note_path: str


class WebhookResponse(BaseModel):
    received: bool
    action: str


# ---------------------------------------------------------------------------
# App lifecycle
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize cloud infrastructure on startup."""
    config = load_cloud_config()
    storage = GCSStorageClient(config)
    indexer = CloudIndexer(config, storage)

    meter = UsageMeter()  # Uses default Firestore client

    # Persistent stores -- backed by the same GCS bucket used for vaults.
    # Both survive Cloud Run scale-to-zero events.
    job_store = JobStore(bucket=storage._bucket)
    tier_store = TierStore(bucket=storage._bucket)

    query_engine = CloudQueryEngine(storage)

    app.state.config = config
    app.state.storage = storage
    app.state.indexer = indexer
    app.state.meter = meter
    app.state.job_store = job_store
    app.state.tier_store = tier_store
    app.state.query_engine = query_engine

    yield


app = FastAPI(title="NeuroStack Cloud", version="0.8.0", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Background indexing
# ---------------------------------------------------------------------------


def _run_indexing(
    app_state, job_id: str, user_id: str, vault_files: dict[str, bytes]
) -> None:
    """Run GCS upload + indexing in a background thread.

    Stores raw vault files in GCS first, then triggers indexing.
    Updates the persistent job store with progress and results.
    """
    try:
        app_state.job_store.update(job_id, {"status": "indexing"})

        result = app_state.indexer.index_vault(user_id, vault_files)
        app_state.job_store.update(job_id, result)

        # Invalidate cached DB so next query fetches the updated version
        app_state.query_engine.invalidate_cache(user_id)
    except Exception as exc:
        log.exception("Background indexing failed for job %s", job_id)
        app_state.job_store.update(job_id, {"status": "failed", "error": str(exc)})


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
    user: dict = Depends(require_auth),
):
    """Accept vault files for cloud indexing.

    Enforces per-tenant limits on file count, individual file size, and
    total upload size. Filenames are sanitised to prevent path traversal.
    """
    user_id = user["user_id"]
    tier = user.get("tier", "free")

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

    # Enforce tier note limit before processing
    allowed, reason = await app.state.meter.check_note_limit(user_id, tier, len(vault_files))
    if not allowed:
        raise HTTPException(status_code=429, detail=reason)

    # Record metering
    await app.state.meter.record_index_job(user_id, len(vault_files))

    # Create job scoped to this user and start background thread.
    # GCS upload + indexing both happen in the background to avoid
    # blocking the 202 response (446 files = slow sequential uploads).
    job_id = str(uuid.uuid4())
    app.state.job_store.create(job_id, {
        "status": "queued",
        "user_id": user_id,
        "note_count": len(vault_files),
    })

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
    user: dict = Depends(require_auth),
):
    """Check indexing job status. Only the owning user can see their jobs."""
    job = app.state.job_store.get(job_id)

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
    user: dict = Depends(require_auth),
):
    """Generate a presigned URL scoped to the authenticated user's database."""
    user_id = user["user_id"]
    url = app.state.storage.generate_download_url(user_id)
    return DownloadResponse(
        download_url=url,
        expires_in=3600,
    )


@app.post("/v1/vault/query", response_model=QueryResponse)
async def query_vault(
    req: QueryRequest,
    user: dict = Depends(require_auth),
):
    """Query the cloud-indexed vault using tiered search.

    Runs NeuroStack's tiered search against the user's pre-indexed DB.
    Returns triples, summaries, and/or full chunks depending on depth.
    """
    user_id = user["user_id"]
    tier = user.get("tier", "free")

    # Enforce query limit
    allowed, reason = await app.state.meter.check_query_limit(user_id, tier)
    if not allowed:
        raise HTTPException(status_code=429, detail=reason)

    await app.state.meter.record_query(user_id)

    try:
        result = app.state.query_engine.search(
            user_id,
            req.query,
            top_k=req.top_k,
            mode=req.mode,
            depth=req.depth,
            workspace=req.workspace,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return QueryResponse(**result)


@app.post("/v1/vault/triples")
async def query_triples(
    req: TriplesRequest,
    user: dict = Depends(require_auth),
):
    """Search knowledge graph triples (SPO facts) in the user's cloud DB."""
    user_id = user["user_id"]
    tier = user.get("tier", "free")

    allowed, reason = await app.state.meter.check_query_limit(user_id, tier)
    if not allowed:
        raise HTTPException(status_code=429, detail=reason)

    await app.state.meter.record_query(user_id)

    try:
        results = app.state.query_engine.search_triples(
            user_id, req.query, top_k=req.top_k, workspace=req.workspace,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return {"triples": results}


@app.post("/v1/vault/summary")
async def get_note_summary(
    req: SummaryRequest,
    user: dict = Depends(require_auth),
):
    """Get the pre-computed summary for a specific note."""
    user_id = user["user_id"]

    try:
        result = app.state.query_engine.get_summary(user_id, req.note_path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    if result is None:
        raise HTTPException(status_code=404, detail="Note not found")

    return result


@app.get("/v1/usage", response_model=UsageResponse)
async def get_usage(
    user: dict = Depends(require_auth),
):
    """Return current usage stats and tier limits for the authenticated user."""
    user_id = user["user_id"]
    tier = user.get("tier", "free")
    usage = await app.state.meter.get_usage(user_id)
    limits = TIER_LIMITS.get(tier, TIER_LIMITS["free"])

    return UsageResponse(
        queries=usage["queries"],
        index_jobs=usage["index_jobs"],
        notes_indexed=usage["notes_indexed"],
        period=usage["period"],
        tier=tier,
        limits={
            "queries_per_month": limits.queries_per_month,
            "notes_max": limits.notes_max,
            "index_jobs_per_month": limits.index_jobs_per_month,
        },
    )


# ---------------------------------------------------------------------------
# Billing endpoints
# ---------------------------------------------------------------------------


def _make_update_user_tier(tier_store: TierStore):
    """Create a tier update callback that persists to GCS.

    Returns a closure that ``handle_webhook_event`` can call with
    ``(user_id, new_tier)``. The tier is written to the persistent
    ``TierStore`` so it survives Cloud Run scale-down.
    """

    def _update(user_id: str, new_tier: str) -> None:
        tier_store.set(user_id, new_tier)
        log.info("Persisted user %s tier to %s", user_id, new_tier)

    return _update


@app.post("/v1/billing/checkout", response_model=CheckoutResponse)
async def billing_checkout(
    req: CheckoutRequest,
    user: dict = Depends(require_auth),
):
    """Create a Stripe Checkout session for subscription purchase."""
    url = create_checkout_session(
        user["user_id"], req.price_id, req.success_url, req.cancel_url
    )
    return CheckoutResponse(checkout_url=url)


@app.post("/v1/billing/portal", response_model=PortalResponse)
async def billing_portal(
    req: PortalRequest,
    user: dict = Depends(require_auth),
):
    """Create a Stripe Customer Portal session for billing management."""
    url = create_portal_session(req.customer_id, req.return_url)
    return PortalResponse(portal_url=url)


@app.post("/v1/billing/webhook", response_model=WebhookResponse)
async def billing_webhook(request: Request):
    """Handle Stripe webhook events. NOT authenticated -- Stripe sends these.

    Validates the event signature using the STRIPE_WEBHOOK_SECRET, then
    processes subscription lifecycle events to provision/deprovision tiers.
    """
    payload = await request.body()
    sig = request.headers.get("Stripe-Signature", "")

    try:
        event = verify_webhook_signature(payload, sig)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    update_fn = _make_update_user_tier(request.app.state.tier_store)
    result = handle_webhook_event(event, update_fn)
    return WebhookResponse(received=True, action=result.get("action", "none"))
