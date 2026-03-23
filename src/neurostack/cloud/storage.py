# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Google Cloud Storage client for NeuroStack Cloud.

Uses google-cloud-storage to interact with GCS.
Tenant isolation is enforced via prefix-based key structure:
  - vaults/{user_id}/neurostack.db  (indexed database)
  - uploads/{user_id}/{filename}    (raw vault files)

All public methods validate user_id to prevent prefix traversal.
"""

from __future__ import annotations

import re
from pathlib import Path

from google.cloud import storage as gcs

from .config import CloudConfig

# user_id must be alphanumeric + hyphens + underscores, 1-128 chars.
# This prevents any path traversal via crafted user IDs.
_VALID_USER_ID = re.compile(r"^[a-zA-Z0-9_-]{1,128}$")


def _validate_user_id(user_id: str) -> str:
    """Validate user_id to prevent GCS prefix traversal."""
    if not _VALID_USER_ID.match(user_id):
        raise ValueError(
            f"Invalid user_id: must be 1-128 alphanumeric/hyphen/underscore chars, got {user_id!r}"
        )
    return user_id


class GCSStorageClient:
    """Google Cloud Storage client with tenant isolation."""

    def __init__(self, config: CloudConfig) -> None:
        self._config = config
        self._client = gcs.Client(project=config.gcp_project)
        self._bucket = self._client.bucket(config.gcs_bucket_name)

    def upload_db(self, user_id: str, db_path: Path) -> str:
        """Upload an indexed database for a user.

        Returns the GCS blob name.
        """
        _validate_user_id(user_id)
        blob_name = f"vaults/{user_id}/neurostack.db"
        blob = self._bucket.blob(blob_name)
        blob.upload_from_filename(str(db_path))
        return blob_name

    def generate_download_url(self, user_id: str, expires_in: int = 3600) -> str:
        """Generate a signed download URL for a user's database.

        Default expiry is 1 hour (3600 seconds).
        On Cloud Run, uses IAM signBlob via service_account_email +
        access_token params (compute credentials can't sign locally).
        """
        import datetime

        import google.auth
        import google.auth.transport.requests

        _validate_user_id(user_id)
        blob = self._bucket.blob(f"vaults/{user_id}/neurostack.db")

        credentials, _ = google.auth.default()
        credentials.refresh(google.auth.transport.requests.Request())

        return blob.generate_signed_url(
            version="v4",
            expiration=datetime.timedelta(seconds=expires_in),
            method="GET",
            service_account_email=credentials.service_account_email,
            access_token=credentials.token,
        )

    def upload_vault_files(self, user_id: str, files: dict[str, bytes]) -> list[str]:
        """Upload raw vault files for indexing.

        Args:
            user_id: Tenant identifier.
            files: Mapping of filename -> content bytes.

        Returns:
            List of GCS blob names for the uploaded files.
        """
        _validate_user_id(user_id)
        blob_names: list[str] = []
        for filename, content in files.items():
            blob_name = f"uploads/{user_id}/{filename}"
            blob = self._bucket.blob(blob_name)
            blob.upload_from_string(content)
            blob_names.append(blob_name)
        return blob_names

    def download_vault_files(self, user_id: str) -> dict[str, bytes]:
        """Download all uploaded vault files for a user.

        Returns:
            Mapping of filename -> content bytes.
        """
        _validate_user_id(user_id)
        prefix = f"uploads/{user_id}/"
        files: dict[str, bytes] = {}

        for blob in self._client.list_blobs(
            self._config.gcs_bucket_name, prefix=prefix
        ):
            filename = blob.name[len(prefix):]
            files[filename] = blob.download_as_bytes()

        return files

    def delete_user_data(self, user_id: str) -> int:
        """Delete all objects for a user (vaults and uploads).

        Returns:
            Total number of objects deleted.
        """
        _validate_user_id(user_id)
        total_deleted = 0
        for prefix in (f"vaults/{user_id}/", f"uploads/{user_id}/"):
            total_deleted += self._delete_prefix(prefix)
        return total_deleted

    def _delete_prefix(self, prefix: str) -> int:
        """Delete all objects under a given prefix.

        Returns number of objects deleted.
        """
        deleted = 0
        blobs = list(
            self._client.list_blobs(self._config.gcs_bucket_name, prefix=prefix)
        )
        for blob in blobs:
            blob.delete()
            deleted += 1
        return deleted
