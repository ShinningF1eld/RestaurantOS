"""Explicit, idempotent operator bootstrap for the existing single workspace."""

import argparse
import asyncio
from sqlalchemy import select
from app.db.database import AsyncSessionLocal, engine
import app.db.models  # noqa: F401 - register the complete business model registry
from app.modules.restaurants.repo.models import Restaurant
from app.modules.auth.repo.models import User
from app.modules.tenancy.repo.models import Membership, Organization
from app.modules.tenancy.domain.roles import MembershipRole
from app.modules.tenancy.domain.policies import AccessContext
from app.modules.audit.service import record


async def bootstrap_existing() -> None:
    async with AsyncSessionLocal() as db, db.begin():
        users = list((await db.scalars(select(User).with_for_update())).all())
        restaurants = list(
            (await db.scalars(select(Restaurant).with_for_update())).all()
        )
        if len(users) != 1 or len(restaurants) != 1:
            raise ValueError("Bootstrap requires exactly one user and one restaurant")
        user, restaurant = users[0], restaurants[0]
        if user.status != "active":
            raise ValueError("Owner account must be active")
        organization = await db.scalar(
            select(Organization).where(Organization.number == 1).with_for_update()
        )
        if organization is None or organization.slug != "restaurantos-development":
            raise ValueError(
                "Organization 1 must be the migrated development workspace"
            )
        existing = await db.scalar(
            select(Membership).where(Membership.user_id == user.id).with_for_update()
        )
        if existing is not None and existing.organization_id != organization.id:
            raise ValueError("User already belongs to another organization")
        if restaurant.organization_id != organization.id:
            raise ValueError("Restaurant already belongs to another organization")
        changed = (
            existing is None
            or existing.role is not MembershipRole.OWNER
            or existing.status != "active"
        )
        if existing is None:
            existing = Membership(
                user_id=user.id,
                organization_id=organization.id,
                role=MembershipRole.OWNER,
            )
            db.add(existing)
            await db.flush()
        existing.role = MembershipRole.OWNER
        existing.status = "active"
        if changed:
            context = AccessContext(
                user.id,
                existing.id,
                organization.id,
                1,
                MembershipRole.OWNER,
                frozenset(),
            )
            record(
                db,
                context,
                "membership.bootstrapped",
                "membership",
                str(existing.id),
                restaurant_id=restaurant.id,
                changes={"role": "OWNER"},
            )
        print(f"Organization 1: restaurant {restaurant.id}; sole active user is OWNER")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["bootstrap-existing"])
    parser.parse_args()

    async def run() -> None:
        try:
            await bootstrap_existing()
        finally:
            await engine.dispose()

    try:
        asyncio.run(run())
    except ValueError as error:
        parser.exit(1, str(error) + "\n")


if __name__ == "__main__":
    main()
