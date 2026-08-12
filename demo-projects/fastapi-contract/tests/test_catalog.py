from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_health():
    assert client.get("/health").status_code == 200


def test_list_books():
    response = client.get("/books")
    assert response.status_code == 200
    assert len(response.json()["books"]) == 2


def test_missing_book():
    assert client.get("/books/99").status_code == 404


def test_get_book_matches_contract():
    """The declared response model requires id, title, author and isbn."""
    response = client.get("/books/1")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == 1
    assert body["title"] == "Structure and Interpretation"
    assert body["author"] == "Abelson"
    assert body["isbn"] == "9780262510875"


def test_get_second_book():
    response = client.get("/books/2")
    assert response.status_code == 200
    assert response.json()["isbn"] == "9780201835953"
