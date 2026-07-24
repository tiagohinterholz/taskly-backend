import os
from collections.abc import AsyncGenerator

import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import async_session_factory
from app.core.security import JWTService
from app.models.user import User
from app.repositories.user_repository import UserRepository


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Yields a request-scoped AsyncSession. Routers depend on this instead of
    importing the session factory directly, so tests can override it.
    """
    async with async_session_factory() as session:
        yield session


def get_jwt_service() -> JWTService:
    return JWTService(secret=os.environ["JWT_SECRET"])


async def get_current_user(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    jwt_service: JWTService = Depends(get_jwt_service),
) -> User:
    """Reads the `access_token` cookie, decodes it via JWTService, and loads
    the User. Raises HTTPException(401) if the cookie is missing, the token
    is invalid/expired, or the user no longer exists (ISO-01).
    """
    token = request.cookies.get("access_token")
    if token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated")

    try:
        user_id = jwt_service.decode(token)
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid or expired session"
        ) from exc

    user = await UserRepository(session).get_by_id(user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid or expired session"
        )
    return user
