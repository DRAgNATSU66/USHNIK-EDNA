"""
Google ID token verification.

google-auth verifies the token signature, expiry, and audience against
Google's public keys. Never trust a token that hasn't been verified here.
"""
from __future__ import annotations
from dataclasses import dataclass

from ..config import get_settings


@dataclass
class GoogleClaims:
    sub: str           # stable Google user ID — use as the primary key
    email: str
    email_verified: bool
    name: str | None
    picture: str | None


async def verify_google_id_token(id_token: str) -> GoogleClaims:
    """
    Verify a Google ID token and return the extracted claims.

    Raises ValueError if the token is invalid, expired, or issued for a
    different audience (wrong GOOGLE_CLIENT_ID).
    """
    settings = get_settings()
    if not settings.google_client_id:
        raise ValueError("GOOGLE_CLIENT_ID is not configured")

    try:
        from google.oauth2 import id_token as google_id_token
        from google.auth.transport import requests as google_requests

        # This makes a network call to fetch Google's public certs on first use.
        # Certs are cached by the google-auth library automatically.
        claims = google_id_token.verify_oauth2_token(
            id_token,
            google_requests.Request(),
            settings.google_client_id,
        )
    except Exception as exc:
        raise ValueError(f"Google token verification failed: {exc}") from exc

    if not claims.get("email_verified"):
        raise ValueError("Google account email is not verified")

    return GoogleClaims(
        sub=claims["sub"],
        email=claims["email"],
        email_verified=bool(claims.get("email_verified")),
        name=claims.get("name"),
        picture=claims.get("picture"),
    )
