import os
from typing import Protocol


class StorageError(Exception):
    """Raised when a StorageBackend fails to save or delete an object.

    Callers (e.g. attachment router/service) catch this single type
    regardless of which backend is configured and map it to a 5xx response.
    """


class StorageBackend(Protocol):
    """Abstraction over attachment persistence (local filesystem, S3, ...)."""

    def save(self, key: str, content: bytes, content_type: str) -> str:
        """Persist content under key, returning a reference to the stored object."""
        ...

    def delete(self, key: str) -> None:
        """Remove the object stored under key."""
        ...

    def get_url(self, key: str) -> str | None:
        """Return a direct, time-limited URL to the object if the backend
        supports one, or None if the backend requires proxying the content
        through the API (e.g. local filesystem has no dereferenceable URL).
        """
        ...

    def read(self, key: str) -> bytes:
        """Return the raw content stored under key. Used by callers when
        get_url() returns None and the content must be proxied.
        """
        ...


def get_storage_backend() -> StorageBackend:
    """Select a StorageBackend implementation based on the STORAGE_BACKEND env var."""
    backend = os.environ.get("STORAGE_BACKEND", "local")

    if backend == "local":
        from app.storage.local import LocalStorageBackend

        base_path = os.environ.get("LOCAL_STORAGE_PATH", "./data/attachments")
        return LocalStorageBackend(base_path=base_path)

    if backend == "s3":
        from app.storage.s3 import S3StorageBackend

        bucket = os.environ["S3_BUCKET"]
        return S3StorageBackend(bucket=bucket)

    raise ValueError(f"Unknown STORAGE_BACKEND: {backend!r}")
