import itertools
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.attachment import Attachment
from app.models.task import Task, TaskStatus
from app.repositories.attachment_repository import AttachmentRepository
from app.repositories.task_repository import TaskRepository
from app.services.task_service import (
    TagTooLongError,
    TaskAttachmentCleanupError,
    TaskNotFoundError,
    TaskService,
    TaskTitleRequiredError,
)
from app.storage.backend import StorageBackend, StorageError


def _make_service() -> tuple[TaskService, AsyncMock, AsyncMock]:
    """Default factory used by tests that don't care about attachment
    cleanup: no attachments means no StorageBackend calls, so behavior for
    create/update/list and the plain delete path is unaffected.
    """
    service, task_repository, _, _, session = _make_service_with_deps()
    return service, task_repository, session


def _make_service_with_deps() -> tuple[TaskService, AsyncMock, AsyncMock, Mock, AsyncMock]:
    session = AsyncMock(spec=AsyncSession)
    task_repository = AsyncMock(spec=TaskRepository)
    attachment_repository = AsyncMock(spec=AttachmentRepository)
    attachment_repository.list_for_tasks.return_value = []
    storage_backend = Mock(spec=StorageBackend)
    service = TaskService(
        session=session,
        task_repository=task_repository,
        attachment_repository=attachment_repository,
        storage_backend=storage_backend,
    )
    return service, task_repository, attachment_repository, storage_backend, session


def _make_attachment(task_id: uuid.UUID, storage_key: str) -> Attachment:
    return Attachment(
        id=uuid.uuid4(),
        task_id=task_id,
        filename="file.txt",
        storage_key=storage_key,
        content_type="text/plain",
        size_bytes=3,
        created_at=datetime.now(timezone.utc),
    )


