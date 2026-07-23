import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import JWTService, PasswordHasher
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.repositories.refresh_token_repository import RefreshTokenRepository
from app.repositories.user_repository import UserRepository
from app.services.auth_service import (
    AuthService,
    EmailAlreadyRegisteredError,
    InvalidCredentialsError,
    InvalidRefreshTokenError,
    RateLimitExceededError,
    TokenPair,
)


def _make_service(
    user_repository: AsyncMock | None = None,
    refresh_token_repository: AsyncMock | None = None,
    session: AsyncMock | None = None,
) -> tuple[AuthService, AsyncMock, AsyncMock, AsyncMock]:
    session = session or AsyncMock(spec=AsyncSession)
    user_repository = user_repository or AsyncMock(spec=UserRepository)
    refresh_token_repository = refresh_token_repository or AsyncMock(spec=RefreshTokenRepository)
    jwt_service = JWTService(secret="test-secret")
    service = AuthService(
        session=session,
        user_repository=user_repository,
        refresh_token_repository=refresh_token_repository,
        jwt_service=jwt_service,
    )
    return service, user_repository, refresh_token_repository, session


def _make_user(email: str = "user@example.com", password: str = "correct-password") -> User:
    return User(
        id=uuid.uuid4(),
        email=email,
        password_hash=PasswordHasher.hash(password),
        created_at=datetime.now(timezone.utc),
    )


def _make_refresh_token_record(
    user_id: uuid.UUID | None = None,
    revoked_at: datetime | None = None,
    expires_at: datetime | None = None,
) -> RefreshToken:
    return RefreshToken(
        id=uuid.uuid4(),
        user_id=user_id or uuid.uuid4(),
        token_hash="irrelevant-for-tests",
        expires_at=expires_at or (datetime.now(timezone.utc) + timedelta(days=7)),
        revoked_at=revoked_at,
        created_at=datetime.now(timezone.utc),
    )


class TestRegister:
    async def test_register_creates_user_with_hashed_password_and_commits(self) -> None:
        service, user_repository, _, session = _make_service()
        created_user = _make_user()
        user_repository.create.return_value = created_user

        result = await service.register("user@example.com", "a-plain-password")

        assert result is created_user
        call_args = user_repository.create.call_args
        assert call_args.args[0] == "user@example.com"
        assert call_args.args[1] != "a-plain-password"  # AUTH-01: password stored hashed, never plain
        assert PasswordHasher.verify("a-plain-password", call_args.args[1]) is True
        session.commit.assert_awaited_once()

    async def test_register_duplicate_email_raises_domain_error_and_rolls_back(self) -> None:
        service, user_repository, _, session = _make_service()
        user_repository.create.side_effect = IntegrityError("stmt", {}, Exception("unique violation"))

        with pytest.raises(EmailAlreadyRegisteredError):
            await service.register("dup@example.com", "a-plain-password")

        session.rollback.assert_awaited_once()
        session.commit.assert_not_awaited()


class TestAuthenticate:
    async def test_authenticate_correct_credentials_returns_token_pair_and_commits(self) -> None:
        service, user_repository, refresh_token_repository, session = _make_service()
        user = _make_user(email="user@example.com", password="correct-password")
        user_repository.get_by_email.return_value = user

        result = await service.authenticate("user@example.com", "correct-password")

        assert isinstance(result, TokenPair)
        assert result.access_token
        assert result.refresh_token
        refresh_token_repository.create.assert_awaited_once()
        assert refresh_token_repository.create.call_args.args[0] == user.id
        session.commit.assert_awaited_once()

    async def test_authenticate_wrong_password_raises_invalid_credentials(self) -> None:
        service, user_repository, _, _ = _make_service()
        user = _make_user(email="user@example.com", password="correct-password")
        user_repository.get_by_email.return_value = user

        with pytest.raises(InvalidCredentialsError):
            await service.authenticate("user@example.com", "wrong-password")

    async def test_authenticate_unknown_email_raises_same_error_type_as_wrong_password(self) -> None:
        service, user_repository, _, _ = _make_service()
        user_repository.get_by_email.return_value = None

        with pytest.raises(InvalidCredentialsError) as unknown_email_exc:
            await service.authenticate("nobody@example.com", "whatever")

        user = _make_user(email="user@example.com", password="correct-password")
        user_repository.get_by_email.return_value = user
        with pytest.raises(InvalidCredentialsError) as wrong_password_exc:
            await service.authenticate("user@example.com", "wrong-password")

        # AUTH-02: identical exception type/message for both cases — no user enumeration
        assert type(unknown_email_exc.value) is type(wrong_password_exc.value)
        assert str(unknown_email_exc.value) == str(wrong_password_exc.value)


