"""Pure dashboard date and percentage calculations."""

from datetime import date, datetime, time
from decimal import Decimal


def start_of_day(value: date) -> datetime:
    return datetime.combine(value, time.min)


def end_of_day(value: date) -> datetime:
    return datetime.combine(value, time.max)


def percent_change(current: Decimal | int, previous: Decimal | int) -> Decimal:
    current_value = Decimal(str(current))
    previous_value = Decimal(str(previous))

    if previous_value == 0:
        return Decimal("0.00")

    return ((current_value - previous_value) / previous_value * 100).quantize(
        Decimal("0.01")
    )
