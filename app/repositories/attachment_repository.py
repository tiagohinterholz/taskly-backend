import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.attachment import Attachment


class AttachmentRepository:
    """Data access for Attachment. The only layer that talks SQLAlchemy for attachments."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        task_id: uuid.UUID,
        filename: str,
        storage_key: str,
        content_type: str,
        size_bytes: int,
    ) -> Attachment:
        attachment = Attachment(
            task_id=task_id,
            filename=filename,
            storage_key=storage_key,
            content_type=content_type,
            size_bytes=size_bytes,
        )
        self._session.add(attachment)
        await self._session.flush()
        return attachment

    async def get_by_id(self, attachment_id: uuid.UUID) -> Attachment | None:
        result = await self._session.execute(
            select(Attachment).where(Attachment.id == attachment_id)
        )
        return result.scalar_one_or_none()

    async def delete(self, attachment_id: uuid.UUID) -> None:
        await self._session.execute(delete(Attachment).where(Attachment.id == attachment_id))
        await self._session.flush()

    async def list_for_tasks(self, task_ids: list[uuid.UUID]) -> list[Attachment]:
        """Batch fetch: attachments for *all* given task ids in a single
        query. Task responses embed their attachments (per the frontend
        contract), so callers building a list of N tasks must call this once
        with all N ids and group the results by task_id in Python — never
        loop and call this once per task (that would be N+1). A single-task
        detail response can call this with a one-element list; that's N=1,
        not N+1.
        """
        if not task_ids:
            return []
        result = await self._session.execute(
            select(Attachment).where(Attachment.task_id.in_(task_ids))
        )
        return list(result.scalars().all())
