"""Catalog API.

Seeded defect for API Doctor: the declared response model requires a field that
the handler does not put in the response, so FastAPI rejects it at serialisation
time with a ResponseValidationError.
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Catalog API", version="1.0.0")


class BookOut(BaseModel):
    id: int
    title: str
    author: str
    isbn: str


BOOKS = [
    {"id": 1, "title": "Structure and Interpretation", "author": "Abelson", "isbn": "9780262510875", "year": 1985},
    {"id": 2, "title": "The Mythical Man-Month", "author": "Brooks", "isbn": "9780201835953", "year": 1975},
]


def book_for(book_id: int) -> dict:
    for book in BOOKS:
        if book["id"] == book_id:
            return book
    raise HTTPException(status_code=404, detail="Book not found")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/books")
def list_books() -> dict:
    return {"books": [{"id": b["id"], "title": b["title"]} for b in BOOKS]}


@app.get("/books/{book_id}", response_model=BookOut)
def get_book(book_id: int):
    book = book_for(book_id)
    return {
        "id": book["id"],
        "title": book["title"],
        "author": book["author"],
    }
