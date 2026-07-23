import uuid

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project
from app.models.task import Task


class ProjectRepository:
    """Data access for Project. The only layer that talks SQLAlchemy for projects."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, user_id: uuid.UUID, name: str) -> Project:
        project = Project(user_id=user_id, name=name)
        self._session.add(project)
        await self._session.flush()
        return project

    async def list_for_user(self, user_id: uuid.UUID) -> list[Project]:
        result = await self._session.execute(select(Project).where(Project.user_id == user_id))
        return list(result.scalars().all())

    async def rename(self, project_id: uuid.UUID, name: str) -> Project:
        await self._session.execute(
            update(Project).where(Project.id == project_id).values(name=name)
        )
        await self._session.flush()
        result = await self._session.execute(select(Project).where(Project.id == project_id))
        return result.scalar_one()

    async def delete(self, project_id: uuid.UUID) -> None:
        await self._session.execute(delete(Project).where(Project.id == project_id))
        await self._session.flush()

    async def count_tasks(self, project_id: uuid.UUID) -> int:
        result = await self._session.execute(
            select(func.count()).select_from(Task).where(Task.project_id == project_id)
        )
        return result.scalar_one()
