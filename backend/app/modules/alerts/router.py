"""User-authorized alert reads in the existing inventory namespace."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.modules.alerts.schemas import ActiveAlert, AlertHistory, AlertPage
from app.modules.alerts.service import AlertReadService
from app.modules.auth.dependencies import get_current_principal
from app.modules.auth.domain.principal import AuthenticatedPrincipal

router = APIRouter(
    prefix="/api/restaurants/{restaurant_id}/inventory/alerts", tags=["Inventory"]
)


@router.get("", response_model=AlertPage[ActiveAlert])
async def active_alerts(
    restaurant_id: int,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
) -> AlertPage[ActiveAlert]:
    rows, total = await AlertReadService(db, principal).active(
        restaurant_id, limit, offset
    )
    return AlertPage(
        items=[ActiveAlert.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/history", response_model=AlertPage[AlertHistory])
async def alert_history(
    restaurant_id: int,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
) -> AlertPage[AlertHistory]:
    rows, total = await AlertReadService(db, principal).history(
        restaurant_id, limit, offset
    )
    return AlertPage(
        items=[AlertHistory.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )
