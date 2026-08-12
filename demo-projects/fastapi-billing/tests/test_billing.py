from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_health():
    assert client.get("/health").status_code == 200


def test_cart_total():
    response = client.get("/carts/1/total")
    assert response.status_code == 200
    assert response.json()["total"] == 123.0


def test_single_item_total():
    response = client.get("/carts/2/total")
    assert response.status_code == 200
    assert response.json()["total"] == 310.0


def test_empty_cart_total():
    response = client.get("/carts/3/total")
    assert response.status_code == 200
    assert response.json()["total"] == 0


def test_cart_average():
    response = client.get("/carts/1/average")
    assert response.status_code == 200
    assert response.json()["average_line_value"] == 61.5


def test_empty_cart_average_is_zero():
    """An empty cart has an average line value of zero, not a server error."""
    response = client.get("/carts/3/average")
    assert response.status_code == 200
    assert response.json()["average_line_value"] == 0


def test_missing_cart():
    assert client.get("/carts/99/total").status_code == 404
