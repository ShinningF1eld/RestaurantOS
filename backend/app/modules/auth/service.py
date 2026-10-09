from dataclasses import dataclass, replace, field
from collections.abc import Awaitable, Callable
import asyncio
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.database import AsyncSessionLocal
from app.modules.auth.domain.errors import (
    AuthenticationError,
    AuthStorageError,
    RateLimitError,
)
from app.modules.auth.domain.policies import normalize_email, session_valid
from app.modules.auth.domain.principal import AuthenticatedPrincipal
from app.modules.auth.rate_limit import AuthLimiter, Admission, get_limiter
from app.modules.auth.deadline import authentication_deadline
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
    access_token: str = field(repr=False)
    refresh_token: str = field(repr=False)
    expires_at: datetime
    delivery_deadline: float | None = None
    abandon_delivery: Callable[[], Awaitable[None]] | None = None


def issued(
    user_id: UUID, email: str, family: AuthSession, refresh: str
) -> IssuedSession:
    return IssuedSession(
        AuthenticatedPrincipal(user_id, email, "active", family.id),
        encode_access(user_id, family.id),
        refresh,
        family.expires_at,
    )


async def finish_admissions(
    limiter: AuthLimiter, admissions: list[Admission], *, count: bool
) -> None:
    try:
        for admission in admissions:
            await limiter.finalize(admission, count=count)
    except asyncio.CancelledError:
        # Compensation touches this request's members only. It never clears
        # other failures or repeats token rotation; leases bound failed cleanup.
        for admission in admissions:
            try:
                await limiter.finalize(admission, count=False, discard=True)
            except asyncio.CancelledError:
                break
        raise AuthStorageError() from None


async def login(email: str, password: str, ip: str) -> IssuedSession:
    settings = get_settings()
    email = normalize_email(email)
    limiter = get_limiter()
    admission = await limiter.admit(limiter.login_buckets(email, ip))
    count = False
    try:
        async with authentication_deadline() as operation:
            async with AsyncSessionLocal() as db:
                async with db.begin():
                    user = await find_by_email(db, email, lock=True)
                    operation.check()
                    valid, replacement = await verify_password(
                        password, user.password_hash if user else None
                    )
                    operation.check()
                    if not user or not valid or user.status != "active":
                        raise AuthenticationError()
                    if replacement:
                        user.password_hash = replacement
                    now = datetime.now(timezone.utc)
                    family = AuthSession(
                        id=uuid4(),
                        user_id=user.id,
                        created_at=now,
                        expires_at=now
                        + timedelta(seconds=settings.auth_session_seconds),
                    )
                    refresh = new_refresh_token()
                    db.add(family)
                    await db.flush()
                    operation.check()
                    db.add(
                        RefreshToken(
                            session_id=family.id,
                            digest=token_digest(refresh),
                            issued_at=now,
                            expires_at=family.expires_at,
                        )
                    )
                    user_id, user_email = user.id, user.email
                    operation.check()
                    operation.commit_started = True
                operation.check()
                operation.commit_finished = True
            operation.check()
            result = issued(user_id, user_email, family, refresh)
    except AuthenticationError:
        count = True
        raise
    except SQLAlchemyError as error:
        raise AuthStorageError() from error
    finally:
        await finish_admissions(limiter, [admission], count=count)
    # Also protect direct service callers if bounded cleanup consumed the last
    # part of the deadline. HTTP delivery has an additional boundary check.
    try:
        operation.check()
    except TimeoutError:
        raise AuthStorageError() from None
    return replace(result, delivery_deadline=operation.expires)


async def refresh_session(refresh: str | None, ip: str) -> IssuedSession:
    limiter: AuthLimiter = get_limiter()
    admissions: list[Admission] = [await limiter.admit(limiter.refresh_ip(ip))]
    count = False
    try:
        async with authentication_deadline() as operation:
            if not refresh or len(refresh) > 128:
                raise AuthenticationError()
            digest = token_digest(refresh)
            async with AsyncSessionLocal() as db:
                identity = await token_identity(db, digest)
            operation.check()
            if not identity:
                raise AuthenticationError()
            admissions.append(
                await limiter.admit(limiter.refresh_family(str(identity[1])))
            )
            operation.check()
            result: IssuedSession | None = None
            async with AsyncSessionLocal() as db:
                async with db.begin():
                    user, family = await lock_family(db, *identity)
                    operation.check()
                    token = await find_token(db, digest)
                    operation.check()
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
                            await db.flush()  # Release partial unique index.
                            operation.check()
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
                            operation.check()
                            token.successor_id = next_token.id
                            result = issued(user.id, user.email, family, successor)
                    operation.check()
                    operation.commit_started = True
                operation.check()
                operation.commit_finished = True
            # Replay revocation must commit before surfacing the failure.
            if result is None:
                raise AuthenticationError()
            operation.check()
        count = True

        async def abandon_delivery() -> None:
            for admission in admissions:
                await limiter.finalize(admission, count=False, discard=True)

    except (AuthenticationError, RateLimitError):
        # Family throttling still represents a client-originated IP attempt.
        count = True
        raise
    except SQLAlchemyError as error:
        raise AuthStorageError() from error
    finally:
        await finish_admissions(limiter, admissions, count=count)
    try:
        operation.check()
    except TimeoutError:
        await abandon_delivery()
        raise AuthStorageError() from None
    return replace(
        result, delivery_deadline=operation.expires, abandon_delivery=abandon_delivery
    )


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


async def active_account_id(session: "AsyncSession", email: str) -> "UUID | None":
    """Public identity lookup for owner-created memberships; no credentials leave auth."""
    from app.modules.auth.repo.users import find_by_email
    from app.modules.auth.domain.policies import normalize_email

    user = await find_by_email(session, normalize_email(email))
    return user.id if user is not None and user.status == "active" else None
