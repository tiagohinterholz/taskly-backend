import uuid

from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user, get_db_session, get_jwt_service
from app.models.user import User
from app.repositories.user_repository import UserRepository

_PASSWORD = "correct-horse-battery-staple"


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4()}@example.com"


class TestRegister:
    async def test_register_returns_201_and_creates_user(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        email = _unique_email("register")

        response = await client.post(
            "/auth/register", json={"email": email, "password": _PASSWORD}
        )

        assert response.status_code == 201
        body = response.json()
        assert body["email"] == email
        assert "id" in body
        assert "password" not in body
        assert "password_hash" not in body

        stored = await UserRepository(db_session).get_by_email(email)
        assert stored is not None
        assert stored.email == email

    async def test_register_duplicate_email_returns_409_without_creating_duplicate(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        email = _unique_email("dup")
        first = await client.post("/auth/register", json={"email": email, "password": _PASSWORD})
        assert first.status_code == 201

        second = await client.post("/auth/register", json={"email": email, "password": _PASSWORD})

        assert second.status_code == 409
        stored = await UserRepository(db_session).get_by_email(email)
        assert stored is not None
        assert stored.id == uuid.UUID(first.json()["id"])

    async def test_register_invalid_email_returns_422(self, client: AsyncClient) -> None:
        response = await client.post(
            "/auth/register", json={"email": "not-an-email", "password": _PASSWORD}
        )

        assert response.status_code == 422

    async def test_register_short_password_returns_422(self, client: AsyncClient) -> None:
        response = await client.post(
            "/auth/register", json={"email": _unique_email("shortpw"), "password": "short"}
        )

        assert response.status_code == 422


class TestLogin:
    async def test_login_valid_credentials_returns_200_and_sets_cookies(
        self, client: AsyncClient
    ) -> None:
        email = _unique_email("login-ok")
        await client.post("/auth/register", json={"email": email, "password": _PASSWORD})

        response = await client.post("/auth/login", json={"email": email, "password": _PASSWORD})

        assert response.status_code == 200
        assert "access_token" in response.cookies
        assert "refresh_token" in response.cookies

    async def test_login_invalid_credentials_returns_401(self, client: AsyncClient) -> None:
        email = _unique_email("login-bad")
        await client.post("/auth/register", json={"email": email, "password": _PASSWORD})

        response = await client.post("/auth/login", json={"email": email, "password": "wrong-password"})

        assert response.status_code == 401
        assert "access_token" not in response.cookies


class TestRefresh:
    async def test_refresh_issues_new_cookie_pair(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        email = _unique_email("refresh-ok")
        await client.post("/auth/register", json={"email": email, "password": _PASSWORD})
        login_response = await client.post(
            "/auth/login", json={"email": email, "password": _PASSWORD}
        )
        old_refresh = login_response.cookies["refresh_token"]

        response = await client.post("/auth/refresh")

        assert response.status_code == 200
        assert "access_token" in response.cookies
        assert "refresh_token" in response.cookies
        # Rotation guarantee: the refresh token is a fresh random secret every
        # time (secrets.token_urlsafe), so identity here is a reliable signal
        # a *new* pair was actually issued. The access token is a JWT whose
        # iat/exp truncate to whole seconds, so it can be byte-identical to
        # the previous one if minted within the same second — not a
        # meaningful distinctness check — so instead we assert it decodes to
        # the same, correct user, proving it's a valid freshly-issued token.
        assert response.cookies["refresh_token"] != old_refresh
        jwt_service = get_jwt_service()
        stored = await UserRepository(db_session).get_by_email(email)
        assert stored is not None
        assert jwt_service.decode(response.cookies["access_token"]) == stored.id

    async def test_refresh_missing_token_returns_401(self, client: AsyncClient) -> None:
        response = await client.post("/auth/refresh")

        assert response.status_code == 401

    async def test_refresh_invalid_token_returns_401(self, client: AsyncClient) -> None:
        response = await client.post("/auth/refresh", cookies={"refresh_token": "not-a-real-token"})

        assert response.status_code == 401

    async def test_refresh_revoked_token_returns_401(self, client: AsyncClient) -> None:
        email = _unique_email("refresh-revoked")
        await client.post("/auth/register", json={"email": email, "password": _PASSWORD})
        login_response = await client.post(
            "/auth/login", json={"email": email, "password": _PASSWORD}
        )
        first_refresh_token = login_response.cookies["refresh_token"]
        # Rotation: using it once succeeds and revokes it.
        rotated = await client.post("/auth/refresh")
        assert rotated.status_code == 200

        reused = await client.post(
            "/auth/refresh", cookies={"refresh_token": first_refresh_token}
        )

        assert reused.status_code == 401


class TestLogout:
    async def test_logout_clears_cookies_and_revokes_refresh_token(
        self, client: AsyncClient
    ) -> None:
        email = _unique_email("logout")
        await client.post("/auth/register", json={"email": email, "password": _PASSWORD})
        login_response = await client.post(
            "/auth/login", json={"email": email, "password": _PASSWORD}
        )
        refresh_token = login_response.cookies["refresh_token"]

        response = await client.post("/auth/logout")

        assert response.status_code == 204
        assert "access_token" not in client.cookies
        assert "refresh_token" not in client.cookies

        # Revocation actually happened server-side, not just a client-side
        # cookie clear: reusing the pre-logout refresh token must fail.
        reused = await client.post("/auth/refresh", cookies={"refresh_token": refresh_token})
        assert reused.status_code == 401


class TestRateLimiting:
    async def test_sixth_failed_login_attempt_within_window_returns_429(
        self, client: AsyncClient
    ) -> None:
        email = _unique_email("ratelimit")
        await client.post("/auth/register", json={"email": email, "password": _PASSWORD})

        statuses = []
        for _ in range(6):
            response = await client.post(
                "/auth/login", json={"email": email, "password": "wrong-password"}
            )
            statuses.append(response.status_code)

        assert statuses[:5] == [401, 401, 401, 401, 401]
        assert statuses[5] == 429


class TestGetCurrentUserDependency:
    async def test_protected_route_without_cookie_returns_401(
        self, db_session: AsyncSession
    ) -> None:
        app = FastAPI()

        @app.get("/protected")
        async def protected(user: User = Depends(get_current_user)) -> dict[str, str]:
            return {"id": str(user.id)}

        app.dependency_overrides[get_db_session] = lambda: db_session
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.get("/protected")

        assert response.status_code == 401

    async def test_protected_route_with_valid_session_cookie_returns_200(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        email = _unique_email("protected-ok")
        await client.post("/auth/register", json={"email": email, "password": _PASSWORD})
        await client.post("/auth/login", json={"email": email, "password": _PASSWORD})

        app = FastAPI()

        @app.get("/protected")
        async def protected(user: User = Depends(get_current_user)) -> dict[str, str]:
            return {"id": str(user.id), "email": user.email}

        app.dependency_overrides[get_db_session] = lambda: db_session
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test", cookies=client.cookies
        ) as ac:
            response = await ac.get("/protected")

        assert response.status_code == 200
        assert response.json()["email"] == email
