from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_list_users():
    response = client.get("/users")
    assert response.status_code == 200
    assert len(response.json()["users"]) == 3


def test_get_user():
    response = client.get("/users/1")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == 1
    assert body["username"] == "ada.lovelace"
    assert body["email"] == "ada@example.com"


def test_get_second_user():
    response = client.get("/users/2")
    assert response.status_code == 200
    assert response.json()["username"] == "grace.hopper"


def test_get_missing_user():
    response = client.get("/users/999")
    assert response.status_code == 404


def test_get_user_role():
    response = client.get("/users/2/role")
    assert response.status_code == 200
    assert response.json()["role"] == "engineer"
