from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import get_settings


class AuthBoundaryMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        if scope["method"] not in {"GET", "HEAD", "OPTIONS"}:
            if (
                headers.get("origin") not in get_settings().auth_trusted_origins
                or headers.get("x-csrf-protection") != "1"
            ):
                await JSONResponse(
                    {"detail": "Invalid request origin or CSRF header"},
                    status_code=403,
                    headers={"Cache-Control": "no-store"},
                )(scope, receive, send)
                return
            if (
                headers.get("content-length", "0") != "0"
                or "transfer-encoding" in headers
            ) and headers.get("content-type", "").split(";")[
                0
            ].strip().lower() != "application/json":
                await JSONResponse({"detail": "JSON body required"}, status_code=415)(
                    scope, receive, send
                )
                return

        async def no_store(message: Message) -> None:
            if message["type"] == "http.response.start" and (
                scope["path"].startswith("/auth")
                or "ros_access=" in headers.get("cookie", "")
            ):
                entries = [
                    (key, value)
                    for key, value in message.get("headers", [])
                    if key.lower() != b"cache-control"
                ]
                message = {
                    **message,
                    "headers": entries + [(b"cache-control", b"no-store")],
                }
            await send(message)

        await self.app(scope, receive, no_store)
