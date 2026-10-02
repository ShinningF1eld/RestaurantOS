"""Database-level tenant integrity, independent of future HTTP authorization."""

from uuid import uuid4

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Restaurant
from app.modules.audit.repo.models import AuditEntry
from app.modules.auth.repo.models import User
from app.modules.tenancy.domain.roles import MembershipRole
from app.modules.tenancy.repo.models import (
    Membership,
    Organization,
    RestaurantAssignment,
)
from conftest import engine


@pytest.fixture
def tenant_rows():
    with Session(engine, expire_on_commit=False) as db, db.begin():
        org_a = Organization(name="Organization A", slug="organization-a")
        org_b = Organization(name="Organization B", slug="organization-b")
        user = User(email="schema@example.test", password_hash="schema-test-only")
        db.add_all([org_a, org_b, user])
        db.flush()
        member = Membership(
            user_id=user.id, organization_id=org_a.id, role=MembershipRole.EMPLOYEE
        )
        restaurant_a = Restaurant(name="Branch A", organization_id=org_a.id)
        restaurant_b = Restaurant(name="Branch B", organization_id=org_b.id)
        db.add_all([member, restaurant_a, restaurant_b])
        db.flush()
    return org_a, org_b, user, member, restaurant_a, restaurant_b


def test_models_round_trip_assignment_and_audit(tenant_rows):
    org_a, _, user, member, restaurant, _ = tenant_rows
    with Session(engine) as db, db.begin():
        db.add(
            RestaurantAssignment(
                membership_id=member.id,
                organization_id=org_a.id,
                restaurant_id=restaurant.id,
            )
        )
        entry = AuditEntry(
            organization_id=org_a.id,
            restaurant_id=restaurant.id,
            actor_user_id=user.id,
            action="menu.updated",
            resource_type="menu",
            resource_id="42",
            changes={"price": {"before": "10", "after": "12"}},
            request_id="schema-request",
        )
        db.add(entry)
        db.flush()
        entry_id = entry.id
    with Session(engine) as db:
        saved = db.get(Membership, member.id)
        assert saved.role is MembershipRole.EMPLOYEE
        assert saved.created_at.tzinfo is not None
        assert db.scalar(select(RestaurantAssignment.restaurant_id)) == restaurant.id
        audit = db.get(AuditEntry, entry_id)
        assert audit.changes == {"price": {"before": "10", "after": "12"}}
        assert audit.occurred_at.tzinfo is not None


@pytest.mark.parametrize("role", ["OWNER", "MANAGER", "EMPLOYEE"])
def test_database_accepts_only_supported_roles(tenant_rows, role):
    _, _, _, member, _, _ = tenant_rows
    with engine.begin() as db:
        db.execute(
            text("UPDATE memberships SET role=:role WHERE id=:id"),
            {"role": role, "id": member.id},
        )
    with Session(engine) as db:
        assert db.get(Membership, member.id).role is MembershipRole(role)


@pytest.mark.parametrize("role", ["KITCHEN", "ADMIN", "owner", ""])
def test_database_rejects_other_roles(tenant_rows, role):
    _, _, _, member, _, _ = tenant_rows
    with pytest.raises(IntegrityError, match="ck_memberships_role"):
        with engine.begin() as db:
            db.execute(
                text("UPDATE memberships SET role=:role WHERE id=:id"),
                {"role": role, "id": member.id},
            )


@pytest.mark.parametrize("second_organization", [False, True])
def test_duplicate_membership_is_rejected(tenant_rows, second_organization):
    org_a, org_b, user, _, _, _ = tenant_rows
    with pytest.raises(IntegrityError, match="uq_memberships_user"):
        with Session(engine) as db, db.begin():
            db.add(
                Membership(
                    user_id=user.id,
                    organization_id=org_b.id if second_organization else org_a.id,
                    role=MembershipRole.OWNER,
                )
            )


def test_restaurant_cannot_be_created_without_organization():
    with pytest.raises(IntegrityError):
        with Session(engine) as db, db.begin():
            db.add(Restaurant(name="Missing tenant"))


@pytest.mark.parametrize("use_membership_org", [True, False])
def test_cross_organization_assignment_is_rejected(tenant_rows, use_membership_org):
    org_a, org_b, _, member, _, restaurant_b = tenant_rows
    constraint = (
        "fk_assignments_restaurant_org"
        if use_membership_org
        else "fk_assignments_membership_org"
    )
    with pytest.raises(IntegrityError, match=constraint):
        with Session(engine) as db, db.begin():
            db.add(
                RestaurantAssignment(
                    membership_id=member.id,
                    restaurant_id=restaurant_b.id,
                    organization_id=org_a.id if use_membership_org else org_b.id,
                )
            )


def test_duplicate_assignment_is_rejected(tenant_rows):
    org_a, _, _, member, restaurant, _ = tenant_rows
    values = {
        "membership_id": member.id,
        "organization_id": org_a.id,
        "restaurant_id": restaurant.id,
    }
    with Session(engine) as db, db.begin():
        db.add(RestaurantAssignment(**values))
    with pytest.raises(IntegrityError):
        with Session(engine) as db, db.begin():
            db.add(RestaurantAssignment(**values))


def test_cross_organization_audit_is_rejected(tenant_rows):
    org_a, _, _, _, _, restaurant_b = tenant_rows
    with pytest.raises(IntegrityError, match="fk_audit_entries_restaurant_org"):
        with Session(engine) as db, db.begin():
            db.add(
                AuditEntry(
                    organization_id=org_a.id,
                    restaurant_id=restaurant_b.id,
                    action="order.updated",
                    resource_type="order",
                    resource_id="1",
                )
            )


def test_audit_summary_must_be_a_json_object(tenant_rows):
    org_a, _, _, _, _, _ = tenant_rows
    with pytest.raises(IntegrityError, match="ck_audit_entries_changes_object"):
        with engine.begin() as db:
            db.execute(
                text(
                    "INSERT INTO audit_entries (id,organization_id,action,resource_type,"
                    "resource_id,changes) VALUES (:id,:org,'menu.updated','menu','1','[]')"
                ),
                {"id": uuid4(), "org": org_a.id},
            )


def test_organization_deletion_cannot_cascade_business_data(tenant_rows):
    org_a, _, _, _, restaurant, _ = tenant_rows
    with pytest.raises(IntegrityError):
        with Session(engine) as db, db.begin():
            db.execute(delete(Organization).where(Organization.id == org_a.id))
    with Session(engine) as db:
        assert db.get(Restaurant, restaurant.id) is not None


def test_audit_survives_actor_deletion(tenant_rows):
    org_a, _, _, _, _, _ = tenant_rows
    with Session(engine, expire_on_commit=False) as db, db.begin():
        actor = User(email="audit-actor@example.test", password_hash="schema-test-only")
        db.add(actor)
        db.flush()
        entry = AuditEntry(
            organization_id=org_a.id,
            actor_user_id=actor.id,
            action="organization.created",
            resource_type="organization",
            resource_id=str(org_a.id),
        )
        db.add(entry)
        db.flush()
    with Session(engine) as db, db.begin():
        db.execute(delete(User).where(User.id == actor.id))
    with Session(engine) as db:
        saved = db.get(AuditEntry, entry.id)
        assert saved.actor_user_id is None
        assert saved.resource_id == str(org_a.id)
