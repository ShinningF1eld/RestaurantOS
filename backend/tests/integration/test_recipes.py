"""Database-backed coverage for inventory-backed menu recipes."""

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from conftest import engine


def create_restaurant(client: TestClient, name: str) -> int:
    response = client.post("/api/restaurants", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def create_menu_item(client: TestClient, restaurant_id: int, name: str = "Dish") -> int:
    menu = client.post(f"/restaurants/{restaurant_id}/menus", json={"name": "Main"})
    assert menu.status_code == 200, menu.text
    item = client.post(
        f"/menus/{menu.json()['menu_id']}/items",
        json={"name": name, "price": "10.00", "is_available": True},
    )
    assert item.status_code == 200, item.text
    return item.json()["menu_item_id"]


def create_ingredient(
    client: TestClient,
    restaurant_id: int,
    *,
    name: str,
    unit: str = "g",
    quantity: str = "10",
) -> dict:
    response = client.post(
        f"/api/restaurants/{restaurant_id}/inventory/ingredients",
        json={
            "name": name,
            "unit": unit,
            "reorder_threshold": "0",
            "opening_quantity": quantity,
            "idempotency_key": uuid4().hex,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def set_recipe(
    client: TestClient,
    menu_item_id: int,
    components: list[dict],
    *,
    tracked: bool = True,
):
    return client.put(
        f"/menu-items/{menu_item_id}/recipe",
        json={"inventory_tracking": tracked, "components": components},
    )


def test_recipe_rejects_bad_components_and_cross_restaurant_ingredients(
    authenticated_client,
):
    client = authenticated_client
    restaurant = create_restaurant(client, "Recipe validation")
    other_restaurant = create_restaurant(client, "Other recipe branch")
    item = create_menu_item(client, restaurant)
    flour = create_ingredient(client, restaurant, name="Flour")
    foreign = create_ingredient(client, other_restaurant, name="Foreign flour")
    recipe_url = f"/menu-items/{item}/recipe"

    assert client.get(recipe_url).status_code == 200
    assert client.get(recipe_url).json() == {
        "menu_item_id": item,
        "restaurant_id": restaurant,
        "inventory_tracking": False,
        "components": [],
    }

    for invalid_quantity in ("0", "-1", "0.0001", "NaN", "Infinity"):
        response = set_recipe(
            client,
            item,
            [{"ingredient_id": flour["id"], "quantity": invalid_quantity}],
        )
        assert response.status_code == 422, response.text

    duplicate = set_recipe(
        client,
        item,
        [
            {"ingredient_id": flour["id"], "quantity": "1"},
            {"ingredient_id": flour["id"], "quantity": "2"},
        ],
    )
    assert duplicate.status_code == 422, duplicate.text

    wrong_branch = set_recipe(
        client, item, [{"ingredient_id": foreign["id"], "quantity": "1"}]
    )
    assert wrong_branch.status_code == 404, wrong_branch.text

    empty_tracked = set_recipe(client, item, [])
    assert empty_tracked.status_code == 422, empty_tracked.text
    assert client.get(recipe_url).json()["inventory_tracking"] is False


def test_recipe_round_trips_base_units_and_drives_available_portions(
    authenticated_client,
):
    client = authenticated_client
    restaurant = create_restaurant(client, "Recipe availability")
    item = create_menu_item(client, restaurant, "Noodle bowl")
    flour = create_ingredient(client, restaurant, name="Flour", quantity="20")
    egg = create_ingredient(
        client, restaurant, name="Eggs", unit="piece", quantity="10"
    )

    saved = set_recipe(
        client,
        item,
        [
            {"ingredient_id": flour["id"], "quantity": "4.250"},
            {"ingredient_id": egg["id"], "quantity": "3"},
        ],
    )
    assert saved.status_code == 200, saved.text
    recipe = client.get(f"/menu-items/{item}/recipe")
    assert recipe.status_code == 200, recipe.text
    assert recipe.json() == {
        "menu_item_id": item,
        "restaurant_id": restaurant,
        "inventory_tracking": True,
        "components": [
            {
                "ingredient_id": flour["id"],
                "ingredient_name": "Flour",
                "unit": "g",
                "quantity": "4.250",
            },
            {
                "ingredient_id": egg["id"],
                "ingredient_name": "Eggs",
                "unit": "piece",
                "quantity": "3.000",
            },
        ],
    }

    menu_item = client.get(f"/menu-items/{item}")
    assert menu_item.status_code == 200, menu_item.text
    assert menu_item.json()["inventory_tracking"] is True
    assert menu_item.json()["available_portions"] == 3
    assert menu_item.json()["out_of_stock"] is False

    # Physical counts are the inventory baseline for availability calculations.
    count = client.post(
        f"/api/restaurants/{restaurant}/inventory/ingredients/{egg['id']}/movements",
        json={
            "kind": "count",
            "quantity": "2",
            "reason": "Cycle count",
            "expected_version": 1,
            "idempotency_key": "recipe-count",
        },
    )
    assert count.status_code == 201, count.text
    refreshed = client.get(f"/menu-items/{item}").json()
    assert refreshed["available_portions"] == 0
    assert refreshed["out_of_stock"] is True


def test_recipe_roles_tenant_scope_and_ingredient_unit_immutability(
    authenticated_client, auth_user
):
    owner = authenticated_client
    restaurant = create_restaurant(owner, "Recipe permissions")
    item = create_menu_item(owner, restaurant)
    ingredient = create_ingredient(owner, restaurant, name="Rice", quantity="0")
    other_restaurant = create_restaurant(owner, "Recipe other branch")
    other_item = create_menu_item(owner, other_restaurant, "Other dish")

    manager_email = "recipe-manager@example.test"
    employee_email = "recipe-employee@example.test"
    foreign_email = "recipe-foreign@example.test"
    manager_id, employee_id, foreign_id = uuid4(), uuid4(), uuid4()
    foreign_org = uuid4()
    with engine.begin() as db:
        password_hash = db.scalar(
            text("SELECT password_hash FROM users WHERE id=:id"),
            {"id": auth_user["id"]},
        )
        db.execute(
            text(
                "INSERT INTO organizations (id,name,slug) "
                "VALUES (:id,'Recipe foreign','recipe-foreign')"
            ),
            {"id": foreign_org},
        )
        for user_id, email, organization_id, role in (
            (manager_id, manager_email, auth_user["organization_id"], "MANAGER"),
            (employee_id, employee_email, auth_user["organization_id"], "EMPLOYEE"),
            (foreign_id, foreign_email, foreign_org, "OWNER"),
        ):
            member_id = uuid4()
            db.execute(
                text(
                    "INSERT INTO users (id,email,password_hash) "
                    "VALUES (:id,:email,:hash)"
                ),
                {"id": user_id, "email": email, "hash": password_hash},
            )
            db.execute(
                text(
                    "INSERT INTO memberships (id,user_id,organization_id,role) "
                    "VALUES (:id,:user,:org,:role)"
                ),
                {
                    "id": member_id,
                    "user": user_id,
                    "org": organization_id,
                    "role": role,
                },
            )
            if role in {"MANAGER", "EMPLOYEE"}:
                db.execute(
                    text(
                        "INSERT INTO restaurant_assignments "
                        "(membership_id,organization_id,restaurant_id) "
                        "VALUES (:membership,:org,:restaurant)"
                    ),
                    {
                        "membership": member_id,
                        "org": organization_id,
                        "restaurant": restaurant,
                    },
                )

    clients = {}
    try:
        for key, email in (
            ("manager", manager_email),
            ("employee", employee_email),
            ("foreign", foreign_email),
        ):
            client = TestClient(app)
            client.headers.update(
                {"Origin": "http://localhost:3000", "X-CSRF-Protection": "1"}
            )
            login = client.post(
                "/auth/login",
                json={"email": email, "password": auth_user["password"]},
            )
            assert login.status_code == 200, login.text
            clients[key] = client

        manager = clients["manager"]
        employee = clients["employee"]
        foreign = clients["foreign"]
        components = [{"ingredient_id": ingredient["id"], "quantity": "1"}]
        assert set_recipe(manager, item, components).status_code == 200
        assert set_recipe(employee, item, components).status_code == 403
        assert set_recipe(owner, other_item, components).status_code == 404
        assert manager.get(f"/menu-items/{other_item}/recipe").status_code == 404
        assert set_recipe(foreign, item, components).status_code == 404

        update = owner.put(
            f"/api/restaurants/{restaurant}/inventory/ingredients/{ingredient['id']}",
            json={
                "name": "Rice",
                "unit": "ml",
                "reorder_threshold": "0",
                "is_active": True,
            },
        )
        assert update.status_code == 409, update.text
        current = owner.get(f"/api/restaurants/{restaurant}/inventory/ingredients")
        assert current.status_code == 200
        row = next(value for value in current.json() if value["id"] == ingredient["id"])
        assert row["unit"] == "g"
    finally:
        for client in clients.values():
            client.close()
