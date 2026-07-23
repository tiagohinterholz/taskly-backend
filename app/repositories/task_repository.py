import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import delete, select
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

    async def update(self, task_id: uuid.UUID, **fields: Any) -> Task:
        result = await self._session.execute(select(Task).where(Task.id == task_id))
        task = result.scalar_one()
        for key, value in fields.items():
            setattr(task, key, value)
        await self._session.flush()
        return task

    async def delete(self, task_id: uuid.UUID) -> None:
        await self._session.execute(delete(Task).where(Task.id == task_id))
        await self._session.flush()
