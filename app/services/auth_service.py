import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import JWTService, PasswordHasher
from app.models.user import User
from app.repositories.refresh_token_repository import RefreshTokenRepository
from app.repositories.user_repository import UserRepository

_ACCESS_TOKEN_TTL = timedelta(minutes=15)
_REFRESH_TOKEN_TTL = timedelta(days=7)
_RATE_LIMIT_MAX_ATTEMPTS = 5
_RATE_LIMIT_WINDOW = timedelta(minutes=15)


@dataclass(frozen=True)
class TokenPair:
    """A newly issued access token (JWT) + opaque refresh token pair."""

    access_token: str
    refresh_token: str


class EmailAlreadyRegisteredError(Exception):
    """Raised by register() when the email is already taken."""


class InvalidCredentialsError(Exception):
    """Raised by authenticate() for any login failure (unknown email OR wrong
    password) — same exception either way so the router can't leak which one
    was wrong.
    """


class InvalidRefreshTokenError(Exception):
    """Raised by refresh() when the token is unknown, revoked, or expired."""


class RateLimitExceededError(Exception):
    """Raised by authenticate() when the failed-attempt limit for an email
    has been exceeded within the rate-limit window.
    """


class AuthService:
    """Auth business rules: registration, login, refresh rotation, logout,
    login rate limiting. Repositories only flush() (AD-011) — this service
    owns the transaction boundary and commits/rolls back explicitly.
    """

    def __init__(
        self,
        session: AsyncSession,
        user_repository: UserRepository,
        refresh_token_repository: RefreshTokenRepository,
        jwt_service: JWTService,
        access_token_ttl: timedelta = _ACCESS_TOKEN_TTL,
        refresh_token_ttl: timedelta = _REFRESH_TOKEN_TTL,
    ) -> None:
        self._session = session
        self._user_repository = user_repository
        self._refresh_token_repository = refresh_token_repository
        self._jwt_service = jwt_service
        self._access_token_ttl = access_token_ttl
        self._refresh_token_ttl = refresh_token_ttl
        self._failed_attempts: dict[str, list[datetime]] = {}

    async def register(self, email: str, password: str) -> User:
        password_hash = PasswordHasher.hash(password)
        try:
            user = await self._user_repository.create(email, password_hash)
        except IntegrityError as exc:
            await self._session.rollback()
            raise EmailAlreadyRegisteredError(email) from exc
        await self._session.commit()
        return user

    async def authenticate(self, email: str, password: str) -> TokenPair:
        self._check_rate_limit(email)

        user = await self._user_repository.get_by_email(email)
        if user is None or not PasswordHasher.verify(password, user.password_hash):
            self._record_failed_attempt(email)
            raise InvalidCredentialsError()

        self._failed_attempts.pop(email, None)
        token_pair = await self._issue_token_pair(user.id)
        await self._session.commit()
        return token_pair

    async def refresh(self, refresh_token: str) -> TokenPair:
        token_hash = self._hash_token(refresh_token)
        record = await self._refresh_token_repository.get_by_hash(token_hash)
        now = datetime.now(timezone.utc)
        if record is None or record.revoked_at is not None or record.expires_at < now:
            raise InvalidRefreshTokenError()

        await self._refresh_token_repository.revoke(record.id)
        token_pair = await self._issue_token_pair(record.user_id)
        await self._session.commit()
        return token_pair

    async def logout(self, refresh_token: str) -> None:
        token_hash = self._hash_token(refresh_token)
        record = await self._refresh_token_repository.get_by_hash(token_hash)
        if record is None:
            return
        await self._refresh_token_repository.revoke(record.id)
        await self._session.commit()

    async def _issue_token_pair(self, user_id: uuid.UUID) -> TokenPair:
        access_token = self._jwt_service.encode(user_id, ttl=self._access_token_ttl)
        refresh_token_plain = secrets.token_urlsafe(32)
        token_hash = self._hash_token(refresh_token_plain)
        expires_at = datetime.now(timezone.utc) + self._refresh_token_ttl
        await self._refresh_token_repository.create(user_id, token_hash, expires_at)
        return TokenPair(access_token=access_token, refresh_token=refresh_token_plain)

    @staticmethod
    def _hash_token(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def _check_rate_limit(self, email: str) -> None:
        now = datetime.now(timezone.utc)
        attempts = [t for t in self._failed_attempts.get(email, []) if now - t < _RATE_LIMIT_WINDOW]
        self._failed_attempts[email] = attempts
        if len(attempts) >= _RATE_LIMIT_MAX_ATTEMPTS:
            raise RateLimitExceededError(email)

    def _record_failed_attempt(self, email: str) -> None:
        self._failed_attempts.setdefault(email, []).append(datetime.now(timezone.utc))
