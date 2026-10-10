import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

import anyio
from anyio.lowlevel import RunVar
import jwt
from pwdlib import PasswordHash

from app.core.config import get_settings
from app.modules.auth.domain.errors import AuthenticationError
from app.modules.auth.domain.policies import normalize_email, validate_password

__all__ = [
    "normalize_email",
    "hash_password",
    "verify_password",
    "encode_access",
    "decode_access",
    "token_digest",
    "new_refresh_token",
]
_hasher = PasswordHash.recommended()
_dummy_hash = _hasher.hash("dummy password for unknown accounts")
_password_limiter: RunVar[anyio.CapacityLimiter] = RunVar(
    "restaurantos_password_limiter"
)


async def hash_password(password: str) -> str:
    validate_password(password)
    return await anyio.to_thread.run_sync(_hasher.hash, password, limiter=_limiter())


def _limiter() -> anyio.CapacityLimiter:
    # A RunVar gives each event loop a bounded hashing pool (also supports tests).
    try:
        return _password_limiter.get()
    except LookupError:
        limiter = anyio.CapacityLimiter(4)
        _password_limiter.set(limiter)
        return limiter


async def verify_password(
    password: str, password_hash: str | None
) -> tuple[bool, str | None]:
    valid, replacement = await anyio.to_thread.run_sync(
        _hasher.verify_and_update,
        password,
        password_hash or _dummy_hash,
        limiter=_limiter(),
        abandon_on_cancel=True,
    )
    return valid and password_hash is not None, replacement


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_refresh_token() -> str:
    return secrets.token_urlsafe(32)


def encode_access(user_id: UUID, session_id: UUID) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": str(user_id),
            "sid": str(session_id),
            "iss": settings.auth_jwt_issuer,
            "aud": settings.auth_jwt_audience,
            "iat": now,
            "exp": now + timedelta(seconds=settings.auth_access_seconds),
            "token_use": "access",
        },
        settings.auth_jwt_secret.get_secret_value(),
        algorithm="HS256",
    )


def decode_access(token: str) -> tuple[UUID, UUID]:
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.auth_jwt_secret.get_secret_value(),
            algorithms=["HS256"],
            issuer=settings.auth_jwt_issuer,
            audience=settings.auth_jwt_audience,
            options={
                "require": ["sub", "sid", "iss", "aud", "iat", "exp", "token_use"]
            },
        )
        if (
            not isinstance(payload["sub"], str)
            or not isinstance(payload["sid"], str)
            or payload["token_use"] != "access"
            or not isinstance(payload["iat"], (int, float))
            or not isinstance(payload["exp"], (int, float))
            or payload["exp"] <= payload["iat"]
        ):
            raise AuthenticationError()
        return UUID(payload["sub"]), UUID(payload["sid"])
    except (jwt.PyJWTError, ValueError, TypeError, KeyError) as error:
        raise AuthenticationError() from error
