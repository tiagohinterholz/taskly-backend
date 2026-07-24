import uuid

import pytest
from httpx import AsyncClient

_RANDOM_ID = uuid.uuid4()
_RANDOM_PROJECT_ID = uuid.uuid4()

# ISO-01: "WHEN uma requisição a qualquer endpoint de projeto/tarefa não
# possui sessão válida THEN o sistema SHALL retornar 401." Every protected
# route (project, task, attachment) must reject an unauthenticated request
# with 401 *before* ever looking up the resource — random/placeholder path
# ids are used so a route that skipped the auth check and went straight to
# a DB lookup would surface as a 404 (or crash), not a 401, making that
# ordering bug visible here.
_PROTECTED_ROUTES: list[tuple[str, str, dict]] = [
    ("GET", "/projects", {}),
    ("POST", "/projects", {"json": {"name": "Unauthorized project"}}),
    ("PATCH", f"/projects/{_RANDOM_ID}", {"json": {"name": "Hijack"}}),
    ("DELETE", f"/projects/{_RANDOM_ID}", {}),
    ("GET", f"/projects/{_RANDOM_ID}/tasks", {}),
    ("POST", f"/projects/{_RANDOM_ID}/tasks", {"json": {"title": "Unauthorized task"}}),
    (
        "PATCH",
        f"/projects/{_RANDOM_PROJECT_ID}/tasks/{_RANDOM_ID}",
        {"json": {"title": "Hijack"}},
    ),
    ("DELETE", f"/projects/{_RANDOM_PROJECT_ID}/tasks/{_RANDOM_ID}", {}),
    (
        "POST",
        f"/projects/{_RANDOM_PROJECT_ID}/tasks/{_RANDOM_ID}/attachments",
        {"files": {"file": ("notes.txt", b"hello", "text/plain")}},
    ),
    (
        "DELETE",
        f"/projects/{_RANDOM_PROJECT_ID}/tasks/{_RANDOM_ID}/attachments/{uuid.uuid4()}",
        {},
    ),
]


class TestProtectedRoutesRequireSession:
    @pytest.mark.parametrize(
        "method, path, kwargs",
        _PROTECTED_ROUTES,
        ids=[f"{method} {path}" for method, path, _ in _PROTECTED_ROUTES],
    )
    async def test_returns_401_without_session_cookie(
        self, client: AsyncClient, method: str, path: str, kwargs: dict
    ) -> None:
        response = await client.request(method, path, **kwargs)

        assert response.status_code == 401
