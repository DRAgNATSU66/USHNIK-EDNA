"""
Tests for Supabase Auth access-token verification.
All external I/O (Supabase) is mocked.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.anyio
async def test_verify_supabase_access_token_returns_claims():
    from app.auth.supabase_auth import verify_supabase_access_token

    fake_user = MagicMock(id="00000000-0000-0000-0000-000000000099", email="bob@example.com")
    with patch("app.auth.supabase_auth.SupabaseClient.get_auth_user", AsyncMock(return_value=fake_user)):
        claims = await verify_supabase_access_token("valid-token")

    assert claims.user_id == "00000000-0000-0000-0000-000000000099"
    assert claims.email == "bob@example.com"


@pytest.mark.anyio
async def test_verify_supabase_access_token_invalid_raises():
    from app.auth.supabase_auth import verify_supabase_access_token

    with patch("app.auth.supabase_auth.SupabaseClient.get_auth_user", AsyncMock(return_value=None)):
        with pytest.raises(ValueError, match="verification failed"):
            await verify_supabase_access_token("bad-token")


@pytest.mark.anyio
async def test_verify_supabase_access_token_not_configured_raises():
    from app.auth.supabase_auth import verify_supabase_access_token

    with patch("app.auth.supabase_auth.SupabaseClient.get_auth_user",
               AsyncMock(side_effect=RuntimeError("Supabase not configured"))):
        with pytest.raises(ValueError, match="not configured"):
            await verify_supabase_access_token("any-token")


# ---------------------------------------------------------------------------
# /auth/supabase/exchange endpoint tests
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_supabase_exchange_with_valid_token(client):
    from app.auth.supabase_auth import SupabaseAuthClaims

    fake_claims = SupabaseAuthClaims(user_id="00000000-0000-0000-0000-000000000010", email="alice@example.com")
    with patch("app.auth.router.verify_supabase_access_token", AsyncMock(return_value=fake_claims)), \
         patch("app.auth.router.SupabaseClient.get_user_by_id",
               AsyncMock(return_value={"id": fake_claims.user_id, "role": "researcher", "display_name": "Alice"})), \
         patch("app.auth.router.SupabaseClient.update_last_login", AsyncMock()):
        resp = await client.post("/auth/supabase/exchange", json={"access_token": "valid-token"})

    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["user"]["email"] == "alice@example.com"
    assert data["user"]["role"] == "researcher"
    assert data["user"]["display_name"] == "Alice"


@pytest.mark.anyio
async def test_supabase_exchange_retries_once_if_profile_missing(client):
    from app.auth.supabase_auth import SupabaseAuthClaims

    fake_claims = SupabaseAuthClaims(user_id="00000000-0000-0000-0000-000000000011", email="new@example.com")
    profile_lookup = AsyncMock(side_effect=[None, {"id": fake_claims.user_id, "role": "researcher", "display_name": None}])
    with patch("app.auth.router.verify_supabase_access_token", AsyncMock(return_value=fake_claims)), \
         patch("app.auth.router.SupabaseClient.get_user_by_id", profile_lookup), \
         patch("app.auth.router.SupabaseClient.update_last_login", AsyncMock()), \
         patch("app.auth.router.asyncio.sleep", AsyncMock()):
        resp = await client.post("/auth/supabase/exchange", json={"access_token": "valid-token"})

    assert resp.status_code == 200
    assert profile_lookup.await_count == 2
    assert resp.json()["user"]["role"] == "researcher"


@pytest.mark.anyio
async def test_supabase_exchange_invalid_token_returns_401(client):
    with patch("app.auth.router.verify_supabase_access_token",
               AsyncMock(side_effect=ValueError("Supabase access token verification failed"))):
        resp = await client.post("/auth/supabase/exchange", json={"access_token": "bad-token"})

    assert resp.status_code == 401


@pytest.mark.anyio
async def test_supabase_exchange_supabase_unavailable_still_works(client):
    """If the profile lookup is down, exchange still succeeds with default researcher role."""
    from app.auth.supabase_auth import SupabaseAuthClaims

    fake_claims = SupabaseAuthClaims(user_id="00000000-0000-0000-0000-000000000012", email="offline@example.com")
    with patch("app.auth.router.verify_supabase_access_token", AsyncMock(return_value=fake_claims)), \
         patch("app.auth.router.SupabaseClient.get_user_by_id",
               AsyncMock(side_effect=RuntimeError("Supabase not configured"))):
        resp = await client.post("/auth/supabase/exchange", json={"access_token": "valid-token"})

    assert resp.status_code == 200
    assert resp.json()["user"]["role"] == "researcher"
