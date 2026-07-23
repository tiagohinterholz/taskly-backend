import pytest

from app.storage.backend import get_storage_backend
from app.storage.local import LocalStorageBackend
from app.storage.s3 import S3StorageBackend


class TestGetStorageBackend:
    def test_returns_local_backend_when_storage_backend_is_local(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        monkeypatch.setenv("STORAGE_BACKEND", "local")
        monkeypatch.setenv("LOCAL_STORAGE_PATH", str(tmp_path))

        backend = get_storage_backend()

        assert isinstance(backend, LocalStorageBackend)

    def test_returns_s3_backend_when_storage_backend_is_s3(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("STORAGE_BACKEND", "s3")
        monkeypatch.setenv("S3_BUCKET", "taskly-attachments")

        backend = get_storage_backend()

        assert isinstance(backend, S3StorageBackend)
