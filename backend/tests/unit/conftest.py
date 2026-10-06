"""Unit-test adapters for pure use-case orchestration, never HTTP bypasses."""

import socket
from ipaddress import ip_address
from threading import local
from uuid import uuid4
import pytest
from app.core.errors import NotFoundError
from app.core.config import Settings
from app.modules.auth.domain.principal import AuthenticatedPrincipal
from app.modules.tenancy.domain.policies import AccessContext
from app.modules.tenancy.domain.roles import MembershipRole


@pytest.fixture(autouse=True)
def clean_database():
    """Unit tests do not connect to or truncate PostgreSQL."""
    yield


@pytest.fixture(autouse=True)
def no_network_connections(monkeypatch):
    """Block outbound/service sockets, allowing Windows loopback socketpairs."""

    connect = socket.socket.connect
    connect_ex = socket.socket.connect_ex
    socketpair = socket.socketpair
    socketpair_scope = local()

    def is_loopback(address):
        try:
            host = address[0]
            return ip_address(host).is_loopback
        except (TypeError, ValueError):
            return False

    def reject_connection(sock, address):
        if getattr(socketpair_scope, "active", False) and is_loopback(address):
            return connect(sock, address)
        raise AssertionError("unit tests must not open network connections")

    def reject_connection_ex(sock, address):
        if getattr(socketpair_scope, "active", False) and is_loopback(address):
            return connect_ex(sock, address)
        raise AssertionError("unit tests must not open network connections")

    def scoped_socketpair(*args, **kwargs):
        socketpair_scope.active = True
        try:
            return socketpair(*args, **kwargs)
        finally:
            socketpair_scope.active = False

    monkeypatch.setattr(socket.socket, "connect", reject_connection)
    monkeypatch.setattr(socket.socket, "connect_ex", reject_connection_ex)
    monkeypatch.setattr(socket, "socketpair", scoped_socketpair)


@pytest.fixture
def unit_principal():
    return AuthenticatedPrincipal(uuid4(), "unit@example.test", "active", uuid4())


@pytest.fixture
def unit_settings_kwargs() -> dict[str, str]:
    """Required throwaway settings shared by unit config boundary tests."""
    return {
        "database_url": "postgresql+asyncpg://127.0.0.1:1/restaurantos_test",
        "auth_jwt_secret": "unit-jwt-" + "j" * 40,  # pragma: allowlist secret
        "auth_rate_limit_secret": "unit-limit-" + "r" * 40,  # pragma: allowlist secret
    }


@pytest.fixture
def unit_settings(unit_settings_kwargs) -> Settings:
    """Provide valid application settings without reading process or .env state."""
    return Settings(_env_file=None, **unit_settings_kwargs)


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
