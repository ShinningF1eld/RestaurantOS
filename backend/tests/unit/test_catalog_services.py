from decimal import Decimal

import pytest

from app.core.errors import NotFoundError
from app.modules.catalog.service import CatalogService, CreateMenu, CreateMenuItem


class RecordingTransaction:
    def __init__(self) -> None:
        self.entered = False
        self.exit_exception: type[BaseException] | None = None

    async def __aenter__(self) -> None:
        self.entered = True

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        _: BaseException | None,
        __: object | None,
    ) -> bool:
        self.exit_exception = exception_type
        return False


class RecordingSession:
    def __init__(self) -> None:
        self.transaction = RecordingTransaction()

    def begin(self) -> RecordingTransaction:
        return self.transaction


class MissingRestaurantRepository:
    def __init__(self, _: RecordingSession, scope=None) -> None:
        pass

    async def get_by_id(self, _: int) -> None:
        return None


class UnusedCatalogRepository:
    def __init__(self, _: RecordingSession, scope=None) -> None:
        pass


@pytest.mark.asyncio
async def test_create_menu_uses_one_transaction_and_raises_typed_not_found(
    monkeypatch: pytest.MonkeyPatch,
    fake_access,
    unit_principal,
) -> None:
    """A failed catalog command is contained by the service transaction."""
    import app.modules.catalog.service as catalog_service_module

    fake_access(catalog_service_module)
    monkeypatch.setattr(
        catalog_service_module, "CatalogRepository", UnusedCatalogRepository
    )
    session = RecordingSession()
    service = CatalogService(session, unit_principal)  # type: ignore[arg-type]

    with pytest.raises(NotFoundError, match="Restaurant not found"):
        await service.create_menu(404, CreateMenu(name="Missing", description=None))

    assert session.transaction.entered is True
    assert session.transaction.exit_exception is NotFoundError


def test_catalog_commands_remain_framework_independent() -> None:
    """Command inputs keep API schema types out of the application boundary."""
    command = CreateMenuItem(
        name="Dish",
        description=None,
        price=Decimal("10.00"),
        is_available=True,
    )

    assert command.price == Decimal("10.00")
    assert command.is_available is True
