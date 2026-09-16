"""Pure business rules for an order's lifecycle.

This module deliberately has no persistence or transport dependencies so the
rules can be used and tested independently of FastAPI and SQLAlchemy.
"""

from collections.abc import Mapping
from typing import Final

from app.core.errors import ConflictError, ValidationError


ORDER_TRANSITIONS: Final[Mapping[str, frozenset[str]]] = {
    "DRAFT": frozenset({"SUBMITTED", "CANCELLED"}),
    "SUBMITTED": frozenset({"ACCEPTED", "CANCELLED"}),
    "ACCEPTED": frozenset({"PREPARING", "CANCELLED"}),
    "PREPARING": frozenset({"READY", "CANCELLED"}),
    "READY": frozenset({"COMPLETED", "CANCELLED"}),
    "COMPLETED": frozenset(),
    "CANCELLED": frozenset(),
}
PAYMENT_STATUSES: Final[frozenset[str]] = frozenset({"UNPAID", "PAID", "VOID"})
ORDER_STATUS_ALIASES: Final[Mapping[str, str]] = {
    "PENDING": "DRAFT",
    "COMPLETE": "COMPLETED",
    "CANCELLED": "CANCELLED",
}


class InvalidOrderStatusTransitionError(ConflictError):
    """Raised when an order lifecycle transition is not allowed."""

    def __init__(self, current_status: str, requested_status: str) -> None:
        self.current_status = current_status
        self.requested_status = requested_status
        super().__init__(
            "Invalid order status transition from "
            f"{current_status} to {requested_status}"
        )


class InvalidPaymentStatusError(ValidationError):
    """Raised when a payment status is outside the supported lifecycle."""

    def __init__(self, payment_status: str) -> None:
        self.payment_status = payment_status
        super().__init__("Invalid payment status")


class OrderItemsLockedError(ConflictError):
    """Raised when an item mutation is requested after an order leaves draft."""

    def __init__(self, order_status: str) -> None:
        self.order_status = order_status
        super().__init__(
            "Order items can only be changed while an order is in DRAFT"
        )


def normalize_order_status(value: str) -> str:
    """Return the canonical stored value for an order-status input."""
    normalized = value.strip().upper()
    return ORDER_STATUS_ALIASES.get(normalized, normalized)


def ensure_valid_order_transition(current: str, requested: str) -> str:
    """Validate and return a requested lifecycle status in canonical form.

    Repeating the current status is intentionally allowed, matching the
    existing update endpoint behavior.
    """
    normalized_current = normalize_order_status(current)
    normalized_requested = normalize_order_status(requested)
    if normalized_requested == normalized_current:
        return normalized_requested
    if normalized_requested not in ORDER_TRANSITIONS.get(
        normalized_current, frozenset()
    ):
        raise InvalidOrderStatusTransitionError(
            normalized_current, normalized_requested
        )
    return normalized_requested


def normalize_payment_status(value: str) -> str:
    """Return the canonical stored value for a payment-status input."""
    return value.strip().upper()


def ensure_valid_payment_status(value: str) -> str:
    """Validate and return a payment status in canonical form."""
    normalized = normalize_payment_status(value)
    if normalized not in PAYMENT_STATUSES:
        raise InvalidPaymentStatusError(normalized)
    return normalized


def ensure_order_items_mutable(order_status: str) -> None:
    """Require an order to remain in draft before its items can change."""
    normalized_status = normalize_order_status(order_status)
    if normalized_status != "DRAFT":
        raise OrderItemsLockedError(normalized_status)
