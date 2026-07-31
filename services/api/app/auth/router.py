import asyncio
import hashlib
from datetime import datetime, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from .deps import get_current_user
from .google import GoogleClaims, exchange_code_for_claims, verify_google_id_token
from .supabase_auth import verify_supabase_access_token
from ..db import get_db
from .jwt import create_access_token
from .session import create_expedition_session, verify_expedition_session, OFFLINE_SESSION_DAYS
from ..db.supabase_client import SupabaseClient, SupabaseUnavailableError
from ..models.user import UserProfile, UserRole

router = APIRouter(prefix="/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------

class GoogleExchangeRequest(BaseModel):
    id_token: str


class GoogleCodeExchangeRequest(BaseModel):
    code: str


class SupabaseExchangeRequest(BaseModel):
    access_token: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserProfile


class AdminKeyRedeemRequest(BaseModel):
    key: str  # raw 8-char alphanumeric — hashed server-side, never logged


class AdminKeyRedeemResponse(BaseModel):
    success: bool
    role_granted: Optional[UserRole] = None
    access_token: Optional[str] = None  # new token with updated role


class ExpeditionSessionRequest(BaseModel):
    expedition_id: str
    device_fingerprint: Optional[str] = None


class ExpeditionSessionResponse(BaseModel):
    expedition_session_token: str
    expires_in_days: int = OFFLINE_SESSION_DAYS
    expedition_id: str
    disclaimer: str = (
        "This token authorises offline Abyss Mode only. "
        "All results are preliminary and require cloud confirmation."
    )


class VerifyExpeditionRequest(BaseModel):
    expedition_session_token: str


# ---------------------------------------------------------------------------
# Shared: Google claims -> Synth Veda JWT
# ---------------------------------------------------------------------------

async def _token_response_for_google_claims(claims: GoogleClaims) -> TokenResponse:
    """
    Look up or create the user_profiles row for a verified set of Google
    claims, mint a Synth Veda JWT, and return the TokenResponse. Shared by
    both /auth/google/exchange (id_token, from the old widget flow) and
    /auth/google/code-exchange (authorization code, from our own custom
    liquid-glass button) — the account-linking rules must stay identical
    regardless of which flow produced the claims.

    user_profiles.id is a Postgres-generated uuid — NOT Google's sub (which
    is a numeric string, not a uuid, and this app never creates Supabase
    Auth users for the Google path). The generated id is what every other
    table's user_profiles(id) foreign key expects.
    """
    # Supabase user lookup / upsert (safe to call even when Supabase is not
    # configured — SupabaseClient raises RuntimeError which we catch below)
    role = UserRole.researcher  # default for new users
    user_id = claims.sub  # fallback subject when Supabase isn't configured
    try:
        existing = await SupabaseClient.get_user_by_google_sub(claims.sub)
        if existing:
            role = UserRole(existing.get("role", UserRole.researcher))
            user_id = existing["id"]
        else:
            # No Google-linked row yet — check for a password account with
            # this email before creating a second, disconnected identity.
            linked = await SupabaseClient.link_google_sub_to_existing_email(
                email=claims.email, google_sub=claims.sub
            )
            if linked:
                role = UserRole(linked.get("role", UserRole.researcher))
                user_id = linked["id"]
            else:
                created = await SupabaseClient.upsert_user_by_google_sub(
                    google_sub=claims.sub,
                    email=claims.email,
                    display_name=claims.name,
                    role=role,
                )
                user_id = created["id"]
        await SupabaseClient.update_last_login(user_id)
    except RuntimeError:
        # Supabase not configured (local dev without .env) — continue with defaults
        pass

    user = UserProfile(
        user_id=user_id,
        email=claims.email,
        display_name=claims.name,
        role=role,
        google_sub=claims.sub,
    )
    token = create_access_token(
        subject=user.user_id,
        extra={"email": user.email, "role": user.role, "name": user.display_name},
    )
    return TokenResponse(access_token=token, user=user)


# ---------------------------------------------------------------------------
# POST /auth/google/exchange
# ---------------------------------------------------------------------------

@router.post("/google/exchange", response_model=TokenResponse)
async def google_exchange(body: GoogleExchangeRequest):
    """
    Exchange a Google ID token (from client-side OAuth) for a Synth Veda JWT.
    Verifies the ID token's signature + audience (google-auth library), then
    delegates to _token_response_for_google_claims for the account lookup.
    """
    try:
        claims = await verify_google_id_token(body.id_token)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))

    return await _token_response_for_google_claims(claims)


