from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import Task
from app.repositories.project_repository import ProjectRepository
from app.repositories.user_repository import UserRepository


async def _make_user(db_session: AsyncSession, email: str = "owner@example.com"):
    return await UserRepository(db_session).create(email=email, password_hash="hash")


class TestProjectRepositoryCreate:
    async def test_create_persists_project_for_user(self, db_session: AsyncSession) -> None:
        user = await _make_user(db_session)
        repo = ProjectRepository(db_session)

        project = await repo.create(user_id=user.id, name="Personal")

        assert project.id is not None
        assert project.user_id == user.id
        assert project.name == "Personal"


class TestProjectRepositoryListForUser:
    async def test_list_for_user_returns_only_that_users_projects(
        self, db_session: AsyncSession
    ) -> None:
        user_a = await _make_user(db_session, email="a@example.com")
        user_b = await _make_user(db_session, email="b@example.com")
        repo = ProjectRepository(db_session)
        project_a = await repo.create(user_id=user_a.id, name="A's project")
        await repo.create(user_id=user_b.id, name="B's project")

        projects_for_a = await repo.list_for_user(user_a.id)

        assert [p.id for p in projects_for_a] == [project_a.id]
        assert all(p.user_id == user_a.id for p in projects_for_a)


class TestProjectRepositoryGetForUser:
    async def test_get_for_user_returns_project_for_owner(self, db_session: AsyncSession) -> None:
        user = await _make_user(db_session)
        repo = ProjectRepository(db_session)
        project = await repo.create(user_id=user.id, name="Mine")

        found = await repo.get_for_user(project.id, user.id)

        assert found is not None
        assert found.id == project.id
        assert found.user_id == user.id

    async def test_get_for_user_returns_none_for_another_users_project(
        self, db_session: AsyncSession
    ) -> None:
        owner = await _make_user(db_session, email="owner-gfu@example.com")
        other = await _make_user(db_session, email="other-gfu@example.com")
        repo = ProjectRepository(db_session)
        project = await repo.create(user_id=owner.id, name="Owner's project")

        found = await repo.get_for_user(project.id, other.id)

        assert found is None


class TestProjectRepositoryRename:
    async def test_rename_updates_name(self, db_session: AsyncSession) -> None:
        user = await _make_user(db_session)
        repo = ProjectRepository(db_session)
        project = await repo.create(user_id=user.id, name="Old name")

        renamed = await repo.rename(project.id, "New name")

        assert renamed.id == project.id
        assert renamed.name == "New name"


class TestProjectRepositoryDelete:
    async def test_delete_removes_project(self, db_session: AsyncSession) -> None:
        user = await _make_user(db_session)
        repo = ProjectRepository(db_session)
        project = await repo.create(user_id=user.id, name="To delete")

        await repo.delete(project.id)

        remaining = await repo.list_for_user(user.id)
        assert remaining == []


class TestProjectRepositoryCountTasks:
    async def test_count_tasks_returns_zero_when_no_tasks(self, db_session: AsyncSession) -> None:
        user = await _make_user(db_session)
        repo = ProjectRepository(db_session)
        project = await repo.create(user_id=user.id, name="Empty project")

        count = await repo.count_tasks(project.id)

        assert count == 0

    async def test_count_tasks_returns_number_of_tasks_in_project(
        self, db_session: AsyncSession
    ) -> None:
        user = await _make_user(db_session)
        repo = ProjectRepository(db_session)
        project = await repo.create(user_id=user.id, name="With tasks")
        db_session.add(Task(project_id=project.id, title="Task 1"))
        db_session.add(Task(project_id=project.id, title="Task 2"))
        await db_session.flush()

        count = await repo.count_tasks(project.id)

        assert count == 2
