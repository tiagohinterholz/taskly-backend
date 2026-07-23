from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.refresh_token_repository import RefreshTokenRepository
from app.repositories.user_repository import UserRepository


async def _make_user(db_session: AsyncSession):
    return await UserRepository(db_session).create(email="owner@example.com", password_hash="hash")


class TestRefreshTokenRepositoryCreate:
    async def test_create_persists_refresh_token_for_user(self, db_session: AsyncSession) -> None:
        user = await _make_user(db_session)
        repo = RefreshTokenRepository(db_session)
        expires_at = datetime.now(timezone.utc) + timedelta(days=7)

        token = await repo.create(user_id=user.id, token_hash="hash-abc", expires_at=expires_at)

        assert token.id is not None
        assert token.user_id == user.id
        assert token.token_hash == "hash-abc"
        assert token.expires_at == expires_at
        assert token.revoked_at is None


class TestRefreshTokenRepositoryGetByHash:
    async def test_get_by_hash_returns_existing_token(self, db_session: AsyncSession) -> None:
        user = await _make_user(db_session)
        repo = RefreshTokenRepository(db_session)
        expires_at = datetime.now(timezone.utc) + timedelta(days=7)
        created = await repo.create(user_id=user.id, token_hash="hash-xyz", expires_at=expires_at)

        found = await repo.get_by_hash("hash-xyz")

        assert found is not None
        assert found.id == created.id

    async def test_get_by_hash_returns_none_when_not_found(self, db_session: AsyncSession) -> None:
        repo = RefreshTokenRepository(db_session)

        found = await repo.get_by_hash("does-not-exist")

        assert found is None

    async def test_get_by_hash_returns_expired_token_row(self, db_session: AsyncSession) -> None:
        """Repository returns the row regardless of expiry; usability is a service-layer concern."""
        user = await _make_user(db_session)
        repo = RefreshTokenRepository(db_session)
        expired_at = datetime.now(timezone.utc) - timedelta(days=1)

        await repo.create(user_id=user.id, token_hash="expired-token", expires_at=expired_at)
        found = await repo.get_by_hash("expired-token")

        assert found is not None
        assert found.expires_at == expired_at


class TestRefreshTokenRepositoryRevoke:
    async def test_revoke_sets_revoked_at(self, db_session: AsyncSession) -> None:
        user = await _make_user(db_session)
        repo = RefreshTokenRepository(db_session)
        expires_at = datetime.now(timezone.utc) + timedelta(days=7)
        token = await repo.create(user_id=user.id, token_hash="to-revoke", expires_at=expires_at)
        assert token.revoked_at is None

        await repo.revoke(token.id)

        revoked = await repo.get_by_hash("to-revoke")
        assert revoked is not None
        assert revoked.revoked_at is not None

    async def test_get_by_hash_returns_revoked_token_row(self, db_session: AsyncSession) -> None:
        """A revoked token is still queryable via get_by_hash (row-level access, no filtering)."""
        user = await _make_user(db_session)
        repo = RefreshTokenRepository(db_session)
        expires_at = datetime.now(timezone.utc) + timedelta(days=7)
        token = await repo.create(user_id=user.id, token_hash="already-revoked", expires_at=expires_at)
        await repo.revoke(token.id)

        found = await repo.get_by_hash("already-revoked")

        assert found is not None
        assert found.id == token.id
        assert found.revoked_at is not None
