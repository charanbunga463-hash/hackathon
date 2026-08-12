"""Inventory API.

Seeded defect for API Doctor: prices are imported from CSV and stored as
strings, and one endpoint uses a price directly in arithmetic.
"""

from fastapi import FastAPI, HTTPException

app = FastAPI(title="Inventory API", version="1.0.0")

TAX_RATE = 0.2

# Imported from a CSV feed, so every price is a string.
PRODUCTS = {
    "kbd-01": {"sku": "kbd-01", "title": "Mechanical keyboard", "price": "49.00", "stock": 12},
    "mse-02": {"sku": "mse-02", "title": "Wireless mouse", "price": "25.50", "stock": 40},
    "mon-27": {"sku": "mon-27", "title": "27-inch monitor", "price": "310.00", "stock": 3},
}


def product_for(sku: str) -> dict:
    product = PRODUCTS.get(sku)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/products")
def list_products() -> dict:
    return {"products": [p["sku"] for p in PRODUCTS.values()]}


@app.get("/products/{sku}")
def get_product(sku: str) -> dict:
    product = product_for(sku)
    return {"sku": product["sku"], "title": product["title"], "price": product["price"]}


@app.get("/products/{sku}/stock")
def get_stock(sku: str) -> dict:
    product = product_for(sku)
    return {"sku": sku, "stock": product["stock"]}


@app.get("/products/{sku}/gross-price")
def gross_price(sku: str) -> dict:
    product = product_for(sku)
    gross = product["price"] * (1 + TAX_RATE)
    return {"sku": sku, "gross_price": round(gross, 2)}
