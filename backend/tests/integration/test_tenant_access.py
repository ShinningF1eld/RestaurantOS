"""Real-session PostgreSQL tests for Milestone 4 exit criteria and failure paths."""

from uuid import uuid4
import json
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from conftest import engine
from app.main import app


@pytest.fixture
def workspace(authenticated_client, auth_user):
    owner = authenticated_client
    branch = owner.post("/api/restaurants", json={"name": "Tenant A"}).json()["id"]
    unassigned = owner.post("/api/restaurants", json={"name": "Unassigned A"}).json()[
        "id"
    ]
    menu = owner.post(f"/restaurants/{branch}/menus", json={"name": "Main"}).json()[
        "menu_id"
    ]
    item = owner.post(
        f"/menus/{menu}/items", json={"name": "Dish", "price": "10"}
    ).json()["menu_item_id"]
    order = owner.post(
        f"/api/restaurants/{branch}/orders",
        json={"idempotency_key": "tenant-local", "items": [{"menu_item_id": item, "quantity": 1}]},
    ).json()["order_id"]
    org_b = uuid4()
    accounts = {}
    with engine.begin() as db:
        encoded = db.scalar(
            text("SELECT password_hash FROM users WHERE id=:id"),
            {"id": auth_user["id"]},
        )
        db.execute(
            text(
                "INSERT INTO organizations (id,name,slug) VALUES (:id,'B','tenant-b')"
            ),
            {"id": org_b},
        )
        for name, role, org, assigned in [
            ("other", "OWNER", org_b, None),
            ("manager", "MANAGER", auth_user["organization_id"], branch),
            ("employee", "EMPLOYEE", auth_user["organization_id"], branch),
        ]:
            user_id, member_id = uuid4(), uuid4()
            email = f"{name}@example.test"
            db.execute(
                text(
                    "INSERT INTO users (id,email,password_hash) VALUES (:id,:email,:hash)"
                ),
                {"id": user_id, "email": email, "hash": encoded},
            )
            db.execute(
                text(
                    "INSERT INTO memberships (id,user_id,organization_id,role) VALUES (:id,:user,:org,:role)"
                ),
                {"id": member_id, "user": user_id, "org": org, "role": role},
            )
            if assigned:
                db.execute(
                    text(
                        "INSERT INTO restaurant_assignments (membership_id,organization_id,restaurant_id) VALUES (:id,:org,:restaurant)"
                    ),
                    {"id": member_id, "org": org, "restaurant": assigned},
                )
            accounts[name] = (email, member_id)
    clients = {}
    try:
        for name, (email, _) in accounts.items():
            client = TestClient(app)
            client.headers.update(
                {"Origin": "http://localhost:3000", "X-CSRF-Protection": "1"}
            )
            assert (
                client.post(
                    "/auth/login",
                    json={"email": email, "password": auth_user["password"]},
                ).status_code
                == 200
            )
            clients[name] = client
        foreign_branch = (
            clients["other"]
            .post("/api/restaurants", json={"name": "B branch"})
            .json()["id"]
        )
        foreign_menu = (
            clients["other"]
            .post(f"/restaurants/{foreign_branch}/menus", json={"name": "B menu"})
            .json()["menu_id"]
        )
        foreign_item = (
            clients["other"]
            .post(
                f"/menus/{foreign_menu}/items", json={"name": "B item", "price": "20"}
            )
            .json()["menu_item_id"]
        )
        foreign_order = (
            clients["other"]
            .post(
                f"/api/restaurants/{foreign_branch}/orders",
                json={"idempotency_key": "tenant-foreign", "items": [{"menu_item_id": foreign_item, "quantity": 1}]},
            )
            .json()["order_id"]
        )
        yield {
            "owner": owner,
            **clients,
            "branch": branch,
            "unassigned": unassigned,
            "menu": menu,
            "item": item,
            "order": order,
            "foreign_branch": foreign_branch,
            "foreign_menu": foreign_menu,
            "foreign_item": foreign_item,
            "foreign_order": foreign_order,
            "memberships": {
                name: str(member) for name, (_, member) in accounts.items()
            },
        }
    finally:
        for client in clients.values():
            client.close()


