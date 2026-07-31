"""
Phase 1 auth smoke tests — updated to mock real Google/Supabase calls.
Full auth coverage lives in test_auth_phase3.py.
"""
import pytest
from unittest.mock import AsyncMock, patch
from app.auth.google import GoogleClaims


@pytest.mark.anyio
async def test_google_exchange_returns_token(client):
    fake_claims = GoogleClaims(
        sub="g-sub-smoke", email="smoke@example.com",
        email_verified=True, name="Smoke User", picture=None,
    )
    with patch("app.auth.router.verify_google_id_token", AsyncMock(return_value=fake_claims)), \
         patch("app.auth.router.SupabaseClient.get_user_by_google_sub", AsyncMock(return_value=None)), \
         patch("app.auth.router.SupabaseClient.upsert_user_by_google_sub", AsyncMock(return_value={"id": "00000000-0000-0000-0000-000000000001"})), \
         patch("app.auth.router.SupabaseClient.update_last_login", AsyncMock()):
        resp = await client.post("/auth/google/exchange", json={"id_token": "fake-google-token"})
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert "user" in data


@pytest.mark.anyio
async def test_get_me_unauthenticated(client):
    resp = await client.get("/auth/me")
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_get_me_authenticated(client, researcher_token):
    resp = await client.get("/auth/me", headers={"Authorization": f"Bearer {researcher_token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["user_id"] == "usr_test_001"
    assert data["role"] == "researcher"


@pytest.mark.anyio
async def test_admin_key_redeem_invalid_format(client, researcher_token):
    resp = await client.post(
        "/auth/admin-key/redeem",
        json={"key": "short"},
        headers={"Authorization": f"Bearer {researcher_token}"},
    )
    assert resp.status_code == 400


@pytest.mark.anyio
async def test_admin_key_redeem_valid_key_not_in_db(client, researcher_token):
    with patch("app.auth.router.SupabaseClient.get_invite_key", AsyncMock(return_value=None)):
        resp = await client.post(
            "/auth/admin-key/redeem",
            json={"key": "ABCD1234"},
            headers={"Authorization": f"Bearer {researcher_token}"},
        )
    assert resp.status_code == 400
    assert "invalid" in resp.json()["detail"].lower()