# ---------------------------------------------------------------------------
# POST /auth/google/code-exchange
# ---------------------------------------------------------------------------

@router.post("/google/code-exchange", response_model=TokenResponse)
async def google_code_exchange(body: GoogleCodeExchangeRequest):
    """
    Exchange a Google OAuth 2.0 authorization code (from our own
    custom-styled Google button, using useGoogleLogin's popup auth-code
    flow) for a Synth Veda JWT.

    Unlike /auth/google/exchange, the client here never sees a Google
    credential directly — it only gets a one-time code, which this endpoint
    exchanges server-side (using GOOGLE_CLIENT_SECRET) for an ID token that
    is then verified exactly as the widget-flow token is. Same account
    lookup rules apply via _token_response_for_google_claims.
    """
    try:
        claims = await exchange_code_for_claims(body.code)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))

    return await _token_response_for_google_claims(claims)


# ---------------------------------------------------------------------------
# POST /auth/supabase/exchange
# ---------------------------------------------------------------------------

@router.post("/supabase/exchange", response_model=TokenResponse)
async def supabase_exchange(body: SupabaseExchangeRequest):
    """
    Exchange a Supabase Auth session access token (from client-side
    supabase-js signUp/signInWithPassword/updateUser) for a Synth Veda JWT.

    The `handle_new_user` Postgres trigger auto-creates the user_profiles
    row when Supabase Auth creates the underlying auth.users row, so by the
    time this runs the profile usually already exists. If it hasn't landed
    yet (trigger race on the very first request right after signup), retry
    once after a short delay before falling back to default researcher
    values — mirroring how /auth/google/exchange tolerates Supabase being
    unavailable.
    """
    try:
        claims = await verify_supabase_access_token(body.access_token)
    except SupabaseUnavailableError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Auth service temporarily unavailable. Please try again.",
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))

    role = UserRole.researcher
    display_name = None
    try:
        profile = await SupabaseClient.get_user_by_id(claims.user_id)
        if profile is None:
            await asyncio.sleep(0.5)
            profile = await SupabaseClient.get_user_by_id(claims.user_id)
        if profile:
            role = UserRole(profile.get("role", UserRole.researcher))
            display_name = profile.get("display_name")
        await SupabaseClient.update_last_login(claims.user_id)
    except RuntimeError:
        pass

    user = UserProfile(
        user_id=claims.user_id,
        email=claims.email,
        display_name=display_name,
        role=role,
    )
    token = create_access_token(
        subject=user.user_id,
        extra={"email": user.email, "role": user.role, "name": user.display_name},
    )
    return TokenResponse(access_token=token, user=user)


# ---------------------------------------------------------------------------
# POST /auth/admin-key/redeem
# ---------------------------------------------------------------------------

@router.post("/admin-key/redeem", response_model=AdminKeyRedeemResponse)
async def admin_key_redeem(
    body: AdminKeyRedeemRequest,
    current_user: Annotated[UserProfile, Depends(get_current_user)],
):
    """
    Redeem a company-issued invite key to elevate the current user's role.

    Rules enforced:
      - Key must be exactly 8 alphanumeric characters.
      - Key is hashed (SHA-256) before lookup — plaintext never stored or logged.
      - Atomic consume via Supabase RPC prevents race conditions.
      - Rate limiting must be enforced at the infra/proxy layer.
      - Every redemption is audit-logged.
    """
    if len(body.key) != 8 or not body.key.isalnum():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invite key must be exactly 8 alphanumeric characters",
        )

    key_hash = hashlib.sha256(body.key.encode()).hexdigest()

    try:
        key_doc = await SupabaseClient.get_invite_key(key_hash)
    except RuntimeError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Auth service unavailable — cannot validate key",
        )

    if not key_doc:
        # Return the same 400 for expired, exhausted, and invalid keys
        # to avoid leaking information about key existence
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invite key is invalid, expired, or already used",
        )

    # Check expiry explicitly (belt + Supabase RLS)
    expires_at = key_doc.get("expires_at")
    if expires_at:
        from datetime import datetime, timezone
        exp = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        if exp < datetime.now(timezone.utc):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invite key is invalid, expired, or already used",
            )

    consumed = await SupabaseClient.consume_invite_key(key_doc["id"], current_user.user_id)
    if not consumed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invite key is invalid, expired, or already used",
        )

    role_to_grant = UserRole(key_doc["role_to_grant"])

    await SupabaseClient.assign_role(
        user_id=current_user.user_id,
        role=role_to_grant,
        granted_by=current_user.user_id,  # self-service via key
        invite_key_id=key_doc["id"],
    )

    await SupabaseClient.log_action(
        action="admin_key_redeemed",
        target_type="invite_key",
        target_id=key_doc["id"],
        actor_id=current_user.user_id,
        actor_role=current_user.role,
        payload={"role_granted": role_to_grant},
    )

    # Re-mint token with updated role
    new_token = create_access_token(
        subject=current_user.user_id,
        extra={
            "email": current_user.email,
            "role": role_to_grant,
            "name": current_user.display_name,
        },
    )
    return AdminKeyRedeemResponse(
        success=True, role_granted=role_to_grant, access_token=new_token
    )


