"""Feature-owned value and command inputs independent of HTTP and persistence."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OrderItemCommand:
    """An order-item input independent of HTTP schemas and persistence."""

    menu_item_id: int
    quantity: int
    notes: str | None


@dataclass(frozen=True, slots=True)
class CreateOrder:
    """Input for creating an order."""

    table_number: str | None
    customer_name: str | None
    notes: str | None
    items: tuple[OrderItemCommand, ...]


@dataclass(frozen=True, slots=True)
class UpdateOrder:
    """Supplied mutable fields for an order update."""

    table_number: str | None
    customer_name: str | None
    status: str | None
    notes: str | None
    items: tuple[OrderItemCommand, ...] | None
    payment_status: str | None
    fields: frozenset[str]
