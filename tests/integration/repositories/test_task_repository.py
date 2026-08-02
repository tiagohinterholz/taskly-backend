import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import TaskStatus
from app.repositories.project_repository import ProjectRepository
from app.repositories.task_repository import TaskRepository
from app.repositories.user_repository import UserRepository


async def _make_project(db_session: AsyncSession):
    user = await UserRepository(db_session).create(email="owner@example.com", password_hash="hash")
    return await ProjectRepository(db_session).create(user_id=user.id, name="Project")


class TestTaskRepositoryCreate:
    async def test_create_with_title_only_uses_defaults(self, db_session: AsyncSession) -> None:
        project = await _make_project(db_session)
        repo = TaskRepository(db_session)

        task = await repo.create(project_id=project.id, title="Write report")

        assert task.id is not None
        assert task.project_id == project.id
        assert task.title == "Write report"
        assert task.short_description is None
        assert task.full_description is None
        assert task.due_at is None
        assert task.tags == []
        assert task.status == TaskStatus.NOT_STARTED

    async def test_create_persists_all_optional_fields(self, db_session: AsyncSession) -> None:
        project = await _make_project(db_session)
        project_id = project.id
        repo = TaskRepository(db_session)
        due_at = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)

        task = await repo.create(
            project_id=project_id,
            title="Ship feature",
            short_description="short",
            full_description="full description here",
            due_at=due_at,
            tags=["backend", "urgent"],
            status=TaskStatus.IN_PROGRESS,
        )

        assert task.short_description == "short"
        assert task.full_description == "full description here"
        assert task.due_at == due_at
        assert task.tags == ["backend", "urgent"]
        assert task.status == TaskStatus.IN_PROGRESS

        # expire_all() forces a real SELECT from Postgres (bypassing the
        # session's identity map), proving tags (ARRAY) and status (Enum)
        # survive an actual round-trip through the asyncpg type adapters.
        # IDs are captured above (project_id) since attribute access after
        # expire_all() would trigger a sync lazy-load, unsupported here.
        db_session.expire_all()
        reloaded, _ = await repo.list_for_project(project_id, limit=50, offset=0)
        assert reloaded[0].tags == ["backend", "urgent"]
        assert reloaded[0].status == TaskStatus.IN_PROGRESS


class TestTaskRepositoryListForProject:
    async def test_list_for_project_returns_only_that_projects_tasks(
        self, db_session: AsyncSession
    ) -> None:
        project_a = await _make_project(db_session)
        other_user = await UserRepository(db_session).create(email="other@example.com", password_hash="hash")
        project_b = await ProjectRepository(db_session).create(user_id=other_user.id, name="Other project")
        repo = TaskRepository(db_session)
        task_a = await repo.create(project_id=project_a.id, title="A task")
        await repo.create(project_id=project_b.id, title="B task")

        tasks, total = await repo.list_for_project(project_a.id, limit=50, offset=0)

        assert [t.id for t in tasks] == [task_a.id]
        assert total == 1


class TestTaskRepositoryGetForProject:
    async def test_get_for_project_returns_task_for_owning_project(
        self, db_session: AsyncSession
    ) -> None:
        project = await _make_project(db_session)
        repo = TaskRepository(db_session)
        task = await repo.create(project_id=project.id, title="Mine")

        found = await repo.get_for_project(task.id, project.id)

        assert found is not None
        assert found.id == task.id
        assert found.project_id == project.id

    async def test_get_for_project_returns_none_for_task_in_different_project(
        self, db_session: AsyncSession
    ) -> None:
        project_a = await _make_project(db_session)
        other_user = await UserRepository(db_session).create(
            email="other-gfp@example.com", password_hash="hash"
        )
        project_b = await ProjectRepository(db_session).create(
            user_id=other_user.id, name="Other project"
        )
        repo = TaskRepository(db_session)
        task_in_b = await repo.create(project_id=project_b.id, title="B task")

        found = await repo.get_for_project(task_in_b.id, project_a.id)

        assert found is None


class TestTaskRepositoryGetById:
    """get_by_id is inherited from BaseRepository and is intentionally
    unscoped (no project_id filter) — see the class docstring on
    TaskRepository for why callers rely on that.
    """

    async def test_get_by_id_returns_task_regardless_of_project(
        self, db_session: AsyncSession
    ) -> None:
        project = await _make_project(db_session)
        repo = TaskRepository(db_session)
        task = await repo.create(project_id=project.id, title="Findable")

        found = await repo.get_by_id(task.id)

        assert found is not None
        assert found.id == task.id
        assert found.project_id == project.id

    async def test_get_by_id_returns_none_when_not_found(self, db_session: AsyncSession) -> None:
        repo = TaskRepository(db_session)

        found = await repo.get_by_id(uuid.uuid4())

        assert found is None


class TestTaskRepositoryUpdate:
    async def test_update_persists_partial_field_change(self, db_session: AsyncSession) -> None:
        project = await _make_project(db_session)
        project_id = project.id
        repo = TaskRepository(db_session)
        task = await repo.create(project_id=project_id, title="Original title")

        updated = await repo.update(task.id, title="Updated title")

        assert updated.title == "Updated title"
        # expire_all() forces the next read to hit Postgres instead of trusting
        # the session's identity map, proving the change was actually flushed.
        db_session.expire_all()
        reloaded, _ = await repo.list_for_project(project_id, limit=50, offset=0)
        assert reloaded[0].title == "Updated title"

    async def test_update_status_round_trips_through_read(self, db_session: AsyncSession) -> None:
        project = await _make_project(db_session)
        project_id = project.id
        repo = TaskRepository(db_session)
        task = await repo.create(project_id=project_id, title="Task")

        await repo.update(task.id, status=TaskStatus.DONE)

        db_session.expire_all()
        reloaded, _ = await repo.list_for_project(project_id, limit=50, offset=0)
        assert reloaded[0].status == TaskStatus.DONE

    async def test_update_tags_round_trips_through_read(self, db_session: AsyncSession) -> None:
        project = await _make_project(db_session)
        project_id = project.id
        repo = TaskRepository(db_session)
        task = await repo.create(project_id=project_id, title="Task")

        await repo.update(task.id, tags=["one", "two", "three"])

        db_session.expire_all()
        reloaded, _ = await repo.list_for_project(project_id, limit=50, offset=0)
        assert reloaded[0].tags == ["one", "two", "three"]


class TestTaskRepositoryDelete:
    async def test_delete_removes_task(self, db_session: AsyncSession) -> None:
        project = await _make_project(db_session)
        repo = TaskRepository(db_session)
        task = await repo.create(project_id=project.id, title="To delete")

        await repo.delete(task.id)

        remaining, total = await repo.list_for_project(project.id, limit=50, offset=0)
        assert remaining == []
        assert total == 0
