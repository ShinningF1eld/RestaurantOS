"""Stage allowlisted audit facts inside the caller's business transaction."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.domain.policies import safe_changes
from app.core.request_id import get_request_id
from app.modules.audit.repo.models import AuditEntry
from app.modules.tenancy.domain.policies import AccessContext
from app.modules.auth.domain.principal import AuthenticatedPrincipal
from app.modules.tenancy.access import AccessService
from app.modules.audit.repo.queries import AuditRepository


class AuditService:
    def __init__(
        self, session: AsyncSession, principal: AuthenticatedPrincipal
    ) -> None:
        self._access = AccessService(session, principal)
        self._audit = AuditRepository(session)

    async def entries(self, limit: int, offset: int) -> list[dict[str, object]]:
        context = await self._access.current()
        context.require("audit.read")
        rows = await self._audit.list_entries(context.organization_id, limit, offset)
        return [
            {
                "id": str(row.id),
                "actor_user_id": str(row.actor_user_id) if row.actor_user_id else None,
                "restaurant_id": row.restaurant_id,
                "action": row.action,
                "resource_type": row.resource_type,
                "resource_id": row.resource_id,
                "changes": row.changes,
                "request_id": row.request_id,
                "occurred_at": row.occurred_at.isoformat(),
            }
            for row in rows
        ]


def record(
    session: AsyncSession,
    context: AccessContext,
    action: str,
    resource_type: str,
    resource_id: str | int,
    *,
    restaurant_id: int | None = None,
    changes: dict[str, object] | None = None,
) -> None:
    safe = safe_changes(changes or {})
    session.add(
        AuditEntry(
            organization_id=context.organization_id,
            actor_user_id=context.user_id,
            restaurant_id=restaurant_id,
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id),
            changes=safe,
            request_id=get_request_id(),
        )
    )
