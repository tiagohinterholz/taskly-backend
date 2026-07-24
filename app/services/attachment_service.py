import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.attachment import Attachment
from app.repositories.attachment_repository import AttachmentRepository
from app.repositories.task_repository import TaskRepository
from app.services.task_service import TaskNotFoundError
from app.storage.backend import StorageBackend, StorageError

_MAX_ATTACHMENT_SIZE_BYTES = 10 * 1024 * 1024  # 10MB (ATT-02)


class AttachmentTooLargeError(Exception):
    """Raised by upload() when the file exceeds the 10MB limit (ATT-02) —
    checked before the StorageBackend is ever called.
    """


class AttachmentNotFoundError(Exception):
    """Raised by delete() when attachment_id doesn't exist or doesn't belong
    to the given task.
    """


class AttachmentStorageError(Exception):
    """Raised when the StorageBackend fails to save/delete the file (ATT-01
    AC3) — the router maps this to a 5xx without touching any other data.
    """


class AttachmentService:
    """Attachment business rules: verifying the task belongs to the given
    project, the 10MB size limit, and delegating persistence to
    StorageBackend + AttachmentRepository. Repositories only flush()
    (AD-011) — this service owns the transaction boundary.

    Project ownership (does project_id belong to the caller?) is verified
    once by the router before this service is ever called — the router
    always has project_id from the nested URL
    (/projects/{project_id}/tasks/{task_id}/attachments). This service only
    has to confirm task_id actually belongs to that project_id (defense in
    depth against a task_id from a different project slipping through),
    the same pattern TaskService.update/delete use.
    """

    def __init__(
        self,
        session: AsyncSession,
        attachment_repository: AttachmentRepository,
        task_repository: TaskRepository,
        storage_backend: StorageBackend,
        max_size_bytes: int = _MAX_ATTACHMENT_SIZE_BYTES,
    ) -> None:
        self._session = session
        self._attachment_repository = attachment_repository
        self._task_repository = task_repository
        self._storage_backend = storage_backend
        self._max_size_bytes = max_size_bytes

    async def upload(
        self,
        project_id: uuid.UUID,
        task_id: uuid.UUID,
        filename: str,
        content: bytes,
        content_type: str,
    ) -> Attachment:
        await self._verify_task_in_project(project_id, task_id)

        if len(content) > self._max_size_bytes:
            raise AttachmentTooLargeError(len(content))

        storage_key_input = f"{task_id}/{uuid.uuid4()}-{filename}"
        try:
            storage_key = self._storage_backend.save(storage_key_input, content, content_type)
        except StorageError as exc:
            raise AttachmentStorageError(str(exc)) from exc

        attachment = await self._attachment_repository.create(
            task_id=task_id,
            filename=filename,
            storage_key=storage_key,
            content_type=content_type,
            size_bytes=len(content),
        )
        await self._session.commit()
        return attachment

    async def delete(self, project_id: uuid.UUID, task_id: uuid.UUID, attachment_id: uuid.UUID) -> None:
        await self._verify_task_in_project(project_id, task_id)

        attachment = await self._attachment_repository.get_by_id(attachment_id)
        if attachment is None or attachment.task_id != task_id:
            raise AttachmentNotFoundError(attachment_id)

        try:
            self._storage_backend.delete(attachment.storage_key)
        except StorageError as exc:
            raise AttachmentStorageError(str(exc)) from exc

        await self._attachment_repository.delete(attachment_id)
        await self._session.commit()

    async def _verify_task_in_project(self, project_id: uuid.UUID, task_id: uuid.UUID) -> None:
        """404 (via TaskNotFoundError) if task_id doesn't exist or doesn't
        belong to project_id — never reveals which case it was (ISO-02).
        """
        task = await self._task_repository.get_for_project(task_id, project_id)
        if task is None:
            raise TaskNotFoundError(task_id)
