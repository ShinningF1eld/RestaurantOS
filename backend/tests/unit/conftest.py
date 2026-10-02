"""Unit-test adapters for pure use-case orchestration, never HTTP bypasses."""

from uuid import uuid4
import pytest
from app.core.errors import NotFoundError
from app.modules.auth.domain.principal import AuthenticatedPrincipal
from app.modules.tenancy.domain.policies import AccessContext
from app.modules.tenancy.domain.roles import MembershipRole


@pytest.fixture(autouse=True)
def clean_database():
    """Unit tests do not connect to or truncate PostgreSQL."""
    yield


@pytest.fixture
def unit_principal():
    return AuthenticatedPrincipal(uuid4(), "unit@example.test", "active", uuid4())


@pytest.fixture
def fake_access(monkeypatch, unit_principal):
    context = AccessContext(
        unit_principal.id, uuid4(), uuid4(), 1, MembershipRole.OWNER, frozenset()
    )

    class FakeAccess:
        def __init__(self, session, principal):
            pass

        async def current(self, *, lock=False):
            return context

        async def restaurant(self, current, restaurant_id, capability):
            if restaurant_id == 404:
                raise NotFoundError("Restaurant not found")
            current.require(capability)

    def install(module):
        monkeypatch.setattr(module, "AccessService", FakeAccess)

    return install
