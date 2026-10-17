"""Cursor paging for lists (docs/spec/base/01-api-conventions-and-errors.md, "Lists")."""
from __future__ import annotations

import json

from app.crypto import b64u_decode, b64u_encode
from app.errors import ApiError


def encode_cursor(created_at_ms: int, item_id: str) -> str:
    return b64u_encode(json.dumps([created_at_ms, item_id]).encode())


def decode_cursor(cursor: str) -> tuple[int, str]:
    try:
        created_at_ms, item_id = json.loads(b64u_decode(cursor))
        if not isinstance(created_at_ms, int) or not isinstance(item_id, str):
            raise ValueError
        return created_at_ms, item_id
    except (ValueError, TypeError):
        raise ApiError(422, "validation_error", "cursor is not valid") from None
