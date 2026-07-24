import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.project_repository import ProjectRepository
from app.repositories.user_repository import UserRepository

# These exercise BaseRepository.get_by_id / BaseRepository.delete — the
# generic single-PK lookup and delete-by-PK shape shared by every concrete
# repository. ProjectRepository is used as the vehicle (it inherits both
# methods unchanged, with no override), rather than inventing a throwaway
# model just for this test.


async def _make_user(db_session: AsyncSession, email: str = "base-repo-owner@example.com"):
    return await UserRepository(db_session).create(email=email, password_hash="hash")


class TestBaseRepositoryGetById:
    async def test_get_by_id_returns_the_matching_row(self, db_session: AsyncSession) -> None:
        user = await _make_user(db_session)
        repo = ProjectRepository(db_session)
        project = await repo.create(user_id=user.id, name="Findable project")

        found = await repo.get_by_id(project.id)

        assert found is not None
        assert found.id == project.id
        assert found.name == "Findable project"

    async def test_get_by_id_returns_none_when_no_row_matches(self, db_session: AsyncSession) -> None:
        repo = ProjectRepository(db_session)

        found = await repo.get_by_id(uuid.uuid4())

        assert found is None

    async def test_get_by_id_is_unscoped_across_different_repositories_own_rows(
        self, db_session: AsyncSession
    ) -> None:
        """Confirms the base implementation queries `model` (set per
        subclass), not some hardcoded table — a user's id must not resolve
        through ProjectRepository.get_by_id.
        """
        user = await _make_user(db_session)
        repo = ProjectRepository(db_session)

        found = await repo.get_by_id(user.id)

        assert found is None


class TestBaseRepositoryDelete:
    async def test_delete_removes_the_row(self, db_session: AsyncSession) -> None:
        user = await _make_user(db_session)
        repo = ProjectRepository(db_session)
        project = await repo.create(user_id=user.id, name="To be deleted")

        await repo.delete(project.id)

        assert await repo.get_by_id(project.id) is None

    async def test_delete_of_nonexistent_id_is_a_no_op(self, db_session: AsyncSession) -> None:
        repo = ProjectRepository(db_session)

        # Should not raise even though nothing matches.
        await repo.delete(uuid.uuid4())