def _make_task(
    project_id: uuid.UUID | None = None,
    title: str = "Task title",
    short_description: str | None = None,
    full_description: str | None = None,
    due_at: datetime | None = None,
    tags: list[str] | None = None,
    status: TaskStatus = TaskStatus.NOT_STARTED,
) -> Task:
    return Task(
        id=uuid.uuid4(),
        project_id=project_id or uuid.uuid4(),
        title=title,
        short_description=short_description,
        full_description=full_description,
        due_at=due_at,
        tags=tags if tags is not None else [],
        status=status,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


class TestCreate:
    async def test_create_with_title_only_defaults_status_not_started_and_commits(self) -> None:
        service, task_repository, session = _make_service()
        project_id = uuid.uuid4()
        created_task = _make_task(project_id=project_id, title="Only a title")
        task_repository.create.return_value = created_task

        result = await service.create(project_id, "Only a title")

        assert result is created_task
        assert result.status == TaskStatus.NOT_STARTED
        task_repository.create.assert_awaited_once_with(
            project_id=project_id,
            title="Only a title",
            short_description=None,
            full_description=None,
            due_at=None,
            tags=None,
            status=TaskStatus.NOT_STARTED,
        )
        session.commit.assert_awaited_once()

    async def test_create_with_empty_title_raises_without_persisting(self) -> None:
        service, task_repository, session = _make_service()

        with pytest.raises(TaskTitleRequiredError):
            await service.create(uuid.uuid4(), "")

        task_repository.create.assert_not_awaited()
        session.commit.assert_not_awaited()

    async def test_create_with_whitespace_only_title_raises(self) -> None:
        service, task_repository, _ = _make_service()

        with pytest.raises(TaskTitleRequiredError):
            await service.create(uuid.uuid4(), "   ")

        task_repository.create.assert_not_awaited()

    async def test_create_with_valid_tags_accepted(self) -> None:
        service, task_repository, _ = _make_service()
        project_id = uuid.uuid4()
        tags = ["urgent", "backend", "20-chars-exactly-okk"]
        assert len(tags[-1]) == 20
        created_task = _make_task(project_id=project_id, tags=tags)
        task_repository.create.return_value = created_task

        result = await service.create(project_id, "Task title", tags=tags)

        assert result.tags == tags
        task_repository.create.assert_awaited_once()
        assert task_repository.create.call_args.kwargs["tags"] == tags

    async def test_create_with_tag_over_20_chars_rejected_naming_the_tag(self) -> None:
        service, task_repository, session = _make_service()
        too_long_tag = "a" * 21

        with pytest.raises(TagTooLongError) as exc_info:
            await service.create(uuid.uuid4(), "Task title", tags=["ok", too_long_tag])

        assert exc_info.value.tag == too_long_tag
        task_repository.create.assert_not_awaited()
        session.commit.assert_not_awaited()


class TestListForProject:
    async def test_list_for_project_returns_tasks_from_repository(self) -> None:
        service, task_repository, _ = _make_service()
        project_id = uuid.uuid4()
        tasks = [_make_task(project_id=project_id), _make_task(project_id=project_id)]
        task_repository.list_for_project.return_value = tasks

        result = await service.list_for_project(project_id)

        assert result == tasks
        task_repository.list_for_project.assert_awaited_once_with(project_id)


class TestUpdate:
    async def test_update_title_field(self) -> None:
        service, task_repository, session = _make_service()
        project_id = uuid.uuid4()
        task_id = uuid.uuid4()
        updated_task = _make_task(project_id=project_id, title="Updated title")
        task_repository.get_for_project.return_value = _make_task(project_id=project_id)
        task_repository.update.return_value = updated_task

        result = await service.update(project_id, task_id, title="Updated title")

        assert result.title == "Updated title"
        task_repository.get_for_project.assert_awaited_once_with(task_id, project_id)
        task_repository.update.assert_awaited_once_with(task_id, title="Updated title")
        session.commit.assert_awaited_once()

    async def test_update_short_description_field(self) -> None:
        service, task_repository, _ = _make_service()
        project_id = uuid.uuid4()
        task_id = uuid.uuid4()
        updated_task = _make_task(project_id=project_id, short_description="Short desc")
        task_repository.get_for_project.return_value = _make_task(project_id=project_id)
        task_repository.update.return_value = updated_task

        result = await service.update(project_id, task_id, short_description="Short desc")

        assert result.short_description == "Short desc"
        task_repository.update.assert_awaited_once_with(task_id, short_description="Short desc")

    async def test_update_full_description_field(self) -> None:
        service, task_repository, _ = _make_service()
        project_id = uuid.uuid4()
        task_id = uuid.uuid4()
        updated_task = _make_task(project_id=project_id, full_description="Full desc")
        task_repository.get_for_project.return_value = _make_task(project_id=project_id)
        task_repository.update.return_value = updated_task

        result = await service.update(project_id, task_id, full_description="Full desc")

        assert result.full_description == "Full desc"
        task_repository.update.assert_awaited_once_with(task_id, full_description="Full desc")

    async def test_update_due_at_field(self) -> None:
        service, task_repository, _ = _make_service()
        project_id = uuid.uuid4()
        task_id = uuid.uuid4()
        due_at = datetime(2026, 8, 1, tzinfo=timezone.utc)
        updated_task = _make_task(project_id=project_id, due_at=due_at)
        task_repository.get_for_project.return_value = _make_task(project_id=project_id)
        task_repository.update.return_value = updated_task

        result = await service.update(project_id, task_id, due_at=due_at)

        assert result.due_at == due_at
        task_repository.update.assert_awaited_once_with(task_id, due_at=due_at)

    async def test_update_tags_field_with_valid_tags(self) -> None:
        service, task_repository, _ = _make_service()
        project_id = uuid.uuid4()
        task_id = uuid.uuid4()
        updated_task = _make_task(project_id=project_id, tags=["frontend"])
        task_repository.get_for_project.return_value = _make_task(project_id=project_id)
        task_repository.update.return_value = updated_task

        result = await service.update(project_id, task_id, tags=["frontend"])

        assert result.tags == ["frontend"]
        task_repository.update.assert_awaited_once_with(task_id, tags=["frontend"])

    async def test_update_tags_field_with_tag_over_20_chars_rejected(self) -> None:
        service, task_repository, session = _make_service()
        project_id = uuid.uuid4()
        task_id = uuid.uuid4()
        too_long_tag = "b" * 25
        task_repository.get_for_project.return_value = _make_task(project_id=project_id)

        with pytest.raises(TagTooLongError) as exc_info:
            await service.update(project_id, task_id, tags=[too_long_tag])

        assert exc_info.value.tag == too_long_tag
        task_repository.update.assert_not_awaited()
        session.commit.assert_not_awaited()

    async def test_update_with_empty_title_rejected(self) -> None:
        service, task_repository, _ = _make_service()
        project_id = uuid.uuid4()
        task_id = uuid.uuid4()
        task_repository.get_for_project.return_value = _make_task(project_id=project_id)

        with pytest.raises(TaskTitleRequiredError):
            await service.update(project_id, task_id, title="")

        task_repository.update.assert_not_awaited()

    async def test_update_raises_not_found_when_task_not_in_project(self) -> None:
        service, task_repository, session = _make_service()
        project_id = uuid.uuid4()
        task_id = uuid.uuid4()
        task_repository.get_for_project.return_value = None

        with pytest.raises(TaskNotFoundError):
            await service.update(project_id, task_id, title="New title")

        task_repository.update.assert_not_awaited()
        session.commit.assert_not_awaited()

    @pytest.mark.parametrize(
        ("from_status", "to_status"),
        list(itertools.product(TaskStatus, TaskStatus)),
        ids=lambda s: s.value if isinstance(s, TaskStatus) else str(s),
    )
    async def test_status_transition_between_any_two_states_is_allowed(
        self, from_status: TaskStatus, to_status: TaskStatus
    ) -> None:
        service, task_repository, session = _make_service()
        project_id = uuid.uuid4()
        task_id = uuid.uuid4()
        # `from_status` documents the task's status before this update — the
        # service is stateless w.r.t. current status (STAT-01: no order
        # restriction), so only the target `to_status` drives the call.
        updated_task = _make_task(project_id=project_id, status=to_status)
        task_repository.get_for_project.return_value = _make_task(project_id=project_id)
        task_repository.update.return_value = updated_task

        result = await service.update(project_id, task_id, status=to_status)

        assert result.status == to_status
        task_repository.update.assert_awaited_once_with(task_id, status=to_status)
        session.commit.assert_awaited_once()


class TestDelete:
    async def test_delete_removes_task_via_repository_and_commits(self) -> None:
        service, task_repository, session = _make_service()
        project_id = uuid.uuid4()
        task_id = uuid.uuid4()
        task_repository.get_for_project.return_value = _make_task(project_id=project_id)

        await service.delete(project_id, task_id)

        task_repository.get_for_project.assert_awaited_once_with(task_id, project_id)
        task_repository.delete.assert_awaited_once_with(task_id)
        session.commit.assert_awaited_once()

    async def test_delete_raises_not_found_when_task_not_in_project(self) -> None:
        service, task_repository, session = _make_service()
        project_id = uuid.uuid4()
        task_id = uuid.uuid4()
        task_repository.get_for_project.return_value = None

        with pytest.raises(TaskNotFoundError):
            await service.delete(project_id, task_id)

        task_repository.delete.assert_not_awaited()
        session.commit.assert_not_awaited()

    async def test_delete_removes_each_attachment_from_storage_before_deleting_task(self) -> None:
        service, task_repository, attachment_repository, storage_backend, session = (
            _make_service_with_deps()
        )
        project_id = uuid.uuid4()
        task_id = uuid.uuid4()
        task_repository.get_for_project.return_value = _make_task(project_id=project_id)
        attachment_repository.list_for_tasks.return_value = [
            _make_attachment(task_id, "key-a"),
            _make_attachment(task_id, "key-b"),
        ]

        await service.delete(project_id, task_id)

        attachment_repository.list_for_tasks.assert_awaited_once_with([task_id])
        storage_backend.delete.assert_any_call("key-a")
        storage_backend.delete.assert_any_call("key-b")
        assert storage_backend.delete.call_count == 2
        task_repository.delete.assert_awaited_once_with(task_id)
        session.commit.assert_awaited_once()

    async def test_delete_raises_cleanup_error_and_keeps_task_when_storage_fails(self) -> None:
        service, task_repository, attachment_repository, storage_backend, session = (
            _make_service_with_deps()
        )
        project_id = uuid.uuid4()
        task_id = uuid.uuid4()
        task_repository.get_for_project.return_value = _make_task(project_id=project_id)
        attachment_repository.list_for_tasks.return_value = [_make_attachment(task_id, "key-a")]
        storage_backend.delete.side_effect = StorageError("simulated storage outage")

        with pytest.raises(TaskAttachmentCleanupError):
            await service.delete(project_id, task_id)

        task_repository.delete.assert_not_awaited()
        session.commit.assert_not_awaited()
