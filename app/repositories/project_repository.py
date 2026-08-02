import uuid

from sqlalchemy import func, select, update

from app.models.project import Project
from app.models.task import Task
from app.repositories.base import BaseRepository


class ProjectRepository(BaseRepository[Project]):
    """Data access for Project. The only layer that talks SQLAlchemy for projects."""

    model = Project

    async def create(self, user_id: uuid.UUID, name: str) -> Project:
        project = Project(user_id=user_id, name=name)
        self._session.add(project)
        await self._session.flush()
        return project

    async def list_for_user(
        self, user_id: uuid.UUID, limit: int, offset: int
    ) -> tuple[list[Project], int]:
        """Paginated listing (AD-021): returns the requested page alongside
        the total matching count (ignoring `limit`/`offset`), so callers can
        build a `Page[ProjectOut]` envelope. Ordered by `created_at` (with
        `id` as a tiebreaker) so the page boundaries are stable across calls.

        Note: strict owner-only, matching `get_for_user`. `groups-rbac`
        (T7, not yet implemented) will rename this to
        `list_accessible_for_user` and expand the WHERE clause to include
        group-accessible projects — this method's pagination logic carries
        forward unchanged into that rename.
        """
        count_result = await self._session.execute(
            select(func.count()).select_from(Project).where(Project.user_id == user_id)
        )
        total = count_result.scalar_one()

        result = await self._session.execute(
            select(Project)
            .where(Project.user_id == user_id)
            .order_by(Project.created_at, Project.id)
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all()), total

    async def get_for_user(self, project_id: uuid.UUID, user_id: uuid.UUID) -> Project | None:
        result = await self._session.execute(
            select(Project).where(Project.id == project_id, Project.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def rename(self, project_id: uuid.UUID, name: str) -> Project:
        await self._session.execute(
            update(Project).where(Project.id == project_id).values(name=name)
        )
        await self._session.flush()
        result = await self._session.execute(select(Project).where(Project.id == project_id))
        return result.scalar_one()

    async def count_tasks(self, project_id: uuid.UUID) -> int:
        result = await self._session.execute(
            select(func.count()).select_from(Task).where(Task.project_id == project_id)
        )
        return result.scalar_one()