# ---------------------------------------------------------------------------
# GET /auth/me
# ---------------------------------------------------------------------------

@router.get("/me", response_model=UserProfile)
async def get_me(current_user: Annotated[UserProfile, Depends(get_current_user)]):
    """Return the authenticated user's profile from the JWT claims."""
    return current_user


# ---------------------------------------------------------------------------
# POST /auth/expedition/session  (Abyss Mode prep)
# ---------------------------------------------------------------------------

@router.post("/expedition/session", response_model=ExpeditionSessionResponse)
async def create_offline_session(
    body: ExpeditionSessionRequest,
    current_user: Annotated[UserProfile, Depends(get_current_user)],
):
    """
    Generate a long-lived offline expedition session token for Abyss Mode.

    The token is a signed JWT valid for 45 days. It contains the expedition_id
    and the user's role so the offline app can validate it without a network
    connection. Only expedition_operator, admin, or company_owner may issue
    these tokens.

    Before departure the app should:
      1. Call this endpoint to get the session token.
      2. Download the offline model pack and reference pack (Phase 10).
      3. Store everything locally on the expedition device.
    """
    allowed = {UserRole.expedition_operator, UserRole.admin, UserRole.company_owner}
    if current_user.role not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only expedition operators and admins may create offline sessions",
        )

    # Verify the expedition exists
    try:
        db = get_db()
        expedition = await db["abyss_expeditions"].find_one(
            {"expedition_id": body.expedition_id}
        )
        if not expedition:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Expedition not found"
            )
    except RuntimeError:
        pass  # MongoDB not connected in dev — skip the check

    offline_token = create_expedition_session(
        expedition_id=body.expedition_id,
        user_id=current_user.user_id,
        role=current_user.role,
        device_fingerprint=body.device_fingerprint,
    )

    try:
        await SupabaseClient.log_action(
            action="expedition_session_created",
            target_type="expedition",
            target_id=body.expedition_id,
            actor_id=current_user.user_id,
            actor_role=current_user.role,
            payload={"device_fingerprint": body.device_fingerprint},
        )
    except RuntimeError:
        pass

    return ExpeditionSessionResponse(
        expedition_session_token=offline_token,
        expedition_id=body.expedition_id,
    )


# ---------------------------------------------------------------------------
# POST /auth/expedition/verify  (offline verification endpoint for testing)
# ---------------------------------------------------------------------------

@router.post("/expedition/verify")
async def verify_offline_session(body: VerifyExpeditionRequest):
    """
    Verify an expedition session token. Used during pre-departure testing
    and after reconnecting to confirm the token is still valid.
    """
    import jwt as pyjwt
    try:
        payload = verify_expedition_session(body.expedition_session_token)
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Expedition session expired")
    except pyjwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid session: {exc}")

    return {
        "valid": True,
        "expedition_id": payload["expedition_id"],
        "user_id": payload["sub"],
        "role": payload["role"],
        "expires_at": datetime.fromtimestamp(payload["exp"], tz=timezone.utc).isoformat(),
    }
