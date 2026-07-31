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
