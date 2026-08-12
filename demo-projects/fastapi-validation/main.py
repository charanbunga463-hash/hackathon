"""Signup API.

Seeded defect for API Doctor: a request model is constructed from stored data
without one of its required fields, raising a Pydantic ValidationError.
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Signup API", version="1.0.0")


class Profile(BaseModel):
    username: str
    email: str
    plan: str


ACCOUNTS = {
    "ada": {"username": "ada", "email": "ada@example.com", "plan": "pro", "created": "2024-01-04"},
    "grace": {"username": "grace", "email": "grace@example.com", "plan": "free", "created": "2024-02-11"},
}


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/accounts")
def list_accounts() -> dict:
    return {"accounts": list(ACCOUNTS)}


@app.get("/accounts/{username}/created")
def account_created(username: str) -> dict:
    account = ACCOUNTS.get(username)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    return {"username": username, "created": account["created"]}


@app.get("/accounts/{username}/profile")
def account_profile(username: str) -> dict:
    account = ACCOUNTS.get(username)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    profile = Profile(
        username=account["username"],
        email=account["email"],
    )
    return profile.model_dump()
