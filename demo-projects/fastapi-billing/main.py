"""Billing API.

Seeded defect for API Doctor: an average is computed without guarding the
denominator, so an empty cart crashes the endpoint.
"""

from fastapi import FastAPI, HTTPException

app = FastAPI(title="Billing API", version="1.0.0")

CARTS = {
    1: [{"sku": "kbd-01", "price": 49.0, "qty": 2}, {"sku": "mse-02", "price": 25.0, "qty": 1}],
    2: [{"sku": "mon-27", "price": 310.0, "qty": 1}],
    3: [],
}


def cart_for(cart_id: int) -> list[dict]:
    if cart_id not in CARTS:
        raise HTTPException(status_code=404, detail="Cart not found")
    return CARTS[cart_id]


def line_total(item: dict) -> float:
    return item["price"] * item["qty"]


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/carts/{cart_id}/total")
def cart_total(cart_id: int) -> dict:
    items = cart_for(cart_id)
    total = sum(line_total(item) for item in items)
    return {"cart_id": cart_id, "total": round(total, 2), "items": len(items)}


@app.get("/carts/{cart_id}/average")
def cart_average(cart_id: int) -> dict:
    items = cart_for(cart_id)
    total = sum(line_total(item) for item in items)
    average = total / len(items)
    return {"cart_id": cart_id, "average_line_value": round(average, 2)}
