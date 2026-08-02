import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import Task, TaskStatus
from app.repositories.attachment_repository import AttachmentRepository
from app.repositories.task_repository import TaskRepository
from app.storage.backend import StorageBackend, StorageError

_MAX_TAG_LENGTH = 20


class TaskTitleRequiredError(Exception):
    """Raised by create()/update() when the title is empty or missing —
    title is the only required task field (TASK-01/TASK-02).
    """


class TagTooLongError(Exception):
    """Raised when a tag exceeds the max length — names the offending tag
    so the router can report which one failed (TAG-02).
    """

    def __init__(self, tag: str) -> None:
        self.tag = tag
        super().__init__(f"tag exceeds {_MAX_TAG_LENGTH} characters: {tag!r}")


class TaskNotFoundError(Exception):
    """Raised by update()/delete() when task_id doesn't exist or doesn't
    belong to the given project — the ownership check happens here so a
    router can map it to a 404 without ever revealing the resource exists
    (ISO-02).
    """


class TaskAttachmentCleanupError(Exception):
    """Raised by delete() when StorageBackend fails to remove one of the
    task's attachment files — the router maps this to a 5xx. The task and
    its attachment rows are left untouched so nothing is deleted from the
    database while its files are still orphaned in storage.
    """


class TaskService:
    """Task business rules: creation (title required, tags validated),
    free-form partial updates (any field, incl. unrestricted status
    transitions per STAT-01), listing, and deletion (including removal of
    associated attachment files from storage — TASK-04). Repositories only
    flush() (AD-011) — this service owns the transaction boundary.
    """

    def __init__(
        self,
        session: AsyncSession,
        task_repository: TaskRepository,
        attachment_repository: AttachmentRepository,
        storage_backend: StorageBackend,
    ) -> None:
        self._session = session
        self._task_repository = task_repository
        self._attachment_repository = attachment_repository
        self._storage_backend = storage_backend

    async def create(
        self,
        project_id: uuid.UUID,
        title: str,
        short_description: str | None = None,
        full_description: str | None = None,
        due_at: datetime | None = None,
        tags: list[str] | None = None,
        status: TaskStatus = TaskStatus.NOT_STARTED,
    ) -> Task:
        self._validate_title(title)
        self._validate_tags(tags)
        task = await self._task_repository.create(
            project_id=project_id,
            title=title,
            short_description=short_description,
            full_description=full_description,
            due_at=due_at,
            tags=tags,
            status=status,
        )
        await self._session.commit()
        return task

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        limit: int,
        offset: int,
        status: TaskStatus | None = None,
    ) -> tuple[list[Task], int]:
        return await self._task_repository.list_for_project(
            project_id, limit, offset, status=status
        )

    async def update(self, project_id: uuid.UUID, task_id: uuid.UUID, **fields: Any) -> Task:
        owned = await self._task_repository.get_for_project(task_id, project_id)
        if owned is None:
            raise TaskNotFoundError(task_id)
        if "title" in fields:
            self._validate_title(fields["title"])
        if "tags" in fields:
            self._validate_tags(fields["tags"])
        task = await self._task_repository.update(task_id, **fields)
        await self._session.commit()
        return task

    async def delete(self, project_id: uuid.UUID, task_id: uuid.UUID) -> None:
        owned = await self._task_repository.get_for_project(task_id, project_id)
        if owned is None:
            raise TaskNotFoundError(task_id)

        attachments = await self._attachment_repository.list_for_tasks([task_id])
        for attachment in attachments:
            try:
                self._storage_backend.delete(attachment.storage_key)
            except StorageError as exc:
                raise TaskAttachmentCleanupError(str(exc)) from exc

        await self._task_repository.delete(task_id)
        await self._session.commit()

    @staticmethod
    def _validate_title(title: str | None) -> None:
        if title is None or not title.strip():
            raise TaskTitleRequiredError()

    @staticmethod
    def _validate_tags(tags: list[str] | None) -> None:
        if not tags:
            return
        for tag in tags:
            if len(tag) > _MAX_TAG_LENGTH:
                raise TagTooLongError(tag)
