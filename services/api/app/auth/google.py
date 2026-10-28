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


async def exchange_code_for_claims(code: str) -> GoogleClaims:
    """
    Exchange an OAuth 2.0 authorization code — from the client-side
    useGoogleLogin({ flow: 'auth-code' }) popup, used by our own
    custom-styled Google button instead of Google's rendered widget — for
    an ID token, then verify it exactly as verify_google_id_token does.

    redirect_uri is the literal string "postmessage": Google's documented
    convention for the JS popup auth-code flow, where the code isn't tied
    to a real redirect URL (see
    https://developers.google.com/identity/oauth2/web/guides/use-code-model).

    Raises ValueError if the exchange or the resulting token's verification
    fails, or if GOOGLE_CLIENT_SECRET is not configured.
    """
    settings = get_settings()
    if not settings.google_client_id or not settings.google_client_secret:
        raise ValueError("GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET is not configured")

    import requests

    try:
        resp = requests.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": "postmessage",
                "grant_type": "authorization_code",
            },
            timeout=10,
        )
        resp.raise_for_status()
        token_data = resp.json()
    except Exception as exc:
        raise ValueError(f"Google code exchange failed: {exc}") from exc

    id_token_str = token_data.get("id_token")
    if not id_token_str:
        raise ValueError("Google code exchange did not return an id_token")

    return await verify_google_id_token(id_token_str)
