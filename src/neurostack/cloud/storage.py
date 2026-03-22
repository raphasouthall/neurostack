# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""R2-compatible object storage client for NeuroStack Cloud.

Uses boto3 with S3-compatible API to interact with Cloudflare R2.
Tenant isolation is enforced via prefix-based key structure:
  - vaults/{user_id}/neurostack.db  (indexed database)
  - uploads/{user_id}/{filename}    (raw vault files)

All public methods validate user_id to prevent prefix traversal.
"""

from __future__ import annotations

import re
from pathlib import Path

import boto3
from botocore.config import Config as BotoConfig

from .config import CloudConfig

# user_id must be alphanumeric + hyphens + underscores, 1-128 chars.
# This prevents any path traversal via crafted user IDs.
_VALID_USER_ID = re.compile(r"^[a-zA-Z0-9_-]{1,128}$")


def _validate_user_id(user_id: str) -> str:
    """Validate user_id to prevent R2 prefix traversal."""
    if not _VALID_USER_ID.match(user_id):
        raise ValueError(
            f"Invalid user_id: must be 1-128 alphanumeric/hyphen/underscore chars, got {user_id!r}"
        )
    return user_id


class R2StorageClient:
    """S3-compatible client for Cloudflare R2 with tenant isolation."""

    def __init__(self, config: CloudConfig) -> None:
        self._config = config
        self._client = boto3.client(
            "s3",
            endpoint_url=config.r2_endpoint_url,
            aws_access_key_id=config.r2_access_key_id,
            aws_secret_access_key=config.r2_secret_access_key,
            config=BotoConfig(signature_version="s3v4"),
        )

    def upload_db(self, user_id: str, db_path: Path) -> str:
        """Upload an indexed database for a user.

        Returns the S3 key.
        """
        _validate_user_id(user_id)
        key = f"vaults/{user_id}/neurostack.db"
        self._client.upload_file(str(db_path), self._config.r2_bucket_name, key)
        return key

    def generate_download_url(self, user_id: str, expires_in: int = 3600) -> str:
        """Generate a presigned download URL for a user's database.

        Default expiry is 1 hour (3600 seconds).
        """
        _validate_user_id(user_id)
        return self._client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": self._config.r2_bucket_name,
                "Key": f"vaults/{user_id}/neurostack.db",
            },
            ExpiresIn=expires_in,
        )

    def upload_vault_files(self, user_id: str, files: dict[str, bytes]) -> list[str]:
        """Upload raw vault files for indexing.

        Args:
            user_id: Tenant identifier.
            files: Mapping of filename -> content bytes.

        Returns:
            List of S3 keys for the uploaded files.
        """
        _validate_user_id(user_id)
        keys: list[str] = []
        for filename, content in files.items():
            key = f"uploads/{user_id}/{filename}"
            self._client.put_object(
                Bucket=self._config.r2_bucket_name, Key=key, Body=content
            )
            keys.append(key)
        return keys

    def download_vault_files(self, user_id: str) -> dict[str, bytes]:
        """Download all uploaded vault files for a user.

        Returns:
            Mapping of filename -> content bytes.
        """
        _validate_user_id(user_id)
        prefix = f"uploads/{user_id}/"
        files: dict[str, bytes] = {}

        response = self._client.list_objects_v2(
            Bucket=self._config.r2_bucket_name, Prefix=prefix
        )
        for obj in response.get("Contents", []):
            obj_key = obj["Key"]
            filename = obj_key[len(prefix):]
            resp = self._client.get_object(
                Bucket=self._config.r2_bucket_name, Key=obj_key
            )
            files[filename] = resp["Body"].read()

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
        paginator_kwargs = {
            "Bucket": self._config.r2_bucket_name,
            "Prefix": prefix,
        }

        while True:
            response = self._client.list_objects_v2(**paginator_kwargs)
            contents = response.get("Contents", [])
            if not contents:
                break

            objects = [{"Key": obj["Key"]} for obj in contents]
            self._client.delete_objects(
                Bucket=self._config.r2_bucket_name,
                Delete={"Objects": objects},
            )
            deleted += len(objects)

            if not response.get("IsTruncated", False):
                break
            paginator_kwargs["ContinuationToken"] = response["NextContinuationToken"]

        return deleted
