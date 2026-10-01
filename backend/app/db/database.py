from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.config import get_settings


settings = get_settings()
if settings.environment == "test":
    # TestClient creates independent event loops. Do not retain asyncpg
    # connections across them, and keep tests isolated from production pooling.
    engine = create_async_engine(
        settings.database_url,
        echo=settings.database_echo,
        hide_parameters=True,
        poolclass=NullPool,
    )
else:
    engine = create_async_engine(
        settings.database_url,
        echo=settings.database_echo,
        hide_parameters=True,
    )

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            # Command services commit through explicit transaction contexts.
            # Roll back reads or abandoned writes before returning the session.
            if session.in_transaction():
                await session.rollback()
