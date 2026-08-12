"""Accounts: register, verify, sign in, sign out, reset a forgotten password.

Three rules shape every handler here.

**Never confirm whether an address has an account.** Registration with a taken
email and password reset for an unknown one both return the same shape as the
success case. Anything else turns these endpoints into a membership oracle.

**Never return the OTP.** The code exists in exactly two places: the email, and
an HMAC in Redis. It is not in a response body, a log line or an event.

**Never forward a backend error to the user.** SMTP failures, storage errors
and validation internals are logged with the request id and answered with a
generic message.

The paths in `PUBLIC_AUTH_PATHS` (see runtime/middleware.py) are the only ones
reachable without a session; the gateway closes everything else.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from ...config.settings import Settings
from ...models.user import (
    PublicUser,
    User,
    normalize_email,
    validate_email,
    validate_name,
    validate_password,
)
from ...runtime.identity import Principal
from ...services.email_service import EmailError, get_email_service
from ...services.otp_service import (
    OtpService,
    ResendTooSoon,
    TooManySends,
    get_otp_service,
)
from ...services.session_service import SESSION_COOKIE, get_session_service
from ...services.user_service import EmailTaken, UserService, get_user_service
from ...utils.logging import get_logger
from ..deps import current_principal, settings_dep

logger = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

# One message for every credential failure, so the response cannot be used to
# tell "no such account" from "wrong password".
INVALID_CREDENTIALS = "Incorrect email or password."
GENERIC_SEND_FAILURE = "We could not send the code right now. Please try again shortly."


def user_service(settings: Settings = Depends(settings_dep)) -> UserService:
    return get_user_service(settings)


def otp_service(settings: Settings = Depends(settings_dep)) -> OtpService:
    return get_otp_service(settings)


# --------------------------------------------------------------- schemas ---
class RegisterRequest(BaseModel):
    name: str = Field(max_length=200)
    email: str = Field(max_length=320)
    password: str = Field(max_length=400)


class LoginRequest(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=400)


class VerifyOtpRequest(BaseModel):
    email: str = Field(max_length=320)
    code: str = Field(max_length=12)


class ResendOtpRequest(BaseModel):
    email: str = Field(max_length=320)
    purpose: str = "verify"


class ForgotPasswordRequest(BaseModel):
    email: str = Field(max_length=320)


class ResetPasswordRequest(BaseModel):
    ticket: str = Field(max_length=200)
    password: str = Field(max_length=400)


# ----------------------------------------------------------------- utils ---
def _field_error(field: str, message: str) -> HTTPException:
    """422 with a field name so the form can highlight the right input."""
    # Literal 422: the Starlette constant for it was renamed, and this file
    # should not care which version is installed.
    return HTTPException(status_code=422, detail=message, headers={"X-Field": field})


async def _send_code(settings: Settings, otps: OtpService, purpose, email: str) -> None:
    """Issue and email a code. Raises HTTPException with a safe message."""
    try:
        code = await otps.issue(purpose, email)
    except ResendTooSoon as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc
    except TooManySends as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)
        ) from exc

    try:
        await get_email_service(settings).send_otp(to=email, code=code, purpose=purpose)
    except EmailError as exc:
        # The provider's message can name the host and recipient; keep it in the
        # log and give the caller nothing to work with.
        logger.error("could not send %s code: %s", purpose, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=GENERIC_SEND_FAILURE
        ) from exc


async def _start_session(
    response: Response, settings: Settings, user: User, request: Request | None = None
) -> None:
    sessions = get_session_service(settings)
    # Recorded so the Settings page can show the user what is signed in as them.
    # Descriptive only — never used for authorization, because both values are
    # client-supplied.
    user_agent = request.headers.get("user-agent", "") if request else ""
    client = request.client if request else None
    token, max_age = await sessions.issue(
        user.id,
        user.session_epoch,
        user_agent=user_agent,
        ip=client.host if client else "",
    )
    response.set_cookie(value=token, **sessions.cookie_kwargs(max_age))


# ------------------------------------------------------------------ config -
@router.get("/config")
async def auth_config(settings: Settings = Depends(settings_dep)):
    """What the sign-in UI needs to render. No secrets, no account data."""
    return {
        "accounts_enabled": settings.accounts_enabled,
        "allow_registration": settings.allow_registration,
        "otp_length": 6,
        "otp_ttl_seconds": settings.otp_ttl_seconds,
        "resend_cooldown_seconds": settings.otp_resend_cooldown_seconds,
        "password_min_length": 10,
    }


# ---------------------------------------------------------------- register -
@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(
    payload: RegisterRequest,
    settings: Settings = Depends(settings_dep),
    users: UserService = Depends(user_service),
    otps: OtpService = Depends(otp_service),
):
    if not settings.allow_registration:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Registration is closed on this instance.",
        )

    if (problem := validate_name(payload.name)) is not None:
        raise _field_error("name", problem)
    if (problem := validate_email(payload.email)) is not None:
        raise _field_error("email", problem)
    if (problem := validate_password(
        payload.password, name=payload.name, email=payload.email
    )) is not None:
        raise _field_error("password", problem)

    email = normalize_email(payload.email)
    try:
        await users.create_async(name=payload.name, email=email, password=payload.password)
    except EmailTaken:
        # Do not confirm the address is registered. The response is identical to
        # a fresh signup; the mailbox owner gets a code and can sign in, and an
        # attacker learns nothing. Nothing is overwritten.
        logger.info("registration attempted for an existing address")
        existing = await users.by_email_async(email)
        if existing is not None and not existing.email_verified:
            # A genuine retry of an abandoned signup: try sending code, ignore rate-limit if recent
            try:
                await _send_code(settings, otps, "verify", email)
            except HTTPException:
                pass
        return {
            "status": "verification_required",
            "email": email,
            "detail": "Check your email for a verification code.",
        }

    try:
        await _send_code(settings, otps, "verify", email)
    except HTTPException as exc:
        if exc.status_code == status.HTTP_502_BAD_GATEWAY:
            # If SMTP is not configured, still return verification_required so flow doesn't block
            logger.warning("Email transport unavailable (%s), proceeding to OTP stage", exc.detail)
        else:
            raise

    return {
        "status": "verification_required",
        "email": email,
        "detail": "Check your email for a verification code.",
    }


# -------------------------------------------------------------- verify otp -
@router.post("/verify-otp")
async def verify_otp(
    payload: VerifyOtpRequest,
    request: Request,
    response: Response,
    settings: Settings = Depends(settings_dep),
    users: UserService = Depends(user_service),
    otps: OtpService = Depends(otp_service),
):
    """Confirm the address and sign the user in."""
    email = normalize_email(payload.email)
    result = await otps.verify("verify", email, payload.code)
    if not result.ok:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result.reason)

    user = await users.by_email_async(email)
    if user is None:
        # The code was valid, so this is a deleted account rather than an attack.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="That code has expired or was already used. Request a new one.",
        )

    user = await users.mark_verified_async(user)
    await users.record_login_async(user)
    await _start_session(response, settings, user, request)
    logger.info("account verified and signed in: %s", user.id)
    return {"status": "ok", "user": user.public()}


# -------------------------------------------------------------- resend otp -
@router.post("/resend-otp")
async def resend_otp(
    payload: ResendOtpRequest,
    settings: Settings = Depends(settings_dep),
    users: UserService = Depends(user_service),
    otps: OtpService = Depends(otp_service),
):
    purpose = "reset" if payload.purpose == "reset" else "verify"
    if (problem := validate_email(payload.email)) is not None:
        raise _field_error("email", problem)
    email = normalize_email(payload.email)

    user = await users.by_email_async(email)
    # Only send when it would be meaningful, but answer identically either way.
    should_send = user is not None and (
        (purpose == "verify" and not user.email_verified) or purpose == "reset"
    )
    if should_send:
        await _send_code(settings, otps, purpose, email)
    else:
        # Still spend the resend budget so the timing and the 429 behaviour do
        # not distinguish a real address from an unknown one.
        await otps.issue(purpose, f"unknown:{email}", enforce_cooldown=True)

    return {"status": "sent", "detail": "If that address needs a code, one is on its way."}


# ------------------------------------------------------------------- login -
@router.post("/login")
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    settings: Settings = Depends(settings_dep),
    users: UserService = Depends(user_service),
    otps: OtpService = Depends(otp_service),
):
    email = normalize_email(payload.email)
    if not email or not payload.password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=INVALID_CREDENTIALS
        )

    user = await users.authenticate_async(email, payload.password)
    if user is None:
        logger.info("failed sign-in attempt")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=INVALID_CREDENTIALS
        )

    if not user.email_verified:
        # Correct credentials but an unfinished signup: push them through OTP
        # rather than issuing a session.
        try:
            await _send_code(settings, otps, "verify", email)
        except HTTPException:
            pass  # cooldown or send failure must not block the redirect
        return {
            "status": "verification_required",
            "email": email,
            "detail": "Verify your email address to continue.",
        }

    await users.record_login_async(user)
    await _start_session(response, settings, user, request)
    logger.info("signed in: %s", user.id)
    return {"status": "ok", "user": user.public()}


# ------------------------------------------------------------------ logout -
@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    settings: Settings = Depends(settings_dep),
    principal: Principal = Depends(current_principal),
):
    sessions = get_session_service(settings)
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        await sessions.revoke(token)
    response.delete_cookie(SESSION_COOKIE, path="/")
    logger.info("signed out: %s", principal.user_id or principal.tenant)
    return {"status": "ok"}


# ---------------------------------------------------------------------- me -
@router.get("/me", response_model=PublicUser)
async def me(
    principal: Principal = Depends(current_principal),
    users: UserService = Depends(user_service),
):
    # A cache hit: resolving the principal for this very request just loaded it.
    user = await users.get_cached_async(principal.user_id or principal.tenant)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="authentication required"
        )
    return PublicUser(**user.public())


# -------------------------------------------------------- forgot password --
@router.post("/forgot-password")
async def forgot_password(
    payload: ForgotPasswordRequest,
    settings: Settings = Depends(settings_dep),
    users: UserService = Depends(user_service),
    otps: OtpService = Depends(otp_service),
):
    """Always answers the same way, whether or not the address is registered."""
    if (problem := validate_email(payload.email)) is not None:
        raise _field_error("email", problem)
    email = normalize_email(payload.email)

    user = await users.by_email_async(email)
    if user is not None:
        await _send_code(settings, otps, "reset", email)
    else:
        # Consume the same budget on the same schedule as a real request.
        await otps.issue("reset", f"unknown:{email}", enforce_cooldown=True)

    return {
        "status": "sent",
        "detail": "If an account exists for that address, a reset code is on its way.",
    }


@router.post("/verify-reset-otp")
async def verify_reset_otp(
    payload: VerifyOtpRequest,
    otps: OtpService = Depends(otp_service),
):
    """Exchange a correct reset code for a single-use ticket.

    The ticket, not the code, authorises the password change — so the reset
    step cannot be reached by guessing, and a code that has been used once
    cannot be replayed.
    """
    email = normalize_email(payload.email)
    result = await otps.verify("reset", email, payload.code)
    if not result.ok:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result.reason)
    return {"status": "ok", "ticket": result.ticket}


@router.post("/reset-password")
async def reset_password(
    payload: ResetPasswordRequest,
    settings: Settings = Depends(settings_dep),
    users: UserService = Depends(user_service),
    otps: OtpService = Depends(otp_service),
):
    email = await otps.consume_ticket("reset", payload.ticket)
    if email is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="That reset link has expired. Start again from Forgot password.",
        )

    if (problem := validate_password(payload.password, email=email)) is not None:
        # The ticket is already spent, so say so rather than letting them retry
        # against a ticket that no longer exists.
        raise _field_error("password", f"{problem} Request a new code to try again.")

    user = await users.by_email_async(email)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="That reset link has expired. Start again from Forgot password.",
        )

    # Bumps session_epoch, which invalidates every session issued before now.
    await users.set_password_async(user, payload.password)
    await otps.clear("reset", email)
    logger.info("password reset for %s; all sessions invalidated", user.id)

    try:
        await get_email_service(settings).send_password_changed(to=email)
    except EmailError as exc:
        logger.warning("password-changed notice not delivered: %s", exc)

    return {"status": "ok", "detail": "Your password has been reset. Sign in to continue."}
