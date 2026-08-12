"""Orders API.

Seeded defect for API Doctor: the lookup endpoint returns an empty successful
response for a missing order instead of raising a 404.
"""

from fastapi import FastAPI, HTTPException

app = FastAPI(title="Orders API", version="1.0.0")

ORDERS = {
    "ord-1001": {"id": "ord-1001", "customer": "ada", "total": 74.0, "status": "shipped"},
    "ord-1002": {"id": "ord-1002", "customer": "grace", "total": 310.0, "status": "packing"},
}


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/orders")
def list_orders() -> dict:
    return {"orders": list(ORDERS)}


@app.get("/orders/{order_id}")
def get_order(order_id: str):
    order = ORDERS.get(order_id)
    if order is None:
        return None
    return order


@app.get("/orders/{order_id}/status")
def get_order_status(order_id: str) -> dict:
    order = ORDERS.get(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return {"id": order["id"], "status": order["status"]}
