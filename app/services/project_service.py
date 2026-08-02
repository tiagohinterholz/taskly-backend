import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project
from app.repositories.project_repository import ProjectRepository


class ProjectHasTasksError(Exception):
    """Raised by delete() when the project still has tasks — deletion is blocked."""


class ProjectNotFoundError(Exception):
    """Raised by rename()/delete() when project_id doesn't exist or doesn't
    belong to the given user — the ownership check happens here so a router
    can map it to a 404 without ever revealing the resource exists (ISO-02).
    """


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

    async def list_for_user(
        self, user_id: uuid.UUID, limit: int, offset: int
    ) -> tuple[list[Project], int]:
        return await self._project_repository.list_for_user(user_id, limit, offset)

    async def rename(self, user_id: uuid.UUID, project_id: uuid.UUID, name: str) -> Project:
        owned = await self._project_repository.get_for_user(project_id, user_id)
        if owned is None:
            raise ProjectNotFoundError(project_id)
        project = await self._project_repository.rename(project_id, name)
        await self._session.commit()
        return project

    async def delete(self, user_id: uuid.UUID, project_id: uuid.UUID) -> None:
        owned = await self._project_repository.get_for_user(project_id, user_id)
        if owned is None:
            raise ProjectNotFoundError(project_id)
        task_count = await self._project_repository.count_tasks(project_id)
        if task_count > 0:
            raise ProjectHasTasksError(project_id)
        await self._project_repository.delete(project_id)
        await self._session.commit()
