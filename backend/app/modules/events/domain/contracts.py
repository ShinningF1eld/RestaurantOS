"""Typed, versioned contracts stored in the PostgreSQL outbox."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Literal, TypeAlias
from uuid import UUID, uuid4

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    TypeAdapter,
    ValidationError,
    field_validator,
    model_validator,
)


EventType = Literal[
    "order.submitted.v1",
    "order.accepted.v1",
    "order.completed.v1",
    "order.cancelled.v1",
    "order.deleted.v1",
    "menu.updated.v1",
    "inventory.state_changed.v1",
    "inventory.low.v1",
]
ConsumerName = Literal["analytics", "alerts", "notification_sink"]


def _decimal_from_lossless_value(value: object) -> Decimal:
    if isinstance(value, (Decimal, str)):
        try:
            decimal_value = Decimal(value)
        except Exception as error:
            raise ValueError("decimal values must be finite decimal strings") from error
        if not decimal_value.is_finite():
            raise ValueError("decimal values must be finite")
        return decimal_value
    raise ValueError("decimal values must be supplied as strings")


DecimalString: TypeAlias = Annotated[
    Decimal,
    BeforeValidator(_decimal_from_lossless_value),
    PlainSerializer(
        lambda value: format(value, "f"), return_type=str, when_used="json"
    ),
]


def _money_value(value: Decimal) -> Decimal:
    if value < 0 or value > Decimal("99999999.99"):
        raise ValueError("money values must fit the order total precision")
    if value != value.quantize(Decimal("0.01")):
        raise ValueError("money values may have at most two decimal places")
    return value


def _quantity_value(value: Decimal) -> Decimal:
    if value < 0 or value > Decimal("999999999.999"):
        raise ValueError("quantity values must fit inventory precision")
    if value != value.quantize(Decimal("0.001")):
        raise ValueError("quantity values may have at most three decimal places")
    return value


MoneyString: TypeAlias = Annotated[DecimalString, AfterValidator(_money_value)]
QuantityString: TypeAlias = Annotated[DecimalString, AfterValidator(_quantity_value)]


def _utc_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("event timestamps must include a UTC offset")
    return value.astimezone(UTC)


def _order_creation_timestamp(value: datetime) -> datetime:
    """Treat legacy naive order timestamps as UTC without changing date grouping."""
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class OrderSubmittedPayload(ContractModel):
    order_id: int = Field(gt=0)
    status: Literal["SUBMITTED"] = "SUBMITTED"


class OrderAcceptedPayload(ContractModel):
    order_id: int = Field(gt=0)
    status: Literal["ACCEPTED"] = "ACCEPTED"


class OrderCompletedPayload(ContractModel):
    order_id: int = Field(gt=0)
    total: MoneyString = Field(ge=0)
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def normalize_creation_time(cls, value: datetime) -> datetime:
        return _order_creation_timestamp(value)


class OrderCancelledPayload(ContractModel):
    order_id: int = Field(gt=0)
    status: Literal["CANCELLED"] = "CANCELLED"


class OrderDeletedPayload(ContractModel):
    order_id: int = Field(gt=0)
    prior_status: str = Field(min_length=1, max_length=50)
    total: MoneyString = Field(ge=0)
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def normalize_creation_time(cls, value: datetime) -> datetime:
        return _order_creation_timestamp(value)


class MenuUpdatedPayload(ContractModel):
    operation: Literal["created", "edited", "deactivated", "deleted"]
    target_type: Literal["menu", "menu_item"]
    target_id: int = Field(gt=0)
    menu_id: int = Field(gt=0)
    affected_menu_item_ids: tuple[int, ...] = ()

    @field_validator("affected_menu_item_ids")
    @classmethod
    def validate_affected_ids(cls, values: tuple[int, ...]) -> tuple[int, ...]:
        if any(value <= 0 for value in values):
            raise ValueError("affected menu item IDs must be positive")
        if len(values) != len(set(values)):
            raise ValueError("affected menu item IDs must be unique")
        return values


class InventoryStateChangedPayload(ContractModel):
    ingredient_id: int = Field(gt=0)
    ingredient_name: str = Field(min_length=1, max_length=255)
    unit: Literal["g", "ml", "piece"]
    quantity: QuantityString = Field(ge=0)
    reorder_threshold: QuantityString = Field(ge=0)
    is_active: bool
    is_low: bool
    episode_id: UUID | None = None
    episode_transition: Literal["opened", "resolved"] | None = None
    resolution_reason: (
        Literal["stock_recovered", "threshold_changed", "archived"] | None
    ) = None

    @model_validator(mode="after")
    def validate_state_and_episode(self) -> InventoryStateChangedPayload:
        expected_low = self.is_active and self.quantity <= self.reorder_threshold
        if self.is_low != expected_low:
            raise ValueError("is_low must match active quantity and threshold")
        if self.is_low and self.episode_id is None:
            raise ValueError("low inventory state requires an episode ID")
        if self.episode_transition == "resolved":
            if self.episode_id is None or self.resolution_reason is None:
                raise ValueError("episode resolution requires its ID and reason")
        elif self.resolution_reason is not None:
            raise ValueError("resolution reason requires a resolved episode")
        return self


class InventoryLowPayload(ContractModel):
    ingredient_id: int = Field(gt=0)
    episode_id: UUID
    ingredient_name: str = Field(min_length=1, max_length=255)
    unit: Literal["g", "ml", "piece"]
    opening_quantity: QuantityString = Field(ge=0)
    reorder_threshold: QuantityString = Field(ge=0)
    opened_at: datetime

    @field_validator("opened_at")
    @classmethod
    def require_utc_open_time(cls, value: datetime) -> datetime:
        return _utc_timestamp(value)


class EventEnvelopeBase(ContractModel):
    event_id: UUID = Field(default_factory=uuid4)
    event_type: str
    schema_version: int
    organization_id: UUID
    restaurant_id: int = Field(gt=0)
    aggregate_type: str
    aggregate_id: str = Field(min_length=1, max_length=100)
    aggregate_revision: int = Field(ge=1)
    occurred_at: datetime
    correlation_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$",
    )

    @field_validator("occurred_at")
    @classmethod
    def normalize_occurred_time(cls, value: datetime) -> datetime:
        return _utc_timestamp(value)


class OrderSubmittedEvent(EventEnvelopeBase):
    event_type: Literal["order.submitted.v1"] = "order.submitted.v1"
    schema_version: Literal[1] = 1
    aggregate_type: Literal["order"] = "order"
    payload: OrderSubmittedPayload

    @model_validator(mode="after")
    def identity_matches_payload(self) -> OrderSubmittedEvent:
        if self.aggregate_id != str(self.payload.order_id):
            raise ValueError("order aggregate ID must match payload order_id")
        return self


class OrderAcceptedEvent(EventEnvelopeBase):
    event_type: Literal["order.accepted.v1"] = "order.accepted.v1"
    schema_version: Literal[1] = 1
    aggregate_type: Literal["order"] = "order"
    payload: OrderAcceptedPayload

    @model_validator(mode="after")
    def identity_matches_payload(self) -> OrderAcceptedEvent:
        if self.aggregate_id != str(self.payload.order_id):
            raise ValueError("order aggregate ID must match payload order_id")
        return self


class OrderCompletedEvent(EventEnvelopeBase):
    event_type: Literal["order.completed.v1"] = "order.completed.v1"
    schema_version: Literal[1] = 1
    aggregate_type: Literal["order"] = "order"
    payload: OrderCompletedPayload

    @model_validator(mode="after")
    def identity_matches_payload(self) -> OrderCompletedEvent:
        if self.aggregate_id != str(self.payload.order_id):
            raise ValueError("order aggregate ID must match payload order_id")
        return self


class OrderCancelledEvent(EventEnvelopeBase):
    event_type: Literal["order.cancelled.v1"] = "order.cancelled.v1"
    schema_version: Literal[1] = 1
    aggregate_type: Literal["order"] = "order"
    payload: OrderCancelledPayload

    @model_validator(mode="after")
    def identity_matches_payload(self) -> OrderCancelledEvent:
        if self.aggregate_id != str(self.payload.order_id):
            raise ValueError("order aggregate ID must match payload order_id")
        return self


class OrderDeletedEvent(EventEnvelopeBase):
    event_type: Literal["order.deleted.v1"] = "order.deleted.v1"
    schema_version: Literal[1] = 1
    aggregate_type: Literal["order"] = "order"
    payload: OrderDeletedPayload

    @model_validator(mode="after")
    def identity_matches_payload(self) -> OrderDeletedEvent:
        if self.aggregate_id != str(self.payload.order_id):
            raise ValueError("order aggregate ID must match payload order_id")
        return self


class MenuUpdatedEvent(EventEnvelopeBase):
    event_type: Literal["menu.updated.v1"] = "menu.updated.v1"
    schema_version: Literal[1] = 1
    aggregate_type: Literal["menu", "menu_item"]
    payload: MenuUpdatedPayload

    @model_validator(mode="after")
    def identity_matches_payload(self) -> MenuUpdatedEvent:
        if self.aggregate_type != self.payload.target_type:
            raise ValueError("menu aggregate type must match payload target_type")
        if self.aggregate_id != str(self.payload.target_id):
            raise ValueError("menu aggregate ID must match payload target_id")
        return self


class InventoryStateChangedEvent(EventEnvelopeBase):
    event_type: Literal["inventory.state_changed.v1"] = "inventory.state_changed.v1"
    schema_version: Literal[1] = 1
    aggregate_type: Literal["ingredient"] = "ingredient"
    payload: InventoryStateChangedPayload

    @model_validator(mode="after")
    def identity_matches_payload(self) -> InventoryStateChangedEvent:
        if self.aggregate_id != str(self.payload.ingredient_id):
            raise ValueError("ingredient aggregate ID must match payload ingredient_id")
        return self


class InventoryLowEvent(EventEnvelopeBase):
    event_type: Literal["inventory.low.v1"] = "inventory.low.v1"
    schema_version: Literal[1] = 1
    aggregate_type: Literal["ingredient"] = "ingredient"
    payload: InventoryLowPayload

    @model_validator(mode="after")
    def identity_matches_payload(self) -> InventoryLowEvent:
        if self.aggregate_id != str(self.payload.ingredient_id):
            raise ValueError("ingredient aggregate ID must match payload ingredient_id")
        return self


EventEnvelope: TypeAlias = Annotated[
    OrderSubmittedEvent
    | OrderAcceptedEvent
    | OrderCompletedEvent
    | OrderCancelledEvent
    | OrderDeletedEvent
    | MenuUpdatedEvent
    | InventoryStateChangedEvent
    | InventoryLowEvent,
    Field(discriminator="event_type"),
]

EVENT_ENVELOPE_ADAPTER: TypeAdapter[EventEnvelope] = TypeAdapter(EventEnvelope)
SUPPORTED_EVENT_TYPES = frozenset(
    {
        "order.submitted.v1",
        "order.accepted.v1",
        "order.completed.v1",
        "order.cancelled.v1",
        "order.deleted.v1",
        "menu.updated.v1",
        "inventory.state_changed.v1",
        "inventory.low.v1",
    }
)


class UnsupportedEventVersion(ValueError):
    """Raised when a persisted event uses an unknown contract version."""


def serialize_event(event: EventEnvelope) -> dict[str, object]:
    """Serialize a validated envelope to JSON-safe, lossless values."""
    return json.loads(event.model_dump_json())


def deserialize_event(
    value: str | bytes | bytearray | dict[str, object],
) -> EventEnvelope:
    """Validate the event type/version before constructing a typed envelope."""
    try:
        raw = json.loads(value) if isinstance(value, (str, bytes, bytearray)) else value
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ValueError("event envelope must contain valid JSON") from error
    if not isinstance(raw, dict):
        raise ValueError("event envelope must be a JSON object")
    event_type = raw.get("event_type")
    version = raw.get("schema_version")
    if not isinstance(event_type, str) or event_type not in SUPPORTED_EVENT_TYPES:
        raise UnsupportedEventVersion(f"unsupported event type: {event_type!r}")
    if version != 1 or isinstance(version, bool):
        raise UnsupportedEventVersion(
            f"unsupported schema version {version!r} for {event_type}"
        )
    try:
        return EVENT_ENVELOPE_ADAPTER.validate_python(raw)
    except ValidationError as error:
        raise ValueError("event envelope failed contract validation") from error
