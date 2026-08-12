from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_health():
    assert client.get("/health").status_code == 200


def test_list_products():
    response = client.get("/products")
    assert response.status_code == 200
    assert len(response.json()["products"]) == 3


def test_get_product():
    response = client.get("/products/kbd-01")
    assert response.status_code == 200
    assert response.json()["title"] == "Mechanical keyboard"


def test_get_stock():
    response = client.get("/products/mse-02/stock")
    assert response.status_code == 200
    assert response.json()["stock"] == 40


def test_missing_product():
    assert client.get("/products/nope-99").status_code == 404


def test_gross_price():
    response = client.get("/products/kbd-01/gross-price")
    assert response.status_code == 200
    assert response.json()["gross_price"] == 58.8


def test_gross_price_monitor():
    response = client.get("/products/mon-27/gross-price")
    assert response.status_code == 200
    assert response.json()["gross_price"] == 372.0