@pytest.mark.parametrize(
    "method,path,payload",
    [
        ("get", "/api/restaurants/{foreign_branch}", None),
        ("put", "/api/restaurants/{foreign_branch}", {"name": "Hijack"}),
        ("delete", "/api/restaurants/{foreign_branch}", None),
        ("get", "/restaurants/{foreign_branch}/menus", None),
        ("post", "/restaurants/{foreign_branch}/menus", {"name": "Hijack"}),
        ("get", "/menus/{foreign_menu}", None),
        ("put", "/menus/{foreign_menu}", {"name": "Hijack"}),
        ("delete", "/menus/{foreign_menu}", None),
        ("get", "/menus/{foreign_menu}/items", None),
        ("post", "/menus/{foreign_menu}/items", {"name": "Hijack", "price": "1"}),
        ("get", "/menu-items/{foreign_item}", None),
        ("put", "/menu-items/{foreign_item}", {"price": "1"}),
        ("delete", "/menu-items/{foreign_item}", None),
        ("get", "/api/restaurants/{foreign_branch}/orders", None),
        ("post", "/api/restaurants/{foreign_branch}/orders", {"items": []}),
        ("get", "/api/orders/{foreign_order}", None),
        ("put", "/api/orders/{foreign_order}", {"status": "SUBMITTED"}),
        ("delete", "/api/orders/{foreign_order}", None),
        ("get", "/api/restaurants/{foreign_branch}/analytics/dashboard", None),
    ],
)
def test_cross_tenant_direct_nested_reads_and_writes(workspace, method, path, payload):
    if method == "post" and path.endswith("/orders"):
        payload = {
            "idempotency_key": "cross-tenant",
            "items": [{"menu_item_id": workspace["foreign_item"], "quantity": 1}],
        }
    response = workspace["owner"].request(
        method,
        path.format(**workspace),
        **({"json": payload} if payload is not None else {}),
    )
    assert response.status_code == 404, response.text


def test_lists_counts_and_payload_references_are_scoped(workspace):
    w = workspace
    assert {row["id"] for row in w["owner"].get("/api/restaurants").json()} == {
        w["branch"],
        w["unassigned"],
    }
    assert {row["id"] for row in w["employee"].get("/api/restaurants").json()} == {
        w["branch"]
    }
    assert w["owner"].get(f"/api/restaurants/{w['branch']}/orders").json()["total"] == 1
    assert w["employee"].get(f"/api/restaurants/{w['unassigned']}").status_code == 404
    assert (
        w["owner"]
        .post(
            f"/api/restaurants/{w['branch']}/orders",
            json={"idempotency_key": "tenant-foreign-item", "items": [{"menu_item_id": w["foreign_item"], "quantity": 1}]},
        )
        .status_code
        == 404
    )
    assert (
        w["owner"]
        .put(
            f"/api/orders/{w['order']}",
            json={"items": [{"menu_item_id": w["foreign_item"], "quantity": 1}]},
        )
        .status_code
        == 404
    )


def test_employee_preparation_only_and_forbidden_fields_roll_back(workspace):
    w = workspace
    assert w["employee"].get("/api/memberships").status_code == 403
    assert (
        w["employee"]
        .get(f"/api/restaurants/{w['branch']}/analytics/dashboard")
        .status_code
        == 403
    )
    assert (
        w["employee"].put(f"/menu-items/{w['item']}", json={"price": "1"}).status_code
        == 403
    )
    assert (
        w["employee"]
        .post(
            f"/api/restaurants/{w['branch']}/orders",
            json={"idempotency_key": "tenant-employee", "items": [{"menu_item_id": w["item"], "quantity": 1}]},
        )
        .status_code
        == 403
    )
    for status in ("SUBMITTED", "ACCEPTED"):
        assert (
            w["owner"]
            .put(f"/api/orders/{w['order']}", json={"status": status})
            .status_code
            == 200
        )
    for field in ("payment_status", "items", "notes", "customer_name", "table_number"):
        response = w["employee"].put(
            f"/api/orders/{w['order']}", json={"status": "PREPARING", field: None}
        )
        assert response.status_code == 403
        assert (
            w["owner"].get(f"/api/orders/{w['order']}").json()["status"] == "ACCEPTED"
        )
    for status in ("PREPARING", "READY"):
        assert (
            w["employee"]
            .put(f"/api/orders/{w['order']}", json={"status": status})
            .status_code
            == 200
        )
    for status in ("COMPLETED", "CANCELLED"):
        assert (
            w["employee"]
            .put(f"/api/orders/{w['order']}", json={"status": status})
            .status_code
            == 403
        )


