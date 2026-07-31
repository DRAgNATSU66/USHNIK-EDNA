"""
Supabase Auth access-token verification.

Delegates to Supabase's own auth endpoint via the server-side client
(already configured with the service-role key) rather than verifying the
JWT signature locally — this avoids managing a second signing secret and
stays correct if Supabase rotates its signing key.
"""
from __future__ import annotations
from dataclasses import dataclass

from ..db.supabase_client import SupabaseClient


@dataclass
class SupabaseAuthClaims:
    user_id: str   # auth.users.id (uuid) — same value as user_profiles.id
    email: str


async def verify_supabase_access_token(access_token: str) -> SupabaseAuthClaims:
    """
    Verify a Supabase Auth access token and return the extracted claims.

    Raises ValueError if the token is invalid, expired, or Supabase is not
    configured.
    """
    try:
        user = await SupabaseClient.get_auth_user(access_token)
    except RuntimeError as exc:
        raise ValueError(str(exc)) from exc

    if user is None:
        raise ValueError("Supabase access token verification failed")

    return SupabaseAuthClaims(user_id=user.id, email=user.email)
