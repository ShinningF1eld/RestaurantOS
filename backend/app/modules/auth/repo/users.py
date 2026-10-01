from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.repo.models import User


async def find_by_email(
    db: AsyncSession, email: str, *, lock: bool = False
) -> User | None:
    query = select(User).where(User.email == email)
    if lock:
        query = query.with_for_update()
    return await db.scalar(query)
