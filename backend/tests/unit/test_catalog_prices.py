from decimal import Decimal

import pytest
from pydantic import ValidationError as SchemaValidationError

from app.core.errors import ValidationError
from app.modules.catalog.domain.policies import validate_menu_price
from app.modules.catalog.item_schemas import MenuItemCreate, MenuItemUpdate


@pytest.mark.parametrize(
    "value", ["-0.01", "100000000", "0.001", "12.345", "NaN", "Infinity", "-Infinity"]
)
def test_invalid_prices_rejected_by_http_and_domain(value):
    with pytest.raises(SchemaValidationError):
        MenuItemCreate(name="Dish", price=value)
    with pytest.raises(SchemaValidationError):
        MenuItemUpdate(price=value)
    with pytest.raises(ValidationError):
        validate_menu_price(Decimal(value))


@pytest.mark.parametrize("value", ["0", "0.01", "12.50", "12.500", "99999999.99"])
def test_valid_prices_preserve_exact_value(value):
    expected = Decimal(value)
    assert MenuItemCreate(name="Dish", price=value).price == expected
    assert MenuItemUpdate(price=value).price == expected
    assert validate_menu_price(expected) == expected


def test_update_can_omit_price():
    assert MenuItemUpdate(name="Renamed").price is None
