from pathlib import Path

import pytest

from app.storage.backend import StorageError
from app.storage.local import LocalStorageBackend


class TestLocalStorageBackend:
    def test_save_writes_real_file_to_disk(self, tmp_path: Path) -> None:
        backend = LocalStorageBackend(base_path=str(tmp_path))

        reference = backend.save("attachments/note.txt", b"hello world", "text/plain")

        saved_file = tmp_path / "attachments" / "note.txt"
        assert saved_file.read_bytes() == b"hello world"
        assert reference == "attachments/note.txt"

    def test_delete_removes_real_file_from_disk(self, tmp_path: Path) -> None:
        backend = LocalStorageBackend(base_path=str(tmp_path))
        backend.save("note.txt", b"hello world", "text/plain")
        saved_file = tmp_path / "note.txt"
        assert saved_file.exists()

        backend.delete("note.txt")

        assert not saved_file.exists()

    def test_get_url_always_returns_none(self, tmp_path: Path) -> None:
        # Local files have no dereferenceable direct URL — callers must
        # proxy the content via read() instead.
        backend = LocalStorageBackend(base_path=str(tmp_path))
        backend.save("note.txt", b"hello world", "text/plain")

        assert backend.get_url("note.txt") is None

    def test_read_returns_the_bytes_written_by_save(self, tmp_path: Path) -> None:
        backend = LocalStorageBackend(base_path=str(tmp_path))
        backend.save("attachments/note.txt", b"hello world", "text/plain")

        content = backend.read("attachments/note.txt")

        assert content == b"hello world"

    def test_read_raises_storage_error_for_missing_key(self, tmp_path: Path) -> None:
        backend = LocalStorageBackend(base_path=str(tmp_path))

        with pytest.raises(StorageError):
            backend.read("does/not/exist.txt")
