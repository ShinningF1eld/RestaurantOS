from fastapi.testclient import TestClient

from app.main import app


def test_health_reports_api_identity() -> None:
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "restaurantos-api",
    }
