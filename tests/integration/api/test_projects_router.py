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
        names = [p["name"] for p in response.json()]
        assert names == ["A's project"]

    async def test_list_projects_excludes_other_users_projects(self, client: AsyncClient) -> None:
        await register_and_login(client, _unique_email("proj-list-b1"))
        await client.post("/projects", json={"name": "User B's project"})
        await client.post("/auth/logout")

        await register_and_login(client, _unique_email("proj-list-b2"))
        response = await client.get("/projects")

        assert response.status_code == 200
        assert response.json() == []


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
        assert listing.json() == []

    async def test_delete_other_users_project_returns_404(self, client: AsyncClient) -> None:
        await register_and_login(client, _unique_email("proj-delete-a"))
        created = await client.post("/projects", json={"name": "A's project"})
        project_id = created.json()["id"]
        await client.post("/auth/logout")

        await register_and_login(client, _unique_email("proj-delete-b"))
        response = await client.delete(f"/projects/{project_id}")

        assert response.status_code == 404
