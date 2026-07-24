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

    async def list_for_user(self, user_id: uuid.UUID) -> list[Project]:
        result = await self._session.execute(select(Project).where(Project.user_id == user_id))
        return list(result.scalars().all())

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
