import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project
from app.repositories.project_repository import ProjectRepository


class ProjectHasTasksError(Exception):
    """Raised by delete() when the project still has tasks — deletion is blocked."""


class ProjectService:
    """Project business rules: creation, listing, renaming, and the
    delete-block rule (a project with tasks can't be deleted). Repositories
    only flush() (AD-011) — this service owns the transaction boundary.
    """

    def __init__(self, session: AsyncSession, project_repository: ProjectRepository) -> None:
        self._session = session
        self._project_repository = project_repository

    async def create(self, user_id: uuid.UUID, name: str) -> Project:
        project = await self._project_repository.create(user_id, name)
        await self._session.commit()
        return project

    async def list_for_user(self, user_id: uuid.UUID) -> list[Project]:
        return await self._project_repository.list_for_user(user_id)

    async def rename(self, user_id: uuid.UUID, project_id: uuid.UUID, name: str) -> Project:
        project = await self._project_repository.rename(project_id, name)
        await self._session.commit()
        return project

    async def delete(self, user_id: uuid.UUID, project_id: uuid.UUID) -> None:
        task_count = await self._project_repository.count_tasks(project_id)
        if task_count > 0:
            raise ProjectHasTasksError(project_id)
        await self._project_repository.delete(project_id)
        await self._session.commit()
