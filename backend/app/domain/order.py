"""Compatibility imports; implementation belongs to the feature module."""

from app.modules.orders.domain.policies import (
    InvalidOrderStatusTransitionError as InvalidOrderStatusTransitionError,
    InvalidPaymentStatusError as InvalidPaymentStatusError,
    OrderItemsLockedError as OrderItemsLockedError,
    normalize_order_status as normalize_order_status,
    ensure_valid_order_transition as ensure_valid_order_transition,
    normalize_payment_status as normalize_payment_status,
    ensure_valid_payment_status as ensure_valid_payment_status,
    ensure_order_items_mutable as ensure_order_items_mutable,
    ORDER_TRANSITIONS as ORDER_TRANSITIONS,
    PAYMENT_STATUSES as PAYMENT_STATUSES,
    ORDER_STATUS_ALIASES as ORDER_STATUS_ALIASES,
)
