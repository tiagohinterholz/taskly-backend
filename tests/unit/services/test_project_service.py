import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project
from app.repositories.project_repository import ProjectRepository
from app.services.project_service import ProjectHasTasksError, ProjectService


def _make_service() -> tuple[ProjectService, AsyncMock, AsyncMock]:
    session = AsyncMock(spec=AsyncSession)
    project_repository = AsyncMock(spec=ProjectRepository)
    service = ProjectService(session=session, project_repository=project_repository)
    return service, project_repository, session


def _make_project(user_id: uuid.UUID, name: str = "My Project") -> Project:
    return Project(
        id=uuid.uuid4(),
        user_id=user_id,
        name=name,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


class TestCreate:
    async def test_create_persists_project_for_user_and_commits(self) -> None:
        service, project_repository, session = _make_service()
        user_id = uuid.uuid4()
        created_project = _make_project(user_id, "My Project")
        project_repository.create.return_value = created_project

        result = await service.create(user_id, "My Project")

        assert result is created_project
        project_repository.create.assert_awaited_once_with(user_id, "My Project")
        session.commit.assert_awaited_once()


class TestListForUser:
    async def test_list_for_user_returns_only_that_users_projects(self) -> None:
        service, project_repository, _ = _make_service()
        user_id = uuid.uuid4()
        user_projects = [_make_project(user_id, "A"), _make_project(user_id, "B")]
        project_repository.list_for_user.return_value = user_projects

        result = await service.list_for_user(user_id)

        assert result == user_projects
        project_repository.list_for_user.assert_awaited_once_with(user_id)

    async def test_list_for_user_returns_empty_list_when_user_has_no_projects(self) -> None:
        service, project_repository, _ = _make_service()
        user_id = uuid.uuid4()
        project_repository.list_for_user.return_value = []

        result = await service.list_for_user(user_id)

        assert result == []


class TestRename:
    async def test_rename_updates_project_name_and_commits(self) -> None:
        service, project_repository, session = _make_service()
        user_id = uuid.uuid4()
        project_id = uuid.uuid4()
        renamed_project = _make_project(user_id, "New Name")
        project_repository.rename.return_value = renamed_project

        result = await service.rename(user_id, project_id, "New Name")

        assert result is renamed_project
        assert result.name == "New Name"
        project_repository.rename.assert_awaited_once_with(project_id, "New Name")
        session.commit.assert_awaited_once()


class TestDelete:
    async def test_delete_blocked_when_project_has_tasks(self) -> None:
        service, project_repository, session = _make_service()
        user_id = uuid.uuid4()
        project_id = uuid.uuid4()
        project_repository.count_tasks.return_value = 3

        with pytest.raises(ProjectHasTasksError):
            await service.delete(user_id, project_id)

        project_repository.delete.assert_not_awaited()
        session.commit.assert_not_awaited()

    async def test_delete_allowed_when_project_has_no_tasks(self) -> None:
        service, project_repository, session = _make_service()
        user_id = uuid.uuid4()
        project_id = uuid.uuid4()
        project_repository.count_tasks.return_value = 0

        await service.delete(user_id, project_id)

        project_repository.delete.assert_awaited_once_with(project_id)
        session.commit.assert_awaited_once()

    async def test_delete_checks_task_count_before_deleting(self) -> None:
        service, project_repository, _ = _make_service()
        project_id = uuid.uuid4()
        project_repository.count_tasks.return_value = 0

        await service.delete(uuid.uuid4(), project_id)

        method_names = [call[0] for call in project_repository.mock_calls]
        assert method_names.index("count_tasks") < method_names.index("delete")
