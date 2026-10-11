from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/healthz")
def healthz():
    return {"status": "ok"}


@router.get("/.well-known/certivo-keys")
def keys(request: Request):
    signer = request.app.state.signer
    return {"keys": [{"key_id": signer.key_id, "alg": "Ed25519", "public_key": signer.public_key}]}
