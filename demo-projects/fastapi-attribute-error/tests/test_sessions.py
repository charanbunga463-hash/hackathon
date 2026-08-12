from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_health():
    assert client.get("/health").status_code == 200


def test_list_sessions():
    response = client.get("/sessions")
    assert response.status_code == 200
    assert set(response.json()["sessions"]) == {"tok-a", "tok-b"}


def test_get_session():
    response = client.get("/sessions/tok-a")
    assert response.status_code == 200
    assert response.json()["owner"] == "ada"


def test_missing_session():
    assert client.get("/sessions/tok-nope").status_code == 404


def test_session_expiry():
    response = client.get("/sessions/tok-a/expiry")
    assert response.status_code == 200
    assert response.json()["expires_at"] == "2030-01-01T00:00:00Z"


def test_expired_session_expiry():
    response = client.get("/sessions/tok-b/expiry")
    assert response.status_code == 200
    assert response.json()["expires_at"] == "2020-01-01T00:00:00Z"