class TestRefresh:
    async def test_refresh_valid_token_revokes_old_and_returns_new_pair(self) -> None:
        service, _, refresh_token_repository, session = _make_service()
        user_id = uuid.uuid4()
        record = _make_refresh_token_record(user_id=user_id)
        refresh_token_repository.get_by_hash.return_value = record

        result = await service.refresh("some-opaque-refresh-token")

        assert isinstance(result, TokenPair)
        refresh_token_repository.revoke.assert_awaited_once_with(record.id)
        refresh_token_repository.create.assert_awaited_once()
        assert refresh_token_repository.create.call_args.args[0] == user_id
        assert result.refresh_token != "some-opaque-refresh-token"
        session.commit.assert_awaited_once()

    async def test_refresh_revoked_token_rejected(self) -> None:
        service, _, refresh_token_repository, _ = _make_service()
        record = _make_refresh_token_record(revoked_at=datetime.now(timezone.utc))
        refresh_token_repository.get_by_hash.return_value = record

        with pytest.raises(InvalidRefreshTokenError):
            await service.refresh("revoked-token")

        refresh_token_repository.revoke.assert_not_awaited()

    async def test_refresh_expired_token_rejected(self) -> None:
        service, _, refresh_token_repository, _ = _make_service()
        record = _make_refresh_token_record(
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)
        )
        refresh_token_repository.get_by_hash.return_value = record

        with pytest.raises(InvalidRefreshTokenError):
            await service.refresh("expired-token")

    async def test_refresh_unknown_token_rejected(self) -> None:
        service, _, refresh_token_repository, _ = _make_service()
        refresh_token_repository.get_by_hash.return_value = None

        with pytest.raises(InvalidRefreshTokenError):
            await service.refresh("unknown-token")


class TestLogout:
    async def test_logout_revokes_refresh_token_and_commits(self) -> None:
        service, _, refresh_token_repository, session = _make_service()
        record = _make_refresh_token_record()
        refresh_token_repository.get_by_hash.return_value = record

        await service.logout("some-opaque-refresh-token")

        refresh_token_repository.revoke.assert_awaited_once_with(record.id)
        session.commit.assert_awaited_once()


class TestRateLimiting:
    async def test_sixth_login_attempt_within_window_is_rate_limited(self) -> None:
        service, user_repository, _, _ = _make_service()
        user = _make_user(email="user@example.com", password="correct-password")
        user_repository.get_by_email.return_value = user

        for _ in range(5):
            with pytest.raises(InvalidCredentialsError):
                await service.authenticate("user@example.com", "wrong-password")

        # AUTH-05: the 6th attempt in the window is blocked — even with correct credentials
        with pytest.raises(RateLimitExceededError):
            await service.authenticate("user@example.com", "correct-password")

    async def test_rate_limit_is_scoped_per_email(self) -> None:
        service, user_repository, _, _ = _make_service()
        other_user = _make_user(email="other@example.com", password="correct-password")

        async def get_by_email(email: str) -> User | None:
            return other_user if email == "other@example.com" else None

        user_repository.get_by_email.side_effect = get_by_email

        for _ in range(5):
            with pytest.raises(InvalidCredentialsError):
                await service.authenticate("victim@example.com", "wrong-password")

        # A different email is not affected by victim@example.com's rate limit
        result = await service.authenticate("other@example.com", "correct-password")
        assert isinstance(result, TokenPair)
