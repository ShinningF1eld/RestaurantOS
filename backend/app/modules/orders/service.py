"""Order application service and framework-independent command inputs."""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
import hashlib
import json
import re
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.modules.audit.service import record
from app.modules.auth.domain.principal import AuthenticatedPrincipal
from app.modules.catalog.repo.models import MenuItem
from app.modules.inventory.repo.models import (
    Ingredient,
    InventoryBalance,
    InventoryMovement,
)
from app.modules.inventory.repo.queries import InventoryRepository
from app.modules.orders.domain.commands import (
    CreateOrder as CreateOrder,
    OrderItemCommand as OrderItemCommand,
    UpdateOrder as UpdateOrder,
)
from app.modules.orders.domain.policies import (
    ensure_order_items_mutable,
    ensure_valid_order_transition,
    ensure_valid_payment_status,
)
from app.modules.orders.domain.snapshots import creation_response_snapshot
from app.modules.orders.repo.models import Order, OrderItem, OrderSubmission
from app.modules.orders.repo.queries import OrderRepository
from app.modules.recipes.repo.queries import get_recipe_components
from app.modules.tenancy.access import AccessService
from app.modules.tenancy.domain.policies import AccessContext, authorize_order_update


@dataclass(frozen=True, slots=True)
class OrderPage:
    """A typed order-list result independent of API response schemas."""

    items: tuple[Order, ...]
    total: int
    limit: int
    offset: int


class OrderRepositoryProtocol(Protocol):
    """Persistence operations required by ``OrderService``."""

    async def restaurant_exists(self, restaurant_id: int) -> bool: ...

    async def get_by_id(self, order_id: int, *, lock: bool = False) -> Order | None: ...

    async def list_for_restaurant(
        self, restaurant_id: int, limit: int, offset: int
    ) -> Sequence[Order]: ...

    async def count_for_restaurant(self, restaurant_id: int) -> int: ...

    async def menu_items_for_restaurant(
        self, restaurant_id: int, menu_item_ids: Sequence[int]
    ) -> Sequence[MenuItem]: ...

    async def submission(
        self, restaurant_id: int, key: str
    ) -> OrderSubmission | None: ...

    async def add_submission(self, submission: OrderSubmission) -> None: ...

    async def inventory_balances(
        self, restaurant_id: int, ingredient_ids: Sequence[int]
    ) -> list[tuple[Ingredient, InventoryBalance]]: ...

    async def lock_inventory_balances(
        self, restaurant_id: int, ingredient_ids: Sequence[int]
    ) -> list[tuple[Ingredient, InventoryBalance]]: ...

    async def has_order_history(self, order_id: int) -> bool: ...

    async def add(self, order: Order) -> None: ...

    async def delete(self, order: Order) -> None: ...

    async def flush(self) -> None: ...


