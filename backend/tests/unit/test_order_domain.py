import pytest

from app.domain.order import (
    InvalidOrderStatusTransitionError,
    InvalidPaymentStatusError,
    OrderItemsLockedError,
    ensure_order_items_mutable,
    ensure_valid_order_transition,
    ensure_valid_payment_status,
    normalize_order_status,
    normalize_payment_status,
)


@pytest.mark.parametrize(
    ("raw_status", "expected_status"),
    [
        (" draft ", "DRAFT"),
        ("pending", "DRAFT"),
        ("complete", "COMPLETED"),
        ("cancelled", "CANCELLED"),
        ("custom", "CUSTOM"),
    ],
)
def test_normalize_order_status_preserves_existing_aliases(
    raw_status: str, expected_status: str
) -> None:
    assert normalize_order_status(raw_status) == expected_status


@pytest.mark.parametrize(
    ("current", "requested", "expected"),
    [
        ("DRAFT", "submitted", "SUBMITTED"),
        ("pending", "DRAFT", "DRAFT"),
        ("READY", "complete", "COMPLETED"),
        ("COMPLETED", "completed", "COMPLETED"),
    ],
)
def test_valid_order_transitions_are_returned_in_canonical_form(
    current: str, requested: str, expected: str
) -> None:
    assert ensure_valid_order_transition(current, requested) == expected


def test_same_unknown_order_status_remains_allowed_for_compatibility() -> None:
    assert ensure_valid_order_transition("legacy", "LEGACY") == "LEGACY"


def test_invalid_order_transition_includes_canonical_statuses() -> None:
    with pytest.raises(
        InvalidOrderStatusTransitionError,
        match="Invalid order status transition from DRAFT to READY",
    ) as error:
        ensure_valid_order_transition("pending", "ready")

    assert error.value.current_status == "DRAFT"
    assert error.value.requested_status == "READY"


@pytest.mark.parametrize(
    ("raw_status", "expected_status"),
    [
        (" unpaid ", "UNPAID"),
        ("Paid", "PAID"),
        ("VOID", "VOID"),
    ],
)
def test_payment_status_is_normalized_and_validated(
    raw_status: str, expected_status: str
) -> None:
    assert normalize_payment_status(raw_status) == expected_status
    assert ensure_valid_payment_status(raw_status) == expected_status


def test_invalid_payment_status_has_stable_error_message() -> None:
    with pytest.raises(InvalidPaymentStatusError, match="Invalid payment status") as error:
        ensure_valid_payment_status("refunded")

    assert error.value.payment_status == "REFUNDED"


@pytest.mark.parametrize("draft_status", ["DRAFT", " draft ", "PENDING"])
def test_order_items_can_change_while_order_is_draft(draft_status: str) -> None:
    ensure_order_items_mutable(draft_status)


@pytest.mark.parametrize("locked_status", ["SUBMITTED", "complete", "CANCELLED"])
def test_order_items_cannot_change_after_draft(locked_status: str) -> None:
    with pytest.raises(
        OrderItemsLockedError,
        match="Order items can only be changed while an order is in DRAFT",
    ) as error:
        ensure_order_items_mutable(locked_status)

    assert error.value.order_status == normalize_order_status(locked_status)
