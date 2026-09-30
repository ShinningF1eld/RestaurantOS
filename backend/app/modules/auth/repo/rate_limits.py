from datetime import datetime

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.repo.models import RateLimitBucket


async def increment(
    db: AsyncSession, digest: str, start: datetime, expiry: datetime
) -> int:
    statement = insert(RateLimitBucket).values(
        key_digest=digest, window_start=start, expires_at=expiry, attempt_count=1
    )
    returning = statement.on_conflict_do_update(
        index_elements=[RateLimitBucket.key_digest, RateLimitBucket.window_start],
        set_={"attempt_count": RateLimitBucket.attempt_count + 1},
    ).returning(RateLimitBucket.attempt_count)
    return (await db.execute(returning)).scalar_one()
