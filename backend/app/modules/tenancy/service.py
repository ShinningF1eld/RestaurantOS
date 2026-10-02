"""Organization bootstrap and owner-only membership administration."""

from uuid import UUID
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.errors import ConflictError, NotFoundError
from app.modules.auth.domain.principal import AuthenticatedPrincipal
from app.modules.auth.service import active_account_id
from app.modules.audit.service import record
from app.modules.tenancy.access import AccessService
from app.modules.tenancy.domain.policies import AccessContext
from app.modules.tenancy.domain.roles import MembershipRole
from app.modules.tenancy.repo.models import Membership, Organization
from app.modules.tenancy.repo.memberships import MembershipRepository


class TenancyService:
    def __init__(
        self, session: AsyncSession, principal: AuthenticatedPrincipal
    ) -> None:
        self._session = session
        self._principal = principal
        self._access = AccessService(session, principal)
        self._members = MembershipRepository(session)

    async def create_organization(self, name: str, slug: str) -> Organization:
        try:
            async with self._session.begin():
                if await self._members.for_user(self._principal.id):
                    raise ConflictError("User already belongs to an organization")
                org = Organization(name=name, slug=slug)
                self._session.add(org)
                await self._session.flush()
                owner = Membership(
                    user_id=self._principal.id,
                    organization_id=org.id,
                    role=MembershipRole.OWNER,
                )
                self._session.add(owner)
                await self._session.flush()
                context = AccessContext(
                    self._principal.id,
                    owner.id,
                    org.id,
                    org.number,
                    owner.role,
                    frozenset(),
                )
                record(
                    self._session,
                    context,
                    "organization.created",
                    "organization",
                    str(org.id),
                )
                record(
                    self._session,
                    context,
                    "membership.created",
                    "membership",
                    str(owner.id),
                    changes={"role": "OWNER"},
                )
                return org
        except IntegrityError as error:
            raise ConflictError("Organization or membership already exists") from error

    async def organization(self) -> Organization:
        context = await self._access.current()
        org = await self._members.organization(context.organization_id)
        assert org is not None
        return org

    async def list_memberships(self) -> list[Membership]:
        context = await self._access.current()
        context.require("staff.manage")
        return await self._members.list_for_organization(context.organization_id)

    async def _owner(self) -> AccessContext:
        # Take the organization lock before membership locks, consistently across admins.
        context = await self._access.current()
        await self._members.lock_organization(context.organization_id)
        context = await self._access.current(lock=True)
        context.require("staff.manage")
        return context

    async def create_membership(
        self, email: str, role: MembershipRole, restaurant_ids: list[int]
    ) -> Membership:
        try:
            async with self._session.begin():
                context = await self._owner()
                user_id = await active_account_id(self._session, email)
                if user_id is None:
                    raise NotFoundError("Active provisioned account not found")
                if await self._members.for_user(user_id):
                    raise ConflictError("User already belongs to an organization")
                member = Membership(
                    user_id=user_id, organization_id=context.organization_id, role=role
                )
                self._session.add(member)
                await self._session.flush()
                if not await self._members.assign(member, restaurant_ids):
                    raise NotFoundError("Restaurant not found")
                record(
                    self._session,
                    context,
                    "membership.created",
                    "membership",
                    str(member.id),
                    changes={
                        "role": role.value,
                        "restaurant_ids": sorted(set(restaurant_ids)),
                    },
                )
                return member
        except IntegrityError as error:
            raise ConflictError("User already belongs to an organization") from error

    async def update_membership(
        self,
        membership_id: UUID,
        *,
        role: MembershipRole | None,
        restaurant_ids: list[int] | None,
        revoke: bool = False,
    ) -> Membership:
        async with self._session.begin():
            context = await self._owner()
            member = await self._members.get(membership_id, context.organization_id)
            if member is None:
                raise NotFoundError("Membership not found")
            if (
                member.role is MembershipRole.OWNER
                and member.status == "active"
                and (revoke or role not in (None, MembershipRole.OWNER))
            ):
                if await self._members.owner_count(context.organization_id) <= 1:
                    raise ConflictError("Cannot remove or demote the last active owner")
            before = {"role": member.role.value, "status": member.status}
            if role is not None:
                member.role = role
            if revoke:
                member.status = "revoked"
            if restaurant_ids is not None and not await self._members.assign(
                member, restaurant_ids
            ):
                raise NotFoundError("Restaurant not found")
            record(
                self._session,
                context,
                "membership.revoked" if revoke else "membership.updated",
                "membership",
                str(member.id),
                changes={
                    "role": {"before": before["role"], "after": member.role.value},
                    "status": {"before": before["status"], "after": member.status},
                    "restaurant_ids": sorted(set(restaurant_ids))
                    if restaurant_ids is not None
                    else None,
                },
            )
            return member
