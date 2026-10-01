import hashlib
import hmac
import math
from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.db.database import AsyncSessionLocal
from app.modules.auth.domain.errors import AuthStorageError, RateLimitError
from app.modules.auth.repo.rate_limits import increment


async def enforce_limits(limits: list[tuple[str, int]], window_seconds: int) -> None:
    now = datetime.now(timezone.utc)
    start = datetime.fromtimestamp(
        int(now.timestamp()) // window_seconds * window_seconds, timezone.utc
    )
    expiry = start + timedelta(seconds=window_seconds)
    exceeded = False
    try:
        async with AsyncSessionLocal() as db, db.begin():
            for key, maximum in limits:
                digest = hmac.new(
                    get_settings().auth_rate_limit_secret.get_secret_value().encode(),
                    key.encode(),
                    hashlib.sha256,
                ).hexdigest()
                exceeded = (
                    await increment(db, digest, start, expiry) > maximum or exceeded
                )
    except SQLAlchemyError as error:
        raise AuthStorageError() from error
    if exceeded:
        raise RateLimitError(max(1, math.ceil((expiry - now).total_seconds())))
