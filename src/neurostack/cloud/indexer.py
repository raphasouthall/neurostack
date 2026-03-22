# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Cloud indexing pipeline for NeuroStack.

Accepts uploaded vault files, delegates AI work (embeddings + LLM
extraction) to the Gemini API via its OpenAI-compatible endpoint, and
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

from .config import GEMINI_BASE_URL, CloudConfig
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
    """Orchestrates cloud indexing via Gemini API and GCS."""

    def __init__(self, config: CloudConfig, storage: GCSStorageClient) -> None:
        self._config = config
        self._storage = storage

    def index_vault(self, user_id: str, vault_files: dict[str, bytes]) -> dict:
        """Index vault files using Gemini API and store result in GCS.

        Runs indexing in a subprocess for complete isolation from the
        parent process's config, DB path, and env vars.

        Auth uses a Gemini API key (passed as NEUROSTACK_EMBED_API_KEY
        and NEUROSTACK_LLM_API_KEY env vars). The NeuroStack embedder
        and summarizer send this as a Bearer token on their httpx calls.

        Args:
            user_id: Tenant identifier for GCS key prefix.
            vault_files: Mapping of filename -> file content bytes.
                         Filenames must already be sanitised by the caller.

        Returns:
            Dict with keys: status, db_size, note_count (on success)
            or status, error (on failure).
        """
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
            # NeuroStack config to point at Gemini API and the temp DB.
            env = os.environ.copy()
            env.update({
                "NEUROSTACK_VAULT_ROOT": str(vault_dir),
                "NEUROSTACK_DB_DIR": str(db_dir),
                "NEUROSTACK_EMBED_URL": GEMINI_BASE_URL,
                "NEUROSTACK_LLM_URL": GEMINI_BASE_URL,
                "NEUROSTACK_EMBED_MODEL": self._config.gemini_embed_model,
                "NEUROSTACK_LLM_MODEL": self._config.gemini_llm_model,
                "NEUROSTACK_EMBED_DIM": str(self._config.gemini_embed_dim),
                "NEUROSTACK_EMBED_API_KEY": self._config.gemini_api_key,
                "NEUROSTACK_LLM_API_KEY": self._config.gemini_api_key,
            })

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
