"""Inventory quantities use three decimal places in each ingredient's base unit."""

from decimal import Decimal, InvalidOperation
from app.core.errors import ValidationError

MAX_QUANTITY = Decimal("999999999.999")


def quantity(value: Decimal, *, positive: bool = False) -> Decimal:
    try:
        valid = value.is_finite() and value >= 0 and value <= MAX_QUANTITY
        valid = valid and value == value.quantize(Decimal("0.001"))
    except (InvalidOperation, AttributeError):
        valid = False
    if not valid or (positive and value == 0):
        raise ValidationError(
            "Quantity must be finite, nonnegative, at most 999999999.999, with at most three decimal places"
        )
    return value
