"""Explicit organization, membership, and access-context HTTP policies."""

from uuid import UUID
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.database import get_db
from app.modules.auth.dependencies import get_current_principal
from app.modules.auth.domain.principal import AuthenticatedPrincipal
from app.modules.tenancy.access import AccessService
from app.modules.tenancy.schemas import (
    AccessResponse,
    MembershipCreate,
    MembershipUpdate,
    MembershipResponse,
    OrganizationCreate,
    OrganizationResponse,
)
from app.modules.tenancy.service import TenancyService

router = APIRouter(prefix="/api", tags=["tenancy"])


def service(
    db: AsyncSession = Depends(get_db),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> TenancyService:
    return TenancyService(db, principal)


@router.get("/access", response_model=AccessResponse)
async def access(
    db: AsyncSession = Depends(get_db),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> AccessResponse:
    context = await AccessService(db, principal).current()
    return AccessResponse(
        organization_id=context.organization_id,
        organization_number=context.organization_number,
        role=context.role,
        capabilities=sorted(context.capabilities),
        restaurant_ids=sorted(context.restaurant_ids),
    )


@router.post("/organizations", response_model=OrganizationResponse, status_code=201)
async def create_organization(
    body: OrganizationCreate, current: TenancyService = Depends(service)
) -> OrganizationResponse:
    return OrganizationResponse.model_validate(
        await current.create_organization(body.name, body.slug)
    )


@router.get("/organization", response_model=OrganizationResponse)
async def organization(
    current: TenancyService = Depends(service),
) -> OrganizationResponse:
    return OrganizationResponse.model_validate(await current.organization())


@router.get("/memberships", response_model=list[MembershipResponse])
async def memberships(
    current: TenancyService = Depends(service),
) -> list[MembershipResponse]:
    return [
        MembershipResponse.model_validate(member)
        for member in await current.list_memberships()
    ]


@router.post("/memberships", response_model=MembershipResponse, status_code=201)
async def create_membership(
    body: MembershipCreate, current: TenancyService = Depends(service)
) -> MembershipResponse:
    return MembershipResponse.model_validate(
        await current.create_membership(body.email, body.role, body.restaurant_ids)
    )


@router.put("/memberships/{membership_id}", response_model=MembershipResponse)
async def update_membership(
    membership_id: UUID,
    body: MembershipUpdate,
    current: TenancyService = Depends(service),
) -> MembershipResponse:
    return MembershipResponse.model_validate(
        await current.update_membership(
            membership_id, role=body.role, restaurant_ids=body.restaurant_ids
        )
    )


@router.delete("/memberships/{membership_id}", status_code=204)
async def revoke_membership(
    membership_id: UUID, current: TenancyService = Depends(service)
) -> None:
    await current.update_membership(
        membership_id, role=None, restaurant_ids=None, revoke=True
    )
