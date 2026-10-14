"""Pure revision and contribution rules; creation dates are UTC dates."""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal


@dataclass(frozen=True, slots=True)
class Contribution:
    order_id: int
    revision: int
    creation_date: date
    total: Decimal
    state: Literal["completed", "inactive", "deleted"]

    @property
    def count(self) -> int:
        return int(self.state == "completed")


def creation_date(created_at: datetime) -> date:
    return (
        created_at.replace(tzinfo=UTC).date()
        if created_at.tzinfo is None
        else created_at.astimezone(UTC).date()
    )


def should_apply(current: Contribution | None, incoming: Contribution) -> bool:
    # A deletion is terminal, even for an erroneously newer completion.
    return current is None or (
        current.state != "deleted" and incoming.revision > current.revision
    )
