"""OpenAPI characterization coverage for route and schema compatibility."""

from fastapi.testclient import TestClient

from app.main import app


def test_openapi_exposes_current_write_routes_and_contract_schemas() -> None:
    with TestClient(app) as client:
        response = client.get("/openapi.json")

    assert response.status_code == 200, response.text
    document = response.json()
    paths = document["paths"]
    schemas = document["components"]["schemas"]

    expected_methods = {
        "/api/restaurants": {"get", "post"},
        "/api/restaurants/{restaurant_id}": {"get", "put", "delete"},
        "/restaurants/{restaurant_id}/menus": {"get", "post"},
        "/menus/{menu_id}": {"get", "put", "delete"},
        "/menus/{menu_id}/items": {"get", "post"},
        "/menu-items/{menu_item_id}": {"get", "put", "delete"},
        "/menu-items/{menu_item_id}/recipe": {"get", "put"},
        "/api/restaurants/{restaurant_id}/orders": {"get", "post"},
        "/api/orders/{order_id}": {"get", "put", "delete"},
    }
    for path, methods in expected_methods.items():
        assert path in paths
        assert methods <= set(paths[path])

    for schema_name in (
        "RestaurantCreate",
        "RestaurantResponse",
        "MenuCreate",
        "MenuResponse",
        "MenuItemCreate",
        "MenuItemResponse",
        "RecipeReplaceRequest",
        "RecipeResponse",
        "OrderCreate",
        "OrderUpdate",
        "OrderResponse",
        "PaginatedOrders",
    ):
        assert schema_name in schemas


def test_openapi_keeps_write_response_statuses_and_response_models() -> None:
    with TestClient(app) as client:
        document = client.get("/openapi.json").json()

    paths = document["paths"]
    schemas = document["components"]["schemas"]
    assert "201" in paths["/api/restaurants"]["post"]["responses"]
    assert (
        "201" in paths["/api/restaurants/{restaurant_id}/orders"]["post"]["responses"]
    )
    assert "204" in paths["/api/restaurants/{restaurant_id}"]["delete"]["responses"]
    assert "204" in paths["/api/orders/{order_id}"]["delete"]["responses"]

    restaurant_response = paths["/api/restaurants"]["post"]["responses"]["201"]
    order_response = paths["/api/restaurants/{restaurant_id}/orders"]["post"][
        "responses"
    ]["201"]
    assert restaurant_response["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("/RestaurantResponse")
    assert order_response["content"]["application/json"]["schema"]["$ref"].endswith(
        "/OrderResponse"
    )
    create_schema = schemas["OrderCreate"]
    assert "idempotency_key" in create_schema["required"]
