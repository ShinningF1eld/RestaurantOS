import asyncio
import json

import pytest

from app.http.auth_middleware import AuthBoundaryMiddleware


@pytest.mark.asyncio
async def test_expiry_at_asgi_headers_discards_cookies_body_and_refresh_charge(
    monkeypatch, unit_settings
):
    from app.http import auth_middleware

    monkeypatch.setattr(auth_middleware, "get_settings", lambda: unit_settings)
    monkeypatch.setattr(auth_middleware, "monotonic", lambda: 9.0)
    discarded = []

    async def abandon():
        discarded.append(True)

    async def application(scope, receive, send):
        # Models an event-loop delay AFTER cookie construction.
        scope["state"] = {
            "auth_delivery_deadline": 8.0,
            "auth_abandon_delivery": abandon,
        }
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"set-cookie", b"ros_access=private-marker")],
            }
        )
        await send({"type": "http.response.body", "body": b"private-body-marker"})

    scope = {
        "type": "http",
        "path": "/auth/refresh",
        "method": "POST",
        "headers": [
            (b"origin", b"http://localhost:3000"),
            (b"x-csrf-protection", b"1"),
        ],
    }
    messages = []

    async def send(message):
        messages.append(message)

    async def receive():
        return {"type": "http.request", "body": b""}

    await AuthBoundaryMiddleware(application)(scope, receive, send)
    assert messages[0]["status"] == 503
    assert all(k != b"set-cookie" for k, _ in messages[0]["headers"])
    assert json.loads(messages[1]["body"]) == {
        "detail": "Authentication service unavailable"
    }
    assert discarded == [True]
    assert "private-marker" not in repr(messages) and "private-body-marker" not in repr(
        messages
    )


@pytest.mark.asyncio
async def test_cancellation_before_delivery_discards_refresh_charge(
    monkeypatch, unit_settings
):
    from app.http import auth_middleware

    monkeypatch.setattr(auth_middleware, "get_settings", lambda: unit_settings)
    discarded = []

    async def abandon():
        discarded.append(True)

    async def application(scope, receive, send):
        scope["state"] = {"auth_abandon_delivery": abandon}
        raise asyncio.CancelledError()

    async def unused(*_):
        raise AssertionError("No credentials may be sent")

    with pytest.raises(asyncio.CancelledError):
        await AuthBoundaryMiddleware(application)(
            {"type": "http", "path": "/auth/refresh", "method": "GET", "headers": []},
            unused,
            unused,
        )
    assert discarded == [True]
