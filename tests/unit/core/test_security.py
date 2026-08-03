import uuid
from datetime import timedelta

import jwt
import pytest

from app.core.security import JWTService, PasswordHasher, generate_opaque_token, hash_token


class TestOpaqueToken:
    def test_hash_token_is_deterministic(self) -> None:
        token = "some-opaque-token-value"

        assert hash_token(token) == hash_token(token)

    def test_hash_token_is_not_the_identity_function(self) -> None:
        token = "some-opaque-token-value"

        assert hash_token(token) != token

    def test_generate_opaque_token_returns_non_empty_url_safe_string(self) -> None:
        token = generate_opaque_token()

        assert isinstance(token, str)
        assert len(token) > 0
        allowed = set(
            "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
        )
        assert set(token) <= allowed

    def test_generate_opaque_token_calls_produce_different_values(self) -> None:
        first = generate_opaque_token()
        second = generate_opaque_token()

        assert first != second


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
