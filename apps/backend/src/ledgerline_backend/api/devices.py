"""Device registration and management endpoints.

A device registers itself (authenticated) to receive a globally-unique HLC
``node_id`` used for offline sync. The device's public key is supplied as
base64; it is stored for later signature verification of pushed events.
"""

from __future__ import annotations

import base64
import binascii
import datetime as dt
import uuid

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field

from ledgerline_backend.dependencies import CurrentUserDep, SessionDep, SettingsDep
from ledgerline_backend.security.device_service import (
    DeviceNotFoundError,
    DeviceService,
)

router = APIRouter(prefix="/auth/devices", tags=["devices"])

_ALLOWED_PLATFORMS = {"win", "mac", "linux", "web"}
_MAX_PUBLIC_KEY_BYTES = 8192


class RegisterDeviceRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    platform: str = Field(min_length=1, max_length=16)
    # Base64-encoded device public key.
    public_key_b64: str = Field(min_length=1)


class RegisterDeviceResponse(BaseModel):
    device_id: uuid.UUID
    node_id: int
    entitlement_exp: dt.datetime


class DeviceResponse(BaseModel):
    id: uuid.UUID
    node_id: int
    name: str
    platform: str
    entitlement_exp: dt.datetime
    revoked: bool


@router.post(
    "/register",
    response_model=RegisterDeviceResponse,
    status_code=status.HTTP_201_CREATED,
)
def register_device(
    body: RegisterDeviceRequest,
    current_user: CurrentUserDep,
    session: SessionDep,
    settings: SettingsDep,
) -> RegisterDeviceResponse:
    """Register a device for the authenticated user and allocate its node id."""
    if body.platform not in _ALLOWED_PLATFORMS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"platform must be one of {sorted(_ALLOWED_PLATFORMS)}",
        )
    try:
        public_key = base64.b64decode(body.public_key_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="public_key_b64 is not valid base64",
        ) from exc
    if not public_key or len(public_key) > _MAX_PUBLIC_KEY_BYTES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="public key is empty or too large",
        )

    registered = DeviceService(session, settings).register(
        user_id=current_user.id,
        name=body.name,
        platform=body.platform,
        public_key=public_key,
    )
    return RegisterDeviceResponse(
        device_id=registered.device_id,
        node_id=registered.node_id,
        entitlement_exp=registered.entitlement_exp,
    )


@router.get("", response_model=list[DeviceResponse])
def list_devices(
    current_user: CurrentUserDep,
    session: SessionDep,
    settings: SettingsDep,
) -> list[DeviceResponse]:
    """List the authenticated user's registered devices."""
    devices = DeviceService(session, settings).list_for_user(current_user.id)
    return [
        DeviceResponse(
            id=d.id,
            node_id=d.node_id,
            name=d.name,
            platform=d.platform,
            entitlement_exp=d.entitlement_exp,
            revoked=d.revoked,
        )
        for d in devices
    ]


@router.post("/{device_id}/revoke", status_code=status.HTTP_204_NO_CONTENT)
def revoke_device(
    device_id: uuid.UUID,
    current_user: CurrentUserDep,
    session: SessionDep,
    settings: SettingsDep,
) -> Response:
    """Revoke one of the authenticated user's devices."""
    service = DeviceService(session, settings)
    try:
        # Ownership check that works even if the device is expired/revoked; a
        # device owned by another user is reported as not-found (leak-safe).
        service.get_owned_device(device_id, current_user.id)
    except DeviceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Device not found"
        ) from exc
    service.revoke(device_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