def test_owner_admin_last_owner_and_immediate_revocation(workspace):
    w = workspace
    manager_id = w["memberships"]["manager"]
    assert (
        w["manager"]
        .put(f"/api/memberships/{manager_id}", json={"role": "OWNER"})
        .status_code
        == 403
    )
    assert (
        w["manager"]
        .get(f"/api/restaurants/{w['branch']}/analytics/dashboard")
        .status_code
        == 200
    )
    assert w["manager"].get(f"/api/restaurants/{w['unassigned']}").status_code == 404
    owner_id = next(
        row["id"]
        for row in w["owner"].get("/api/memberships").json()
        if row["role"] == "OWNER"
    )
    assert w["owner"].delete(f"/api/memberships/{owner_id}").status_code == 409
    assert (
        w["owner"]
        .put(f"/api/memberships/{owner_id}", json={"role": "MANAGER"})
        .status_code
        == 409
    )
    employee_id = w["memberships"]["employee"]
    assert w["owner"].delete(f"/api/memberships/{employee_id}").status_code == 204
    assert w["employee"].get("/auth/me").status_code == 200
    assert w["employee"].get("/api/restaurants").status_code == 403
    assert w["employee"].get(f"/api/orders/{w['order']}").status_code == 403
    assert (
        w["owner"]
        .put(f"/api/memberships/{manager_id}", json={"restaurant_ids": []})
        .status_code
        == 200
    )
    assert w["manager"].get(f"/api/restaurants/{w['branch']}").status_code == 404


def test_single_org_membership_and_cross_org_assignment_admin(workspace):
    w = workspace
    assert (
        w["owner"]
        .post("/api/memberships", json={"email": "other@example.test", "role": "OWNER"})
        .status_code
        == 409
    )
    assert (
        w["owner"]
        .put(
            f"/api/memberships/{w['memberships']['manager']}",
            json={"restaurant_ids": [w["foreign_branch"]]},
        )
        .status_code
        == 404
    )
    assert (
        w["owner"]
        .put(f"/api/memberships/{w['memberships']['other']}", json={"role": "EMPLOYEE"})
        .status_code
        == 404
    )
    assert (
        w["owner"]
        .post("/api/organizations", json={"name": "Extra", "slug": "extra"})
        .status_code
        == 409
    )


def test_audit_safe_summary_tenant_scope_and_atomic_failure(workspace, monkeypatch):
    w = workspace
    customer_secret = "customer private marker"  # pragma: allowlist secret
    assert (
        w["owner"]
        .put(
            f"/api/orders/{w['order']}",
            json={"notes": customer_secret, "payment_status": "PAID"},
            headers={"X-Request-ID": "audit-proof"},
        )
        .status_code
        == 200
    )
    entries = w["owner"].get("/api/audit?limit=100").json()
    assert entries and any(row["request_id"] == "audit-proof" for row in entries)
    serialized = json.dumps(entries)
    assert customer_secret not in serialized
    assert "password_hash" not in serialized and "ros_refresh" not in serialized
    assert all(row["restaurant_id"] != w["foreign_branch"] for row in entries)
    assert w["employee"].get("/api/audit").status_code == 403
    import app.modules.catalog.service as catalog

    def fail(*args, **kwargs):
        raise RuntimeError("audit write failed")

    monkeypatch.setattr(catalog, "record", fail)
    with TestClient(app, raise_server_exceptions=False) as client:
        client.cookies.update(w["owner"].cookies)
        client.headers.update(w["owner"].headers)
        assert (
            client.put(f"/menu-items/{w['item']}", json={"price": "99"}).status_code
            == 500
        )
    assert w["owner"].get(f"/menu-items/{w['item']}").json()["price"] == "10.00"


