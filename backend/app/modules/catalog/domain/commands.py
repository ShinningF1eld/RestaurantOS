"""Feature-owned value and command inputs independent of HTTP and persistence."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal


@dataclass(frozen=True, slots=True)
class CreateMenu:
    name: str
    description: str | None


@dataclass(frozen=True, slots=True)
class UpdateMenu:
    name: str | None
    description: str | None


@dataclass(frozen=True, slots=True)
class CreateMenuItem:
    name: str
    description: str | None
    price: Decimal
    is_available: bool


@dataclass(frozen=True, slots=True)
class UpdateMenuItem:
    name: str | None
    description: str | None
    price: Decimal | None
    is_available: bool | None


DeleteMenuItemOutcome = Literal["deleted", "deactivated"]
