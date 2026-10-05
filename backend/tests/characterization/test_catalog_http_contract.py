"""HTTP characterization coverage for catalog write behavior."""

from fastapi.testclient import TestClient
import pytest
from uuid import uuid4


def create_restaurant(client: TestClient, name: str = "Catalog Test") -> int:
    response = client.post("/api/restaurants", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def create_menu(client: TestClient, restaurant_id: int, name: str = "Main") -> int:
    response = client.post(
        f"/restaurants/{restaurant_id}/menus",
        json={"name": name, "description": "Original description"},
    )
    assert response.status_code == 200, response.text
    return response.json()["menu_id"]


def create_menu_item(
    client: TestClient,
    menu_id: int,
    *,
    name: str = "Dish",
    price: str = "10.00",
) -> int:
    response = client.post(
        f"/menus/{menu_id}/items",
        json={"name": name, "price": price},
    )
    assert response.status_code == 200, response.text
    return response.json()["menu_item_id"]


@pytest.mark.parametrize("price", ["-0.01", "0.001", "100000000", "NaN", "Infinity"])
def test_invalid_price_returns_422_without_changing_item(authenticated_client, price):
    client = authenticated_client
    restaurant_id = create_restaurant(client)
    menu_id = create_menu(client, restaurant_id)
    item_id = create_menu_item(client, menu_id)

    created = client.post(f"/menus/{menu_id}/items", json={"name": "Bad", "price": price})
    assert created.status_code == 422
    updated = client.put(
        f"/menu-items/{item_id}", json={"name": "Should not persist", "price": price}
    )
    assert updated.status_code == 422
    persisted = client.get(f"/menu-items/{item_id}").json()
    assert persisted["name"] == "Dish"
    assert persisted["price"] == "10.00"
    assert len(client.get(f"/menus/{menu_id}/items").json()) == 1


@pytest.mark.parametrize("price", ["0.00", "0.01", "99999999.99"])
def test_price_boundaries_round_trip(authenticated_client, price):
    client = authenticated_client
    restaurant_id = create_restaurant(client)
    menu_id = create_menu(client, restaurant_id)
    item_id = create_menu_item(client, menu_id, price=price)
    assert client.get(f"/menu-items/{item_id}").json()["price"] == price
    assert client.put(f"/menu-items/{item_id}", json={"price": price}).json()["price"] == price


def test_catalog_updates_and_deletes_preserve_status_and_response_shapes(
    authenticated_client,
) -> None:
    with authenticated_client as client:
        restaurant_id = create_restaurant(client)
        menu_id = create_menu(client, restaurant_id)
        item_id = create_menu_item(client, menu_id)

        restaurant_update = client.put(
            f"/api/restaurants/{restaurant_id}",
            json={"name": "Renamed Restaurant"},
        )
        assert restaurant_update.status_code == 200, restaurant_update.text
        assert restaurant_update.json()["name"] == "Renamed Restaurant"

        menu_update = client.put(
            f"/menus/{menu_id}",
            json={"name": "Dinner", "description": "Dinner menu"},
        )
        assert menu_update.status_code == 200, menu_update.text
        assert menu_update.json()["menu_id"] == menu_id
        assert menu_update.json()["name"] == "Dinner"
        assert menu_update.json()["description"] == "Dinner menu"

        item_update = client.put(
            f"/menu-items/{item_id}",
            json={"name": "Updated Dish", "price": "11.50", "is_available": False},
        )
        assert item_update.status_code == 200, item_update.text
        assert item_update.json()["menu_item_id"] == item_id
        assert item_update.json()["name"] == "Updated Dish"
        assert item_update.json()["price"] == "11.50"
        assert item_update.json()["is_available"] is False

        empty_menu_id = create_menu(client, restaurant_id, name="Empty menu")
        menu_delete = client.delete(f"/menus/{empty_menu_id}")
        assert menu_delete.status_code == 200, menu_delete.text
        assert menu_delete.json()["message"] == "Menu deleted successfully"
        assert client.get(f"/menus/{empty_menu_id}").status_code == 404


def test_menu_item_without_order_history_is_hard_deleted(authenticated_client) -> None:
    with authenticated_client as client:
        restaurant_id = create_restaurant(client)
        menu_id = create_menu(client, restaurant_id)
        item_id = create_menu_item(client, menu_id)

        response = client.delete(f"/menu-items/{item_id}")

        assert response.status_code == 200, response.text
        assert response.json()["message"] == "Menu item deleted successfully"
        missing = client.get(f"/menu-items/{item_id}")
        assert missing.status_code == 404


def test_menu_item_with_order_history_is_deactivated_and_snapshot_is_retained(
    authenticated_client,
) -> None:
    with authenticated_client as client:
        restaurant_id = create_restaurant(client)
        menu_id = create_menu(client, restaurant_id)
        item_id = create_menu_item(client, menu_id, name="Historic Dish", price="9.00")

        created_order = client.post(
            f"/api/restaurants/{restaurant_id}/orders",
            json={"idempotency_key": uuid4().hex, "items": [{"menu_item_id": item_id, "quantity": 2}]},
        )
        assert created_order.status_code == 201, created_order.text
        order_id = created_order.json()["order_id"]

        deleted = client.delete(f"/menu-items/{item_id}")
        assert deleted.status_code == 200, deleted.text
        assert "deactivated" in deleted.json()["message"]

        item = client.get(f"/menu-items/{item_id}")
        assert item.status_code == 200, item.text
        assert item.json()["is_available"] is False

        unavailable = client.post(
            f"/api/restaurants/{restaurant_id}/orders",
            json={"idempotency_key": uuid4().hex, "items": [{"menu_item_id": item_id, "quantity": 1}]},
        )
        assert unavailable.status_code == 422, unavailable.text

        historic = client.get(f"/api/orders/{order_id}")
        assert historic.status_code == 200, historic.text
        assert historic.json()["items"][0]["menu_item_name"] == "Historic Dish"
        assert historic.json()["items"][0]["unit_price"] == "9.00"


def test_catalog_missing_resources_keep_not_found_status(authenticated_client) -> None:
    with authenticated_client as client:
        assert (
            client.put("/api/restaurants/999999", json={"name": "Nope"}).status_code
            == 404
        )
        assert client.put("/menus/999999", json={"name": "Nope"}).status_code == 404
        assert (
            client.put("/menu-items/999999", json={"name": "Nope"}).status_code == 404
        )
        assert client.delete("/menus/999999").status_code == 404
        assert client.delete("/menu-items/999999").status_code == 404
