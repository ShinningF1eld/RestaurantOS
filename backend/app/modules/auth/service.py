from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.db.database import AsyncSessionLocal
from app.modules.auth.domain.errors import AuthenticationError, AuthStorageError
from app.modules.auth.domain.policies import session_valid
from app.modules.auth.domain.principal import AuthenticatedPrincipal
from app.modules.auth.rate_limit import enforce_limits
from app.modules.auth.repo.models import AuthSession, RefreshToken
from app.modules.auth.repo.sessions import find_token, lock_family, token_identity
from app.modules.auth.repo.users import find_by_email
from app.modules.auth.security import (
    decode_access,
    encode_access,
    new_refresh_token,
    token_digest,
    verify_password,
)


@dataclass(frozen=True)
class IssuedSession:
    principal: AuthenticatedPrincipal
    access_token: str
    refresh_token: str
    expires_at: datetime


def issued(
    user_id: UUID, email: str, family: AuthSession, refresh: str
) -> IssuedSession:
    return IssuedSession(
        AuthenticatedPrincipal(user_id, email, "active", family.id),
        encode_access(user_id, family.id),
        refresh,
        family.expires_at,
    )


async def login(email: str, password: str, ip: str) -> IssuedSession:
    settings = get_settings()
    await enforce_limits(
        [
            ("login-email:" + email, settings.auth_login_email_limit),
            ("login-ip:" + ip, settings.auth_login_ip_limit),
        ],
        settings.auth_login_window_seconds,
    )
    try:
        async with AsyncSessionLocal() as db, db.begin():
            user = await find_by_email(db, email, lock=True)
            valid, replacement = await verify_password(
                password, user.password_hash if user else None
            )
            if not user or not valid or user.status != "active":
                raise AuthenticationError()
            if replacement:
                user.password_hash = replacement
            now = datetime.now(timezone.utc)
            family = AuthSession(
                id=uuid4(),
                user_id=user.id,
                created_at=now,
                expires_at=now + timedelta(seconds=settings.auth_session_seconds),
            )
            refresh = new_refresh_token()
            db.add(family)
            await db.flush()
            db.add(
                RefreshToken(
                    session_id=family.id,
                    digest=token_digest(refresh),
                    issued_at=now,
                    expires_at=family.expires_at,
                )
            )
            user_id, user_email = user.id, user.email
        return issued(user_id, user_email, family, refresh)
    except SQLAlchemyError as error:
        raise AuthStorageError() from error


async def refresh_session(refresh: str | None, ip: str) -> IssuedSession:
    settings = get_settings()
    await enforce_limits(
        [("refresh-ip:" + ip, settings.auth_refresh_ip_limit)],
        settings.auth_refresh_window_seconds,
    )
    if not refresh or len(refresh) > 128:
        raise AuthenticationError()
    digest = token_digest(refresh)
    try:
        async with AsyncSessionLocal() as db:
            identity = await token_identity(db, digest)
        if not identity:
            raise AuthenticationError()
        await enforce_limits(
            [
                (
                    "refresh-family:" + str(identity[1]),
                    settings.auth_refresh_family_limit,
                )
            ],
            settings.auth_refresh_window_seconds,
        )
        result: IssuedSession | None = None
        async with AsyncSessionLocal() as db, db.begin():
            user, family = await lock_family(db, *identity)
            token = await find_token(db, digest)
            now = datetime.now(timezone.utc)
            if (
                user
                and family
                and token
                and session_valid(
                    user.status, family.revoked_at, family.expires_at, now
                )
                and token.expires_at > now
            ):
                if token.consumed_at is not None:
                    family.revoked_at = now
                    family.revoked_reason = "refresh_replay"
                else:
                    token.consumed_at = now
                    await (
                        db.flush()
                    )  # Release the partial unique index before insertion.
                    successor = new_refresh_token()
                    next_token = RefreshToken(
                        id=uuid4(),
                        session_id=family.id,
                        digest=token_digest(successor),
                        issued_at=now,
                        expires_at=family.expires_at,
                    )
                    db.add(next_token)
                    await db.flush()
                    token.successor_id = next_token.id
                    result = issued(user.id, user.email, family, successor)
        # Replay revocation must commit before surfacing the failure.
        if result is None:
            raise AuthenticationError()
        return result
    except SQLAlchemyError as error:
        raise AuthStorageError() from error


async def logout(refresh: str | None, access: str | None) -> None:
    try:
        async with AsyncSessionLocal() as db, db.begin():
            identity = (
                await token_identity(db, token_digest(refresh))
                if refresh and len(refresh) <= 128
                else None
            )
            if identity is None and access:
                try:
                    identity = decode_access(access)
                except AuthenticationError:
                    pass
            if identity:
                _, family = await lock_family(db, *identity)
                if family and family.revoked_at is None:
                    family.revoked_at = datetime.now(timezone.utc)
                    family.revoked_reason = "logout"
    except SQLAlchemyError as error:
        raise AuthStorageError() from error
