import uuid
from pathlib import Path

from fastapi import FastAPI
from httpx import AsyncClient

from app.storage.backend import StorageError, get_storage_backend
from app.storage.local import LocalStorageBackend
from tests.integration.api.conftest import register_and_login

_TEN_MB = 10 * 1024 * 1024


class _FailingStorageBackend:
    """Fake StorageBackend that always fails, for exercising ATT-01 AC3
    (storage failure -> 5xx without affecting other data).
    """

    def save(self, key: str, content: bytes, content_type: str) -> str:
        raise StorageError("simulated storage outage")

    def delete(self, key: str) -> None:
        raise StorageError("simulated storage outage")


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4()}@example.com"


async def _create_task(client: AsyncClient, project_name: str = "Project") -> tuple[str, str]:
    project = await client.post("/projects", json={"name": project_name})
    project_id = project.json()["id"]
    task = await client.post(f"/projects/{project_id}/tasks", json={"title": "Task"})
    return project_id, task.json()["id"]


class TestUploadAttachment:
    async def test_upload_success_returns_attachment_reference(
        self, app: FastAPI, client: AsyncClient, tmp_path: Path
    ) -> None:
        app.dependency_overrides[get_storage_backend] = lambda: LocalStorageBackend(
            base_path=str(tmp_path)
        )
        await register_and_login(client, _unique_email("att-upload-ok"))
        _, task_id = await _create_task(client)

        response = await client.post(
            f"/tasks/{task_id}/attachments",
            files={"file": ("notes.txt", b"hello world", "text/plain")},
        )

        assert response.status_code == 201
        body = response.json()
        assert body["filename"] == "notes.txt"
        assert body["content_type"] == "text/plain"
        assert body["size_bytes"] == len(b"hello world")
        assert body["storage_key"]
        # The file was actually written through the storage backend.
        assert (tmp_path / body["storage_key"]).read_bytes() == b"hello world"

    async def test_upload_embeds_attachment_in_task_listing(
        self, app: FastAPI, client: AsyncClient, tmp_path: Path
    ) -> None:
        app.dependency_overrides[get_storage_backend] = lambda: LocalStorageBackend(
            base_path=str(tmp_path)
        )
        await register_and_login(client, _unique_email("att-embed"))
        project_id, task_id = await _create_task(client)
        upload = await client.post(
            f"/tasks/{task_id}/attachments",
            files={"file": ("photo.png", b"binary-data", "image/png")},
        )
        attachment_id = upload.json()["id"]

        listing = await client.get(f"/projects/{project_id}/tasks")

        assert listing.status_code == 200
        [task] = listing.json()
        assert [a["id"] for a in task["attachments"]] == [attachment_id]

    async def test_upload_file_over_10mb_returns_413_without_saving(
        self, app: FastAPI, client: AsyncClient, tmp_path: Path
    ) -> None:
        app.dependency_overrides[get_storage_backend] = lambda: LocalStorageBackend(
            base_path=str(tmp_path)
        )
        await register_and_login(client, _unique_email("att-too-big"))
        project_id, task_id = await _create_task(client)
        oversized = b"x" * (_TEN_MB + 1)

        response = await client.post(
            f"/tasks/{task_id}/attachments",
            files={"file": ("huge.bin", oversized, "application/octet-stream")},
        )

        assert response.status_code == 413
        listing = await client.get(f"/projects/{project_id}/tasks")
        [task] = listing.json()
        assert task["attachments"] == []
        assert list(tmp_path.rglob("*")) == []

    async def test_upload_for_other_users_task_returns_404(self, client: AsyncClient) -> None:
        await register_and_login(client, _unique_email("att-upload-a"))
        _, task_id = await _create_task(client, "A's project")
        await client.post("/auth/logout")

        await register_and_login(client, _unique_email("att-upload-b"))
        response = await client.post(
            f"/tasks/{task_id}/attachments",
            files={"file": ("notes.txt", b"hello", "text/plain")},
        )

        assert response.status_code == 404

    async def test_upload_storage_failure_returns_502_without_affecting_task(
        self, app: FastAPI, client: AsyncClient
    ) -> None:
        app.dependency_overrides[get_storage_backend] = lambda: _FailingStorageBackend()
        await register_and_login(client, _unique_email("att-storage-fail"))
        project_id, task_id = await _create_task(client)

        response = await client.post(
            f"/tasks/{task_id}/attachments",
            files={"file": ("notes.txt", b"hello", "text/plain")},
        )

        assert response.status_code == 502
        # The task itself (already-saved fields) is untouched by the failure.
        listing = await client.get(f"/projects/{project_id}/tasks")
        [task] = listing.json()
        assert task["title"] == "Task"
        assert task["attachments"] == []


class TestDeleteAttachment:
    async def test_delete_removes_from_storage_and_listing(
        self, app: FastAPI, client: AsyncClient, tmp_path: Path
    ) -> None:
        app.dependency_overrides[get_storage_backend] = lambda: LocalStorageBackend(
            base_path=str(tmp_path)
        )
        await register_and_login(client, _unique_email("att-delete"))
        project_id, task_id = await _create_task(client)
        upload = await client.post(
            f"/tasks/{task_id}/attachments",
            files={"file": ("notes.txt", b"hello", "text/plain")},
        )
        attachment_id = upload.json()["id"]
        storage_key = upload.json()["storage_key"]

        response = await client.delete(f"/tasks/{task_id}/attachments/{attachment_id}")

        assert response.status_code == 204
        assert not (tmp_path / storage_key).exists()
        listing = await client.get(f"/projects/{project_id}/tasks")
        [task] = listing.json()
        assert task["attachments"] == []

    async def test_delete_nonexistent_attachment_returns_404(
        self, app: FastAPI, client: AsyncClient, tmp_path: Path
    ) -> None:
        app.dependency_overrides[get_storage_backend] = lambda: LocalStorageBackend(
            base_path=str(tmp_path)
        )
        await register_and_login(client, _unique_email("att-delete-404"))
        _, task_id = await _create_task(client)

        response = await client.delete(f"/tasks/{task_id}/attachments/{uuid.uuid4()}")

        assert response.status_code == 404

    async def test_delete_storage_failure_returns_502(
        self, app: FastAPI, client: AsyncClient, tmp_path: Path
    ) -> None:
        app.dependency_overrides[get_storage_backend] = lambda: LocalStorageBackend(
            base_path=str(tmp_path)
        )
        await register_and_login(client, _unique_email("att-delete-fail"))
        _, task_id = await _create_task(client)
        upload = await client.post(
            f"/tasks/{task_id}/attachments",
            files={"file": ("notes.txt", b"hello", "text/plain")},
        )
        attachment_id = upload.json()["id"]

        app.dependency_overrides[get_storage_backend] = lambda: _FailingStorageBackend()
        response = await client.delete(f"/tasks/{task_id}/attachments/{attachment_id}")

        assert response.status_code == 502
