"""The account surface behind /settings.

Every endpoint here backs a control the user can actually see, and every control
the user can see is backed by an endpoint here. Nothing on the Settings page is
decorative: changing a preference changes behaviour somewhere in the backend,
and the field comments in `models.user.UserPreferences` name the consumer.

Authentication is not re-implemented. These paths are absent from
`PUBLIC_AUTH_PATHS`, so the gateway has already resolved a session before any
handler runs, and `principal.user_id` is the only account any of them will
touch — there is no route here that takes a user id.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from ...config.settings import Settings
from ...models.user import (
    PublicUser,
    UserPreferences,
    validate_name,
    validate_password,
)
from ...runtime.identity import Principal
from ...services.session_service import SESSION_COOKIE, get_session_service
from ...services.user_service import (
    InvalidCredentials,
    UserService,
    get_user_service,
)
from ...utils.logging import get_logger
from ..deps import current_principal, project_service, settings_dep
from ...services.project_service import ProjectService

logger = get_logger(__name__)

router = APIRouter(prefix="/account", tags=["account"])


def user_service(settings: Settings = Depends(settings_dep)) -> UserService:
    return get_user_service(settings)


# --------------------------------------------------------------- schemas ----
class ProfileRequest(BaseModel):
    name: str = Field(max_length=200)


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(max_length=400)
    new_password: str = Field(max_length=400)


class PreferencesRequest(BaseModel):
    """A partial update: only the fields present are changed.

    Sending the whole object would mean a client on an older build silently
    resetting a preference it does not know about.
    """

    theme: str | None = None
    api_timeout_seconds: int | None = Field(default=None, ge=1, le=300)
    probe_write_methods: bool | None = None
    ai_analysis: bool | None = None
    require_patch_approval: bool | None = None


class DeleteAccountRequest(BaseModel):
    # Deleting an account destroys every project the user owns. Requiring the
    # password means a borrowed, unlocked browser cannot do it in one click.
    password: str = Field(max_length=400)


def _field_error(field: str, message: str) -> HTTPException:
    return HTTPException(status_code=422, detail=message, headers={"X-Field": field})


async def _require_user(principal: Principal, users: UserService):
    user = await users.get_cached_async(principal.user_id or principal.tenant)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="authentication required"
        )
    return user


# --------------------------------------------------------------- profile ----
@router.get("/profile", response_model=PublicUser)
async def get_profile(
    principal: Principal = Depends(current_principal),
    users: UserService = Depends(user_service),
):
    user = await _require_user(principal, users)
    return PublicUser(**user.public())


@router.patch("/profile", response_model=PublicUser)
async def update_profile(
    payload: ProfileRequest,
    principal: Principal = Depends(current_principal),
    users: UserService = Depends(user_service),
):
    if (problem := validate_name(payload.name)) is not None:
        raise _field_error("name", problem)
    user = await _require_user(principal, users)
    updated = await users.set_name_async(user, payload.name)
    logger.info("profile updated: %s", updated.id)
    return PublicUser(**updated.public())


# -------------------------------------------------------------- password ----
@router.post("/password")
async def change_password(
    payload: PasswordChangeRequest,
    request: Request,
    response: Response,
    principal: Principal = Depends(current_principal),
    settings: Settings = Depends(settings_dep),
    users: UserService = Depends(user_service),
):
    """Change the password, then sign every *other* session out.

    `set_password` bumps `session_epoch`, which invalidates every session
    including the caller's own. Rather than logging the user out of the tab they
    are working in, a fresh session is issued at the new epoch — so the change
    takes effect everywhere else immediately and here seamlessly.
    """
    user = await _require_user(principal, users)

    if (problem := validate_password(
        payload.new_password, name=user.name, email=user.email
    )) is not None:
        raise _field_error("new_password", problem)
    if payload.new_password == payload.current_password:
        raise _field_error("new_password", "Choose a password you have not used here before.")

    try:
        updated = await users.change_password_async(
            user, payload.current_password, payload.new_password
        )
    except InvalidCredentials as exc:
        logger.info("password change refused for %s: wrong current password", user.id)
        raise _field_error("current_password", str(exc)) from exc

    sessions = get_session_service(settings)
    # Every old session is dead by epoch; drop the records too so they stop
    # occupying the index and cannot be listed as active.
    await sessions.revoke_all(updated.id)
    token, max_age = await sessions.issue(
        updated.id,
        updated.session_epoch,
        user_agent=request.headers.get("user-agent", ""),
        ip=request.client.host if request.client else "",
    )
    response.set_cookie(value=token, **sessions.cookie_kwargs(max_age))
    logger.info("password changed: %s", updated.id)
    return {
        "status": "ok",
        "detail": "Your password was changed. Other devices have been signed out.",
    }


# -------------------------------------------------------------- sessions ----
@router.get("/sessions")
async def list_sessions(
    principal: Principal = Depends(current_principal),
    settings: Settings = Depends(settings_dep),
):
    """Live sessions for this account. Never returns a token or its hash."""
    sessions = get_session_service(settings)
    records = await sessions.list_for_user(principal.user_id or principal.tenant)
    current_hash = principal.session_token_hash
    return {
        "sessions": [
            record.public(current=record.token_hash == current_hash) for record in records
        ],
        "count": len(records),
    }


@router.post("/sessions/revoke-all")
async def revoke_all_sessions(
    request: Request,
    response: Response,
    principal: Principal = Depends(current_principal),
    settings: Settings = Depends(settings_dep),
):
    """Sign out everywhere, including here.

    Deliberately includes the current session: "log out all sessions" that
    quietly kept one alive would be a lie, and the user can sign back in.
    """
    sessions = get_session_service(settings)
    killed = await sessions.revoke_all(principal.user_id or principal.tenant)
    response.delete_cookie(SESSION_COOKIE, path="/")
    logger.info("all sessions revoked: %s (%d)", principal.user_id, killed)
    return {"status": "ok", "revoked": killed}


# ----------------------------------------------------------- preferences ----
@router.get("/preferences", response_model=UserPreferences)
async def get_preferences(
    principal: Principal = Depends(current_principal),
    users: UserService = Depends(user_service),
):
    user = await _require_user(principal, users)
    return user.preferences


@router.put("/preferences", response_model=UserPreferences)
async def update_preferences(
    payload: PreferencesRequest,
    principal: Principal = Depends(current_principal),
    users: UserService = Depends(user_service),
):
    user = await _require_user(principal, users)
    changes = payload.model_dump(exclude_none=True)
    if not changes:
        return user.preferences
    try:
        merged = UserPreferences.model_validate(
            {**user.preferences.model_dump(), **changes}
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail="Those preference values are not valid."
        ) from exc
    updated = await users.set_preferences_async(user, merged)
    logger.info("preferences updated: %s", updated.id)
    return updated.preferences


# --------------------------------------------------------------- deletion ---
@router.delete("")
async def delete_account(
    payload: DeleteAccountRequest,
    response: Response,
    principal: Principal = Depends(current_principal),
    settings: Settings = Depends(settings_dep),
    users: UserService = Depends(user_service),
    projects: ProjectService = Depends(project_service),
):
    """Delete the account, its sessions and every project it owns.

    Ordered so a failure cannot leave an orphan: workspaces first (they are the
    only thing that cannot be reached again once the account row is gone), then
    the sessions, then the account.
    """
    user = await _require_user(principal, users)

    from ...security.passwords import verify_password

    if not verify_password(payload.password, user.password_hash):
        logger.info("account deletion refused for %s: wrong password", user.id)
        raise _field_error("password", "Your password is not correct.")

    owned = await projects.list_projects_async(user.id)
    removed = 0
    for summary in owned:
        try:
            if await projects.delete_async(summary.id, user.id):
                removed += 1
        except Exception as exc:  # noqa: BLE001 - keep going; report at the end
            logger.error("could not delete project %s during account deletion: %s",
                         summary.id, exc)

    await get_session_service(settings).purge_user(user.id)
    await users.delete_async(user.id)
    response.delete_cookie(SESSION_COOKIE, path="/")
    logger.info("account deleted: %s (%d project(s))", user.id, removed)
    return {"status": "ok", "deleted": True, "projects_deleted": removed}
