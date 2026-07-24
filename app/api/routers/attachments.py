import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user, get_db_session
from app.api.routers.tasks import AttachmentOut
from app.models.attachment import Attachment
from app.models.user import User
from app.repositories.attachment_repository import AttachmentRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.task_repository import TaskRepository
from app.services.attachment_service import (
    AttachmentNotFoundError,
    AttachmentService,
    AttachmentStorageError,
    AttachmentTooLargeError,
)
from app.services.task_service import TaskNotFoundError
from app.storage.backend import StorageBackend, get_storage_backend

router = APIRouter(tags=["attachments"])


def _get_attachment_service(
    session: AsyncSession = Depends(get_db_session),
    storage_backend: StorageBackend = Depends(get_storage_backend),
) -> AttachmentService:
    return AttachmentService(
        session=session,
        attachment_repository=AttachmentRepository(session),
        task_repository=TaskRepository(session),
        project_repository=ProjectRepository(session),
        storage_backend=storage_backend,
    )


@router.post(
    "/tasks/{task_id}/attachments", response_model=AttachmentOut, status_code=status.HTTP_201_CREATED
)
async def upload_attachment(
    task_id: uuid.UUID,
    file: UploadFile,
    user: User = Depends(get_current_user),
    attachment_service: AttachmentService = Depends(_get_attachment_service),
) -> Attachment:
    content = await file.read()
    try:
        return await attachment_service.upload(
            user.id,
            task_id,
            filename=file.filename or "unnamed",
            content=content,
            content_type=file.content_type or "application/octet-stream",
        )
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found") from exc
    except AttachmentTooLargeError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="file exceeds the 10MB limit",
        ) from exc
    except AttachmentStorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="failed to store attachment"
        ) from exc


@router.delete("/tasks/{task_id}/attachments/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_attachment(
    task_id: uuid.UUID,
    attachment_id: uuid.UUID,
    user: User = Depends(get_current_user),
    attachment_service: AttachmentService = Depends(_get_attachment_service),
) -> None:
    try:
        await attachment_service.delete(user.id, task_id, attachment_id)
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found") from exc
    except AttachmentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="attachment not found"
        ) from exc
    except AttachmentStorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="failed to delete attachment"
        ) from exc
