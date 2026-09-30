import pytest
from fastapi import Request

from app.core.errors import ConflictError, DomainError, NotFoundError, ValidationError
from app.http.error_handlers import domain_error_handler, domain_error_status


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (NotFoundError("Restaurant not found"), 404),
        (ConflictError("Order is closed"), 409),
        (ValidationError("Invalid payment status"), 422),
        (DomainError("Invalid request"), 400),
    ],
)
def test_domain_errors_have_stable_http_mapping(
    error: DomainError, expected_status: int
) -> None:
    assert domain_error_status(error) == expected_status


@pytest.mark.asyncio
async def test_domain_error_handler_preserves_existing_detail_shape() -> None:
    request = Request({"type": "http", "method": "GET", "headers": []})
    response = await domain_error_handler(request, NotFoundError("Menu not found"))

    assert response.status_code == 404
    assert response.body == b'{"detail":"Menu not found"}'


def test_domain_error_copies_details_and_keeps_stable_code() -> None:
    details = {"order_id": 7}
    error = ConflictError("Order is closed", details=details)
    details["order_id"] = 8

    assert error.code == "conflict"
    assert error.message == "Order is closed"
    assert error.details == {"order_id": 7}
