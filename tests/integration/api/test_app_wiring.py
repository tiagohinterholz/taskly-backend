"""T16: wiring smoke tests against the fully-assembled `app.main.app` --
exercises the real ASGI app (all four routers + CORS middleware mounted
together), not the per-router test apps built in conftest.py's `_build_app`.
"""

import os
import uuid
from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db_session
from app.main import app

DEFAULT_PASSWORD = "correct-horse-battery-staple"


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4()}@example.com"


@pytest_asyncio.fixture
async def wired_client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Client against the real `app.main.app`, with only the DB session
    dependency overridden (same override every router test uses) so writes
    land in -- and get truncated from -- the shared test Postgres instance.
    """
    app.dependency_overrides[get_db_session] = lambda: db_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


class TestHealthAndDocs:
    async def test_health_returns_200(self, wired_client: AsyncClient) -> None:
        response = await wired_client.get("/health")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    async def test_docs_returns_200(self, wired_client: AsyncClient) -> None:
        response = await wired_client.get("/docs")

        assert response.status_code == 200

    async def test_openapi_json_returns_200(self, wired_client: AsyncClient) -> None:
        response = await wired_client.get("/openapi.json")

        assert response.status_code == 200


class TestCORS:
    async def test_configured_frontend_origin_is_allowed(self, wired_client: AsyncClient) -> None:
        origin = os.environ.get("CORS_ORIGIN", "http://localhost:5173")

        response = await wired_client.get("/health", headers={"Origin": origin})

        assert response.headers.get("access-control-allow-origin") == origin
        assert response.headers.get("access-control-allow-credentials") == "true"

    async def test_other_origin_is_not_allowed(self, wired_client: AsyncClient) -> None:
        response = await wired_client.get(
            "/health", headers={"Origin": "https://evil.example.com"}
        )

        assert "access-control-allow-origin" not in response.headers


class TestFullStackSmokeWalk:
    async def test_register_login_create_project_create_task_list_tasks(
        self, wired_client: AsyncClient
    ) -> None:
        email = _unique_email("wiring-smoke")

        register_response = await wired_client.post(
            "/auth/register", json={"email": email, "password": DEFAULT_PASSWORD}
        )
        assert register_response.status_code == 201, register_response.text

        login_response = await wired_client.post(
            "/auth/login", json={"email": email, "password": DEFAULT_PASSWORD}
        )
        assert login_response.status_code == 200, login_response.text

        project_response = await wired_client.post(
            "/projects", json={"name": "Wiring smoke project"}
        )
        assert project_response.status_code == 201, project_response.text
        project_id = project_response.json()["id"]

        task_response = await wired_client.post(
            f"/projects/{project_id}/tasks", json={"title": "Wiring smoke task"}
        )
        assert task_response.status_code == 201, task_response.text

        list_response = await wired_client.get(f"/projects/{project_id}/tasks")
        assert list_response.status_code == 200, list_response.text
        tasks = list_response.json()
        assert len(tasks) == 1
        assert tasks[0]["title"] == "Wiring smoke task"
