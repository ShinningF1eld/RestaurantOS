"""Pure role/field policy coverage without database infrastructure."""

from uuid import uuid4
import pytest
from app.core.errors import ForbiddenError
from app.modules.tenancy.domain.policies import AccessContext, authorize_order_update
from app.modules.tenancy.domain.roles import MembershipRole


def context(role):
    return AccessContext(uuid4(), uuid4(), uuid4(), 1, role, frozenset({7}))


@pytest.mark.parametrize("role", list(MembershipRole))
def test_all_roles_have_operational_reads(role):
    current = context(role)
    for capability in ("restaurant.read", "menu.read", "order.read"):
        current.require(capability)
    assert current.permits_restaurant(7)
    assert current.permits_restaurant(8) == (role is MembershipRole.OWNER)


@pytest.mark.parametrize(
    "capability",
    [
        "staff.manage",
        "analytics.read",
        "menu.manage",
        "order.create",
        "order.details.update",
        "order.payment.update",
        "order.items.manage",
        "order.delete",
    ],
)
def test_employee_cannot_manage_or_read_financial_analytics(capability):
    with pytest.raises(ForbiddenError):
        context(MembershipRole.EMPLOYEE).require(capability)


@pytest.mark.parametrize(
    "capability",
    [
        "staff.manage",
        "restaurant.create",
        "restaurant.delete",
        "order.delete",
        "audit.read",
    ],
)
def test_manager_cannot_administer_ownership_or_delete(capability):
    with pytest.raises(ForbiddenError):
        context(MembershipRole.MANAGER).require(capability)


@pytest.mark.parametrize(
    "current,requested", [("ACCEPTED", "PREPARING"), ("PREPARING", "READY")]
)
def test_employee_can_only_advance_preparation(current, requested):
    authorize_order_update(
        context(MembershipRole.EMPLOYEE), frozenset({"status"}), current, requested
    )


@pytest.mark.parametrize(
    "current,requested",
    [
        ("DRAFT", "SUBMITTED"),
        ("SUBMITTED", "ACCEPTED"),
        ("READY", "COMPLETED"),
        ("ACCEPTED", "CANCELLED"),
        ("COMPLETED", "PREPARING"),
        ("READY", None),
    ],
)
def test_employee_forbidden_status_changes(current, requested):
    with pytest.raises(ForbiddenError):
        authorize_order_update(
            context(MembershipRole.EMPLOYEE), frozenset({"status"}), current, requested
        )


@pytest.mark.parametrize(
    "field", ["payment_status", "items", "table_number", "customer_name", "notes"]
)
def test_employee_mixed_update_rejects_every_non_status_field_even_null(field):
    with pytest.raises(ForbiddenError):
        authorize_order_update(
            context(MembershipRole.EMPLOYEE),
            frozenset({"status", field}),
            "ACCEPTED",
            "PREPARING",
        )


def test_employee_empty_update_has_no_authorized_transition():
    with pytest.raises(ForbiddenError):
        authorize_order_update(
            context(MembershipRole.EMPLOYEE), frozenset(), "ACCEPTED", None
        )


@pytest.mark.parametrize("role", list(MembershipRole))
def test_unknown_order_fields_are_denied_by_default(role):
    with pytest.raises(ForbiddenError):
        authorize_order_update(
            context(role), frozenset({"future_field"}), "ACCEPTED", None
        )
