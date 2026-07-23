from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.storage.backend import StorageError


class S3StorageBackend:
    """StorageBackend implementation that persists attachments to an S3 bucket (prod)."""

    def __init__(self, bucket: str, client: Any = None) -> None:
        self._bucket = bucket
        self._client = client if client is not None else boto3.client("s3")

    def save(self, key: str, content: bytes, content_type: str) -> str:
        try:
            self._client.put_object(
                Bucket=self._bucket, Key=key, Body=content, ContentType=content_type
            )
        except (BotoCoreError, ClientError) as exc:
            raise StorageError(f"failed to save {key!r} to S3: {exc}") from exc
        return key

    def delete(self, key: str) -> None:
        try:
            self._client.delete_object(Bucket=self._bucket, Key=key)
        except (BotoCoreError, ClientError) as exc:
            raise StorageError(f"failed to delete {key!r} from S3: {exc}") from exc
