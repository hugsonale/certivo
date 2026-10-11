from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.crypto import b64u_decode
from app.db import get_db
from app.errors import ApiError
from app.models import Device, Partner, new_id
from app.schemas import DeviceIn, DeviceOut
from app.security import require_partner

router = APIRouter()


def _out(d: Device) -> DeviceOut:
    return DeviceOut(id=d.id, trust_tier=d.trust_tier, status=d.status,
                     created_at_ms=d.created_at_ms)


@router.post("/v1/devices", status_code=201, response_model=DeviceOut)
def register_device(body: DeviceIn, request: Request, partner: Partner = Depends(require_partner),
                    db: Session = Depends(get_db)):
    if len(b64u_decode(body.public_key)) != 32:
        raise ApiError(422, "invalid_public_key", "public_key must be a 32-byte Ed25519 key")
    device = Device(id=new_id("dev"), partner_id=partner.id, public_key=body.public_key,
                    trust_tier="software_only", status="active",
                    created_at_ms=request.app.state.clock())
    db.add(device)
    db.commit()
    return _out(device)


@router.get("/v1/devices/{device_id}", response_model=DeviceOut)
def get_device(device_id: str, partner: Partner = Depends(require_partner),
               db: Session = Depends(get_db)):
    device = db.get(Device, device_id)
    if device is None or device.partner_id != partner.id:
        raise ApiError(404, "device_not_found", "Device not found")
    return _out(device)
