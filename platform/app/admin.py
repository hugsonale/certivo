"""Bootstrap helpers (also used by scripts/ and tests)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import ApiKey, Partner, Policy, new_id
from app.policy import DEFAULT_POLICY_CONFIG, DEFAULT_USE_CASE, validate_policy_config
from app.scopes import ALL_SCOPES
from app.security import new_api_key, sha256_hex
from app.timeutil import now_ms


def ensure_default_policy(db: Session) -> None:
    exists = db.scalar(select(Policy).where(Policy.partner_id.is_(None),
                                            Policy.use_case == DEFAULT_USE_CASE))
    if exists is None:
        validate_policy_config(DEFAULT_POLICY_CONFIG)
        db.add(Policy(id=new_id("pol"), partner_id=None, use_case=DEFAULT_USE_CASE, version=1,
                      config=dict(DEFAULT_POLICY_CONFIG), created_at_ms=now_ms()))
        try:
            db.flush()
        except IntegrityError:
            # Another process seeded it first (two app instances starting together). That's fine.
            db.rollback()


def create_api_key(db: Session, partner_id: str, name: str, scopes: list[str],
                   now: int | None = None) -> tuple[ApiKey, str]:
    """Returns (key row, raw key). The raw key exists only here, once; only its hash is stored."""
    raw = new_api_key()
    key = ApiKey(id=new_id("key"), partner_id=partner_id, name=name, key_hash=sha256_hex(raw),
                 key_prefix=raw[:12], scopes=list(scopes), active=True,
                 created_at_ms=now if now is not None else now_ms())
    db.add(key)
    return key, raw


def create_partner(db: Session, name: str) -> tuple[Partner, str]:
    """Creates a partner with one all-scopes key. Returns (partner, raw_api_key), shown once."""
    partner = Partner(id=new_id("ptn"), name=name, created_at_ms=now_ms())
    db.add(partner)
    db.flush()
    _, raw = create_api_key(db, partner.id, "initial key", list(ALL_SCOPES))
    db.commit()
    return partner, raw
