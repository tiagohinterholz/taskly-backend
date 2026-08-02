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


class _FakeS3StorageBackend:
    """Fake StorageBackend mimicking an S3-backed configuration's direct-URL
    behavior, for exercising the download route's redirect path without a
    real S3 client.
    """

    def __init__(self, presigned_url: str) -> None:
        self._presigned_url = presigned_url

    def save(self, key: str, content: bytes, content_type: str) -> str:
        return key

    def delete(self, key: str) -> None:
        pass

    def get_url(self, key: str) -> str | None:
        return self._presigned_url

    def read(self, key: str) -> bytes:
        raise AssertionError("read() must not be called when get_url() returns a URL")


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
        project_id, task_id = await _create_task(client)

        response = await client.post(
            f"/projects/{project_id}/tasks/{task_id}/attachments",
            files={"file": ("notes.txt", b"hello world", "text/plain")},
        )

        assert response.status_code == 201
        body = response.json()
        assert body["filename"] == "notes.txt"
        assert body["content_type"] == "text/plain"
        assert body["size_bytes"] == len(b"hello world")
        assert body["storage_key"]
        # ATT-01: the response must include a dereferenceable URL, not just
        # the internal storage_key — this API's own download endpoint.
        assert body["url"] == f"/projects/{project_id}/tasks/{task_id}/attachments/{body['id']}/download"
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
            f"/projects/{project_id}/tasks/{task_id}/attachments",
            files={"file": ("photo.png", b"binary-data", "image/png")},
        )
        attachment_id = upload.json()["id"]

        listing = await client.get(f"/projects/{project_id}/tasks")

        assert listing.status_code == 200
        [task] = listing.json()["items"]
        assert [a["id"] for a in task["attachments"]] == [attachment_id]
        assert task["attachments"][0]["url"] == (
            f"/projects/{project_id}/tasks/{task_id}/attachments/{attachment_id}/download"
        )

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
            f"/projects/{project_id}/tasks/{task_id}/attachments",
            files={"file": ("huge.bin", oversized, "application/octet-stream")},
        )

        assert response.status_code == 413
        listing = await client.get(f"/projects/{project_id}/tasks")
        [task] = listing.json()["items"]
        assert task["attachments"] == []
        assert list(tmp_path.rglob("*")) == []

    async def test_upload_for_other_users_task_returns_404(self, client: AsyncClient) -> None:
        await register_and_login(client, _unique_email("att-upload-a"))
        project_id, task_id = await _create_task(client, "A's project")
        await client.post("/auth/logout")

        await register_and_login(client, _unique_email("att-upload-b"))
        response = await client.post(
            f"/projects/{project_id}/tasks/{task_id}/attachments",
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
            f"/projects/{project_id}/tasks/{task_id}/attachments",
            files={"file": ("notes.txt", b"hello", "text/plain")},
        )

        assert response.status_code == 502
        # The task itself (already-saved fields) is untouched by the failure.
        listing = await client.get(f"/projects/{project_id}/tasks")
        [task] = listing.json()["items"]
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
            f"/projects/{project_id}/tasks/{task_id}/attachments",
            files={"file": ("notes.txt", b"hello", "text/plain")},
        )
        attachment_id = upload.json()["id"]
        storage_key = upload.json()["storage_key"]

        response = await client.delete(f"/projects/{project_id}/tasks/{task_id}/attachments/{attachment_id}")

        assert response.status_code == 204
        assert not (tmp_path / storage_key).exists()
        listing = await client.get(f"/projects/{project_id}/tasks")
        [task] = listing.json()["items"]
        assert task["attachments"] == []

    async def test_delete_nonexistent_attachment_returns_404(
        self, app: FastAPI, client: AsyncClient, tmp_path: Path
    ) -> None:
        app.dependency_overrides[get_storage_backend] = lambda: LocalStorageBackend(
            base_path=str(tmp_path)
        )
        await register_and_login(client, _unique_email("att-delete-404"))
        project_id, task_id = await _create_task(client)

        response = await client.delete(f"/projects/{project_id}/tasks/{task_id}/attachments/{uuid.uuid4()}")

        assert response.status_code == 404

    async def test_delete_storage_failure_returns_502(
        self, app: FastAPI, client: AsyncClient, tmp_path: Path
    ) -> None:
        app.dependency_overrides[get_storage_backend] = lambda: LocalStorageBackend(
            base_path=str(tmp_path)
        )
        await register_and_login(client, _unique_email("att-delete-fail"))
        project_id, task_id = await _create_task(client)
        upload = await client.post(
            f"/projects/{project_id}/tasks/{task_id}/attachments",
            files={"file": ("notes.txt", b"hello", "text/plain")},
        )
        attachment_id = upload.json()["id"]

        app.dependency_overrides[get_storage_backend] = lambda: _FailingStorageBackend()
        response = await client.delete(f"/projects/{project_id}/tasks/{task_id}/attachments/{attachment_id}")

        assert response.status_code == 502


