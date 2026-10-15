"""Inventory write transactions; ledger and balance always change together."""

from dataclasses import asdict
import hashlib
import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from uuid import UUID, uuid4
from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.events.service import CommandEvents
from app.core.errors import ConflictError, ValidationError
from app.modules.auth.domain.principal import AuthenticatedPrincipal
from app.modules.audit.service import record
from app.modules.inventory.domain.policies import quantity
from app.modules.inventory.repo.models import (
    Ingredient,
    InventoryBalance,
    InventoryLowStockEpisode,
    InventoryMovement,
)
from app.modules.inventory.repo.queries import (
    InventoryRepository,
    InventoryTransitionRepository,
)
from app.modules.inventory.domain.transitions import (
    InventoryEpisodeFacts,
    InventoryEpisodeTransition,
    InventoryStateSnapshot,
    InventoryTransition,
    InventoryTransitionSource,
    episode_resolution_reason,
    inventory_state_changed,
    low_episode_transition,
)
from app.modules.inventory.domain.commands import (
    CreateIngredient,
    UpdateIngredient,
    IngredientView,
    ChangeStock,
)
from app.modules.tenancy.access import AccessService
from app.modules.tenancy.domain.policies import AccessContext


def inventory_state_snapshot(
    organization_id: UUID, item: Ingredient, balance: InventoryBalance
) -> InventoryStateSnapshot:
    """Copy transition-relevant values before mutating inventory ORM rows."""
    return InventoryStateSnapshot(
        organization_id=organization_id,
        restaurant_id=item.restaurant_id,
        ingredient_id=item.id,
        state_revision=item.state_revision,
        ingredient_name=item.name,
        unit=item.unit,  # type: ignore[arg-type]
        quantity=balance.quantity,
        reorder_threshold=item.reorder_threshold,
        is_active=item.is_active,
    )


def _episode_facts(episode: InventoryLowStockEpisode) -> InventoryEpisodeFacts:
    return InventoryEpisodeFacts(
        episode_id=episode.episode_id,
        organization_id=episode.organization_id,
        restaurant_id=episode.restaurant_id,
        ingredient_id=episode.ingredient_id,
        ingredient_name=episode.ingredient_name,
        unit=episode.unit,  # type: ignore[arg-type]
        opening_quantity=episode.opening_quantity,
        opening_reorder_threshold=episode.opening_reorder_threshold,
        opened_at=episode.opened_at,
        opening_revision=episode.opening_revision,
        opening_source=episode.opening_source,  # type: ignore[arg-type]
        opening_actor_user_id=episode.opening_actor_user_id,
        opening_order_id=episode.opening_order_id,
        notification_suppressed=episode.notification_suppressed,
        resolved_at=episode.resolved_at,
        resolution_reason=episode.resolution_reason,  # type: ignore[arg-type]
        closing_quantity=episode.closing_quantity,
        closing_reorder_threshold=episode.closing_reorder_threshold,
        closing_is_active=episode.closing_is_active,
        resolution_revision=episode.resolution_revision,
        resolution_source=episode.resolution_source,  # type: ignore[arg-type]
        resolution_actor_user_id=episode.resolution_actor_user_id,
        resolution_order_id=episode.resolution_order_id,
    )


def _transition_snapshot(
    state: InventoryStateSnapshot,
    episode: InventoryLowStockEpisode | None = None,
    episode_transition: InventoryEpisodeTransition | None = None,
) -> InventoryTransition:
    facts = _episode_facts(episode) if episode is not None else None
    episode_id = (
        episode.episode_id
        if episode is not None
        else episode_transition.episode_id
        if episode_transition is not None
        else None
    )
    return InventoryTransition(
        organization_id=state.organization_id,
        restaurant_id=state.restaurant_id,
        ingredient_id=state.ingredient_id,
        state_revision=state.state_revision,
        ingredient_name=state.ingredient_name,
        unit=state.unit,
        quantity=state.quantity,
        reorder_threshold=state.reorder_threshold,
        is_active=state.is_active,
        episode_id=episode_id,
        episode_transition=episode_transition,
        episode_facts=facts,
    )


