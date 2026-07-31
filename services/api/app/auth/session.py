"""
Offline expedition session tokens for Abyss Mode.

An expedition session is a long-lived signed JWT that validates entirely
offline — the device never calls the server while submerged. It contains:
  - expedition_id
  - user_id + role
  - device_fingerprint (optional)
  - issued_at / expires_at
  - mode = "abyss_offline"

The JWT is signed with JWT_SECRET. It is NOT a bearer token for the API —
it is only used by the local Abyss Mode app to unlock offline functionality.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

from ..config import get_settings

# Offline sessions are valid for 45 days (typical expedition window + buffer)
OFFLINE_SESSION_DAYS = 45


def create_expedition_session(
    expedition_id: str,
    user_id: str,
    role: str,
    device_fingerprint: str | None = None,
) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "mode": "abyss_offline",
        "expedition_id": expedition_id,
        "sub": user_id,
        "role": role,
        "iat": now,
        "exp": now + timedelta(days=OFFLINE_SESSION_DAYS),
    }
    if device_fingerprint:
        payload["device"] = device_fingerprint
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def verify_expedition_session(token: str) -> dict[str, Any]:
    """
    Verify an offline expedition session token.
    Returns the decoded payload or raises jwt.PyJWTError.
    """
    settings = get_settings()
    payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    if payload.get("mode") != "abyss_offline":
        raise jwt.InvalidTokenError("Not an expedition session token")
    return payload
