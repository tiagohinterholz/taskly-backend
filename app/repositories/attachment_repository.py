import uuid

from sqlalchemy import select

from app.models.attachment import Attachment
from app.repositories.base import BaseRepository


class AttachmentRepository(BaseRepository[Attachment]):
    """Data access for Attachment. The only layer that talks SQLAlchemy for attachments."""

    model = Attachment

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
