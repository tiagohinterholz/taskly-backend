from sqlalchemy import select

from app.models.user import User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    """Data access for User. The only layer that talks SQLAlchemy for users."""

    model = User

    async def create(self, email: str, password_hash: str) -> User:
        user = User(email=email, password_hash=password_hash)
        self._session.add(user)
        await self._session.flush()
        return user

    async def get_by_email(self, email: str) -> User | None:
        result = await self._session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()
