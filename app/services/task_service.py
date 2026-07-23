import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import Task, TaskStatus
from app.repositories.task_repository import TaskRepository

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


class TaskService:
    """Task business rules: creation (title required, tags validated),
    free-form partial updates (any field, incl. unrestricted status
    transitions per STAT-01), listing, and deletion. Repositories only
    flush() (AD-011) — this service owns the transaction boundary.
    """

    def __init__(self, session: AsyncSession, task_repository: TaskRepository) -> None:
        self._session = session
        self._task_repository = task_repository

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

    async def list_for_project(self, project_id: uuid.UUID) -> list[Task]:
        return await self._task_repository.list_for_project(project_id)

    async def update(self, task_id: uuid.UUID, **fields: Any) -> Task:
        if "title" in fields:
            self._validate_title(fields["title"])
        if "tags" in fields:
            self._validate_tags(fields["tags"])
        task = await self._task_repository.update(task_id, **fields)
        await self._session.commit()
        return task

    async def delete(self, task_id: uuid.UUID) -> None:
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
