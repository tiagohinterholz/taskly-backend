import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.task_repository import TaskRepository
from tests.integration.api.conftest import register_and_login


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4()}@example.com"


class TestCreateProject:
    async def test_create_project_returns_201(self, client: AsyncClient) -> None:
        await register_and_login(client, _unique_email("proj-create"))

        response = await client.post("/projects", json={"name": "Personal"})

        assert response.status_code == 201
        body = response.json()
        assert body["name"] == "Personal"
        assert "id" in body

    async def test_create_project_without_session_returns_401(self, client: AsyncClient) -> None:
        response = await client.post("/projects", json={"name": "Personal"})

        assert response.status_code == 401


class TestListProjects:
    async def test_list_projects_returns_only_own_projects(self, client: AsyncClient) -> None:
        await register_and_login(client, _unique_email("proj-list-a"))
        created = await client.post("/projects", json={"name": "A's project"})
        assert created.status_code == 201

        response = await client.get("/projects")

        assert response.status_code == 200
        body = response.json()
        names = [p["name"] for p in body["items"]]
        assert names == ["A's project"]
        assert body["total"] == 1
        assert body["limit"] == 50
        assert body["offset"] == 0

    async def test_list_projects_excludes_other_users_projects(self, client: AsyncClient) -> None:
        await register_and_login(client, _unique_email("proj-list-b1"))
        await client.post("/projects", json={"name": "User B's project"})
        await client.post("/auth/logout")

        await register_and_login(client, _unique_email("proj-list-b2"))
        response = await client.get("/projects")

        assert response.status_code == 200
        body = response.json()
        assert body["items"] == []
        assert body["total"] == 0

    async def test_list_projects_respects_limit_and_offset(self, client: AsyncClient) -> None:
        await register_and_login(client, _unique_email("proj-list-page"))
        for name in ["P1", "P2", "P3"]:
            created = await client.post("/projects", json={"name": name})
            assert created.status_code == 201

        first_page = await client.get("/projects", params={"limit": 2, "offset": 0})
        second_page = await client.get("/projects", params={"limit": 2, "offset": 2})

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

        first_names = {p["name"] for p in first_body["items"]}
        second_names = {p["name"] for p in second_body["items"]}
        assert first_names.isdisjoint(second_names)
        assert first_names | second_names == {"P1", "P2", "P3"}

    async def test_list_projects_limit_over_100_returns_422(self, client: AsyncClient) -> None:
        await register_and_login(client, _unique_email("proj-list-limit-422"))

        response = await client.get("/projects", params={"limit": 101})

        assert response.status_code == 422

    async def test_list_projects_negative_offset_returns_422(self, client: AsyncClient) -> None:
        await register_and_login(client, _unique_email("proj-list-offset-422"))

        response = await client.get("/projects", params={"offset": -1})

        assert response.status_code == 422

    async def test_project_out_group_id_is_null_for_a_personal_project(
        self, client: AsyncClient
    ) -> None:
        await register_and_login(client, _unique_email("proj-list-group-null"))
        await client.post("/projects", json={"name": "Personal"})

        response = await client.get("/projects")

        assert response.json()["items"][0]["group_id"] is None

    async def test_project_out_group_id_reflects_the_linked_group_after_linking(
        self, client: AsyncClient
    ) -> None:
        await register_and_login(client, _unique_email("proj-list-group-set"))
        project = await client.post("/projects", json={"name": "Shared"})
        project_id = project.json()["id"]
        group = await client.post("/groups", json={"name": "Team"})
        group_id = group.json()["id"]
        link = await client.post(f"/groups/{group_id}/projects/{project_id}/link")
        assert link.status_code == 200

        response = await client.get("/projects")

        items = response.json()["items"]
        assert next(p for p in items if p["id"] == project_id)["group_id"] == group_id

    async def test_list_projects_group_id_filter_narrows_to_that_groups_projects(
        self, client: AsyncClient
    ) -> None:
        await register_and_login(client, _unique_email("proj-list-group-filter"))
        personal = await client.post("/projects", json={"name": "Personal"})
        shared = await client.post("/projects", json={"name": "Shared"})
        group = await client.post("/groups", json={"name": "Team"})
        group_id = group.json()["id"]
        await client.post(f"/groups/{group_id}/projects/{shared.json()['id']}/link")

        response = await client.get("/projects", params={"group_id": group_id})

        body = response.json()
        assert body["total"] == 1
        assert [p["id"] for p in body["items"]] == [shared.json()["id"]]
        assert personal.json()["id"] not in [p["id"] for p in body["items"]]


class TestRenameProject:
    async def test_rename_project_updates_name(self, client: AsyncClient) -> None:
        await register_and_login(client, _unique_email("proj-rename"))
        created = await client.post("/projects", json={"name": "Old name"})
        project_id = created.json()["id"]

        response = await client.patch(f"/projects/{project_id}", json={"name": "New name"})

        assert response.status_code == 200
        assert response.json()["name"] == "New name"

    async def test_rename_nonexistent_project_returns_404(self, client: AsyncClient) -> None:
        await register_and_login(client, _unique_email("proj-rename-404"))

        response = await client.patch(f"/projects/{uuid.uuid4()}", json={"name": "New name"})

        assert response.status_code == 404

    async def test_rename_other_users_project_returns_404(self, client: AsyncClient) -> None:
        await register_and_login(client, _unique_email("proj-rename-a"))
        created = await client.post("/projects", json={"name": "A's project"})
        project_id = created.json()["id"]
        await client.post("/auth/logout")

        await register_and_login(client, _unique_email("proj-rename-b"))
        response = await client.patch(f"/projects/{project_id}", json={"name": "Hijacked"})

        assert response.status_code == 404


class TestDeleteProject:
    async def test_delete_project_with_tasks_returns_409(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await register_and_login(client, _unique_email("proj-delete-409"))
        created = await client.post("/projects", json={"name": "Has tasks"})
        project_id = created.json()["id"]
        await TaskRepository(db_session).create(project_id=uuid.UUID(project_id), title="A task")
        await db_session.commit()

        response = await client.delete(f"/projects/{project_id}")

        assert response.status_code == 409

    async def test_delete_project_without_tasks_returns_204(self, client: AsyncClient) -> None:
        await register_and_login(client, _unique_email("proj-delete-204"))
        created = await client.post("/projects", json={"name": "Empty"})
        project_id = created.json()["id"]

        response = await client.delete(f"/projects/{project_id}")

        assert response.status_code == 204
        listing = await client.get("/projects")
        assert listing.json()["items"] == []

    async def test_delete_other_users_project_returns_404(self, client: AsyncClient) -> None:
        await register_and_login(client, _unique_email("proj-delete-a"))
        created = await client.post("/projects", json={"name": "A's project"})
        project_id = created.json()["id"]
        await client.post("/auth/logout")

        await register_and_login(client, _unique_email("proj-delete-b"))
        response = await client.delete(f"/projects/{project_id}")

        assert response.status_code == 404