async def record_inventory_transition(
    session: AsyncSession,
    organization_id: UUID,
    item: Ingredient,
    balance: InventoryBalance,
    before: InventoryStateSnapshot | None,
    *,
    source: InventoryTransitionSource,
    actor_user_id: UUID | None,
    order_id: int | None = None,
    occurred_at: datetime | None = None,
    command_events: CommandEvents | None = None,
) -> InventoryTransition | None:
    """Persist a state revision and episode boundary in the caller's transaction.

    The caller must hold the restaurant lock and the ingredient row lock (after
    any order lock). This is the shared writer used by manual stock commands and
    order acceptance; it never commits or changes the physical-count version.
    """
    after = inventory_state_snapshot(organization_id, item, balance)
    if not inventory_state_changed(before, after):
        return None

    if before is None:
        # A new ingredient's initial authoritative state is its first revision.
        item.state_revision = max(1, item.state_revision)
    else:
        if item.state_revision != before.state_revision:
            raise RuntimeError("inventory state revision changed outside its lock")
        item.state_revision = before.state_revision + 1
    after = inventory_state_snapshot(organization_id, item, balance)

    repository = InventoryTransitionRepository(session)
    episode = await repository.open_episode(item.id, lock=True)
    transition_fact: InventoryEpisodeTransition | None = None
    boundary = low_episode_transition(before, after)
    if boundary == "opened":
        if episode is not None:
            raise RuntimeError("normal inventory state has an unresolved low episode")
        timestamp = occurred_at or datetime.now(timezone.utc)
        episode = InventoryLowStockEpisode(
            episode_id=uuid4(),
            organization_id=organization_id,
            restaurant_id=item.restaurant_id,
            ingredient_id=item.id,
            ingredient_name=item.name,
            unit=item.unit,
            opening_quantity=balance.quantity,
            opening_reorder_threshold=item.reorder_threshold,
            opened_at=timestamp,
            opening_revision=item.state_revision,
            opening_source=source,
            opening_actor_user_id=actor_user_id,
            opening_order_id=order_id,
            notification_suppressed=False,
        )
        repository.add_episode(episode)
        transition_fact = InventoryEpisodeTransition(
            episode_id=episode.episode_id, kind="opened", occurred_at=timestamp
        )
    elif boundary == "resolved" and before is not None and episode is not None:
        timestamp = occurred_at or datetime.now(timezone.utc)
        reason = episode_resolution_reason(before, after)
        episode.resolved_at = timestamp
        episode.resolution_reason = reason
        episode.closing_quantity = balance.quantity
        episode.closing_reorder_threshold = item.reorder_threshold
        episode.closing_is_active = item.is_active
        episode.resolution_revision = item.state_revision
        episode.resolution_source = source
        episode.resolution_actor_user_id = actor_user_id
        episode.resolution_order_id = order_id
        transition_fact = InventoryEpisodeTransition(
            episode_id=episode.episode_id,
            kind="resolved",
            occurred_at=timestamp,
            resolution_reason=reason,
        )
    elif after.is_low and before is not None and before.is_low:
        # A low legacy row may have no episode until the approved initialization
        # operation records a truthful baseline; never invent one here.
        pass

    await session.flush()
    transition = _transition_snapshot(after, episode, transition_fact)
    events = command_events or CommandEvents()
    await events.append(
        session,
        event_type="inventory.state_changed.v1",
        organization_id=organization_id,
        restaurant_id=item.restaurant_id,
        aggregate_type="ingredient",
        aggregate_id=item.id,
        aggregate_revision=transition.state_revision,
        payload={
            "ingredient_id": item.id,
            "ingredient_name": transition.ingredient_name,
            "unit": transition.unit,
            "quantity": transition.quantity,
            "reorder_threshold": transition.reorder_threshold,
            "is_active": transition.is_active,
            "is_low": transition.is_low,
            "episode_id": transition.episode_id,
            "episode_transition": transition_fact.kind if transition_fact else None,
            "resolution_reason": transition_fact.resolution_reason
            if transition_fact
            else None,
        },
    )
    if transition_fact is not None and transition_fact.kind == "opened":
        assert transition.episode_facts is not None
        facts = transition.episode_facts
        await events.append(
            session,
            event_type="inventory.low.v1",
            organization_id=organization_id,
            restaurant_id=item.restaurant_id,
            aggregate_type="ingredient",
            aggregate_id=item.id,
            aggregate_revision=facts.opening_revision,
            payload={
                "ingredient_id": item.id,
                "episode_id": facts.episode_id,
                "ingredient_name": facts.ingredient_name,
                "unit": facts.unit,
                "opening_quantity": facts.opening_quantity,
                "reorder_threshold": facts.opening_reorder_threshold,
                "opened_at": facts.opened_at,
            },
        )
    return transition


