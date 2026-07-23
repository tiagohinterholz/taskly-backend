import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.user_repository import UserRepository


class TestUserRepositoryCreate:
    async def test_create_persists_user_with_email_and_password_hash(
        self, db_session: AsyncSession
    ) -> None:
        repo = UserRepository(db_session)

        user = await repo.create(email="alice@example.com", password_hash="hashed-value")

        assert user.id is not None
        assert user.email == "alice@example.com"
        assert user.password_hash == "hashed-value"
        assert user.created_at is not None

    async def test_create_duplicate_email_raises_integrity_error(
        self, db_session: AsyncSession
    ) -> None:
        repo = UserRepository(db_session)
        await repo.create(email="dup@example.com", password_hash="hash-1")

        with pytest.raises(IntegrityError):
            await repo.create(email="dup@example.com", password_hash="hash-2")


class TestUserRepositoryGetByEmail:
    async def test_get_by_email_returns_existing_user(self, db_session: AsyncSession) -> None:
        repo = UserRepository(db_session)
        created = await repo.create(email="bob@example.com", password_hash="hash")

        found = await repo.get_by_email("bob@example.com")

        assert found is not None
        assert found.id == created.id
        assert found.email == "bob@example.com"

    async def test_get_by_email_returns_none_when_not_found(self, db_session: AsyncSession) -> None:
        repo = UserRepository(db_session)

        found = await repo.get_by_email("nobody@example.com")

        assert found is None
