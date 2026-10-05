"""Framework-independent recipe commands."""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class RecipeComponentInput:
    ingredient_id: int
    quantity: Decimal


@dataclass(frozen=True, slots=True)
class ReplaceRecipe:
    inventory_tracking: bool
    components: tuple[RecipeComponentInput, ...]
