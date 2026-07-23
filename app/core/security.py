import uuid
from datetime import datetime, timedelta, timezone

import jwt
from passlib.context import CryptContext

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class PasswordHasher:
    """Pure password hashing utility (bcrypt via passlib). No I/O, no state."""

    @staticmethod
    def hash(plain: str) -> str:
        return _pwd_context.hash(plain)

    @staticmethod
    def verify(plain: str, hashed: str) -> bool:
        return _pwd_context.verify(plain, hashed)


class JWTService:
    """Pure JWT encode/decode utility (PyJWT). No I/O, no state beyond the secret."""

    def __init__(self, secret: str, algorithm: str = "HS256") -> None:
        self._secret = secret
        self._algorithm = algorithm

    def encode(self, user_id: uuid.UUID, ttl: timedelta) -> str:
        now = datetime.now(timezone.utc)
        payload = {"sub": str(user_id), "iat": now, "exp": now + ttl}
        return jwt.encode(payload, self._secret, algorithm=self._algorithm)

    def decode(self, token: str) -> uuid.UUID:
        """Decode and validate a JWT, returning the user id.

        Raises jwt.ExpiredSignatureError for an expired token, and
        jwt.InvalidTokenError (or a subclass, e.g. DecodeError) for a
        malformed/invalid token.
        """
        payload = jwt.decode(token, self._secret, algorithms=[self._algorithm])
        return uuid.UUID(payload["sub"])
