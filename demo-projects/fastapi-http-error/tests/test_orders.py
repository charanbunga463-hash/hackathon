from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_health():
    assert client.get("/health").status_code == 200


def test_list_orders():
    response = client.get("/orders")
    assert response.status_code == 200
    assert len(response.json()["orders"]) == 2


def test_get_order():
    response = client.get("/orders/ord-1001")
    assert response.status_code == 200
    assert response.json()["customer"] == "ada"


def test_get_order_status():
    response = client.get("/orders/ord-1002/status")
    assert response.status_code == 200
    assert response.json()["status"] == "packing"


def test_missing_order_status_is_404():
    assert client.get("/orders/ord-9999/status").status_code == 404


def test_missing_order_is_404():
    """A missing order must be a 404, not a 200 with a null body."""
    response = client.get("/orders/ord-9999")
    assert response.status_code == 404
