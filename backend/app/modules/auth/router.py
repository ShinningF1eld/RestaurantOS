from datetime import datetime, timezone
import time

from fastapi import APIRouter, Depends, Request, Response

from app.core.config import get_settings
from app.modules.auth.dependencies import client_ip, get_current_principal
from app.modules.auth.domain.principal import AuthenticatedPrincipal
from app.modules.auth.schemas import LoginRequest, UserSummary
from app.modules.auth.service import IssuedSession, login, logout, refresh_session
from app.modules.auth.domain.errors import AuthStorageError

router = APIRouter(prefix="/auth", tags=["auth"])


def clear_cookies(response: Response) -> None:
    for name, path in (("ros_access", "/"), ("ros_refresh", "/auth")):
        response.delete_cookie(
            name,
            path=path,
            secure=get_settings().auth_cookie_secure,
            httponly=True,
            samesite="lax",
        )


def set_cookies(response: Response, result: IssuedSession) -> UserSummary:
    if (
        result.delivery_deadline is not None
        and time.monotonic() >= result.delivery_deadline
    ):
        raise AuthStorageError()
    settings = get_settings()
    response.headers["Cache-Control"] = "no-store"
    remaining = max(
        0, int((result.expires_at - datetime.now(timezone.utc)).total_seconds())
    )
    response.set_cookie(
        "ros_access",
        result.access_token,
        max_age=min(settings.auth_access_seconds, remaining),
        path="/",
        secure=settings.auth_cookie_secure,
        httponly=True,
        samesite="lax",
    )
    response.set_cookie(
        "ros_refresh",
        result.refresh_token,
        max_age=remaining,
        path="/auth",
        secure=settings.auth_cookie_secure,
        httponly=True,
        samesite="lax",
    )
    summary = UserSummary(
        id=result.principal.id,
        email=result.principal.email,
        status=result.principal.status,
    )
    if (
        result.delivery_deadline is not None
        and time.monotonic() >= result.delivery_deadline
    ):
        # The exception handler constructs a new response without these cookies.
        raise AuthStorageError()
    return summary


@router.post("/login", response_model=UserSummary)
async def login_route(
    body: LoginRequest, request: Request, response: Response
) -> UserSummary:
    result = await login(body.email, body.password, client_ip(request))
    request.state.auth_delivery_deadline = result.delivery_deadline
    return set_cookies(response, result)


@router.post("/refresh", response_model=UserSummary)
async def refresh_route(request: Request, response: Response) -> UserSummary:
    result = await refresh_session(
        request.cookies.get("ros_refresh"), client_ip(request)
    )
    request.state.auth_delivery_deadline = result.delivery_deadline
    request.state.auth_abandon_delivery = result.abandon_delivery
    try:
        return set_cookies(response, result)
    except AuthStorageError:
        if result.abandon_delivery:
            await result.abandon_delivery()
        raise


@router.post("/logout", status_code=204)
async def logout_route(request: Request) -> Response:
    await logout(request.cookies.get("ros_refresh"), request.cookies.get("ros_access"))
    response = Response(status_code=204, headers={"Cache-Control": "no-store"})
    clear_cookies(response)
    return response


@router.get("/me", response_model=UserSummary)
async def me(
    response: Response,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> UserSummary:
    response.headers["Cache-Control"] = "no-store"
    return UserSummary(id=principal.id, email=principal.email, status=principal.status)
