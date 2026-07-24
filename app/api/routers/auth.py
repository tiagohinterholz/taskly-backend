import os
import re
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db_session, get_jwt_service
from app.core.security import JWTService
from app.models.user import User
from app.repositories.refresh_token_repository import RefreshTokenRepository
from app.repositories.user_repository import UserRepository
from app.services.auth_service import (
    AuthService,
    EmailAlreadyRegisteredError,
    InvalidCredentialsError,
    InvalidRefreshTokenError,
    RateLimitExceededError,
)

router = APIRouter(prefix="/auth", tags=["auth"])

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_ACCESS_COOKIE_MAX_AGE = 15 * 60
_REFRESH_COOKIE_MAX_AGE = 7 * 24 * 60 * 60

# Dev-mode default: cookies are not marked Secure so the browser will still
# send them over plain http://localhost. TODO(production): set
# COOKIE_SECURE=true (env var) once the app is served over HTTPS — full
# CORS/cookie hardening for the real deploy topology is T16's job.
_COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "false").lower() == "true"

# AuthService.authenticate() rate-limits failed login attempts using an
# instance attribute (`_failed_attempts`), but a fresh AuthService is built
# per request (see _get_auth_service) because the DB session is
# request-scoped. This module-level dict is shared across requests and
# injected into each AuthService instance so AUTH-05's 5-attempts/15min
# window is actually enforced across separate HTTP requests, not reset on
# every call.
_shared_failed_attempts: dict[str, list[datetime]] = {}


class RegisterRequest(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def _valid_email(cls, value: str) -> str:
        if not _EMAIL_RE.match(value):
            raise ValueError("invalid email address")
        return value

    @field_validator("password")
    @classmethod
    def _valid_password(cls, value: str) -> str:
        if len(value) < 8:
            raise ValueError("password must be at least 8 characters")
        return value


class LoginRequest(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    created_at: datetime


def _get_auth_service(
    session: AsyncSession = Depends(get_db_session),
    jwt_service: JWTService = Depends(get_jwt_service),
) -> AuthService:
    service = AuthService(
        session=session,
        user_repository=UserRepository(session),
        refresh_token_repository=RefreshTokenRepository(session),
        jwt_service=jwt_service,
    )
    service._failed_attempts = _shared_failed_attempts
    return service


def _set_session_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    response.set_cookie(
        "access_token",
        access_token,
        httponly=True,
        secure=_COOKIE_SECURE,
        samesite="lax",
        max_age=_ACCESS_COOKIE_MAX_AGE,
    )
    response.set_cookie(
        "refresh_token",
        refresh_token,
        httponly=True,
        secure=_COOKIE_SECURE,
        samesite="lax",
        max_age=_REFRESH_COOKIE_MAX_AGE,
    )


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(
    payload: RegisterRequest, auth_service: AuthService = Depends(_get_auth_service)
) -> User:
    try:
        return await auth_service.register(payload.email, payload.password)
    except EmailAlreadyRegisteredError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="email already registered"
        ) from exc


@router.post("/login")
async def login(
    payload: LoginRequest,
    response: Response,
    auth_service: AuthService = Depends(_get_auth_service),
) -> dict[str, str]:
    try:
        token_pair = await auth_service.authenticate(payload.email, payload.password)
    except RateLimitExceededError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="too many login attempts, try again later",
        ) from exc
    except InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid email or password"
        ) from exc
    _set_session_cookies(response, token_pair.access_token, token_pair.refresh_token)
    return {"message": "logged in"}


@router.post("/refresh")
async def refresh(
    request: Request,
    response: Response,
    auth_service: AuthService = Depends(_get_auth_service),
) -> dict[str, str]:
    refresh_token = request.cookies.get("refresh_token")
    if refresh_token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing refresh token")
    try:
        token_pair = await auth_service.refresh(refresh_token)
    except InvalidRefreshTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid or expired refresh token"
        ) from exc
    _set_session_cookies(response, token_pair.access_token, token_pair.refresh_token)
    return {"message": "token refreshed"}


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    auth_service: AuthService = Depends(_get_auth_service),
) -> None:
    refresh_token = request.cookies.get("refresh_token")
    if refresh_token is not None:
        await auth_service.logout(refresh_token)
    response.delete_cookie("access_token")
    response.delete_cookie("refresh_token")
