import uuid
from collections import defaultdict
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user, get_db_session
from app.api.pagination import Page, PaginationParams
from app.models.attachment import Attachment
from app.models.task import Task, TaskStatus
from app.models.user import User
from app.repositories.attachment_repository import AttachmentRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.task_repository import TaskRepository
from app.services.task_service import (
    TagTooLongError,
    TaskAttachmentCleanupError,
    TaskNotFoundError,
    TaskService,
    TaskTitleRequiredError,
)
from app.storage.backend import StorageBackend, get_storage_backend

router = APIRouter(tags=["tasks"])


class TaskCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    short_description: str | None = None
    full_description: str | None = None
    due_at: datetime | None = None
    tags: list[str] = Field(default_factory=list)


class TaskUpdateRequest(BaseModel):
    """All fields optional; only keys the client actually sent are applied
    (see `.model_dump(exclude_unset=True)` in the PATCH handler) — so a task
    can be updated one field at a time (TASK-02) without clobbering the rest.
    """

    title: str | None = Field(default=None, min_length=1, max_length=200)
    short_description: str | None = None
    full_description: str | None = None
    due_at: datetime | None = None
    tags: list[str] | None = None
    status: TaskStatus | None = None


class AttachmentOut(BaseModel):
    id: uuid.UUID
    filename: str
    storage_key: str
    content_type: str
    size_bytes: int
    created_at: datetime
    url: str


class TaskOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    title: str
    short_description: str | None
    full_description: str | None
    due_at: datetime | None
    tags: list[str]
    status: TaskStatus
    created_at: datetime
    updated_at: datetime
    attachments: list[AttachmentOut]


def _to_attachment_out(attachment: Attachment, project_id: uuid.UUID) -> AttachmentOut:
    """Builds the response DTO for a single attachment. `url` always points
    at this API's own authenticated download endpoint (AD-016) — never a
    raw storage reference — regardless of which storage backend is
    configured; the download route itself decides redirect vs. proxy.
    """
    return AttachmentOut(
        id=attachment.id,
        filename=attachment.filename,
        storage_key=attachment.storage_key,
        content_type=attachment.content_type,
        size_bytes=attachment.size_bytes,
        created_at=attachment.created_at,
        url=f"/projects/{project_id}/tasks/{attachment.task_id}/attachments/{attachment.id}/download",
    )


def _to_task_out(task: Task, attachments: list[Attachment]) -> TaskOut:
    return TaskOut(
        id=task.id,
        project_id=task.project_id,
        title=task.title,
        short_description=task.short_description,
        full_description=task.full_description,
        due_at=task.due_at,
        tags=task.tags,
        status=task.status,
        created_at=task.created_at,
        updated_at=task.updated_at,
        attachments=[_to_attachment_out(a, task.project_id) for a in attachments],
    )


def _get_task_service(
    session: AsyncSession = Depends(get_db_session),
    storage_backend: StorageBackend = Depends(get_storage_backend),
) -> TaskService:
    return TaskService(
        session=session,
        task_repository=TaskRepository(session),
        attachment_repository=AttachmentRepository(session),
        storage_backend=storage_backend,
    )


async def _get_accessible_project_id(
    project_id: uuid.UUID, user_id: uuid.UUID, session: AsyncSession
) -> uuid.UUID:
    """Every task/attachment route is nested under /projects/{project_id}/...,
    so project_id is always available straight from the URL. This verifies
    the current user can access it -- direct owner OR member of the group
    it's linked to (AD-018) -- once per request, before any task-level work
    happens. 404 otherwise (ISO-02, unchanged for non-accessible projects).
    """
    project = await ProjectRepository(session).get_accessible_for_user(project_id, user_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="project not found")
    return project.id


@router.post(
    "/projects/{project_id}/tasks", response_model=TaskOut, status_code=status.HTTP_201_CREATED
)
async def create_task(
    project_id: uuid.UUID,
    payload: TaskCreateRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
    task_service: TaskService = Depends(_get_task_service),
) -> TaskOut:
    await _get_accessible_project_id(project_id, user.id, session)
    try:
        task = await task_service.create(
            project_id,
            payload.title,
            short_description=payload.short_description,
            full_description=payload.full_description,
            due_at=payload.due_at,
            tags=payload.tags,
        )
    except TaskTitleRequiredError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="title is required") from exc
    except TagTooLongError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"tag exceeds 20 characters: {exc.tag!r}",
        ) from exc
    # A brand-new task has no attachments yet; no query needed.
    return _to_task_out(task, [])


@router.get("/projects/{project_id}/tasks", response_model=Page[TaskOut])
async def list_tasks(
    project_id: uuid.UUID,
    status_filter: TaskStatus | None = Query(default=None, alias="status"),
    pagination: PaginationParams = Depends(),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
    task_service: TaskService = Depends(_get_task_service),
) -> Page[TaskOut]:
    await _get_accessible_project_id(project_id, user.id, session)
    tasks, total = await task_service.list_for_project(
        project_id, pagination.limit, pagination.offset, status=status_filter
    )

    # Batch-fetch attachments for every returned task in a single query and
    # group them in Python — avoids N+1 (one attachment query per task).
    attachments = await AttachmentRepository(session).list_for_tasks([t.id for t in tasks])
    attachments_by_task: dict[uuid.UUID, list[Attachment]] = defaultdict(list)
    for attachment in attachments:
        attachments_by_task[attachment.task_id].append(attachment)

    items = [_to_task_out(task, attachments_by_task.get(task.id, [])) for task in tasks]
    return Page[TaskOut](items=items, total=total, limit=pagination.limit, offset=pagination.offset)


@router.patch("/projects/{project_id}/tasks/{task_id}", response_model=TaskOut)
async def update_task(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    payload: TaskUpdateRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
    task_service: TaskService = Depends(_get_task_service),
) -> TaskOut:
    await _get_accessible_project_id(project_id, user.id, session)
    fields = payload.model_dump(exclude_unset=True)
    try:
        task = await task_service.update(project_id, task_id, **fields)
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found") from exc
    except TaskTitleRequiredError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="title is required") from exc
    except TagTooLongError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"tag exceeds 20 characters: {exc.tag!r}",
        ) from exc

    # Single task detail response: one attachments-by-task_id query (N=1),
    # not the batched form above — there's only one task here.
    attachments = await AttachmentRepository(session).list_for_tasks([task.id])
    return _to_task_out(task, attachments)


@router.delete("/projects/{project_id}/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
    task_service: TaskService = Depends(_get_task_service),
) -> None:
    await _get_accessible_project_id(project_id, user.id, session)
    try:
        await task_service.delete(project_id, task_id)
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found") from exc
    except TaskAttachmentCleanupError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="failed to remove task attachments"
        ) from exc
