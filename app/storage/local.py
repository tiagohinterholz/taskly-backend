from pathlib import Path

from app.storage.backend import StorageError


class LocalStorageBackend:
    """StorageBackend implementation that writes attachments to the local filesystem (dev)."""

    def __init__(self, base_path: str) -> None:
        self._base_path = Path(base_path)

    def save(self, key: str, content: bytes, content_type: str) -> str:
        target = self._base_path / key
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        except OSError as exc:
            raise StorageError(f"failed to save {key!r} locally: {exc}") from exc
        return key

    def delete(self, key: str) -> None:
        target = self._base_path / key
        try:
            target.unlink(missing_ok=True)
        except OSError as exc:
            raise StorageError(f"failed to delete {key!r} locally: {exc}") from exc

    def get_url(self, key: str) -> str | None:
        # No direct URL exists for a local file — callers must proxy via read().
        return None

    def read(self, key: str) -> bytes:
        target = self._base_path / key
        try:
            return target.read_bytes()
        except OSError as exc:
            raise StorageError(f"failed to read {key!r} locally: {exc}") from exc
