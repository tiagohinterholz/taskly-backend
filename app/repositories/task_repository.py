import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, update

from app.models.task import Task, TaskStatus
from app.repositories.base import BaseRepository


class TaskRepository(BaseRepository[Task]):
    """Data access for Task. The only layer that talks SQLAlchemy for tasks.

    `get_by_id` (inherited from BaseRepository) is an *unscoped* lookup: no
    project_id filter. Every task/attachment route is now nested under
    /projects/{project_id}/..., so callers verifying a task belongs to a
    specific project use `get_for_project` instead — `get_by_id` currently
    has no caller in this codebase but is kept as generic inherited
    capability (other repositories still use it).
    """

    model = Task

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

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        limit: int,
        offset: int,
        status: TaskStatus | None = None,
    ) -> tuple[list[Task], int]:
        """Paginated listing (AD-021): returns the requested page alongside
        the total matching count (ignoring `limit`/`offset`), so callers can
        build a `Page[TaskOut]` envelope. `status`, when given, narrows both
        the page and the total to tasks in that status. Ordered by
        `created_at` (with `id` as a tiebreaker) for stable page boundaries.
        """
        conditions = [Task.project_id == project_id]
        if status is not None:
            conditions.append(Task.status == status)

        count_result = await self._session.execute(
            select(func.count()).select_from(Task).where(*conditions)
        )
        total = count_result.scalar_one()

        result = await self._session.execute(
            select(Task)
            .where(*conditions)
            .order_by(Task.created_at, Task.id)
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all()), total

    async def get_for_project(self, task_id: uuid.UUID, project_id: uuid.UUID) -> Task | None:
        result = await self._session.execute(
            select(Task).where(Task.id == task_id, Task.project_id == project_id)
        )
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
