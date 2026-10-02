"""Feature-owned value and command inputs independent of HTTP and persistence."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CreateRestaurant:
    name: str
    address: str | None
    phone: str | None


@dataclass(frozen=True, slots=True)
class UpdateRestaurant:
    name: str | None
    address: str | None
    phone: str | None
    fields: frozenset[str]
