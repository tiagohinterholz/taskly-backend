import uuid
from datetime import datetime

from sqlalchemy import func, select, update

from app.models.group import GroupInvite
from app.repositories.base import BaseRepository


class GroupInviteRepository(BaseRepository[GroupInvite]):
    """Data access for GroupInvite. The only layer that talks SQLAlchemy for
    group invites — mirrors RefreshTokenRepository's shape line for line.

    Returns rows as-is: whether an invite is usable (not consumed, not
    revoked, not expired) is a business-logic concern for the service
    layer for single-invite lookups (get_by_hash); list_pending is the
    one exception, since "pending" is the query's own definition.
    """

    model = GroupInvite

    async def create(
        self,
        group_id: uuid.UUID,
        created_by_user_id: uuid.UUID,
        token_hash: str,
        expires_at: datetime,
    ) -> GroupInvite:
        invite = GroupInvite(
            group_id=group_id,
            created_by_user_id=created_by_user_id,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        self._session.add(invite)
        await self._session.flush()
        return invite

    async def get_by_hash(self, token_hash: str) -> GroupInvite | None:
        result = await self._session.execute(
            select(GroupInvite).where(GroupInvite.token_hash == token_hash)
        )
        return result.scalar_one_or_none()

    async def list_pending(
        self, group_id: uuid.UUID, limit: int, offset: int
    ) -> tuple[list[GroupInvite], int]:
        """Paginated listing (AD-021) of invites that are neither consumed,
        revoked, nor expired. "Now" is taken from the database's own clock
        (func.now()) rather than Python's datetime.now(), consistent with
        how expires_at/created_at are stored (server_default=func.now()).
        """
        conditions = (
            GroupInvite.group_id == group_id,
            GroupInvite.consumed_at.is_(None),
            GroupInvite.revoked_at.is_(None),
            GroupInvite.expires_at > func.now(),
        )

        count_result = await self._session.execute(
            select(func.count()).select_from(GroupInvite).where(*conditions)
        )
        total = count_result.scalar_one()

        result = await self._session.execute(
            select(GroupInvite)
            .where(*conditions)
            .order_by(GroupInvite.created_at, GroupInvite.id)
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all()), total

    async def mark_consumed(self, invite_id: uuid.UUID) -> None:
        await self._session.execute(
            update(GroupInvite).where(GroupInvite.id == invite_id).values(consumed_at=func.now())
        )
        await self._session.flush()

    async def mark_revoked(self, invite_id: uuid.UUID) -> None:
        await self._session.execute(
            update(GroupInvite).where(GroupInvite.id == invite_id).values(revoked_at=func.now())
        )
        await self._session.flush()
