import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

import app.repositories.attachment_repository as attachment_repository_module
from app.models.task import TaskStatus
from app.storage.backend import StorageError, get_storage_backend
from app.storage.local import LocalStorageBackend
from tests.integration.api.conftest import register_and_login


class _FailingStorageBackend:
    """Fake StorageBackend that always fails deletes — mirrors the fake used
    in test_attachments_router.py for ATT-01 AC3-style storage-failure tests.
    """

    def save(self, key: str, content: bytes, content_type: str) -> str:
        raise StorageError("simulated storage outage")

    def delete(self, key: str) -> None:
        raise StorageError("simulated storage outage")


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4()}@example.com"


async def _create_project(client: AsyncClient, name: str = "Project") -> str:
    response = await client.post("/projects", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _create_group_owned_project_and_invite(client: AsyncClient) -> tuple[str, str]:
    """Owner A creates a group, creates + links a project to it, and
    generates a pending invite. Leaves the client logged out (matching the
    register/logout/register pattern used throughout this file) so the
    caller can log in as whoever should accept the invite next.

    Returns (project_id, invite_token).
    """
    await register_and_login(client, _unique_email("grp-task-owner"))
    group_response = await client.post("/groups", json={"name": "Task Access Team"})
    assert group_response.status_code == 201, group_response.text
    group_id = group_response.json()["id"]

    project_id = await _create_project(client, "Group-linked project")

    link_response = await client.post(f"/groups/{group_id}/projects/{project_id}/link")
    assert link_response.status_code == 200, link_response.text

    invite_response = await client.post(f"/groups/{group_id}/invites")
    assert invite_response.status_code == 201, invite_response.text
    token = invite_response.json()["token"]

    await client.post("/auth/logout")
    return project_id, token


class TestCreateTask:
    async def test_create_task_with_title_only_returns_201(self, client: AsyncClient) -> None:
        await register_and_login(client, _unique_email("task-create"))
        project_id = await _create_project(client)

        response = await client.post(f"/projects/{project_id}/tasks", json={"title": "Write report"})

        assert response.status_code == 201
        body = response.json()
        assert body["title"] == "Write report"
        assert body["status"] == "not_started"
        assert body["short_description"] is None
        assert body["full_description"] is None
        assert body["due_at"] is None
        assert body["tags"] == []
        assert body["attachments"] == []
        assert body["project_id"] == project_id

    async def test_create_task_without_title_returns_422(self, client: AsyncClient) -> None:
        await register_and_login(client, _unique_email("task-create-422"))
        project_id = await _create_project(client)

        response = await client.post(f"/projects/{project_id}/tasks", json={})

        assert response.status_code == 422

    async def test_create_task_due_at_invalid_format_returns_422(self, client: AsyncClient) -> None:
        await register_and_login(client, _unique_email("task-create-bad-due-at"))
        project_id = await _create_project(client)

        response = await client.post(
            f"/projects/{project_id}/tasks", json={"title": "T", "due_at": "not-a-date"}
        )

        assert response.status_code == 422

    async def test_create_task_in_other_users_project_returns_404(self, client: AsyncClient) -> None:
        await register_and_login(client, _unique_email("task-create-a"))
        project_id = await _create_project(client, "A's project")
        await client.post("/auth/logout")

        await register_and_login(client, _unique_email("task-create-b"))
        response = await client.post(f"/projects/{project_id}/tasks", json={"title": "Sneaky"})

        assert response.status_code == 404


class TestListTasks:
    async def test_list_tasks_returns_all_fields(self, client: AsyncClient) -> None:
        await register_and_login(client, _unique_email("task-list"))
        project_id = await _create_project(client)
        await client.post(
            f"/projects/{project_id}/tasks",
            json={"title": "Task 1", "tags": ["backend"]},
        )
        await client.post(f"/projects/{project_id}/tasks", json={"title": "Task 2"})

        response = await client.get(f"/projects/{project_id}/tasks")

        assert response.status_code == 200
        body = response.json()
        titles = {t["title"] for t in body["items"]}
        assert titles == {"Task 1", "Task 2"}
        assert body["total"] == 2
        assert body["limit"] == 50
        assert body["offset"] == 0

    async def test_list_tasks_for_other_users_project_returns_404(self, client: AsyncClient) -> None:
        await register_and_login(client, _unique_email("task-list-a"))
        project_id = await _create_project(client, "A's project")
        await client.post("/auth/logout")

        await register_and_login(client, _unique_email("task-list-b"))
        response = await client.get(f"/projects/{project_id}/tasks")

        assert response.status_code == 404

    async def test_list_tasks_respects_limit_and_offset(self, client: AsyncClient) -> None:
        await register_and_login(client, _unique_email("task-list-page"))
        project_id = await _create_project(client)
        for title in ["T1", "T2", "T3"]:
            await client.post(f"/projects/{project_id}/tasks", json={"title": title})

        first_page = await client.get(
            f"/projects/{project_id}/tasks", params={"limit": 2, "offset": 0}
        )
        second_page = await client.get(
            f"/projects/{project_id}/tasks", params={"limit": 2, "offset": 2}
        )

        assert first_page.status_code == 200
        first_body = first_page.json()
        assert len(first_body["items"]) == 2
        assert first_body["total"] == 3
        assert first_body["limit"] == 2
        assert first_body["offset"] == 0

        second_body = second_page.json()
        assert len(second_body["items"]) == 1
        assert second_body["total"] == 3
        assert second_body["offset"] == 2

        first_titles = {t["title"] for t in first_body["items"]}
        second_titles = {t["title"] for t in second_body["items"]}
        assert first_titles.isdisjoint(second_titles)
        assert first_titles | second_titles == {"T1", "T2", "T3"}

    async def test_list_tasks_filters_by_status(self, client: AsyncClient) -> None:
        await register_and_login(client, _unique_email("task-list-status"))
        project_id = await _create_project(client)
        created_done = await client.post(
            f"/projects/{project_id}/tasks", json={"title": "Done task"}
        )
        done_task_id = created_done.json()["id"]
        await client.patch(
            f"/projects/{project_id}/tasks/{done_task_id}", json={"status": "done"}
        )
        await client.post(f"/projects/{project_id}/tasks", json={"title": "Not started task"})

        response = await client.get(
            f"/projects/{project_id}/tasks", params={"status": "done"}
        )

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert [t["id"] for t in body["items"]] == [done_task_id]
        assert all(t["status"] == "done" for t in body["items"])

    async def test_list_tasks_limit_over_100_returns_422(self, client: AsyncClient) -> None:
        await register_and_login(client, _unique_email("task-list-limit-422"))
        project_id = await _create_project(client)

        response = await client.get(
            f"/projects/{project_id}/tasks", params={"limit": 101}
        )

        assert response.status_code == 422

    async def test_list_tasks_negative_offset_returns_422(self, client: AsyncClient) -> None:
        await register_and_login(client, _unique_email("task-list-offset-422"))
        project_id = await _create_project(client)

        response = await client.get(
            f"/projects/{project_id}/tasks", params={"offset": -1}
        )

        assert response.status_code == 422


class TestUpdateTask:
    async def test_update_title_field(self, client: AsyncClient) -> None:
        await register_and_login(client, _unique_email("task-upd-title"))
        project_id = await _create_project(client)
        created = await client.post(f"/projects/{project_id}/tasks", json={"title": "Original"})
        task_id = created.json()["id"]

        response = await client.patch(f"/projects/{project_id}/tasks/{task_id}", json={"title": "Updated"})

        assert response.status_code == 200
        assert response.json()["title"] == "Updated"

    async def test_update_short_description_field(self, client: AsyncClient) -> None:
        await register_and_login(client, _unique_email("task-upd-short"))
        project_id = await _create_project(client)
        created = await client.post(f"/projects/{project_id}/tasks", json={"title": "T"})
        task_id = created.json()["id"]

        response = await client.patch(
            f"/projects/{project_id}/tasks/{task_id}", json={"short_description": "A short summary"}
        )

        assert response.status_code == 200
        assert response.json()["short_description"] == "A short summary"

    async def test_update_full_description_field(self, client: AsyncClient) -> None:
        await register_and_login(client, _unique_email("task-upd-full"))
        project_id = await _create_project(client)
        created = await client.post(f"/projects/{project_id}/tasks", json={"title": "T"})
        task_id = created.json()["id"]

        response = await client.patch(
            f"/projects/{project_id}/tasks/{task_id}", json={"full_description": "A much longer description"}
        )

        assert response.status_code == 200
        assert response.json()["full_description"] == "A much longer description"

    async def test_update_due_at_field(self, client: AsyncClient) -> None:
        await register_and_login(client, _unique_email("task-upd-due"))
        project_id = await _create_project(client)
        created = await client.post(f"/projects/{project_id}/tasks", json={"title": "T"})
        task_id = created.json()["id"]

        response = await client.patch(
            f"/projects/{project_id}/tasks/{task_id}", json={"due_at": "2026-08-01T12:00:00Z"}
        )

        assert response.status_code == 200
        assert response.json()["due_at"].startswith("2026-08-01T12:00:00")

    async def test_update_tags_field(self, client: AsyncClient) -> None:
        await register_and_login(client, _unique_email("task-upd-tags"))
        project_id = await _create_project(client)
        created = await client.post(f"/projects/{project_id}/tasks", json={"title": "T"})
        task_id = created.json()["id"]

        response = await client.patch(f"/projects/{project_id}/tasks/{task_id}", json={"tags": ["urgent", "backend"]})

        assert response.status_code == 200
        assert response.json()["tags"] == ["urgent", "backend"]

    async def test_update_tag_over_20_chars_returns_422(self, client: AsyncClient) -> None:
        await register_and_login(client, _unique_email("task-upd-tag-long"))
        project_id = await _create_project(client)
        created = await client.post(f"/projects/{project_id}/tasks", json={"title": "T"})
        task_id = created.json()["id"]
        too_long_tag = "a" * 21

        response = await client.patch(f"/projects/{project_id}/tasks/{task_id}", json={"tags": ["urgent", too_long_tag]})

        assert response.status_code == 422
        # TAG-02 requires the 422 to indicate *which* tag exceeded the
        # limit, not just that some tag did.
        assert too_long_tag in response.json()["detail"]

    async def test_update_with_empty_title_returns_422(self, client: AsyncClient) -> None:
        await register_and_login(client, _unique_email("task-upd-empty-title"))
        project_id = await _create_project(client)
        created = await client.post(f"/projects/{project_id}/tasks", json={"title": "T"})
        task_id = created.json()["id"]

        response = await client.patch(f"/projects/{project_id}/tasks/{task_id}", json={"title": ""})

        assert response.status_code == 422

    async def test_update_due_at_invalid_format_returns_422(self, client: AsyncClient) -> None:
        await register_and_login(client, _unique_email("task-upd-bad-due-at"))
        project_id = await _create_project(client)
        created = await client.post(f"/projects/{project_id}/tasks", json={"title": "T"})
        task_id = created.json()["id"]

        response = await client.patch(f"/projects/{project_id}/tasks/{task_id}", json={"due_at": "not-a-date"})

        assert response.status_code == 422

    async def test_update_invalid_status_returns_422(self, client: AsyncClient) -> None:
        await register_and_login(client, _unique_email("task-upd-bad-status"))
        project_id = await _create_project(client)
        created = await client.post(f"/projects/{project_id}/tasks", json={"title": "T"})
        task_id = created.json()["id"]

        response = await client.patch(f"/projects/{project_id}/tasks/{task_id}", json={"status": "not_a_real_status"})

        assert response.status_code == 422

    async def test_update_nonexistent_task_returns_404(self, client: AsyncClient) -> None:
        await register_and_login(client, _unique_email("task-upd-404"))
        project_id = await _create_project(client)

        response = await client.patch(
            f"/projects/{project_id}/tasks/{uuid.uuid4()}", json={"title": "New"}
        )

        assert response.status_code == 404

    async def test_update_other_users_task_returns_404(self, client: AsyncClient) -> None:
        await register_and_login(client, _unique_email("task-upd-a"))
        project_id = await _create_project(client, "A's project")
        created = await client.post(f"/projects/{project_id}/tasks", json={"title": "A's task"})
        task_id = created.json()["id"]
        await client.post("/auth/logout")

        await register_and_login(client, _unique_email("task-upd-b"))
        response = await client.patch(f"/projects/{project_id}/tasks/{task_id}", json={"title": "Hijacked"})

        assert response.status_code == 404

    @pytest.mark.parametrize(
        "target_status",
        [s.value for s in TaskStatus],
    )
    async def test_status_can_transition_to_any_of_the_four_states(
        self, client: AsyncClient, target_status: str
    ) -> None:
        await register_and_login(client, _unique_email(f"task-status-{target_status}"))
        project_id = await _create_project(client)
        created = await client.post(f"/projects/{project_id}/tasks", json={"title": "T"})
        task_id = created.json()["id"]

        response = await client.patch(f"/projects/{project_id}/tasks/{task_id}", json={"status": target_status})

        assert response.status_code == 200
        assert response.json()["status"] == target_status

    async def test_status_transition_backwards_done_to_not_started(self, client: AsyncClient) -> None:
        await register_and_login(client, _unique_email("task-status-backwards"))
        project_id = await _create_project(client)
        created = await client.post(f"/projects/{project_id}/tasks", json={"title": "T"})
        task_id = created.json()["id"]
        forward = await client.patch(f"/projects/{project_id}/tasks/{task_id}", json={"status": "done"})
        assert forward.json()["status"] == "done"

        backward = await client.patch(f"/projects/{project_id}/tasks/{task_id}", json={"status": "not_started"})

        assert backward.status_code == 200
        assert backward.json()["status"] == "not_started"


class TestDeleteTask:
    async def test_delete_task_removes_it_from_listing(self, client: AsyncClient) -> None:
        await register_and_login(client, _unique_email("task-delete"))
        project_id = await _create_project(client)
        created = await client.post(f"/projects/{project_id}/tasks", json={"title": "To delete"})
        task_id = created.json()["id"]

        response = await client.delete(f"/projects/{project_id}/tasks/{task_id}")

        assert response.status_code == 204
        listing = await client.get(f"/projects/{project_id}/tasks")
        assert listing.json()["items"] == []

    async def test_delete_nonexistent_task_returns_404(self, client: AsyncClient) -> None:
        await register_and_login(client, _unique_email("task-delete-404"))
        project_id = await _create_project(client)

        response = await client.delete(f"/projects/{project_id}/tasks/{uuid.uuid4()}")

        assert response.status_code == 404

    async def test_delete_other_users_task_returns_404(self, client: AsyncClient) -> None:
        await register_and_login(client, _unique_email("task-delete-a"))
        project_id = await _create_project(client, "A's project")
        created = await client.post(f"/projects/{project_id}/tasks", json={"title": "A's task"})
        task_id = created.json()["id"]
        await client.post("/auth/logout")

        await register_and_login(client, _unique_email("task-delete-b"))
        response = await client.delete(f"/projects/{project_id}/tasks/{task_id}")

        assert response.status_code == 404

    async def test_delete_task_removes_its_attachment_files_from_storage(
        self, app: FastAPI, client: AsyncClient, tmp_path: Path
    ) -> None:
        """TASK-04: deleting a task must remove its associated attachments —
        not just the DB rows (which cascade-delete automatically), but the
        actual files in storage. Regression test for the orphaned-file leak.
        """
        app.dependency_overrides[get_storage_backend] = lambda: LocalStorageBackend(
            base_path=str(tmp_path)
        )
        await register_and_login(client, _unique_email("task-delete-att"))
        project_id = await _create_project(client)
        created = await client.post(f"/projects/{project_id}/tasks", json={"title": "With attachment"})
        task_id = created.json()["id"]
        upload = await client.post(
            f"/projects/{project_id}/tasks/{task_id}/attachments",
            files={"file": ("notes.txt", b"hello world", "text/plain")},
        )
        assert upload.status_code == 201, upload.text
        storage_key = upload.json()["storage_key"]
        assert (tmp_path / storage_key).exists()

        response = await client.delete(f"/projects/{project_id}/tasks/{task_id}")

        assert response.status_code == 204
        assert not (tmp_path / storage_key).exists()
        listing = await client.get(f"/projects/{project_id}/tasks")
        assert listing.json()["items"] == []

    async def test_delete_task_returns_502_and_keeps_task_when_storage_fails(
        self, app: FastAPI, client: AsyncClient, tmp_path: Path
    ) -> None:
        app.dependency_overrides[get_storage_backend] = lambda: LocalStorageBackend(
            base_path=str(tmp_path)
        )
        await register_and_login(client, _unique_email("task-delete-att-fail"))
        project_id = await _create_project(client)
        created = await client.post(f"/projects/{project_id}/tasks", json={"title": "With attachment"})
        task_id = created.json()["id"]
        upload = await client.post(
            f"/projects/{project_id}/tasks/{task_id}/attachments",
            files={"file": ("notes.txt", b"hello world", "text/plain")},
        )
        assert upload.status_code == 201, upload.text

        app.dependency_overrides[get_storage_backend] = lambda: _FailingStorageBackend()
        response = await client.delete(f"/projects/{project_id}/tasks/{task_id}")

        assert response.status_code == 502
        listing = await client.get(f"/projects/{project_id}/tasks")
        [task] = listing.json()["items"]
        assert task["id"] == task_id


class TestNoNPlusOneOnListing:
    async def test_list_tasks_batches_attachment_fetch_into_a_single_call(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Regression guard: listing N tasks must fetch their attachments
        with exactly one batched call to AttachmentRepository.list_for_tasks
        (all task ids at once), never one call per task (N+1).
        """
        await register_and_login(client, _unique_email("task-n-plus-one"))
        project_id = await _create_project(client)
        for i in range(5):
            await client.post(f"/projects/{project_id}/tasks", json={"title": f"Task {i}"})

        original = attachment_repository_module.AttachmentRepository.list_for_tasks
        call_count = 0

        async def _counting_list_for_tasks(self, task_ids):
            nonlocal call_count
            call_count += 1
            return await original(self, task_ids)

        monkeypatch.setattr(
            attachment_repository_module.AttachmentRepository,
            "list_for_tasks",
            _counting_list_for_tasks,
        )

        response = await client.get(f"/projects/{project_id}/tasks")

        assert response.status_code == 200
        assert len(response.json()["items"]) == 5
        assert call_count == 1


class TestGroupMemberTaskAccess:
    """T16 / spec P1 AC10-AC11 (GRP-05): the actual payoff of groups-rbac --
    a Member of a group can fully CRUD tasks on a project linked to that
    group, exactly like the original owner could, via `_get_accessible_project_id`
    (AD-018). A non-member gets the exact same 404 a v1 outsider always got --
    proving the group extension is additive, never a broadening of who can
    reach an unrelated project's tasks.
    """

    async def test_group_member_can_fully_crud_tasks_on_linked_project(
        self, client: AsyncClient
    ) -> None:
        project_id, token = await _create_group_owned_project_and_invite(client)

        await register_and_login(client, _unique_email("grp-task-member"))
        accept_response = await client.post(f"/invites/{token}/accept")
        assert accept_response.status_code == 200, accept_response.text

        create_response = await client.post(
            f"/projects/{project_id}/tasks", json={"title": "Member-created task"}
        )
        assert create_response.status_code == 201, create_response.text
        task_id = create_response.json()["id"]
        assert create_response.json()["project_id"] == project_id

        list_response = await client.get(f"/projects/{project_id}/tasks")
        assert list_response.status_code == 200
        assert list_response.json()["total"] == 1
        assert [t["id"] for t in list_response.json()["items"]] == [task_id]

        update_response = await client.patch(
            f"/projects/{project_id}/tasks/{task_id}", json={"title": "Updated by member"}
        )
        assert update_response.status_code == 200
        assert update_response.json()["title"] == "Updated by member"

        delete_response = await client.delete(f"/projects/{project_id}/tasks/{task_id}")
        assert delete_response.status_code == 204

        post_delete_listing = await client.get(f"/projects/{project_id}/tasks")
        assert post_delete_listing.json()["items"] == []

    async def test_non_member_still_gets_404_on_group_linked_project_tasks(
        self, client: AsyncClient
    ) -> None:
        project_id, token = await _create_group_owned_project_and_invite(client)
        # Consume the invite as a legitimate member first, so the project has
        # real group-based traffic -- the outsider below is a genuinely
        # different, uninvited third party (spec's user C), not merely an
        # empty group.
        await register_and_login(client, _unique_email("grp-task-member-b"))
        accept_response = await client.post(f"/invites/{token}/accept")
        assert accept_response.status_code == 200, accept_response.text
        seed_task = await client.post(
            f"/projects/{project_id}/tasks", json={"title": "Seed task"}
        )
        assert seed_task.status_code == 201, seed_task.text
        task_id = seed_task.json()["id"]
        await client.post("/auth/logout")

        await register_and_login(client, _unique_email("grp-task-outsider-c"))

        create_response = await client.post(
            f"/projects/{project_id}/tasks", json={"title": "Sneaky create"}
        )
        assert create_response.status_code == 404

        list_response = await client.get(f"/projects/{project_id}/tasks")
        assert list_response.status_code == 404

        update_response = await client.patch(
            f"/projects/{project_id}/tasks/{task_id}", json={"title": "Sneaky update"}
        )
        assert update_response.status_code == 404

        delete_response = await client.delete(f"/projects/{project_id}/tasks/{task_id}")
        assert delete_response.status_code == 404
