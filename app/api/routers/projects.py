import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user, get_db_session
from app.api.pagination import Page, PaginationParams
from app.models.project import Project
from app.models.user import User
from app.repositories.project_repository import ProjectRepository
from app.services.project_service import ProjectHasTasksError, ProjectNotFoundError, ProjectService

router = APIRouter(prefix="/projects", tags=["projects"])


class ProjectCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class ProjectRenameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    group_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


def _get_project_service(session: AsyncSession = Depends(get_db_session)) -> ProjectService:
    return ProjectService(session=session, project_repository=ProjectRepository(session))


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
async def create_project(
    payload: ProjectCreateRequest,
    user: User = Depends(get_current_user),
    project_service: ProjectService = Depends(_get_project_service),
) -> Project:
    return await project_service.create(user.id, payload.name)


@router.get("", response_model=Page[ProjectOut])
async def list_projects(
    group_id: uuid.UUID | None = Query(default=None),
    pagination: PaginationParams = Depends(),
    user: User = Depends(get_current_user),
    project_service: ProjectService = Depends(_get_project_service),
) -> Page[ProjectOut]:
    projects, total = await project_service.list_for_user(
        user.id, pagination.limit, pagination.offset, group_id=group_id
    )
    return Page[ProjectOut](
        items=projects, total=total, limit=pagination.limit, offset=pagination.offset
    )


@router.patch("/{project_id}", response_model=ProjectOut)
async def rename_project(
    project_id: uuid.UUID,
    payload: ProjectRenameRequest,
    user: User = Depends(get_current_user),
    project_service: ProjectService = Depends(_get_project_service),
) -> Project:
    try:
        return await project_service.rename(user.id, project_id, payload.name)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="project not found") from exc


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: uuid.UUID,
    user: User = Depends(get_current_user),
    project_service: ProjectService = Depends(_get_project_service),
) -> None:
    try:
        await project_service.delete(user.id, project_id)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="project not found") from exc
    except ProjectHasTasksError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="remova as tarefas antes de excluir o projeto",
        ) from exc