async def load_inventory_state(
    session: AsyncSession,
    organization_id: UUID,
    restaurant_id: int,
    ingredient_id: int,
    *,
    lock: bool = False,
) -> InventoryTransition:
    """Load authoritative state for trusted internal consumers.

    When `lock` is true this method takes the restaurant row first and then the
    ingredient/balance rows, giving alert consumers the same timing boundary as
    inventory writes. The caller owns the transaction.
    """
    repository = InventoryTransitionRepository(session)
    if lock:
        await repository.lock_restaurant_for_organization(
            organization_id, restaurant_id
        )
    item, balance = await repository.ingredient_state(
        organization_id, restaurant_id, ingredient_id, lock=lock
    )
    episode = await repository.open_episode(ingredient_id, lock=lock)
    return _transition_snapshot(
        inventory_state_snapshot(organization_id, item, balance), episode
    )


async def load_inventory_episode_facts(
    session: AsyncSession, episode_id: UUID
) -> InventoryEpisodeFacts | None:
    """Return immutable producer-owned episode facts to trusted consumers."""
    episode = await InventoryTransitionRepository(session).episode_by_id(episode_id)
    return _episode_facts(episode) if episode is not None else None


async def load_inventory_episode_history(
    session: AsyncSession, organization_id: UUID, restaurant_id: int
) -> list[InventoryEpisodeFacts]:
    """T8 maintenance hook for retained producer opening/closing facts."""
    repository = InventoryTransitionRepository(session)
    episodes = await repository.episodes_for_restaurant(organization_id, restaurant_id)
    return [_episode_facts(episode) for episode in episodes]


async def load_inventory_restaurant_states(
    session: AsyncSession,
    organization_id: UUID,
    restaurant_id: int,
    *,
    lock: bool = False,
) -> list[InventoryTransition]:
    """Trusted bulk read/init hook; optional locks follow restaurant/ingredient order."""
    repository = InventoryTransitionRepository(session)
    if lock:
        await repository.lock_restaurant_for_organization(
            organization_id, restaurant_id
        )
    rows = await repository.ingredients_for_restaurant(
        organization_id, restaurant_id, lock=lock
    )
    return [
        _transition_snapshot(
            inventory_state_snapshot(organization_id, item, balance),
            await repository.open_episode(item.id, lock=lock),
        )
        for item, balance in rows
    ]


async def record_baseline_inventory_episode(
    session: AsyncSession,
    organization_id: UUID,
    restaurant_id: int,
    ingredient_id: int,
    *,
    observed_at: datetime | None = None,
) -> InventoryTransition:
    """Idempotently mark current low stock as a suppressed initialization baseline.

    `opened_at` is the observation time. This method does not advance the state
    revision or claim that the ingredient became low before initialization.
    """
    repository = InventoryTransitionRepository(session)
    await repository.lock_restaurant_for_organization(organization_id, restaurant_id)
    item, balance = await repository.ingredient_state(
        organization_id, restaurant_id, ingredient_id, lock=True
    )
    episode = await repository.open_episode(ingredient_id, lock=True)
    if (
        episode is None
        and item.is_active
        and balance.quantity <= item.reorder_threshold
    ):
        timestamp = observed_at or datetime.now(timezone.utc)
        episode = InventoryLowStockEpisode(
            episode_id=uuid4(),
            organization_id=organization_id,
            restaurant_id=restaurant_id,
            ingredient_id=ingredient_id,
            ingredient_name=item.name,
            unit=item.unit,
            opening_quantity=balance.quantity,
            opening_reorder_threshold=item.reorder_threshold,
            opened_at=timestamp,
            opening_revision=item.state_revision,
            opening_source="maintenance_initialization",
            opening_actor_user_id=None,
            opening_order_id=None,
            notification_suppressed=True,
        )
        repository.add_episode(episode)
        await session.flush()
    return _transition_snapshot(
        inventory_state_snapshot(organization_id, item, balance), episode
    )


