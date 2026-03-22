# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Cloud indexing pipeline for NeuroStack.

Accepts uploaded vault files, delegates AI work (embeddings + LLM
extraction) to Vertex AI via OpenAI-compatible endpoints, and
produces indexed SQLite databases stored in Google Cloud Storage.

Tenant isolation guarantees:
- Each indexing job runs in a subprocess with its own env and DB path.
- The parent process is never mutated (no env var patching, no mock).
- Vault files are written to a per-job temp directory, isolated from
  other tenants and the host filesystem.
- Filenames must be pre-sanitised by the API layer before reaching here.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from .config import CloudConfig
from .storage import GCSStorageClient

log = logging.getLogger("neurostack.cloud.indexer")

# Subprocess script that runs full_index in an isolated environment.
# This avoids mutating the parent process's module-level globals
# (DB_PATH, _config singleton, env vars).
_INDEX_SCRIPT = """\
import json
import sys
from pathlib import Path

# Force config reload with the env vars set by the parent.
from neurostack.config import load_config
_cfg = load_config()

# Override the module-level DB_PATH in schema and watcher before they cache it.
import neurostack.schema as _schema
import neurostack.watcher as _watcher
_schema.DB_PATH = _cfg.db_path
_schema.DB_DIR = _cfg.db_dir
_watcher.DB_PATH = _cfg.db_path

from neurostack.watcher import full_index

vault_root = Path(sys.argv[1])
full_index(
    vault_root=vault_root,
    embed_url=_cfg.embed_url,
    summarize_url=_cfg.llm_url,
)

# Output result as JSON on stdout
db_path = _cfg.db_path
result = {
    "db_exists": db_path.exists(),
    "db_size": db_path.stat().st_size if db_path.exists() else 0,
}
print(json.dumps(result))
"""


class CloudIndexer:
    """Orchestrates cloud indexing via Vertex AI and GCS."""

    def __init__(self, config: CloudConfig, storage: GCSStorageClient) -> None:
        self._config = config
        self._storage = storage

    def index_vault(self, user_id: str, vault_files: dict[str, bytes]) -> dict:
        """Index vault files using Vertex AI and store result in GCS.

        Runs indexing in a subprocess for complete isolation from the
        parent process's config, DB path, and env vars.

        Vertex AI auth uses Application Default Credentials (ADC),
        which Cloud Run provides automatically via its service account.
        No API key needed — the subprocess inherits the ADC from the parent.

        Args:
            user_id: Tenant identifier for GCS key prefix.
            vault_files: Mapping of filename -> file content bytes.
                         Filenames must already be sanitised by the caller.

        Returns:
            Dict with keys: status, db_size, note_count (on success)
            or status, error (on failure).
        """
        vertex_base_url = self._config.vertex_base_url

        with tempfile.TemporaryDirectory(prefix=f"ns-cloud-{user_id}-") as tmpdir:
            tmp_path = Path(tmpdir)
            vault_dir = tmp_path / "vault"
            vault_dir.mkdir()
            db_dir = tmp_path / "db"
            db_dir.mkdir()

            # Write vault files to isolated temp directory
            for filename, content in vault_files.items():
                filepath = vault_dir / filename
                filepath.parent.mkdir(parents=True, exist_ok=True)
                filepath.write_bytes(content)

            # Build env for subprocess — inherits parent env but overrides
            # NeuroStack config to point at Vertex AI and the temp DB.
            # Vertex AI uses ADC (Application Default Credentials) inherited
            # from the Cloud Run service account — no API key env var needed.
            env = os.environ.copy()
            env.update({
                "NEUROSTACK_VAULT_ROOT": str(vault_dir),
                "NEUROSTACK_DB_DIR": str(db_dir),
                "NEUROSTACK_EMBED_URL": vertex_base_url,
                "NEUROSTACK_LLM_URL": vertex_base_url,
                "NEUROSTACK_EMBED_MODEL": self._config.vertex_embed_model,
                "NEUROSTACK_LLM_MODEL": self._config.vertex_llm_model,
                # Vertex AI OpenAI-compat uses ADC bearer tokens, not static keys.
                # The httpx calls in embedder.py/summarizer.py will use the
                # NEUROSTACK_EMBED_API_KEY / NEUROSTACK_LLM_API_KEY if set.
                # For Vertex AI, we generate a short-lived access token.
            })

            # Generate a GCP access token for the subprocess to use.
            # On Cloud Run, this comes from the metadata server automatically.
            # For local dev, it uses `gcloud auth print-access-token`.
            try:
                import google.auth
                import google.auth.transport.requests

                credentials, _ = google.auth.default()
                credentials.refresh(google.auth.transport.requests.Request())
                if credentials.token:
                    env["NEUROSTACK_EMBED_API_KEY"] = credentials.token
                    env["NEUROSTACK_LLM_API_KEY"] = credentials.token
            except Exception:
                log.warning("Could not obtain GCP access token for Vertex AI")

            try:
                result = subprocess.run(
                    [sys.executable, "-c", _INDEX_SCRIPT, str(vault_dir)],
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=600,  # 10 minute timeout per indexing job
                )

                if result.returncode != 0:
                    log.error(
                        "Cloud indexing subprocess failed for user %s: %s",
                        user_id,
                        result.stderr[-2000:] if result.stderr else "no stderr",
                    )
                    return {
                        "status": "failed",
                        "error": f"Indexing failed: {result.stderr[-500:]}" if result.stderr else "Indexing process failed",
                    }

                # Parse result from subprocess stdout
                stdout_lines = result.stdout.strip().splitlines()
                if not stdout_lines:
                    return {"status": "failed", "error": "No output from indexing process"}

                sub_result = json.loads(stdout_lines[-1])

                db_path = db_dir / "neurostack.db"
                if sub_result.get("db_exists") and db_path.exists():
                    self._storage.upload_db(user_id, db_path)
                    return {
                        "status": "complete",
                        "db_size": db_path.stat().st_size,
                        "note_count": len(vault_files),
                    }
                else:
                    return {"status": "failed", "error": "No database produced"}

            except subprocess.TimeoutExpired:
                log.error("Cloud indexing timed out for user %s", user_id)
                return {"status": "failed", "error": "Indexing timed out (10 min limit)"}
            except Exception as exc:
                log.exception("Cloud indexing failed for user %s", user_id)
                return {"status": "failed", "error": str(exc)}
