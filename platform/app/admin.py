"""Bootstrap helpers (also used by scripts/ and tests)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ApiKey, Partner, Policy, new_id
from app.policy import DEFAULT_POLICY_CONFIG, DEFAULT_USE_CASE, validate_policy_config
from app.security import new_api_key, sha256_hex
from app.timeutil import now_ms


def ensure_default_policy(db: Session) -> None:
    exists = db.scalar(select(Policy).where(Policy.partner_id.is_(None),
                                            Policy.use_case == DEFAULT_USE_CASE))
    if exists is None:
        validate_policy_config(DEFAULT_POLICY_CONFIG)
        db.add(Policy(id=new_id("pol"), partner_id=None, use_case=DEFAULT_USE_CASE, version=1,
                      config=dict(DEFAULT_POLICY_CONFIG), created_at_ms=now_ms()))


def create_partner(db: Session, name: str) -> tuple[Partner, str]:
    """Returns (partner, raw_api_key). The raw key is only available here, once."""
    partner = Partner(id=new_id("ptn"), name=name, created_at_ms=now_ms())
    raw = new_api_key()
    db.add(partner)
    db.flush()
    db.add(ApiKey(id=new_id("key"), partner_id=partner.id, key_hash=sha256_hex(raw),
                  key_prefix=raw[:12], active=True, created_at_ms=now_ms()))
    db.commit()
    return partner, raw
