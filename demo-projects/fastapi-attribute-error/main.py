"""Sessions API.

Seeded defect for API Doctor: the handler reads an attribute the model class
does not define.
"""

from dataclasses import dataclass

from fastapi import FastAPI, HTTPException

app = FastAPI(title="Sessions API", version="1.0.0")


@dataclass
class Session:
    token: str
    owner: str
    expires_at: str
    active: bool


SESSIONS = {
    "tok-a": Session(token="tok-a", owner="ada", expires_at="2030-01-01T00:00:00Z", active=True),
    "tok-b": Session(token="tok-b", owner="grace", expires_at="2020-01-01T00:00:00Z", active=False),
}


def session_for(token: str) -> Session:
    session = SESSIONS.get(token)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/sessions")
def list_sessions() -> dict:
    return {"sessions": list(SESSIONS)}


@app.get("/sessions/{token}")
def get_session(token: str) -> dict:
    session = session_for(token)
    return {"token": session.token, "owner": session.owner, "active": session.active}


@app.get("/sessions/{token}/expiry")
def session_expiry(token: str) -> dict:
    session = session_for(token)
    return {"token": session.token, "expires_at": session.expiry}
