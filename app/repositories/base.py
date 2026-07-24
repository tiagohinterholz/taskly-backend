import uuid
from typing import Generic, TypeVar

from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import Base

ModelType = TypeVar("ModelType", bound=Base)


class BaseRepository(Generic[ModelType]):
    """Shared data-access plumbing for repositories: session storage plus the
    generic single-PK `get_by_id` / `delete` shape that's identical across
    entities with a UUID `id` primary key. Subclasses set the `model` class
    attribute to their SQLAlchemy model.

    Entity-specific access (ownership-scoped lookups, multi-field creates,
    Core-style updates, etc.) stays on the concrete repository classes —
    this base only covers the byte-for-byte-identical plumbing.
    """

    model: type[ModelType]

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, id: uuid.UUID) -> ModelType | None:
        result = await self._session.execute(select(self.model).where(self.model.id == id))
        return result.scalar_one_or_none()

    async def delete(self, id: uuid.UUID) -> None:
        await self._session.execute(sa_delete(self.model).where(self.model.id == id))
        await self._session.flush()