def fingerprint(data: CreateIngredient | ChangeStock) -> str:
    payload = asdict(data)
    payload.pop("idempotency_key")
    for key in ("quantity", "opening_quantity", "reorder_threshold"):
        if key in payload:
            value = payload[key]
            if isinstance(value, Decimal):
                if value.is_zero():
                    payload[key] = "0"
                elif value.is_finite():
                    try:
                        payload[key] = str(value.normalize())
                    except InvalidOperation:
                        payload[key] = str(value)
                else:
                    payload[key] = str(value)
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def response(item: Ingredient, balance: InventoryBalance) -> IngredientView:
    return IngredientView(
        id=item.id,
        restaurant_id=item.restaurant_id,
        name=item.name,
        unit=item.unit,
        reorder_threshold=item.reorder_threshold,
        is_active=item.is_active,
        quantity=balance.quantity,
        version=balance.version,
        low_stock=item.is_active and balance.quantity <= item.reorder_threshold,
    )


class InventoryService:
    def __init__(
        self, session: AsyncSession, principal: AuthenticatedPrincipal
    ) -> None:
        self.session = session
        self.access = AccessService(session, principal)

    @staticmethod
    def validate_ingredient(name: str, unit: str) -> None:
        if (
            name != name.strip()
            or not name
            or len(name) > 255
            or len(name.casefold()) > 765
            or unit not in {"g", "ml", "piece"}
        ):
            raise ValidationError("Valid ingredient name and base unit are required")

    async def prepare(
        self, restaurant_id: int, capability: str, *, lock: bool = False
    ) -> tuple[AccessContext, InventoryRepository]:
        context = await self.access.current(lock=lock)
        await self.access.restaurant(context, restaurant_id, capability)
        repo = InventoryRepository(self.session, context)
        if lock:
            await repo.lock_restaurant(restaurant_id)
        return context, repo

    async def list_ingredients(
        self, restaurant_id: int, limit: int = 100, offset: int = 0
    ) -> list[IngredientView]:
        _, repo = await self.prepare(restaurant_id, "inventory.read")
        return [
            response(item, balance)
            for item, balance in await repo.ingredients(restaurant_id, limit, offset)
        ]

    async def create(
        self, restaurant_id: int, data: CreateIngredient
    ) -> IngredientView:
        async with self.session.begin():
            context, repo = await self.prepare(
                restaurant_id, "inventory.manage", lock=True
            )
            self.validate_ingredient(data.name, data.unit)
            opening = quantity(data.opening_quantity)
            threshold = quantity(data.reorder_threshold)
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", data.idempotency_key):
                raise ValidationError("Invalid idempotency key")
            signature = fingerprint(data)
            replay = await repo.replay(restaurant_id, data.idempotency_key)
            if replay:
                if replay.request_fingerprint != signature:
                    raise ConflictError(
                        "Idempotency key was already used for a different request"
                    )
                item, balance = await repo.ingredient(
                    restaurant_id, replay.ingredient_id
                )
                return response(item, balance)
            if await repo.duplicate(restaurant_id, data.name.casefold()):
                raise ConflictError("An ingredient with this name already exists")
            item = Ingredient(
                restaurant_id=restaurant_id,
                name=data.name,
                normalized_name=data.name.casefold(),
                unit=data.unit,
                reorder_threshold=threshold,
                is_active=True,
                state_revision=1,
            )
            self.session.add(item)
            await self.session.flush()
            balance = InventoryBalance(
                ingredient_id=item.id, quantity=opening, version=1
            )
            self.session.add(balance)
            self.session.add(
                InventoryMovement(
                    ingredient_id=item.id,
                    kind="opening",
                    quantity_delta=opening,
                    balance_after=opening,
                    version_after=1,
                    actor_user_id=context.user_id,
                    reason="Opening stock",
                    idempotency_key=data.idempotency_key,
                    request_fingerprint=signature,
                )
            )
            await record_inventory_transition(
                self.session,
                context.organization_id,
                item,
                balance,
                None,
                source="ingredient_creation",
                actor_user_id=context.user_id,
            )
            record(
                self.session,
                context,
                "inventory.ingredient.created",
                "ingredient",
                item.id,
                restaurant_id=restaurant_id,
                changes={"quantity": str(opening)},
            )
            await self.session.flush()
            return response(item, balance)

    async def update(
        self, restaurant_id: int, ingredient_id: int, data: UpdateIngredient
    ) -> IngredientView:
        async with self.session.begin():
            context, repo = await self.prepare(
                restaurant_id, "inventory.manage", lock=True
            )
            item, balance = await repo.ingredient(
                restaurant_id, ingredient_id, lock=True
            )
            self.validate_ingredient(data.name, data.unit)
            if await repo.duplicate(restaurant_id, data.name.casefold(), ingredient_id):
                raise ConflictError("An ingredient with this name already exists")
            if item.unit != data.unit and await repo.has_history(ingredient_id):
                raise ConflictError("Unit cannot change after stock history exists")
            if not data.is_active and balance.quantity > 0:
                raise ConflictError(
                    "Record remaining stock as waste or count it to zero before archiving"
                )
            before = inventory_state_snapshot(context.organization_id, item, balance)
            item.name = data.name
            item.normalized_name = data.name.casefold()
            item.unit = data.unit
            item.reorder_threshold = quantity(data.reorder_threshold)
            item.is_active = data.is_active
            await record_inventory_transition(
                self.session,
                context.organization_id,
                item,
                balance,
                before,
                source="ingredient_update",
                actor_user_id=context.user_id,
            )
            record(
                self.session,
                context,
                "inventory.ingredient.updated",
                "ingredient",
                ingredient_id,
                restaurant_id=restaurant_id,
                changes={"fields": ["name", "unit", "reorder_threshold", "is_active"]},
            )
            await self.session.flush()
            return response(item, balance)

    async def change(
        self, restaurant_id: int, ingredient_id: int, data: ChangeStock
    ) -> InventoryMovement:
        async with self.session.begin():
            context, repo = await self.prepare(
                restaurant_id, "inventory.manage", lock=True
            )
            item, balance = await repo.ingredient(
                restaurant_id, ingredient_id, lock=True
            )
            if (
                data.kind not in {"receipt", "waste", "count"}
                or not data.reason.strip()
                or len(data.reason) > 500
            ):
                raise ValidationError("Valid stock action and reason are required")
            amount = quantity(data.quantity, positive=data.kind != "count")
            if data.kind == "count" and data.expected_version is None:
                raise ValidationError("Physical counts require the stock version")
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", data.idempotency_key):
                raise ValidationError("Invalid idempotency key")
            signature = fingerprint(data)
            replay = await repo.replay(
                restaurant_id, data.idempotency_key, ingredient_id
            )
            if replay:
                if replay.request_fingerprint != signature:
                    raise ConflictError(
                        "Idempotency key was already used for a different request"
                    )
                return replay
            if not item.is_active:
                raise ConflictError("Restore this ingredient before changing stock")
            if data.kind == "count":
                if data.expected_version != balance.version:
                    raise ConflictError(
                        "Stock changed since this count began. Refresh and count again"
                    )
                delta = amount - balance.quantity
            else:
                delta = amount if data.kind == "receipt" else -amount
            after = balance.quantity + delta
            if after < 0:
                raise ConflictError("Insufficient stock")
            quantity(after)
            before = inventory_state_snapshot(context.organization_id, item, balance)
            balance.quantity = after
            balance.version += 1
            movement = InventoryMovement(
                ingredient_id=ingredient_id,
                kind=data.kind,
                quantity_delta=delta,
                balance_after=after,
                version_after=balance.version,
                actor_user_id=context.user_id,
                reason=data.reason,
                idempotency_key=data.idempotency_key,
                request_fingerprint=signature,
            )
            self.session.add(movement)
            await record_inventory_transition(
                self.session,
                context.organization_id,
                item,
                balance,
                before,
                source="stock_command",
                actor_user_id=context.user_id,
            )
            record(
                self.session,
                context,
                "inventory.stock." + data.kind,
                "ingredient",
                ingredient_id,
                restaurant_id=restaurant_id,
                changes={"quantity": str(delta)},
            )
            await self.session.flush()
            return movement

    async def history(
        self, restaurant_id: int, ingredient_id: int, limit: int, offset: int
    ) -> list[InventoryMovement]:
        _, repo = await self.prepare(restaurant_id, "inventory.read")
        await repo.ingredient(restaurant_id, ingredient_id)
        return await repo.movements(ingredient_id, limit, offset)
