"""Creating and reading policies (docs/spec/base/03-policy-engine.md, section 4).

A policy is an immutable version: changing settings adds a new version and never edits an old one.
A session copies the settings it starts with, so a new version can never alter a call in progress.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.attestation import config_sha256
from app.errors import ApiError
from app.models import Partner, Policy, new_id
from app.policy import build_config, normalize_config, validate_policy_settings
from app.schemas import PolicyOut


def policy_out(policy: Policy) -> PolicyOut:
    settings = normalize_config(policy.config)
    return PolicyOut(id=policy.id, use_case=policy.use_case, version=policy.version,
                     owner="certivo" if policy.partner_id is None else "partner",
                     settings=settings, settings_sha256=config_sha256(policy.config),
                     created_at_ms=policy.created_at_ms)


def create_policy(db: Session, partner: Partner, use_case: str, settings: dict, now: int) -> Policy:
    problems = validate_policy_settings(settings)
    if problems:
        raise ApiError(422, "policy_invalid", "The policy breaks the rules in document 03", details=problems)
    config = build_config(settings)
    for _ in range(3):  # two requests may race for the same version number; the loser tries the next one
        latest = db.scalar(select(func.max(Policy.version)).where(
            Policy.partner_id == partner.id, Policy.use_case == use_case)) or 0
        policy = Policy(id=new_id("pol"), partner_id=partner.id, use_case=use_case, version=latest + 1,
                        config=config, created_at_ms=now)
        db.add(policy)
        try:
            db.commit()
            return policy
        except IntegrityError:
            db.rollback()
    raise ApiError(409, "policy_version_conflict", "Another policy was created at the same moment. Try again.")
