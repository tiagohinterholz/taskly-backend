from pathlib import Path

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
