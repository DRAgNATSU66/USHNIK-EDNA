"""
Phase 3 auth tests.
Covers: Google exchange, admin key redeem, expedition session create/verify.
All external I/O (google-auth, Supabase) is mocked.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.auth.google import GoogleClaims
from app.auth.session import create_expedition_session, verify_expedition_session
from app.auth.jwt import create_access_token
from app.models.user import UserRole


# ---------------------------------------------------------------------------
# google.py unit tests
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_verify_google_id_token_missing_client_id():
    from app.auth.google import verify_google_id_token
    from app.config import get_settings
    import app.auth.google as g_mod

    with patch("app.auth.google.get_settings") as mock_cfg:
        mock_cfg.return_value = MagicMock(google_client_id="")
        with pytest.raises(ValueError, match="GOOGLE_CLIENT_ID is not configured"):
            await verify_google_id_token("fake-token")


@pytest.mark.anyio
async def test_verify_google_id_token_returns_claims():
    from app.auth.google import verify_google_id_token

    fake_claims = {
        "sub": "google-sub-001",
        "email": "alice@example.com",
        "email_verified": True,
        "name": "Alice",
        "picture": "https://example.com/pic.jpg",
    }

    with patch("app.auth.google.get_settings") as mock_cfg, \
         patch("google.oauth2.id_token.verify_oauth2_token", return_value=fake_claims):
        mock_cfg.return_value = MagicMock(google_client_id="mock-client-id")
        claims = await verify_google_id_token("valid-google-token")

    assert claims.sub == "google-sub-001"
    assert claims.email == "alice@example.com"
    assert claims.email_verified is True
    assert claims.name == "Alice"


@pytest.mark.anyio
async def test_verify_google_id_token_unverified_email_raises():
    from app.auth.google import verify_google_id_token

    fake_claims = {
        "sub": "google-sub-002",
        "email": "unverified@example.com",
        "email_verified": False,
        "name": "Bob",
    }

    with patch("app.auth.google.get_settings") as mock_cfg, \
         patch("google.oauth2.id_token.verify_oauth2_token", return_value=fake_claims):
        mock_cfg.return_value = MagicMock(google_client_id="mock-client-id")
        with pytest.raises(ValueError, match="not verified"):
            await verify_google_id_token("unverified-token")


@pytest.mark.anyio
async def test_verify_google_id_token_bad_signature_raises():
    from app.auth.google import verify_google_id_token

    with patch("app.auth.google.get_settings") as mock_cfg, \
         patch("google.oauth2.id_token.verify_oauth2_token", side_effect=ValueError("Token signature invalid")):
        mock_cfg.return_value = MagicMock(google_client_id="mock-client-id")
        with pytest.raises(ValueError, match="verification failed"):
            await verify_google_id_token("tampered-token")


# ---------------------------------------------------------------------------
# session.py unit tests
# ---------------------------------------------------------------------------

def test_create_expedition_session_is_valid_jwt():
    token = create_expedition_session(
        expedition_id="exp_test_001",
        user_id="usr_test_001",
        role="expedition_operator",
    )
    assert isinstance(token, str)
    assert len(token.split(".")) == 3  # header.payload.signature


def test_expedition_session_round_trip():
    token = create_expedition_session(
        expedition_id="exp_rt_001",
        user_id="usr_rt_001",
        role="admin",
        device_fingerprint="device-abc",
    )
    payload = verify_expedition_session(token)
    assert payload["expedition_id"] == "exp_rt_001"
    assert payload["sub"] == "usr_rt_001"
    assert payload["role"] == "admin"
    assert payload["device"] == "device-abc"
    assert payload["mode"] == "abyss_offline"


def test_expedition_session_wrong_mode_rejected():
    import jwt
    from app.config import get_settings
    settings = get_settings()
    # Forge a token with mode != "abyss_offline"
    bad_token = jwt.encode(
        {"sub": "usr", "expedition_id": "exp", "mode": "api_access", "exp": 9999999999},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(jwt.InvalidTokenError):
        verify_expedition_session(bad_token)


def test_expedition_session_expired_raises():
    import jwt
    from datetime import datetime, timezone, timedelta
    from app.config import get_settings
    settings = get_settings()
    # Issue token that expired in the past
    expired_token = jwt.encode(
        {
            "sub": "usr",
            "expedition_id": "exp",
            "mode": "abyss_offline",
            "exp": datetime(2020, 1, 1, tzinfo=timezone.utc),
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(jwt.ExpiredSignatureError):
        verify_expedition_session(expired_token)


# ---------------------------------------------------------------------------
# /auth/google/exchange endpoint tests
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_google_exchange_with_valid_token(client):
    fake_claims = GoogleClaims(
        sub="g-sub-001", email="alice@example.com",
        email_verified=True, name="Alice", picture=None,
    )
    with patch("app.auth.router.verify_google_id_token", AsyncMock(return_value=fake_claims)), \
         patch("app.auth.router.SupabaseClient.get_user_by_google_sub", AsyncMock(return_value=None)), \
         patch("app.auth.router.SupabaseClient.upsert_user_by_google_sub", AsyncMock(return_value={"id": "00000000-0000-0000-0000-000000000001"})), \
         patch("app.auth.router.SupabaseClient.update_last_login", AsyncMock()):
        resp = await client.post("/auth/google/exchange", json={"id_token": "valid-google-token"})

    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["user"]["email"] == "alice@example.com"
    assert data["user"]["role"] == "researcher"


@pytest.mark.anyio
async def test_google_exchange_existing_user_keeps_role(client):
    fake_claims = GoogleClaims(
        sub="g-sub-002", email="curator@example.com",
        email_verified=True, name="Curator", picture=None,
    )
    with patch("app.auth.router.verify_google_id_token", AsyncMock(return_value=fake_claims)), \
         patch("app.auth.router.SupabaseClient.get_user_by_google_sub",
               AsyncMock(return_value={"id": "00000000-0000-0000-0000-000000000002", "role": "curator"})), \
         patch("app.auth.router.SupabaseClient.update_last_login", AsyncMock()):
        resp = await client.post("/auth/google/exchange", json={"id_token": "curator-token"})

    assert resp.status_code == 200
    assert resp.json()["user"]["role"] == "curator"


@pytest.mark.anyio
async def test_google_exchange_invalid_token_returns_401(client):
    with patch("app.auth.router.verify_google_id_token",
               AsyncMock(side_effect=ValueError("Token signature invalid"))):
        resp = await client.post("/auth/google/exchange", json={"id_token": "bad-token"})

    assert resp.status_code == 401


@pytest.mark.anyio
async def test_google_exchange_supabase_unavailable_still_works(client):
    """If Supabase is down, the exchange should succeed with default researcher role."""
    fake_claims = GoogleClaims(
        sub="g-sub-003", email="new@example.com",
        email_verified=True, name="New User", picture=None,
    )
    with patch("app.auth.router.verify_google_id_token", AsyncMock(return_value=fake_claims)), \
         patch("app.auth.router.SupabaseClient.get_user_by_google_sub",
               AsyncMock(side_effect=RuntimeError("Supabase not configured"))):
        resp = await client.post("/auth/google/exchange", json={"id_token": "valid-token"})

    assert resp.status_code == 200
    assert resp.json()["user"]["role"] == "researcher"


# ---------------------------------------------------------------------------
# /auth/admin-key/redeem endpoint tests
# ---------------------------------------------------------------------------

def _valid_key_doc(role: str = "expert_contributor"):
    from datetime import datetime, timezone, timedelta
    return {
        "id": "key-uuid-001",
        "key_hash": "ignored",
        "role_to_grant": role,
        "is_active": True,
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
    }


@pytest.mark.anyio
async def test_redeem_key_wrong_length(client, researcher_token):
    resp = await client.post(
        "/auth/admin-key/redeem",
        json={"key": "SHORT"},
        headers={"Authorization": f"Bearer {researcher_token}"},
    )
    assert resp.status_code == 400
    assert "8 alphanumeric" in resp.json()["detail"]


@pytest.mark.anyio
async def test_redeem_key_non_alphanumeric(client, researcher_token):
    resp = await client.post(
        "/auth/admin-key/redeem",
        json={"key": "ABCD-123"},  # hyphen not allowed
        headers={"Authorization": f"Bearer {researcher_token}"},
    )
    assert resp.status_code == 400


@pytest.mark.anyio
async def test_redeem_key_not_found_returns_400(client, researcher_token):
    with patch("app.auth.router.SupabaseClient.get_invite_key", AsyncMock(return_value=None)):
        resp = await client.post(
            "/auth/admin-key/redeem",
            json={"key": "NOTFOUND"},
            headers={"Authorization": f"Bearer {researcher_token}"},
        )
    assert resp.status_code == 400
    assert "invalid" in resp.json()["detail"].lower()


@pytest.mark.anyio
async def test_redeem_key_supabase_unavailable_returns_503(client, researcher_token):
    with patch("app.auth.router.SupabaseClient.get_invite_key",
               AsyncMock(side_effect=RuntimeError("Supabase not configured"))):
        resp = await client.post(
            "/auth/admin-key/redeem",
            json={"key": "ABCD1234"},
            headers={"Authorization": f"Bearer {researcher_token}"},
        )
    assert resp.status_code == 503


@pytest.mark.anyio
async def test_redeem_key_success(client, researcher_token):
    with patch("app.auth.router.SupabaseClient.get_invite_key",
               AsyncMock(return_value=_valid_key_doc("expert_contributor"))), \
         patch("app.auth.router.SupabaseClient.consume_invite_key",
               AsyncMock(return_value=True)), \
         patch("app.auth.router.SupabaseClient.assign_role", AsyncMock(return_value={})), \
         patch("app.auth.router.SupabaseClient.log_action", AsyncMock()):
        resp = await client.post(
            "/auth/admin-key/redeem",
            json={"key": "ABCD1234"},
            headers={"Authorization": f"Bearer {researcher_token}"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["role_granted"] == "expert_contributor"
    assert "access_token" in data


@pytest.mark.anyio
async def test_redeem_key_already_exhausted(client, researcher_token):
    with patch("app.auth.router.SupabaseClient.get_invite_key",
               AsyncMock(return_value=_valid_key_doc())), \
         patch("app.auth.router.SupabaseClient.consume_invite_key",
               AsyncMock(return_value=False)):
        resp = await client.post(
            "/auth/admin-key/redeem",
            json={"key": "ABCD1234"},
            headers={"Authorization": f"Bearer {researcher_token}"},
        )
    assert resp.status_code == 400


@pytest.mark.anyio
async def test_redeem_key_not_authenticated(client):
    resp = await client.post("/auth/admin-key/redeem", json={"key": "ABCD1234"})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# /auth/expedition/session endpoint tests
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_expedition_session_requires_operator_role(client, researcher_token):
    resp = await client.post(
        "/auth/expedition/session",
        json={"expedition_id": "exp_001"},
        headers={"Authorization": f"Bearer {researcher_token}"},
    )
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_expedition_session_created_for_operator(client):
    operator_token = create_access_token(
        "usr_op_001",
        {"email": "op@example.com", "role": UserRole.expedition_operator, "name": "Operator"},
    )
    mock_coll = MagicMock()
    mock_coll.find_one = AsyncMock(return_value={"expedition_id": "exp_001"})
    mock_db = MagicMock()
    mock_db.__getitem__ = MagicMock(return_value=mock_coll)

    with patch("app.auth.router.SupabaseClient.log_action", AsyncMock()), \
         patch("app.auth.router.get_db", return_value=mock_db):
        resp = await client.post(
            "/auth/expedition/session",
            json={"expedition_id": "exp_001", "device_fingerprint": "dev-xyz"},
            headers={"Authorization": f"Bearer {operator_token}"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert "expedition_session_token" in data
    assert data["expedition_id"] == "exp_001"
    assert data["expires_in_days"] == 45
    assert "preliminary" in data["disclaimer"]


@pytest.mark.anyio
async def test_expedition_session_verify_valid(client):
    token = create_expedition_session("exp_001", "usr_001", "admin")
    resp = await client.post(
        "/auth/expedition/verify",
        json={"expedition_session_token": token},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["valid"] is True
    assert data["expedition_id"] == "exp_001"


@pytest.mark.anyio
async def test_expedition_session_verify_expired(client):
    import jwt
    from app.config import get_settings
    settings = get_settings()
    from datetime import datetime, timezone
    expired = jwt.encode(
        {"sub": "u", "expedition_id": "e", "mode": "abyss_offline",
         "exp": datetime(2020, 1, 1, tzinfo=timezone.utc)},
        settings.jwt_secret, algorithm=settings.jwt_algorithm,
    )
    resp = await client.post(
        "/auth/expedition/verify",
        json={"expedition_session_token": expired},
    )
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_expedition_session_verify_tampered(client):
    resp = await client.post(
        "/auth/expedition/verify",
        json={"expedition_session_token": "totally.not.valid"},
    )
    assert resp.status_code == 401
