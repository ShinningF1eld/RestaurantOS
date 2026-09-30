import json
import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.logging import JsonFormatter
from app.core.request_id import get_request_id, is_valid_request_id, select_request_id
from app.http.request_middleware import RequestIdMiddleware


def test_request_id_selection_reuses_sane_value_and_replaces_unsafe_value() -> None:
    assert select_request_id("checkout.42") == "checkout.42"
    generated = select_request_id("unsafe value\n")

    assert is_valid_request_id(generated)
    assert generated != "unsafe value\n"


def test_request_id_middleware_echoes_valid_header_and_sets_context() -> None:
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)

    @app.get("/")
    async def index() -> dict[str, str | None]:
        return {"request_id": get_request_id()}

    with TestClient(app) as client:
        response = client.get("/", headers={"X-Request-ID": "checkout-42"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "checkout-42"
    assert response.json() == {"request_id": "checkout-42"}


def test_request_id_middleware_replaces_invalid_header() -> None:
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)

    @app.get("/")
    async def index() -> dict[str, str | None]:
        return {"request_id": get_request_id()}

    with TestClient(app) as client:
        response = client.get("/", headers={"X-Request-ID": "has spaces"})

    echoed = response.headers["X-Request-ID"]
    assert is_valid_request_id(echoed)
    assert echoed != "has spaces"
    assert response.json() == {"request_id": echoed}


def test_json_logging_keeps_request_metadata_but_not_arbitrary_extras() -> None:
    record = logging.LogRecord(
        name="restaurantos.request",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="request completed",
        args=(),
        exc_info=None,
    )
    record.http_method = "GET"
    record.http_path = "/health"
    record.status_code = 200
    record.duration_ms = 1.25
    record.secret = "do-not-log"  # pragma: allowlist secret

    payload = json.loads(JsonFormatter().format(record))

    assert payload["http_method"] == "GET"
    assert payload["http_path"] == "/health"
    assert payload["status_code"] == 200
    assert payload["duration_ms"] == 1.25
    assert "secret" not in payload
