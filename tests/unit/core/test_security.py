import uuid
from datetime import timedelta

import jwt
import pytest

from app.core.security import JWTService, PasswordHasher


class TestPasswordHasher:
    def test_verify_correct_password_succeeds(self) -> None:
        hashed = PasswordHasher.hash("correct-horse-battery-staple")

        assert PasswordHasher.verify("correct-horse-battery-staple", hashed) is True

    def test_verify_wrong_password_fails(self) -> None:
        hashed = PasswordHasher.hash("correct-horse-battery-staple")

        assert PasswordHasher.verify("wrong-password", hashed) is False


class TestJWTService:
    def test_encode_decode_roundtrip_returns_user_id(self) -> None:
        service = JWTService(secret="test-secret")
        user_id = uuid.uuid4()

        token = service.encode(user_id, ttl=timedelta(minutes=15))

        assert service.decode(token) == user_id

    def test_decode_expired_token_raises(self) -> None:
        service = JWTService(secret="test-secret")
        user_id = uuid.uuid4()
        token = service.encode(user_id, ttl=timedelta(seconds=-1))

        with pytest.raises(jwt.ExpiredSignatureError):
            service.decode(token)

    def test_decode_malformed_token_raises(self) -> None:
        service = JWTService(secret="test-secret")

        with pytest.raises(jwt.InvalidTokenError):
            service.decode("not-a-valid-jwt-token")