class TestDownloadAttachment:
    async def test_download_with_local_backend_streams_file_content(
        self, app: FastAPI, client: AsyncClient, tmp_path: Path
    ) -> None:
        app.dependency_overrides[get_storage_backend] = lambda: LocalStorageBackend(
            base_path=str(tmp_path)
        )
        await register_and_login(client, _unique_email("att-download-local"))
        project_id, task_id = await _create_task(client)
        upload = await client.post(
            f"/projects/{project_id}/tasks/{task_id}/attachments",
            files={"file": ("notes.txt", b"hello world", "text/plain")},
        )
        download_url = upload.json()["url"]

        response = await client.get(download_url)

        assert response.status_code == 200
        assert response.content == b"hello world"
        assert response.headers["content-type"].startswith("text/plain")

    async def test_download_with_s3_backend_redirects_to_presigned_url(
        self, app: FastAPI, client: AsyncClient, tmp_path: Path
    ) -> None:
        app.dependency_overrides[get_storage_backend] = lambda: LocalStorageBackend(
            base_path=str(tmp_path)
        )
        await register_and_login(client, _unique_email("att-download-s3"))
        project_id, task_id = await _create_task(client)
        upload = await client.post(
            f"/projects/{project_id}/tasks/{task_id}/attachments",
            files={"file": ("notes.txt", b"hello world", "text/plain")},
        )
        download_url = upload.json()["url"]
        presigned_url = "https://taskly-attachments.s3.amazonaws.com/some-key?X-Amz-Signature=abc"
        app.dependency_overrides[get_storage_backend] = lambda: _FakeS3StorageBackend(presigned_url)

        response = await client.get(download_url)

        assert response.status_code == 307
        assert response.headers["location"] == presigned_url

    async def test_download_nonexistent_attachment_returns_404(
        self, app: FastAPI, client: AsyncClient, tmp_path: Path
    ) -> None:
        app.dependency_overrides[get_storage_backend] = lambda: LocalStorageBackend(
            base_path=str(tmp_path)
        )
        await register_and_login(client, _unique_email("att-download-404"))
        project_id, task_id = await _create_task(client)

        response = await client.get(
            f"/projects/{project_id}/tasks/{task_id}/attachments/{uuid.uuid4()}/download"
        )

        assert response.status_code == 404

    async def test_download_for_other_users_attachment_returns_404(
        self, app: FastAPI, client: AsyncClient, tmp_path: Path
    ) -> None:
        app.dependency_overrides[get_storage_backend] = lambda: LocalStorageBackend(
            base_path=str(tmp_path)
        )
        await register_and_login(client, _unique_email("att-download-a"))
        project_id, task_id = await _create_task(client, "A's project")
        upload = await client.post(
            f"/projects/{project_id}/tasks/{task_id}/attachments",
            files={"file": ("notes.txt", b"hello", "text/plain")},
        )
        download_url = upload.json()["url"]
        await client.post("/auth/logout")

        await register_and_login(client, _unique_email("att-download-b"))
        response = await client.get(download_url)

        assert response.status_code == 404

    async def test_download_for_attachment_of_a_different_task_returns_404(
        self, app: FastAPI, client: AsyncClient, tmp_path: Path
    ) -> None:
        app.dependency_overrides[get_storage_backend] = lambda: LocalStorageBackend(
            base_path=str(tmp_path)
        )
        await register_and_login(client, _unique_email("att-download-cross-task"))
        project_id, task_id = await _create_task(client)
        other_project_id, other_task_id = await _create_task(client, "Other project")
        upload = await client.post(
            f"/projects/{project_id}/tasks/{task_id}/attachments",
            files={"file": ("notes.txt", b"hello", "text/plain")},
        )
        attachment_id = upload.json()["id"]

        response = await client.get(
            f"/projects/{other_project_id}/tasks/{other_task_id}/attachments/{attachment_id}/download"
        )

        assert response.status_code == 404

    async def test_download_for_task_in_different_project_returns_404(
        self, app: FastAPI, client: AsyncClient, tmp_path: Path
    ) -> None:
        """Isolates the same-user, cross-project mismatch from the
        attachment-to-task check (level c), which would otherwise mask it:
        the attachment genuinely belongs to task_id (so level c passes), and
        project_id genuinely belongs to the caller (so the top-level
        ownership check passes) — but task_id actually belongs to a
        *different* project than the one named in the URL. Only the
        task-to-project check (TaskRepository.get_for_project) can catch
        this. A prior discrimination mutant survived here (Verifier round
        following T19) because the original cross-project test also swapped
        the attachment's task, which let level (c) catch it for the wrong
        reason.
        """
        app.dependency_overrides[get_storage_backend] = lambda: LocalStorageBackend(
            base_path=str(tmp_path)
        )
        await register_and_login(client, _unique_email("att-download-cross-project"))
        project_a_id, _ = await _create_task(client, "Project A")
        project_b_id, task_b_id = await _create_task(client, "Project B")
        upload = await client.post(
            f"/projects/{project_b_id}/tasks/{task_b_id}/attachments",
            files={"file": ("notes.txt", b"hello", "text/plain")},
        )
        attachment_id = upload.json()["id"]

        response = await client.get(
            f"/projects/{project_a_id}/tasks/{task_b_id}/attachments/{attachment_id}/download"
        )

        assert response.status_code == 404
