from collections.abc import AsyncGenerator

import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db_session
from app.api.routers.attachments import router as attachments_router
from app.api.routers.auth import router as auth_router
from app.api.routers.groups import router as groups_router
from app.api.routers.projects import router as projects_router
from app.api.routers.tasks import router as tasks_router

# Routers are mounted here (not on app.main.app, which stays untouched until
# T16's final wiring) so each Phase-5 task's e2e tests exercise the real
# ASGI app in-process via httpx.ASGITransport, without a running server.
_ROUTERS = [auth_router, projects_router, tasks_router, attachments_router, groups_router]


def _build_app(session: AsyncSession) -> FastAPI:
    app = FastAPI()
    for router in _ROUTERS:
        app.include_router(router)
    app.dependency_overrides[get_db_session] = lambda: session
    return app


@pytest_asyncio.fixture
async def app(db_session: AsyncSession) -> AsyncGenerator[FastAPI, None]:
    """The FastAPI app instance, exposed separately from `client` so tests
    can mutate `app.dependency_overrides` (e.g. swap in a fake storage
    backend for T15's attachment tests) before making requests.
    """
    yield _build_app(db_session)


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


DEFAULT_PASSWORD = "correct-horse-battery-staple"


async def register_and_login(client: AsyncClient, email: str, password: str = DEFAULT_PASSWORD) -> None:
    """Registers a user and logs in, leaving session cookies set on `client`.
    Shared by every Phase-5 router test that needs an authenticated caller.
    """
    register_response = await client.post("/auth/register", json={"email": email, "password": password})
    assert register_response.status_code == 201, register_response.text
    login_response = await client.post("/auth/login", json={"email": email, "password": password})
    assert login_response.status_code == 200, login_response.text
