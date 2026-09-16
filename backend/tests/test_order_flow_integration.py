"""PostgreSQL-backed critical-path regression coverage for Milestone 1."""
from fastapi.testclient import TestClient

from app.main import app


def create_restaurant(client: TestClient, name: str) -> int:
    response = client.post("/api/restaurants", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def create_menu_item(client: TestClient, restaurant_id: int, *, name: str, price: str, available: bool = True) -> int:
    menu = client.post(f"/restaurants/{restaurant_id}/menus", json={"name": "Main"})
    assert menu.status_code == 200, menu.text
    item = client.post(f"/menus/{menu.json()['menu_id']}/items", json={"name": name, "price": price, "is_available": available})
    assert item.status_code == 200, item.text
    return item.json()["menu_item_id"]


def advance_to_completed(client: TestClient, order_id: int) -> None:
    for state in ("SUBMITTED", "ACCEPTED", "PREPARING", "READY", "COMPLETED"):
        response = client.put(f"/api/orders/{order_id}", json={"status": state})
        assert response.status_code == 200, response.text


def test_restaurant_menu_order_completion_and_analytics_flow() -> None:
    with TestClient(app) as client:
        first_restaurant = create_restaurant(client, "First")
        second_restaurant = create_restaurant(client, "Second")
        first_item = create_menu_item(client, first_restaurant, name="Pad Thai", price="120.00")
        second_item = create_menu_item(client, second_restaurant, name="Other", price="99.00")
        unavailable_item = create_menu_item(client, first_restaurant, name="Sold out", price="70.00", available=False)
        assert client.post(f"/api/restaurants/{first_restaurant}/orders", json={"items": [{"menu_item_id": second_item, "quantity": 1}]}).status_code == 404
        assert client.post(f"/api/restaurants/{first_restaurant}/orders", json={"items": [{"menu_item_id": unavailable_item, "quantity": 1}]}).status_code == 422
        created = client.post(f"/api/restaurants/{first_restaurant}/orders", json={"items": [{"menu_item_id": first_item, "quantity": 2, "unit_price": "0.01"}]})
        assert created.status_code == 201, created.text
        order = created.json()
        assert order["subtotal"] == "240.00" and order["total"] == "240.00"
        assert order["items"][0]["unit_price"] == "120.00"
        assert order["payment_status"] == "UNPAID"
        order_id = order["order_id"]
        assert client.put(f"/api/orders/{order_id}", json={"status": "COMPLETED"}).status_code == 409
        advance_to_completed(client, order_id)
        paid = client.put(f"/api/orders/{order_id}", json={"payment_status": "PAID"})
        assert paid.status_code == 200
        assert paid.json()["payment_status"] == "PAID"
        assert client.put(f"/api/orders/{order_id}", json={"status": "PREPARING"}).status_code == 409
        assert client.delete(f"/menu-items/{first_item}").status_code == 200
        historic = client.get(f"/api/orders/{order_id}")
        assert historic.status_code == 200
        assert historic.json()["items"][0]["menu_item_name"] == "Pad Thai"
        page = client.get(f"/api/restaurants/{first_restaurant}/orders?limit=1&offset=0")
        assert page.status_code == 200 and page.json()["total"] == 1 and len(page.json()["items"]) == 1
        dashboard = client.get(f"/api/restaurants/{first_restaurant}/analytics/dashboard")
        assert dashboard.status_code == 200
        assert dashboard.json()["sales"]["value"] == "240.00"
        assert dashboard.json()["orders"]["value"] == 1
        assert dashboard.json()["average_order"]["value"] == "240.00"
        assert dashboard.json()["top_selling_items"][0]["name"] == "Pad Thai"
        # A cancelled ticket is retained operationally but never counted as revenue.
        later_item = create_menu_item(client, first_restaurant, name="Tea", price="30.00")
        cancelled = client.post(f"/api/restaurants/{first_restaurant}/orders", json={"items": [{"menu_item_id": later_item, "quantity": 1}]})
        assert cancelled.status_code == 201
        assert client.put(f"/api/orders/{cancelled.json()['order_id']}", json={"status": "CANCELLED"}).status_code == 200
        dashboard_after_cancel = client.get(f"/api/restaurants/{first_restaurant}/analytics/dashboard")
        assert dashboard_after_cancel.json()["sales"]["value"] == "240.00"
