# NeuroStack Cloud API Contract v2 -- Sync & Data Transfer

Covers all REST API changes needed to implement findings from:
- `neurostack-vault-sync-architecture-research.md` (sync triggers, memory merge, removed files bug)
- `neurostack-data-transfer-architecture-research.md` (tar.gz uploads, ETag caching, compression, push lock, db-version)

## Table of Contents

1. [Modified: POST /v1/vault/upload](#1-modified-post-v1vaultupload)
2. [New: POST /v1/vault/sync](#2-new-post-v1vaultsync)
3. [Modified: POST /v1/vault/query](#3-modified-post-v1vaultquery)
4. [New: GET /v1/vault/db-version](#4-new-get-v1vaultdb-version)
5. [New: POST /v1/vault/push-lock](#5-new-post-v1vaultpush-lock)
6. [Modified: GET /v1/vault/download](#6-modified-get-v1vaultdownload)
7. [New: GET /v1/vault/memories/since](#7-new-get-v1vaultmemoriessince)
8. [New: POST /v1/vault/upload/artifacts](#8-new-post-v1vaultuploadartifacts)
9. [New: DELETE /v1/vault/files](#9-new-delete-v1vaultfiles)
10. [CloudClient Method Signatures](#10-cloudclient-method-signatures)
11. [Breaking Changes Summary](#11-breaking-changes-summary)
12. [Migration Guide](#12-migration-guide)

---

## Common Conventions

**Authentication:** All endpoints require `Authorization: Bearer <api_key>` unless noted.

**Error envelope:**
```json
{
  "detail": "Human-readable error message"
}
```

**Rate limiting headers** (returned on all authenticated responses):
```
X-RateLimit-Limit: 1000
X-RateLimit-Remaining: 994
X-RateLimit-Reset: 1711497600
```

**Tenant isolation:** All data is scoped to the authenticated `user_id`. No endpoint can access another user's data.

---

## 1. Modified: POST /v1/vault/upload

**Research finding:** Switch from multipart to tar.gz (breaks 32MB multipart limit), transmit removed files list (fixes ghost entry bug), support pre-computed artifacts to eliminate Gemini dependency.

### Current Behavior
- Accepts `multipart/form-data` with individual `.md` files
- No removed files support
- No compression
- 32MB practical limit from Cloud Run body default

### New Behavior
- Accepts `application/gzip` body (tar.gz archive) OR legacy `multipart/form-data`
- Includes removed files list and optional pre-computed artifacts via JSON metadata inside the archive
- Supports vaults up to 500MB compressed

### Request

**Option A: tar.gz upload (new, preferred)**

```
POST /v1/vault/upload
Content-Type: application/gzip
Content-Length: <bytes>
Authorization: Bearer <api_key>
X-Upload-Format: tar.gz

<binary tar.gz body>
```

The tar.gz archive MUST contain a `_manifest.json` at the root with this schema:

```json
{
  "format_version": 1,
  "removed": ["old-note.md", "archive/deleted.md"],
  "file_hashes": {
    "notes/new-note.md": "sha256:abc123...",
    "notes/changed-note.md": "sha256:def456..."
  }
}
```

All other entries in the archive are the actual `.md` file contents, at paths matching `file_hashes` keys.

**Option B: multipart upload (legacy, still supported)**

```
POST /v1/vault/upload
Content-Type: multipart/form-data
Authorization: Bearer <api_key>

files[]: (binary .md files)
removed: ["old-note.md"]  (form field, JSON-encoded string list)
```

The `removed` field is a new optional form field. Omitting it preserves backward compatibility.

### Response (unchanged)

```
HTTP 202 Accepted
```

```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "queued",
  "message": "Received 12 files for indexing, 3 files marked for removal"
}
```

### Error Responses

| Status | Detail | Condition |
|--------|--------|-----------|
| 400 | `"Invalid tar.gz archive"` | Archive is corrupt or missing `_manifest.json` |
| 400 | `"Too many files: N exceeds limit of 5000"` | File count exceeded |
| 400 | `"Total upload size exceeds 500MB"` | Size limit exceeded |
| 400 | `"Only .md files accepted, got: X"` | Non-markdown file in archive |
| 400 | `"Absolute path not allowed: X"` | Path traversal attempt |
| 401 | `"Invalid or expired API key"` | Auth failure |
| 409 | `"Push already in progress. Lock held until <ISO timestamp>"` | Concurrent push (see push-lock) |
| 429 | `"Note limit exceeded for tier: free"` | Tier quota hit |

### Rate Limiting
- Free: 2 uploads/hour, 200 notes max
- Pro: 20 uploads/hour, 5000 notes max

### Breaking Changes
- **None.** Multipart path is preserved. `X-Upload-Format: tar.gz` triggers new path. Clients without the header get legacy behavior.

---

## 2. New: POST /v1/vault/sync

**Research finding:** Orchestrate push + memory pull in one call. `neurostack cloud sync` CLI command needs a single round-trip that uploads changes AND fetches new memories created since last sync.

### Request

```
POST /v1/vault/sync
Content-Type: application/gzip
Authorization: Bearer <api_key>
X-Upload-Format: tar.gz

<binary tar.gz body -- same format as /v1/vault/upload>
```

Query parameters:
- `memories_since` (optional, ISO 8601 timestamp): fetch memories created after this time. If omitted, no memories are returned.
- `wait` (optional, boolean, default `false`): if `true`, block until indexing completes (up to 300s). If `false`, return immediately with `job_id`.

```
POST /v1/vault/sync?memories_since=2026-03-25T10:00:00Z&wait=true
```

If there are no file changes to upload but the client wants memories only, send an empty tar.gz (just `_manifest.json` with empty `file_hashes` and empty `removed`).

### Response

**When `wait=false` (default):**

```
HTTP 202 Accepted
```

```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "queued",
  "message": "Received 5 files for indexing, 1 removed",
  "memories": [
    {
      "uuid": "mem-abc-123",
      "content": "Rapha prefers kebab-case filenames",
      "entity_type": "convention",
      "tags": ["formatting"],
      "created_at": "2026-03-25T14:30:00Z",
      "updated_at": "2026-03-25T14:30:00Z",
      "source_agent": "claude-code"
    }
  ],
  "memories_count": 1,
  "db_version": "gen-1711497600-abc123"
}
```

**When `wait=true` and indexing completes:**

```
HTTP 200 OK
```

```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "complete",
  "message": "Indexed 5 files, removed 1",
  "db_version": "gen-1711497600-def456",
  "db_size": 15728640,
  "note_count": 458,
  "memories": [],
  "memories_count": 0
}
```

**When `wait=true` and indexing times out:**

```
HTTP 202 Accepted
```

```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "indexing",
  "message": "Indexing still in progress after 300s",
  "memories": [],
  "memories_count": 0,
  "db_version": null
}
```

### Error Responses

| Status | Detail | Condition |
|--------|--------|-----------|
| 400 | `"Invalid tar.gz archive"` | Bad archive |
| 400 | `"Invalid memories_since timestamp"` | Unparseable ISO 8601 |
| 409 | `"Push already in progress"` | Concurrent push conflict |
| 429 | `"Rate limit exceeded"` | Tier limit hit |

### Rate Limiting
- Same as `/v1/vault/upload` (counts as one upload)

---

## 3. Modified: POST /v1/vault/query

**Research finding:** Query-time memory union. Cloud search currently only queries SQLite. Memories live in Firestore but are invisible to search. Fix: merge Firestore memories into search results at query time.

### Request (unchanged schema, new optional field)

```json
{
  "query": "neurostack architecture decisions",
  "top_k": 10,
  "mode": "hybrid",
  "depth": "auto",
  "workspace": null,
  "include_memories": true
}
```

New field:
- `include_memories` (boolean, default `true`): When true, the server queries Firestore memories in parallel with the SQLite search and merges results. When false, behaves identically to current behavior (SQLite only).

### Response (extended)

```json
{
  "triples": [...],
  "summaries": [...],
  "chunks": [...],
  "depth_used": "summaries",
  "memories": [
    {
      "uuid": "mem-abc-123",
      "content": "NeuroStack uses neuroscience-grounded retrieval",
      "entity_type": "observation",
      "tags": ["neurostack", "architecture"],
      "relevance_score": 0.85,
      "created_at": "2026-03-20T10:00:00Z"
    }
  ],
  "db_version": "gen-1711497600-abc123"
}
```

New fields:
- `memories` (list): Firestore memories matching the query, ranked by relevance. Empty list when `include_memories=false`.
- `db_version` (string): Current database version for cache coherence.

### Error Responses

No new error codes. Firestore memory query failure is non-fatal -- the response returns with `memories: []` and logs the error server-side.

### Breaking Changes
- **Additive only.** New fields (`memories`, `db_version`) are added to the response. Existing clients that don't read these fields are unaffected.
- `include_memories` defaults to `true`, which means existing clients will see slightly higher latency (~100ms) from the parallel Firestore query. Set to `false` to opt out.

---

## 4. New: GET /v1/vault/db-version

**Research finding:** Firestore version check for cross-instance cache coherence. When a push completes on one Cloud Run instance, other instances (and other devices) need to know the DB changed so they don't serve stale cached copies.

### Request

```
GET /v1/vault/db-version
Authorization: Bearer <api_key>
```

No request body.

### Response

```
HTTP 200 OK
```

```json
{
  "db_version": "gen-1711497600-abc123",
  "updated_at": "2026-03-26T14:30:00Z",
  "db_size": 15728640,
  "note_count": 458
}
```

Fields:
- `db_version` (string): Opaque version identifier. Format: `gen-<unix_timestamp>-<short_hash>`. Changes on every successful push/index.
- `updated_at` (string, ISO 8601): When the DB was last updated.
- `db_size` (int): DB file size in bytes.
- `note_count` (int): Number of indexed notes.

**When no DB exists yet:**

```
HTTP 404 Not Found
```

```json
{
  "detail": "No database found for this user"
}
```

### Error Responses

| Status | Detail | Condition |
|--------|--------|-----------|
| 401 | `"Invalid or expired API key"` | Auth failure |
| 404 | `"No database found for this user"` | User has never pushed |

### Rate Limiting
- No rate limit (Firestore read: ~$0.06/100K requests). Clients may poll this every 30-60s for staleness detection.

### Implementation Notes
- Server writes `db_version` to Firestore doc `users/{user_id}/vault_meta/db_version` after every successful index job.
- Cloud Run instances check this before serving a cached SQLite DB. If the cached version mismatches, re-download from GCS.

---

## 5. New: POST /v1/vault/push-lock

**Research finding:** Server-side push lock prevents concurrent push conflicts from multiple devices. Uses Firestore for distributed locking.

### Acquire Lock

```
POST /v1/vault/push-lock
Authorization: Bearer <api_key>
Content-Type: application/json
```

```json
{
  "action": "acquire",
  "ttl_seconds": 300,
  "device_id": "laptop-home"
}
```

Fields:
- `action` (string, required): `"acquire"` or `"release"`
- `ttl_seconds` (int, default 300): Lock auto-expires after this duration (max 600)
- `device_id` (string, optional): Identifier for the device acquiring the lock. For diagnostics and stale lock identification.

### Acquire Response

**Success:**

```
HTTP 200 OK
```

```json
{
  "locked": true,
  "lock_id": "lock-abc-123",
  "expires_at": "2026-03-26T14:35:00Z",
  "device_id": "laptop-home"
}
```

**Already locked by another device:**

```
HTTP 409 Conflict
```

```json
{
  "locked": false,
  "held_by": "desktop-office",
  "expires_at": "2026-03-26T14:32:00Z",
  "detail": "Push lock held by another device until 2026-03-26T14:32:00Z"
}
```

### Release Lock

```
POST /v1/vault/push-lock
Authorization: Bearer <api_key>
Content-Type: application/json
```

```json
{
  "action": "release",
  "lock_id": "lock-abc-123"
}
```

### Release Response

```
HTTP 200 OK
```

```json
{
  "released": true
}
```

**Lock not found or not owned:**

```
HTTP 404 Not Found
```

```json
{
  "detail": "Lock not found or not owned by this user"
}
```

### Error Responses

| Status | Detail | Condition |
|--------|--------|-----------|
| 400 | `"Invalid action, must be acquire or release"` | Bad action value |
| 400 | `"ttl_seconds must be between 1 and 600"` | TTL out of range |
| 401 | `"Invalid or expired API key"` | Auth failure |
| 404 | `"Lock not found or not owned by this user"` | Release of non-existent lock |
| 409 | `"Push lock held by another device"` | Lock contention |

### Rate Limiting
- 10 requests/minute per user

### Implementation Notes
- Firestore document: `users/{user_id}/locks/push`
- Uses Firestore transactions for atomic acquire (check-and-set)
- Expired locks are treated as unlocked (server checks `expires_at` on acquire)
- `/v1/vault/upload` and `/v1/vault/sync` should auto-acquire the lock if not already held, and release on completion

---

## 6. Modified: GET /v1/vault/download

**Research finding:** ETag caching to skip redundant downloads (90%+ requests skip download). Gzip compression for 46% bandwidth reduction. Expose `db_version` for cache coherence.

### Request

```
GET /v1/vault/download
Authorization: Bearer <api_key>
If-None-Match: "gen-1711497600-abc123"
Accept-Encoding: gzip
```

New request headers:
- `If-None-Match` (optional): The `db_version` value from a previous download or from `GET /v1/vault/db-version`. If the current DB matches this version, the server returns 304.
- `Accept-Encoding: gzip` (optional): If present, the presigned URL will point to a gzip-compressed copy of the DB.

### Response -- DB has changed (or no ETag provided)

```
HTTP 200 OK
```

```json
{
  "download_url": "https://storage.googleapis.com/...",
  "expires_in": 3600,
  "db_version": "gen-1711497600-def456",
  "db_size": 15728640,
  "db_size_compressed": 8503296,
  "compressed": true,
  "note_count": 458
}
```

New fields:
- `db_version` (string): Current version, to be stored by the client for future `If-None-Match`.
- `db_size` (int): Uncompressed DB size in bytes.
- `db_size_compressed` (int | null): Compressed size if `compressed=true`, null otherwise.
- `compressed` (bool): Whether the download URL points to a gzip file.
- `note_count` (int): Number of indexed notes.

### Response -- DB unchanged (ETag match)

```
HTTP 304 Not Modified
```

```json
{
  "db_version": "gen-1711497600-abc123",
  "message": "Database unchanged since last download"
}
```

No `download_url` is generated (saves GCS signed URL computation).

### Error Responses

| Status | Detail | Condition |
|--------|--------|-----------|
| 401 | `"Invalid or expired API key"` | Auth failure |
| 404 | `"No database found for this user"` | User has never pushed |

### Rate Limiting
- No rate limit on the metadata check (304 path). The actual download goes directly to GCS.

### Breaking Changes
- **Additive.** New fields in the 200 response body. The `download_url` and `expires_in` fields are unchanged.
- Clients not sending `If-None-Match` or `Accept-Encoding: gzip` get identical behavior to today.

---

## 7. New: GET /v1/vault/memories/since

**Research finding:** Fetch memories created after a timestamp, enabling local clients to pull new memories from Firestore and merge them into the local SQLite DB without a full re-index.

### Request

```
GET /v1/vault/memories/since?after=2026-03-25T10:00:00Z&limit=100
Authorization: Bearer <api_key>
```

Query parameters:
- `after` (required, ISO 8601): Return memories created or updated after this timestamp.
- `limit` (optional, int, default 100, max 500): Maximum number of memories to return.
- `include_deleted` (optional, bool, default false): If true, include memories deleted after `after` (for local cache invalidation). Deleted memories have `"deleted": true`.

### Response

```
HTTP 200 OK
```

```json
{
  "memories": [
    {
      "uuid": "mem-abc-123",
      "content": "NeuroStack uses debounced file watching",
      "entity_type": "observation",
      "tags": ["neurostack", "sync"],
      "created_at": "2026-03-25T14:30:00Z",
      "updated_at": "2026-03-25T14:30:00Z",
      "source_agent": "claude-code",
      "session_id": 42,
      "workspace": null,
      "ttl_hours": null,
      "deleted": false
    }
  ],
  "count": 1,
  "has_more": false,
  "server_time": "2026-03-26T15:00:00Z"
}
```

Fields:
- `memories` (list): Memories matching the time filter, ordered by `updated_at` ascending.
- `count` (int): Number of memories in this response.
- `has_more` (bool): If true, there are more memories after the last one in this response. Client should paginate using the last memory's `updated_at` as the new `after`.
- `server_time` (string, ISO 8601): Server's current time. Client should store this as the `after` value for the next sync.

### Error Responses

| Status | Detail | Condition |
|--------|--------|-----------|
| 400 | `"Missing required parameter: after"` | No timestamp provided |
| 400 | `"Invalid timestamp format"` | Unparseable ISO 8601 |
| 401 | `"Invalid or expired API key"` | Auth failure |

### Rate Limiting
- 30 requests/minute per user

---

## 8. New: POST /v1/vault/upload/artifacts

**Research finding:** Client-side indexing with Ollama eliminates Gemini API costs (97-99% of total cost). Clients push pre-computed embeddings, summaries, and triples alongside vault files.

### Request

```
POST /v1/vault/upload/artifacts
Content-Type: application/gzip
Authorization: Bearer <api_key>
X-Upload-Format: tar.gz
```

The tar.gz archive contains a `_artifacts.json` manifest and the artifact data files:

```json
{
  "format_version": 1,
  "embed_model": "nomic-embed-text",
  "embed_dimensions": 768,
  "llm_model": "phi3.5",
  "artifacts": {
    "notes/my-note.md": {
      "sha256": "abc123...",
      "summary": "This note discusses the architecture of...",
      "triples": [
        {"subject": "NeuroStack", "predicate": "uses", "object": "SQLite"}
      ],
      "chunks": [
        {
          "text": "NeuroStack is a neuroscience-grounded...",
          "embedding": [0.123, -0.456, ...],
          "start_line": 1,
          "end_line": 15
        }
      ]
    }
  }
}
```

Fields in `_artifacts.json`:
- `format_version` (int): Schema version. Currently `1`.
- `embed_model` (string): Name of the embedding model used (for compatibility validation).
- `embed_dimensions` (int): Embedding vector dimensions.
- `llm_model` (string): Name of the LLM used for summaries/triples.
- `artifacts` (dict): Keyed by note relative path. Each entry contains:
  - `sha256` (string): Content hash of the source `.md` file. Server uses this to verify the artifact matches the uploaded file.
  - `summary` (string): AI-generated note summary.
  - `triples` (list): SPO triples extracted from the note.
  - `chunks` (list): Text chunks with embeddings. Each chunk has `text`, `embedding` (float array), `start_line`, `end_line`.

### Response

```
HTTP 202 Accepted
```

```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "queued",
  "message": "Received artifacts for 12 notes",
  "skipped_reindex": 12,
  "gemini_calls_saved": 12
}
```

Fields:
- `skipped_reindex` (int): Number of notes that will skip Gemini re-indexing because valid artifacts were provided.
- `gemini_calls_saved` (int): Number of Gemini API calls saved.

### Error Responses

| Status | Detail | Condition |
|--------|--------|-----------|
| 400 | `"Invalid artifact archive"` | Missing `_artifacts.json` or corrupt archive |
| 400 | `"Embedding dimension mismatch: expected 768, got 384"` | Incompatible embedding model |
| 400 | `"SHA256 mismatch for notes/my-note.md"` | Artifact does not match uploaded file content |
| 401 | `"Invalid or expired API key"` | Auth failure |
| 413 | `"Artifact archive too large (max 200MB)"` | Size limit exceeded |
| 429 | `"Rate limit exceeded"` | Tier quota hit |

### Rate Limiting
- Same as `/v1/vault/upload` (counts as one upload)

### Usage Notes
- This endpoint is typically called AFTER `/v1/vault/upload` (or combined via `/v1/vault/sync`). The server matches artifacts to already-uploaded files by `sha256` hash.
- Alternatively, the tar.gz sent to `/v1/vault/upload` can include an `_artifacts.json` alongside `_manifest.json`. The server will detect and process both in a single upload. This is the preferred approach for the combined flow.
- Notes without matching artifacts fall back to server-side Gemini indexing.

---

## 9. New: DELETE /v1/vault/files

**Research finding:** While `/v1/vault/upload` now accepts a `removed` list, a standalone delete endpoint is useful for git hook integrations where a commit only deletes files (no additions/changes).

### Request

```
DELETE /v1/vault/files
Content-Type: application/json
Authorization: Bearer <api_key>
```

```json
{
  "files": ["old-note.md", "archive/deleted.md"]
}
```

Fields:
- `files` (list[string], required): Relative paths to remove from the cloud index. Max 500.

### Response

```
HTTP 200 OK
```

```json
{
  "removed": 2,
  "db_version": "gen-1711497600-abc123"
}
```

### Error Responses

| Status | Detail | Condition |
|--------|--------|-----------|
| 400 | `"files list is required and must be non-empty"` | Missing or empty list |
| 400 | `"Too many files: N exceeds limit of 500"` | List too long |
| 400 | `"Path traversal not allowed: .."` | Path traversal attempt |
| 401 | `"Invalid or expired API key"` | Auth failure |
| 404 | `"No database found for this user"` | No index exists |

### Rate Limiting
- 10 requests/minute per user

---

## 10. CloudClient Method Signatures

All methods below are additions or modifications to `neurostack/cloud/client.py::CloudClient`.

### New/Modified Methods

```python
class CloudClient:

    # --- Modified ---

    def upload_vault(
        self,
        files: dict[str, bytes],
        *,
        removed: list[str] | None = None,
        artifacts: dict[str, dict] | None = None,
        use_tar: bool = True,
        timeout: float = 300.0,
    ) -> dict:
        """Upload vault files to the cloud.

        Args:
            files: Mapping of relative_path -> file content bytes.
            removed: List of relative paths to remove from cloud index.
            artifacts: Pre-computed artifacts keyed by note path.
                       Each value has keys: sha256, summary, triples, chunks.
            use_tar: If True (default), pack into tar.gz. If False, use legacy
                     multipart upload for backward compatibility.
            timeout: Request timeout in seconds.

        Returns:
            {"job_id": "...", "status": "queued", "message": "..."}
        """

    # --- New ---

    def sync(
        self,
        files: dict[str, bytes],
        *,
        removed: list[str] | None = None,
        artifacts: dict[str, dict] | None = None,
        memories_since: str | None = None,
        wait: bool = False,
        timeout: float = 300.0,
    ) -> dict:
        """Upload changes and fetch new memories in one call.

        Args:
            files: Mapping of relative_path -> file content bytes.
            removed: List of relative paths removed from vault.
            artifacts: Pre-computed indexing artifacts (summaries, triples,
                       embeddings) keyed by note path.
            memories_since: ISO 8601 timestamp. Fetch memories created after
                           this time. None = don't fetch memories.
            wait: If True, block until indexing completes (up to 300s).
            timeout: Request timeout in seconds.

        Returns:
            {
                "job_id": "...",
                "status": "queued" | "complete" | "indexing",
                "memories": [...],
                "memories_count": N,
                "db_version": "..."
            }
        """

    def get_db_version(self) -> dict:
        """Check the current database version for cache coherence.

        Returns:
            {
                "db_version": "gen-...",
                "updated_at": "2026-...",
                "db_size": 15728640,
                "note_count": 458
            }

        Raises:
            FileNotFoundError: User has never pushed a vault.
        """

    def acquire_push_lock(
        self,
        *,
        ttl_seconds: int = 300,
        device_id: str | None = None,
    ) -> dict:
        """Acquire a per-user push lock.

        Args:
            ttl_seconds: Lock auto-expires after this many seconds (max 600).
            device_id: Identifier for the pushing device.

        Returns:
            {"locked": True, "lock_id": "...", "expires_at": "..."}

        Raises:
            httpx.HTTPStatusError: 409 if lock is held by another device.
        """

    def release_push_lock(self, lock_id: str) -> dict:
        """Release a previously acquired push lock.

        Args:
            lock_id: The lock_id returned by acquire_push_lock.

        Returns:
            {"released": True}
        """

    def download_db(
        self,
        *,
        db_version: str | None = None,
        accept_gzip: bool = True,
    ) -> dict:
        """Get download URL with ETag caching and gzip support.

        Args:
            db_version: If provided, sent as If-None-Match. Returns
                       {"not_modified": True} if DB hasn't changed.
            accept_gzip: If True, request gzip-compressed DB.

        Returns:
            {
                "download_url": "https://...",
                "db_version": "gen-...",
                "compressed": True,
                "db_size": 15728640
            }
            OR {"not_modified": True, "db_version": "gen-..."} on 304.
        """

    def get_memories_since(
        self,
        after: str,
        *,
        limit: int = 100,
        include_deleted: bool = False,
    ) -> dict:
        """Fetch memories created after a timestamp.

        Args:
            after: ISO 8601 timestamp.
            limit: Max memories to return (1-500).
            include_deleted: Include deleted memories for cache invalidation.

        Returns:
            {
                "memories": [...],
                "count": N,
                "has_more": False,
                "server_time": "2026-..."
            }
        """

    def upload_artifacts(
        self,
        artifacts: dict[str, dict],
        *,
        embed_model: str = "nomic-embed-text",
        embed_dimensions: int = 768,
        llm_model: str = "phi3.5",
        timeout: float = 300.0,
    ) -> dict:
        """Upload pre-computed indexing artifacts.

        Args:
            artifacts: Mapping of note_path -> {sha256, summary, triples, chunks}.
            embed_model: Name of embedding model used.
            embed_dimensions: Embedding vector dimensionality.
            llm_model: Name of LLM used for summaries/triples.
            timeout: Request timeout in seconds.

        Returns:
            {"job_id": "...", "skipped_reindex": N, "gemini_calls_saved": N}
        """

    def delete_files(self, files: list[str]) -> dict:
        """Remove files from the cloud index.

        Args:
            files: List of relative paths to remove.

        Returns:
            {"removed": N, "db_version": "gen-..."}
        """
```

### Modified VaultSyncEngine Methods

```python
class VaultSyncEngine:

    def push(
        self,
        *,
        progress_callback: Callable[[str], None] | None = None,
        include_artifacts: bool = False,
    ) -> dict:
        """Upload changed vault files and wait for indexing.

        Changes from current:
        - Transmits diff.removed to the server via _manifest.json
        - Uses tar.gz format instead of multipart
        - Optionally includes pre-computed artifacts

        Args:
            progress_callback: Called with status messages.
            include_artifacts: If True, include local pre-computed
                             embeddings/summaries/triples in the upload.

        Returns:
            {"status": "complete", "job_id": "...", ...}
        """

    def pull(
        self,
        *,
        db_path: Path | None = None,
        cached_version: str | None = None,
    ) -> Path | None:
        """Download indexed DB from cloud with ETag caching.

        Changes from current:
        - Sends If-None-Match with cached_version
        - Accepts gzip-compressed downloads
        - Returns None if DB is unchanged (304)

        Args:
            db_path: Target path for the DB file.
            cached_version: db_version from previous download.
                           If DB hasn't changed, returns None.

        Returns:
            Path to downloaded DB, or None if unchanged.
        """

    def sync(
        self,
        *,
        progress_callback: Callable[[str], None] | None = None,
        memories_since: str | None = None,
        include_artifacts: bool = False,
        wait: bool = True,
    ) -> dict:
        """Push changes and pull memories in one operation.

        New method that orchestrates the full sync lifecycle:
        1. Scan vault and compute diff
        2. Acquire push lock
        3. Upload changes via POST /v1/vault/sync
        4. Optionally wait for indexing
        5. Release push lock
        6. Save manifest on success
        7. Return job result + memories

        Args:
            progress_callback: Called with status messages.
            memories_since: Fetch memories created after this timestamp.
            include_artifacts: Include pre-computed artifacts.
            wait: Block until indexing completes.

        Returns:
            {
                "status": "complete" | "queued",
                "job_id": "...",
                "memories": [...],
                "db_version": "..."
            }
        """
```

---

## 11. Breaking Changes Summary

| Endpoint | Change | Breaking? | Migration |
|----------|--------|-----------|-----------|
| `POST /v1/vault/upload` | New tar.gz format, `removed` field | **No** | Multipart still works. New format activated by `X-Upload-Format: tar.gz` header. |
| `POST /v1/vault/query` | New `memories` and `db_version` fields in response | **No** | Additive. Existing clients ignore new fields. |
| `POST /v1/vault/query` | New `include_memories` request field | **No** | Defaults to `true`. Set to `false` to preserve old behavior and latency. |
| `GET /v1/vault/download` | New response fields, 304 support | **No** | Additive. Clients not sending `If-None-Match` get full behavior. |
| All new endpoints | New endpoints | **No** | Existing clients never call them. |

**Zero breaking changes.** All modifications are additive or opt-in via new headers/fields.

---

## 12. Migration Guide

### Client Upgrade Path

**Phase 1 -- Immediate (no server changes needed for existing clients):**
1. Server deploys new endpoints. Old clients continue working.
2. New client versions start using `removed` field in uploads.

**Phase 2 -- Opt-in improvements:**
1. Clients switch to tar.gz uploads for large vaults (>32MB uncompressed).
2. Clients start sending `If-None-Match` on downloads.
3. Clients call `GET /v1/vault/db-version` for staleness checks.

**Phase 3 -- Full sync:**
1. Clients switch from `push()` + `pull()` to `sync()`.
2. Clients implement local memory merge from `memories_since`.
3. Clients generate artifacts locally and skip Gemini costs.

### Version Negotiation

The client should check the server version before using new features:

```python
health = client.health()
server_version = health.get("version", "0.8.0")

# tar.gz upload requires server >= 0.9.0
if parse_version(server_version) >= parse_version("0.9.0"):
    client.upload_vault(files, removed=removed, use_tar=True)
else:
    client.upload_vault(files, use_tar=False)  # legacy multipart
```

### Server Version Header

All responses include:
```
X-NeuroStack-Version: 0.9.0
```

Clients can use this to detect feature availability without a separate health check.

---

## Appendix A: Endpoint Summary Table

| Method | Path | Status | Research Finding |
|--------|------|--------|-----------------|
| POST | `/v1/vault/upload` | Modified | tar.gz upload, removed files bug fix, artifact support |
| POST | `/v1/vault/sync` | **New** | Orchestrated push + memory pull |
| POST | `/v1/vault/query` | Modified | Query-time Firestore memory merge |
| GET | `/v1/vault/db-version` | **New** | Firestore version for cache coherence |
| POST | `/v1/vault/push-lock` | **New** | Concurrent push safety |
| GET | `/v1/vault/download` | Modified | ETag caching, gzip, db_version |
| GET | `/v1/vault/memories/since` | **New** | Incremental memory pull |
| POST | `/v1/vault/upload/artifacts` | **New** | Client-side indexing, Gemini cost elimination |
| DELETE | `/v1/vault/files` | **New** | Standalone file deletion for git hooks |

## Appendix B: Firestore Schema Additions

```
users/{user_id}/
  vault_meta/
    db_version        # {version: "gen-...", updated_at: timestamp, db_size: int, note_count: int}
  locks/
    push              # {lock_id: str, device_id: str, expires_at: timestamp, user_id: str}
```

## Appendix C: GCS Layout Changes

```
vaults/{user_id}/
  neurostack.db            # existing: uncompressed SQLite
  neurostack.db.gz         # new: gzip-compressed SQLite (written alongside .db after index)
```

Both files are written on every successful index. The download endpoint serves `.db.gz` when client sends `Accept-Encoding: gzip`, `.db` otherwise.
