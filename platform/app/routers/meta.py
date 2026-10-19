from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.keyregistry import published_keys

router = APIRouter()


@router.get("/healthz")
def healthz():
    return {"status": "ok"}


@router.get("/.well-known/certivo-keys")
def keys(db: Session = Depends(get_db)):
    """Every key the platform has signed with. Retired keys stay listed so old attestations verify."""
    return {"keys": published_keys(db)}
