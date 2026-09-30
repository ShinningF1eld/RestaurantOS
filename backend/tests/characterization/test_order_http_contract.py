"""HTTP characterization coverage for the order write contract."""

from fastapi.testclient import TestClient

from app.main import app


def create_restaurant(client: TestClient, name: str = "Order Test") -> int:
    response = client.post("/api/restaurants", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def create_menu_item(
    client: TestClient,
    restaurant_id: int,
    *,
    name: str,
    price: str,
    available: bool = True,
) -> int:
    menu_response = client.post(
        f"/restaurants/{restaurant_id}/menus",
        json={"name": "Main"},
    )
    assert menu_response.status_code == 200, menu_response.text

    item_response = client.post(
        f"/menus/{menu_response.json()['menu_id']}/items",
        json={
            "name": name,
            "price": price,
            "is_available": available,
        },
    )
    assert item_response.status_code == 200, item_response.text
    return item_response.json()["menu_item_id"]


def create_order(
    client: TestClient,
    restaurant_id: int,
    menu_item_id: int,
    *,
    quantity: int = 1,
) -> dict:
    response = client.post(
        f"/api/restaurants/{restaurant_id}/orders",
        json={"items": [{"menu_item_id": menu_item_id, "quantity": quantity}]},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_draft_item_replacement_recalculates_totals_and_snapshots_item_name() -> None:
    with TestClient(app) as client:
        restaurant_id = create_restaurant(client)
        first_item = create_menu_item(
            client,
            restaurant_id,
            name="Noodles",
            price="12.50",
        )
        replacement_item = create_menu_item(
            client,
            restaurant_id,
            name="Curry",
            price="8.25",
        )
        order = create_order(client, restaurant_id, first_item, quantity=2)

        response = client.put(
            f"/api/orders/{order['order_id']}",
            json={
                "items": [
                    {
                        "menu_item_id": replacement_item,
                        "quantity": 3,
                        "unit_price": "0.01",
                    }
                ]
            },
        )

        assert response.status_code == 200, response.text
        updated = response.json()
        assert updated["status"] == "DRAFT"
        assert updated["subtotal"] == "24.75"
        assert updated["total"] == "24.75"
        assert len(updated["items"]) == 1
        assert updated["items"][0]["menu_item_id"] == replacement_item
        assert updated["items"][0]["menu_item_name"] == "Curry"
        assert updated["items"][0]["unit_price"] == "8.25"
        assert updated["items"][0]["line_total"] == "24.75"


def test_item_replacement_is_rejected_after_order_leaves_draft() -> None:
    with TestClient(app) as client:
        restaurant_id = create_restaurant(client)
        original_item = create_menu_item(
            client,
            restaurant_id,
            name="Original",
            price="10.00",
        )
        replacement_item = create_menu_item(
            client,
            restaurant_id,
            name="Replacement",
            price="15.00",
        )
        order = create_order(client, restaurant_id, original_item)

        submitted = client.put(
            f"/api/orders/{order['order_id']}",
            json={"status": "submitted"},
        )
        assert submitted.status_code == 200, submitted.text

        response = client.put(
            f"/api/orders/{order['order_id']}",
            json={
                "items": [{"menu_item_id": replacement_item, "quantity": 1}]
            },
        )
        assert response.status_code == 409, response.text

        unchanged = client.get(f"/api/orders/{order['order_id']}")
        assert unchanged.status_code == 200, unchanged.text
        assert unchanged.json()["status"] == "SUBMITTED"
        assert unchanged.json()["items"][0]["menu_item_id"] == original_item


def test_invalid_payment_status_is_rejected_without_changing_order() -> None:
    with TestClient(app) as client:
        restaurant_id = create_restaurant(client)
        item_id = create_menu_item(
            client,
            restaurant_id,
            name="Coffee",
            price="4.00",
        )
        order = create_order(client, restaurant_id, item_id)

        response = client.put(
            f"/api/orders/{order['order_id']}",
            json={"payment_status": "refunded"},
        )

        assert response.status_code == 422, response.text
        unchanged = client.get(f"/api/orders/{order['order_id']}")
        assert unchanged.status_code == 200, unchanged.text
        assert unchanged.json()["payment_status"] == "UNPAID"


def test_order_transition_aliases_and_invalid_transition_statuses() -> None:
    with TestClient(app) as client:
        restaurant_id = create_restaurant(client)
        item_id = create_menu_item(
            client,
            restaurant_id,
            name="Tea",
            price="3.00",
        )
        order = create_order(client, restaurant_id, item_id)
        order_url = f"/api/orders/{order['order_id']}"

        same_state = client.put(order_url, json={"status": "pending"})
        assert same_state.status_code == 200, same_state.text
        assert same_state.json()["status"] == "DRAFT"

        submitted = client.put(order_url, json={"status": "SUBMITTED"})
        assert submitted.status_code == 200, submitted.text
        assert submitted.json()["status"] == "SUBMITTED"

        invalid = client.put(order_url, json={"status": "COMPLETED"})
        assert invalid.status_code == 409, invalid.text
        current = client.get(order_url)
        assert current.status_code == 200, current.text
        assert current.json()["status"] == "SUBMITTED"


def test_failed_order_update_does_not_commit_prior_field_mutations() -> None:
    with TestClient(app) as client:
        restaurant_id = create_restaurant(client)
        item_id = create_menu_item(
            client,
            restaurant_id,
            name="Soup",
            price="7.00",
        )
        order = create_order(client, restaurant_id, item_id)
        order_url = f"/api/orders/{order['order_id']}"

        response = client.put(
            order_url,
            json={
                "status": "SUBMITTED",
                "items": [{"menu_item_id": item_id, "quantity": 2}],
            },
        )
        assert response.status_code == 409, response.text

        unchanged = client.get(order_url)
        assert unchanged.status_code == 200, unchanged.text
        assert unchanged.json()["status"] == "DRAFT"
        assert unchanged.json()["items"][0]["quantity"] == 1
