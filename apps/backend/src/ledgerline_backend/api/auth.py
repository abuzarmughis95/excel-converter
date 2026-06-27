"""Authentication endpoints: register, login, refresh, logout, and me.

Error responses are deliberately generic for credential failures to avoid user
enumeration. All state-changing handlers run within the request-scoped session
dependency, which commits on success and rolls back on error.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, EmailStr, Field

from ledgerline_backend.dependencies import (
    ClientIpDep,
    CurrentUserDep,
    RateLimiterDep,
    SessionDep,
    SettingsDep,
)
from ledgerline_backend.security.auth_service import (
    AccountInactiveError,
    AccountLockedError,
    AuthService,
    DuplicateEmailError,
    InvalidCredentialsError,
    InvalidRefreshTokenError,
    UnknownOrganisationError,
)

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    org_id: uuid.UUID
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=8, max_length=1024)


class UserResponse(BaseModel):
    id: uuid.UUID
    email: EmailStr
    display_name: str
    status: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=1024)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    mfa_required: bool = False


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class LogoutRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


_INVALID_CREDENTIALS = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid email or password",
    headers={"WWW-Authenticate": "Bearer"},
)


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest, session: SessionDep, settings: SettingsDep) -> UserResponse:
    """Register a new user and credentials.

    Disabled when ``allow_open_registration`` is false (invitation-only
    deployments). The referenced organisation must already exist.
    """
    if not settings.allow_open_registration:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Open registration is disabled",
        )
    service = AuthService(session, settings)
    try:
        user = service.register(
            org_id=body.org_id,
            email=str(body.email),
            display_name=body.display_name,
            password=body.password,
        )
    except UnknownOrganisationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Unknown organisation",
        ) from exc
    except DuplicateEmailError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with that email already exists",
        ) from exc
    return UserResponse(
        id=user.id, email=user.email, display_name=user.display_name, status=user.status
    )


@router.post("/login", response_model=TokenResponse)
def login(
    body: LoginRequest,
    session: SessionDep,
    settings: SettingsDep,
    rate_limiter: RateLimiterDep,
    client_ip: ClientIpDep,
) -> TokenResponse:
    """Authenticate and issue an access/refresh token pair.

    Per-IP throttling complements per-account lockout so an attacker cannot evade
    the lockout by spreading attempts across many accounts from one host.
    """
    if rate_limiter.is_blocked(client_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts; try again later",
        )

    service = AuthService(session, settings)
    try:
        pair = service.login(email=str(body.email), password=body.password)
    except AccountLockedError as exc:
        rate_limiter.record(client_ip)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Account temporarily locked due to failed attempts",
        ) from exc
    except (InvalidCredentialsError, AccountInactiveError) as exc:
        rate_limiter.record(client_ip)
        raise _INVALID_CREDENTIALS from exc

    # Successful login clears the IP's failure budget.
    rate_limiter.reset(client_ip)
    return TokenResponse(
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
        expires_in=pair.expires_in,
        mfa_required=pair.mfa_required,
    )


@router.post("/refresh", response_model=TokenResponse)
def refresh(body: RefreshRequest, session: SessionDep, settings: SettingsDep) -> TokenResponse:
    """Rotate a refresh token, returning a fresh pair and revoking the old one."""
    service = AuthService(session, settings)
    try:
        pair = service.refresh(refresh_token=body.refresh_token)
    except InvalidRefreshTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        ) from exc
    return TokenResponse(
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
        expires_in=pair.expires_in,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(body: LogoutRequest, session: SessionDep, settings: SettingsDep) -> Response:
    """Revoke a refresh token. Idempotent: unknown tokens succeed silently."""
    AuthService(session, settings).logout(refresh_token=body.refresh_token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=UserResponse)
def me(current_user: CurrentUserDep) -> UserResponse:
    """Return the authenticated user's profile."""
    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        display_name=current_user.display_name,
        status=current_user.status,
    )
