"""Owner-only audit inspection; persistence lives in the module."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.modules.auth.dependencies import get_current_principal
from app.modules.auth.domain.principal import AuthenticatedPrincipal
from app.modules.audit.service import AuditService

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("")
async def entries(
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> list[dict[str, object]]:
    return await AuditService(db, principal).entries(limit, offset)
