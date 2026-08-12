"""Users API.

Seeded defect for API Doctor: the handler reads a dictionary key that the data
does not have.
"""

from fastapi import FastAPI, HTTPException

app = FastAPI(title="Users API", version="1.0.0")

USERS = [
    {"id": 1, "name": "ada.lovelace", "email": "ada@example.com", "role": "admin"},
    {"id": 2, "name": "grace.hopper", "email": "grace@example.com", "role": "engineer"},
    {"id": 3, "name": "alan.turing", "email": "alan@example.com", "role": "engineer"},
]


def find_user(user_id: int) -> dict | None:
    for user in USERS:
        if user["id"] == user_id:
            return user
    return None


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/users")
def list_users() -> dict:
    return {"users": [{"id": u["id"], "name": u["name"]} for u in USERS]}


@app.get("/users/{user_id}")
def get_user(user_id: int) -> dict:
    user = find_user(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return {
        "id": user["id"],
        "username": user["username"],
        "email": user["email"],
    }


@app.get("/users/{user_id}/role")
def get_user_role(user_id: int) -> dict:
    user = find_user(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return {"id": user["id"], "role": user["role"]}
