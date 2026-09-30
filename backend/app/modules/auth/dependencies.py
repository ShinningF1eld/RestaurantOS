from datetime import datetime, timezone
from ipaddress import ip_address

from fastapi import Request, Security
from fastapi.security import APIKeyCookie
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.db.database import AsyncSessionLocal
from app.modules.auth.domain.errors import AuthenticationError, AuthStorageError
from app.modules.auth.domain.policies import session_valid
from app.modules.auth.domain.principal import AuthenticatedPrincipal
from app.modules.auth.repo.models import AuthSession, User
from app.modules.auth.security import decode_access

access_cookie = APIKeyCookie(name="ros_access", auto_error=False)


async def get_current_principal(
    token: str | None = Security(access_cookie),
) -> AuthenticatedPrincipal:
    if not token or len(token) > 4096:
        raise AuthenticationError()
    user_id, session_id = decode_access(token)
    try:
        # Never use the business get_db dependency: auth reads autobegin.
        async with AsyncSessionLocal() as db:
            user = await db.get(User, user_id)
            family = await db.get(AuthSession, session_id)
            if (
                not user
                or not family
                or family.user_id != user.id
                or not session_valid(
                    user.status,
                    family.revoked_at,
                    family.expires_at,
                    datetime.now(timezone.utc),
                )
            ):
                raise AuthenticationError()
            return AuthenticatedPrincipal(user.id, user.email, user.status, family.id)
    except SQLAlchemyError as error:
        raise AuthStorageError() from error


def client_ip(request: Request) -> str:
    current = request.client.host if request.client else "unknown"
    trusted = get_settings().auth_trusted_proxy_ips
    # Walk right to left only while each peer is explicitly trusted.
    for value in reversed(request.headers.get("x-forwarded-for", "").split(",")):
        if current not in trusted:
            break
        try:
            current = str(ip_address(value.strip()))
        except ValueError:
            break
    return current
