import uuid
from datetime import datetime

from sqlalchemy import func, select, update

from app.models.refresh_token import RefreshToken
from app.repositories.base import BaseRepository


class RefreshTokenRepository(BaseRepository[RefreshToken]):
    """Data access for RefreshToken. The only layer that talks SQLAlchemy for refresh tokens.

    Returns rows as-is: whether a token is usable (not expired, not revoked)
    is a business-logic concern for the service layer, not this repository.

    No get_by_id / delete here (unlike other repositories): refresh tokens
    are looked up by hash and retired via revoke(), never fetched or removed
    by id.
    """

    model = RefreshToken

    async def create(self, user_id: uuid.UUID, token_hash: str, expires_at: datetime) -> RefreshToken:
        refresh_token = RefreshToken(user_id=user_id, token_hash=token_hash, expires_at=expires_at)
        self._session.add(refresh_token)
        await self._session.flush()
        return refresh_token

    async def get_by_hash(self, token_hash: str) -> RefreshToken | None:
        result = await self._session.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )
        return result.scalar_one_or_none()

    async def revoke(self, refresh_token_id: uuid.UUID) -> None:
        await self._session.execute(
            update(RefreshToken)
            .where(RefreshToken.id == refresh_token_id)
            .values(revoked_at=func.now())
        )
        await self._session.flush()