def provision_unassigned(auth_user, name):
    user_id = uuid4()
    email = name + "@example.test"
    with engine.begin() as db:
        encoded = db.scalar(
            text("SELECT password_hash FROM users WHERE id=:id"),
            {"id": auth_user["id"]},
        )
        db.execute(
            text(
                "INSERT INTO users (id,email,password_hash) VALUES (:id,:email,:hash)"
            ),
            {"id": user_id, "email": email, "hash": encoded},
        )
    client = TestClient(app)
    client.headers.update({"Origin": "http://localhost:3000", "X-CSRF-Protection": "1"})
    assert (
        client.post(
            "/auth/login", json={"email": email, "password": auth_user["password"]}
        ).status_code
        == 200
    )
    return client, email


def test_unassigned_user_bootstraps_only_own_organization(auth_user):
    client, _ = provision_unassigned(auth_user, "new-owner")
    try:
        assert client.get("/api/restaurants").status_code == 403
        created = client.post(
            "/api/organizations",
            json={"name": "New workspace", "slug": "new-workspace"},
        )
        assert created.status_code == 201
        access = client.get("/api/access").json()
        assert access["role"] == "OWNER"
        assert access["organization_id"] == created.json()["id"]
        assert (
            client.post("/api/restaurants", json={"name": "New branch"}).status_code
            == 201
        )
        assert (
            client.post(
                "/api/organizations", json={"name": "Extra", "slug": "extra"}
            ).status_code
            == 409
        )
    finally:
        client.close()


def test_membership_creation_assignment_validation_and_live_role_change(
    workspace, auth_user
):
    w = workspace
    client, email = provision_unassigned(auth_user, "new-staff")
    try:
        before = len(w["owner"].get("/api/memberships").json())
        assert (
            w["owner"]
            .post(
                "/api/memberships",
                json={
                    "email": email,
                    "role": "MANAGER",
                    "restaurant_ids": [w["foreign_branch"]],
                },
            )
            .status_code
            == 404
        )
        assert len(w["owner"].get("/api/memberships").json()) == before
        assert client.get("/api/access").status_code == 403
        created = w["owner"].post(
            "/api/memberships",
            json={"email": email, "role": "MANAGER", "restaurant_ids": [w["branch"]]},
        )
        assert created.status_code == 201
        assert (
            client.get(
                f"/api/restaurants/{w['branch']}/analytics/dashboard"
            ).status_code
            == 200
        )
        assert (
            w["owner"]
            .put(f"/api/memberships/{created.json()['id']}", json={"role": "EMPLOYEE"})
            .status_code
            == 200
        )
        assert client.get("/auth/me").status_code == 200
        assert (
            client.get(
                f"/api/restaurants/{w['branch']}/analytics/dashboard"
            ).status_code
            == 403
        )
        assert client.get(f"/api/orders/{w['order']}").status_code == 200
    finally:
        client.close()


@pytest.mark.asyncio
async def test_access_refreshes_role_from_database_in_reused_session(owner_principal):
    from app.db.database import AsyncSessionLocal
    from app.modules.tenancy.access import AccessService
    from app.modules.tenancy.domain.roles import MembershipRole

    async with AsyncSessionLocal() as session:
        access = AccessService(session, owner_principal)
        assert (await access.current()).role is MembershipRole.OWNER
        with engine.begin() as db:
            db.execute(
                text("UPDATE memberships SET role='EMPLOYEE' WHERE user_id=:id"),
                {"id": owner_principal.id},
            )
        assert (await access.current()).role is MembershipRole.EMPLOYEE
