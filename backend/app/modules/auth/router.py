from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request, Response

from app.core.config import get_settings
from app.modules.auth.dependencies import client_ip, get_current_principal
from app.modules.auth.domain.principal import AuthenticatedPrincipal
from app.modules.auth.schemas import LoginRequest, UserSummary
from app.modules.auth.service import IssuedSession, login, logout, refresh_session

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
    return UserSummary(
        id=result.principal.id,
        email=result.principal.email,
        status=result.principal.status,
    )


@router.post("/login", response_model=UserSummary)
async def login_route(
    body: LoginRequest, request: Request, response: Response
) -> UserSummary:
    return set_cookies(
        response, await login(body.email, body.password, client_ip(request))
    )


@router.post("/refresh", response_model=UserSummary)
async def refresh_route(request: Request, response: Response) -> UserSummary:
    return set_cookies(
        response,
        await refresh_session(request.cookies.get("ros_refresh"), client_ip(request)),
    )


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
