from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_health():
    assert client.get("/health").status_code == 200


def test_list_accounts():
    response = client.get("/accounts")
    assert response.status_code == 200
    assert set(response.json()["accounts"]) == {"ada", "grace"}


def test_account_created():
    response = client.get("/accounts/ada/created")
    assert response.status_code == 200
    assert response.json()["created"] == "2024-01-04"


def test_missing_account():
    assert client.get("/accounts/nobody/profile").status_code == 404


def test_account_profile():
    response = client.get("/accounts/ada/profile")
    assert response.status_code == 200
    body = response.json()
    assert body["username"] == "ada"
    assert body["email"] == "ada@example.com"
    assert body["plan"] == "pro"


def test_free_plan_profile():
    response = client.get("/accounts/grace/profile")
    assert response.status_code == 200
    assert response.json()["plan"] == "free"
