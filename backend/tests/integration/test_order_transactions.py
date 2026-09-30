"""Database-backed transaction guarantees for order writes."""

from fastapi.testclient import TestClient

from app.main import app


def test_failed_status_and_item_update_rolls_back_all_order_changes() -> None:
    with TestClient(app) as client:
        restaurant = client.post("/api/restaurants", json={"name": "Rollback"})
        assert restaurant.status_code == 201, restaurant.text
        restaurant_id = restaurant.json()["id"]

        menu = client.post(
            f"/restaurants/{restaurant_id}/menus", json={"name": "Main"}
        )
        assert menu.status_code == 200, menu.text
        menu_item = client.post(
            f"/menus/{menu.json()['menu_id']}/items",
            json={"name": "Rice", "price": "5.00", "is_available": True},
        )
        assert menu_item.status_code == 200, menu_item.text

        created = client.post(
            f"/api/restaurants/{restaurant_id}/orders",
            json={"items": [{"menu_item_id": menu_item.json()["menu_item_id"], "quantity": 1}]},
        )
        assert created.status_code == 201, created.text
        order_id = created.json()["order_id"]

        failed_update = client.put(
            f"/api/orders/{order_id}",
            json={
                "status": "SUBMITTED",
                "items": [
                    {"menu_item_id": menu_item.json()["menu_item_id"], "quantity": 2}
                ],
            },
        )
        assert failed_update.status_code == 409, failed_update.text
        assert failed_update.json() == {
            "detail": "Order items can only be changed while an order is in DRAFT"
        }

        persisted = client.get(f"/api/orders/{order_id}")
        assert persisted.status_code == 200, persisted.text
        assert persisted.json()["status"] == "DRAFT"
        assert persisted.json()["items"][0]["quantity"] == 1
