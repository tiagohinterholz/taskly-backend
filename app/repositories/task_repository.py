import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import Task, TaskStatus


class TaskRepository:
    """Data access for Task. The only layer that talks SQLAlchemy for tasks."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

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
        task = Task(
            project_id=project_id,
            title=title,
            short_description=short_description,
            full_description=full_description,
            due_at=due_at,
            tags=tags if tags is not None else [],
            status=status,
        )
        self._session.add(task)
        await self._session.flush()
        return task

    async def list_for_project(self, project_id: uuid.UUID) -> list[Task]:
        result = await self._session.execute(select(Task).where(Task.project_id == project_id))
        return list(result.scalars().all())

    async def get_for_project(self, task_id: uuid.UUID, project_id: uuid.UUID) -> Task | None:
        result = await self._session.execute(
            select(Task).where(Task.id == task_id, Task.project_id == project_id)
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, task_id: uuid.UUID) -> Task | None:
        """Unscoped lookup (no project_id filter). Used by the flat
        PATCH/DELETE /tasks/{id} routes to discover which project a task
        belongs to, so the router/service can then verify project ownership
        (see get_for_project / ProjectRepository.get_for_user).
        """
        result = await self._session.execute(select(Task).where(Task.id == task_id))
        return result.scalar_one_or_none()

    async def update(self, task_id: uuid.UUID, **fields: Any) -> Task:
        # Core-style UPDATE (not ORM attribute assignment) + a fresh SELECT,
        # mirroring ProjectRepository.rename: mutating a loaded Task's
        # attributes directly and flushing would leave onupdate=func.now()
        # columns (updated_at) expired, and a bare synchronous attribute
        # access on that expired column later (e.g. building a response DTO)
        # raises MissingGreenlet outside of a flush/refresh context. The
        # re-SELECT below both avoids that and refreshes updated_at from the
        # server-computed value.
        if fields:
            await self._session.execute(update(Task).where(Task.id == task_id).values(**fields))
            await self._session.flush()
        result = await self._session.execute(select(Task).where(Task.id == task_id))
        return result.scalar_one()

    async def delete(self, task_id: uuid.UUID) -> None:
        await self._session.execute(delete(Task).where(Task.id == task_id))
        await self._session.flush()
