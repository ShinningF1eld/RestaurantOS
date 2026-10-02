"""Pure capability and branch-scope rules for the three agreed roles."""

from dataclasses import dataclass
from uuid import UUID

from app.core.errors import ForbiddenError
from app.modules.tenancy.domain.roles import MembershipRole

READ_CAPABILITIES = frozenset(
    {"restaurant.read", "menu.read", "order.read", "order.status.update"}
)
MANAGER_CAPABILITIES = READ_CAPABILITIES | frozenset(
    {
        "restaurant.update",
        "menu.manage",
        "order.create",
        "order.details.update",
        "order.items.manage",
        "order.payment.update",
        "order.cancel",
        "analytics.read",
    }
)
ROLE_CAPABILITIES = {
    MembershipRole.OWNER: MANAGER_CAPABILITIES
    | frozenset(
        {
            "restaurant.create",
            "restaurant.delete",
            "order.delete",
            "staff.manage",
            "audit.read",
        }
    ),
    MembershipRole.MANAGER: MANAGER_CAPABILITIES,
    MembershipRole.EMPLOYEE: READ_CAPABILITIES,
}
EMPLOYEE_TRANSITIONS = frozenset({("ACCEPTED", "PREPARING"), ("PREPARING", "READY")})


@dataclass(frozen=True)
class AccessContext:
    user_id: UUID
    membership_id: UUID
    organization_id: UUID
    organization_number: int
    role: MembershipRole
    restaurant_ids: frozenset[int]

    @property
    def capabilities(self) -> frozenset[str]:
        return ROLE_CAPABILITIES[self.role]

    def require(self, capability: str) -> None:
        if capability not in self.capabilities:
            raise ForbiddenError("Permission denied")

    def permits_restaurant(self, restaurant_id: int) -> bool:
        return self.role is MembershipRole.OWNER or restaurant_id in self.restaurant_ids


def authorize_order_update(
    context: AccessContext, fields: frozenset[str], current: str, requested: str | None
) -> None:
    capabilities = {
        "status": "order.status.update",
        "payment_status": "order.payment.update",
        "items": "order.items.manage",
        "table_number": "order.details.update",
        "customer_name": "order.details.update",
        "notes": "order.details.update",
    }
    for field in fields:
        capability = capabilities.get(field)
        if capability is None:
            raise ForbiddenError("Permission denied")
        context.require(capability)
    if context.role is MembershipRole.EMPLOYEE:
        if (
            fields != frozenset({"status"})
            or requested is None
            or (current, requested.strip().upper()) not in EMPLOYEE_TRANSITIONS
        ):
            raise ForbiddenError(
                "Employees may only start preparation or mark an order ready"
            )