def _request_fingerprint(command: CreateOrder) -> str:
    """Hash the normalized business payload without its idempotency key."""
    payload = {
        "table_number": command.table_number,
        "customer_name": command.customer_name,
        "notes": command.notes,
        "items": [
            {
                "menu_item_id": int(item.menu_item_id),
                "quantity": int(item.quantity),
                "notes": item.notes,
            }
            for item in command.items
        ],
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class OrderService:
    """Coordinates order use cases and owns every order write transaction."""

    def __init__(
        self,
        session: AsyncSession,
        principal: AuthenticatedPrincipal,
        repository: OrderRepositoryProtocol | None = None,
    ) -> None:
        self._session = session
        self._repository = repository
        self._access = AccessService(session, principal)

    async def _prepare(self, *, lock: bool = False) -> AccessContext:
        context = await self._access.current(lock=lock)
        self._orders = self._repository or OrderRepository(self._session, context)
        return context

    async def create(
        self, restaurant_id: int, command: CreateOrder
    ) -> dict[str, object]:
        """Create a draft order, validating stock without reserving or deducting it."""
        async with self._session.begin():
            context = await self._prepare(lock=True)
            await self._access.restaurant(context, restaurant_id, "order.create")
            if not await self._orders.restaurant_exists(restaurant_id):
                raise NotFoundError("Restaurant not found")
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", command.idempotency_key):
                raise ValidationError("Invalid order idempotency key")

            inventory = InventoryRepository(self._session, context)
            await inventory.lock_restaurant(restaurant_id)

            signature = _request_fingerprint(command)
            replay = await self._orders.submission(
                restaurant_id, command.idempotency_key
            )
            if replay is not None:
                if replay.request_fingerprint != signature:
                    raise ConflictError(
                        "Idempotency key was already used for a different order"
                    )
                return dict(replay.response_snapshot)

            order_items, subtotal = await self._build_order_items(
                restaurant_id, command.items
            )
            await self._check_stock(restaurant_id, order_items)

            order = Order(
                restaurant_id=restaurant_id,
                table_number=command.table_number,
                customer_name=command.customer_name,
                notes=command.notes,
                status="DRAFT",
                payment_status="UNPAID",
                subtotal=subtotal,
                total=subtotal,
                inventory_processed=False,
                items=order_items,
            )
            await self._orders.add(order)
            await self._orders.flush()
            result = await self._get_order_or_error(order.order_id)
            snapshot = creation_response_snapshot(result)
            await self._orders.add_submission(
                OrderSubmission(
                    restaurant_id=restaurant_id,
                    idempotency_key=command.idempotency_key,
                    order_id=order.order_id,
                    request_fingerprint=signature,
                    response_snapshot=snapshot,
                )
            )
            record(
                self._session,
                context,
                "order.created",
                "order",
                order.order_id,
                restaurant_id=restaurant_id,
                changes={"total": str(order.total)},
            )
            await self._orders.flush()
            return snapshot

    async def get(self, order_id: int) -> Order:
        """Return one fully loaded order."""
        context = await self._prepare()
        context.require("order.read")
        return await self._get_order_or_error(order_id)

    async def list_for_restaurant(
        self, restaurant_id: int, limit: int, offset: int
    ) -> OrderPage:
        """Return a restaurant's order page or its established not-found error."""
        context = await self._prepare()
        await self._access.restaurant(context, restaurant_id, "order.read")
        if not await self._orders.restaurant_exists(restaurant_id):
            raise NotFoundError("Restaurant not found")
        total = await self._orders.count_for_restaurant(restaurant_id)
        orders = await self._orders.list_for_restaurant(restaurant_id, limit, offset)
        return OrderPage(tuple(orders), total, limit, offset)

    async def update(self, order_id: int, command: UpdateOrder) -> Order:
        """Apply supplied order fields atomically, including inventory consumption."""
        async with self._session.begin():
            context = await self._prepare(lock=True)
            # All order writes follow restaurant -> order -> ingredient lock order.
            initial = await self._get_order_or_error(order_id)
            inventory = InventoryRepository(self._session, context)
            await inventory.lock_restaurant(initial.restaurant_id)
            order = await self._get_order_or_error(order_id, lock=True)
            authorize_order_update(
                context, command.fields, order.status, command.status
            )

            previous_status = order.status
            if command.status is not None:
                requested_status = ensure_valid_order_transition(
                    order.status, command.status
                )
                if requested_status == "SUBMITTED":
                    await self._check_stock(order.restaurant_id, order.items)
                elif previous_status != "ACCEPTED" and requested_status == "ACCEPTED":
                    await self._consume_order_stock(order, context)
                    # True also records that a deliberately untracked order was
                    # evaluated, separating it from pre-migration accepted rows.
                    order.inventory_processed = True
                order.status = requested_status

            if command.payment_status is not None:
                order.payment_status = ensure_valid_payment_status(
                    command.payment_status
                )
            if command.table_number is not None:
                order.table_number = command.table_number
            if command.customer_name is not None:
                order.customer_name = command.customer_name
            if command.notes is not None:
                order.notes = command.notes
            if command.items is not None:
                ensure_order_items_mutable(order.status)
                order_items, subtotal = await self._build_order_items(
                    order.restaurant_id, command.items
                )
                await self._check_stock(order.restaurant_id, order_items)
                order.items = order_items
                order.subtotal = subtotal
                order.total = subtotal
            await self._orders.flush()
            result = await self._get_order_or_error(order_id)
            record(
                self._session,
                context,
                "order.updated",
                "order",
                order_id,
                restaurant_id=order.restaurant_id,
                changes={
                    "fields": sorted(command.fields),
                    "status": order.status,
                    "payment_status": order.payment_status,
                    "total": str(order.total),
                },
            )
            return result

    async def delete(self, order_id: int) -> None:
        """Delete an order unless immutable stock or replay history refers to it."""
        async with self._session.begin():
            context = await self._prepare(lock=True)
            initial = await self._get_order_or_error(order_id)
            inventory = InventoryRepository(self._session, context)
            await inventory.lock_restaurant(initial.restaurant_id)
            order = await self._get_order_or_error(order_id, lock=True)
            context.require("order.delete")
            if await self._orders.has_order_history(order_id):
                raise ConflictError("Orders with inventory history cannot be deleted")
            record(
                self._session,
                context,
                "order.deleted",
                "order",
                order_id,
                restaurant_id=order.restaurant_id,
                changes={"status": order.status, "total": str(order.total)},
            )
            await self._orders.delete(order)

    async def _get_order_or_error(self, order_id: int, *, lock: bool = False) -> Order:
        order = await self._orders.get_by_id(order_id, lock=lock)
        if order is None:
            raise NotFoundError("Order not found")
        return order

    async def _check_stock(
        self, restaurant_id: int, order_items: Sequence[OrderItem]
    ) -> None:
        await self._stock_rows(restaurant_id, order_items, lock_balances=False)

    async def _consume_order_stock(self, order: Order, context: AccessContext) -> None:
        rows = await self._stock_rows(
            order.restaurant_id, order.items, lock_balances=True
        )
        for ingredient, balance, required in rows:
            after = balance.quantity - required
            balance.quantity = after
            balance.version += 1
            self._session.add(
                InventoryMovement(
                    ingredient_id=ingredient.id,
                    kind="consumption",
                    quantity_delta=-required,
                    balance_after=after,
                    version_after=balance.version,
                    actor_user_id=context.user_id,
                    reason=f"Order {order.order_id} accepted",
                    idempotency_key=None,
                    request_fingerprint=None,
                    order_id=order.order_id,
                )
            )

    async def _stock_rows(
        self,
        restaurant_id: int,
        order_items: Sequence[OrderItem],
        *,
        lock_balances: bool,
    ) -> list[tuple[Ingredient, InventoryBalance, Decimal]]:
        """Aggregate portions into exact ingredient quantities and verify stock."""
        menu_item_portions: dict[int, int] = defaultdict(int)
        for order_item in order_items:
            if order_item.menu_item_id is None:
                raise ConflictError(
                    "An order item no longer has a menu item for stock validation"
                )
            menu_item_portions[order_item.menu_item_id] += int(order_item.quantity)
        if not menu_item_portions:
            return []

        menu_items = await self._orders.menu_items_for_restaurant(
            restaurant_id, sorted(menu_item_portions)
        )
        menu_by_id = {item.menu_item_id: item for item in menu_items}
        missing_ids = sorted(set(menu_item_portions) - set(menu_by_id))
        if missing_ids:
            raise ConflictError(
                f"Menu items are no longer available for stock validation: {missing_ids}"
            )
        unavailable_ids = sorted(
            item_id
            for item_id in menu_item_portions
            if not menu_by_id[item_id].is_available
        )
        if unavailable_ids:
            raise ConflictError(f"Menu items are unavailable: {unavailable_ids}")

        tracked_item_ids = sorted(
            item_id
            for item_id, item in menu_by_id.items()
            if getattr(item, "inventory_tracking", False)
        )
        if not tracked_item_ids:
            return []

        requirements: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
        ingredients: dict[int, Ingredient] = {}
        missing_recipe_items: list[int] = []
        for menu_item_id in tracked_item_ids:
            components = await get_recipe_components(self._session, menu_item_id)
            if not components:
                missing_recipe_items.append(menu_item_id)
                continue
            portions = Decimal(menu_item_portions[menu_item_id])
            for component, ingredient in components:
                component_quantity = Decimal(str(component.quantity))
                if component_quantity <= 0:
                    raise ConflictError(
                        f"Tracked menu item {menu_item_id} has an invalid recipe"
                    )
                if ingredient.restaurant_id != restaurant_id:
                    raise ConflictError(
                        f"Tracked menu item {menu_item_id} has an invalid recipe ingredient"
                    )
                requirements[ingredient.id] += component_quantity * portions
                ingredients[ingredient.id] = ingredient
        if missing_recipe_items:
            raise ConflictError(
                "Tracked menu items require recipe ingredients: "
                + ", ".join(str(item_id) for item_id in missing_recipe_items)
            )

        ingredient_ids = sorted(requirements)
        if lock_balances:
            balances = await self._orders.lock_inventory_balances(
                restaurant_id, ingredient_ids
            )
        else:
            balances = await self._orders.inventory_balances(
                restaurant_id, ingredient_ids
            )
        balance_by_id = {ingredient.id: balance for ingredient, balance in balances}

        shortages: list[str] = []
        for ingredient_id in ingredient_ids:
            ingredient = ingredients[ingredient_id]
            balance = balance_by_id.get(ingredient_id)
            available = (
                balance.quantity
                if balance is not None and ingredient.is_active
                else Decimal("0")
            )
            required = requirements[ingredient_id]
            if available < required:
                label = ingredient.name or f"ingredient {ingredient_id}"
                state = (
                    "inactive or missing balance"
                    if balance is None or not ingredient.is_active
                    else "insufficient stock"
                )
                shortages.append(
                    f"{label}: requires {required} {ingredient.unit}, "
                    f"has {available} ({state})"
                )
        if shortages:
            raise ConflictError("Insufficient tracked stock: " + "; ".join(shortages))

        return [
            (
                ingredients[ingredient_id],
                balance_by_id[ingredient_id],
                requirements[ingredient_id],
            )
            for ingredient_id in ingredient_ids
        ]

    async def _build_order_items(
        self, restaurant_id: int, item_commands: Sequence[OrderItemCommand]
    ) -> tuple[list[OrderItem], Decimal]:
        menu_item_ids = [item.menu_item_id for item in item_commands]
        menu_items = await self._orders.menu_items_for_restaurant(
            restaurant_id, menu_item_ids
        )
        by_id = {menu_item.menu_item_id: menu_item for menu_item in menu_items}
        missing_items = [
            menu_item_id for menu_item_id in menu_item_ids if menu_item_id not in by_id
        ]
        if missing_items:
            raise NotFoundError(f"Menu items not found for restaurant: {missing_items}")
        unavailable_items = [
            menu_item.menu_item_id
            for menu_item in by_id.values()
            if not menu_item.is_available
        ]
        if unavailable_items:
            raise ValidationError(f"Menu items are unavailable: {unavailable_items}")

        subtotal = Decimal("0.00")
        order_items: list[OrderItem] = []
        for item_command in item_commands:
            menu_item = by_id[item_command.menu_item_id]
            line_total = menu_item.price * item_command.quantity
            subtotal += line_total
            order_items.append(
                OrderItem(
                    menu_item_id=menu_item.menu_item_id,
                    item_name=menu_item.name,
                    quantity=item_command.quantity,
                    unit_price=menu_item.price,
                    line_total=line_total,
                    notes=item_command.notes,
                )
            )
        return order_items, subtotal
