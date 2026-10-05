from decimal import Decimal
import pytest
from app.core.errors import ValidationError
from app.modules.inventory.domain.policies import quantity
from app.modules.inventory.domain.commands import CreateIngredient
from app.modules.inventory.service import fingerprint


@pytest.mark.parametrize(
    "value", ["NaN", "Infinity", "-0.001", "0.0001", "1000000000", "1e999"]
)
def test_reject_invalid_quantities(value):
    with pytest.raises(ValidationError):
        quantity(Decimal(value))


@pytest.mark.parametrize("value", ["0", "0.001", "999999999.999"])
def test_supported_quantities(value):
    assert quantity(Decimal(value)) == Decimal(value)


def test_positive_stock_action_rejects_zero():
    with pytest.raises(ValidationError):
        quantity(Decimal("0"), positive=True)


def test_fingerprint_normalizes_decimal_representation_and_excludes_key():
    one = CreateIngredient("Rice", "g", Decimal("2.000"), Decimal("10.0"), "first")
    two = CreateIngredient("Rice", "g", Decimal("2"), Decimal("10"), "second")
    assert fingerprint(one) == fingerprint(two)
