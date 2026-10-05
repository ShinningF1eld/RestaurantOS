"""Inventory write transactions; ledger and balance always change together."""

from dataclasses import asdict
import hashlib
import json
import re
from decimal import Decimal, InvalidOperation
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.errors import ConflictError, ValidationError
from app.modules.auth.domain.principal import AuthenticatedPrincipal
from app.modules.audit.service import record
from app.modules.inventory.domain.policies import quantity
from app.modules.inventory.repo.models import (
    Ingredient,
    InventoryBalance,
    InventoryMovement,
)
from app.modules.inventory.repo.queries import InventoryRepository
from app.modules.inventory.domain.commands import (
    CreateIngredient,
    UpdateIngredient,
    IngredientView,
    ChangeStock,
)
from app.modules.tenancy.access import AccessService
from app.modules.tenancy.domain.policies import AccessContext


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
            item.name = data.name
            item.normalized_name = data.name.casefold()
            item.unit = data.unit
            item.reorder_threshold = quantity(data.reorder_threshold)
            item.is_active = data.is_active
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
