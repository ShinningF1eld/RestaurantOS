from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.repo.models import AuthSession, RefreshToken, User


async def token_identity(db: AsyncSession, digest: str) -> tuple[UUID, UUID] | None:
    row = (
        await db.execute(
            select(AuthSession.user_id, AuthSession.id)
            .join(RefreshToken, RefreshToken.session_id == AuthSession.id)
            .where(RefreshToken.digest == digest)
        )
    ).one_or_none()
    return (row[0], row[1]) if row else None


async def find_token(db: AsyncSession, digest: str) -> RefreshToken | None:
    return await db.scalar(select(RefreshToken).where(RefreshToken.digest == digest))


async def lock_family(
    db: AsyncSession, user_id: UUID, session_id: UUID
) -> tuple[User | None, AuthSession | None]:
    # Every command locks user then family, including disable-user.
    user = await db.scalar(select(User).where(User.id == user_id).with_for_update())
    family = await db.scalar(
        select(AuthSession)
        .where(AuthSession.id == session_id, AuthSession.user_id == user_id)
        .with_for_update()
    )
    return user, family
