"""Catalog invariants shared by HTTP and non-HTTP callers."""

from decimal import Decimal

from app.core.errors import ValidationError


MAX_MENU_PRICE = Decimal("99999999.99")


def validate_menu_price(price: Decimal) -> Decimal:
    """Require a finite, nonnegative NUMERIC(10, 2) value without rounding."""
    if (
        not price.is_finite()
        or not Decimal("0") <= price <= MAX_MENU_PRICE
        or price != price.quantize(Decimal("0.01"))
    ):
        raise ValidationError(
            "Price must be between 0 and 99999999.99 with at most two decimal places"
        )
    return price
