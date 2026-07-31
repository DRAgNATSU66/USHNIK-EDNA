"""
Tests for SupabaseClient method contracts.
All Supabase I/O is mocked — no real network calls.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _mock_supabase_client():
    """Build a mock that mirrors the supabase-py AsyncClient chain API."""
    table_mock = MagicMock()

    def table_chain(*args, **kwargs):
        chain = MagicMock()
        chain.upsert = MagicMock(return_value=chain)
        chain.insert = MagicMock(return_value=chain)
        chain.update = MagicMock(return_value=chain)
        chain.select = MagicMock(return_value=chain)
        chain.eq   = MagicMock(return_value=chain)
        chain.single = MagicMock(return_value=chain)
        chain.execute = AsyncMock(return_value=MagicMock(data=[{"id": "mock-uuid", "role": "researcher"}]))
        return chain

    client = MagicMock()
    client.table = MagicMock(side_effect=table_chain)
    client.rpc = MagicMock(return_value=MagicMock(execute=AsyncMock(return_value=MagicMock(data=True))))
    return client


@pytest.mark.anyio
async def test_upsert_user_calls_table():
    from app.db.supabase_client import SupabaseClient
    import app.db.supabase_client as sc_module

    mock_client = _mock_supabase_client()
    with patch.object(sc_module, "_client", mock_client):
        result = await SupabaseClient.upsert_user_by_google_sub(
            "g-sub-001", "a@b.com", "Alice", "researcher"
        )
    assert mock_client.table.called
    mock_client.table.assert_called_with("user_profiles")


@pytest.mark.anyio
async def test_get_user_returns_none_on_empty():
    from app.db.supabase_client import SupabaseClient
    import app.db.supabase_client as sc_module

    chain = MagicMock()
    chain.select = MagicMock(return_value=chain)
    chain.eq = MagicMock(return_value=chain)
    chain.maybe_single = MagicMock(return_value=chain)
    chain.execute = AsyncMock(return_value=MagicMock(data=None))

    mock_client = MagicMock()
    mock_client.table = MagicMock(return_value=chain)

    with patch.object(sc_module, "_client", mock_client):
        result = await SupabaseClient.get_user_by_google_sub("g-sub-nonexistent")
    assert result is None


@pytest.mark.anyio
async def test_get_user_by_id_returns_profile():
    from app.db.supabase_client import SupabaseClient
    import app.db.supabase_client as sc_module

    chain = MagicMock()
    chain.select = MagicMock(return_value=chain)
    chain.eq = MagicMock(return_value=chain)
    chain.maybe_single = MagicMock(return_value=chain)
    chain.execute = AsyncMock(return_value=MagicMock(data={"id": "u1", "role": "researcher"}))

    mock_client = MagicMock()
    mock_client.table = MagicMock(return_value=chain)

    with patch.object(sc_module, "_client", mock_client):
        result = await SupabaseClient.get_user_by_id("u1")
    mock_client.table.assert_called_with("user_profiles")
    assert result == {"id": "u1", "role": "researcher"}


@pytest.mark.anyio
async def test_get_user_by_id_returns_none_on_empty():
    from app.db.supabase_client import SupabaseClient
    import app.db.supabase_client as sc_module

    chain = MagicMock()
    chain.select = MagicMock(return_value=chain)
    chain.eq = MagicMock(return_value=chain)
    chain.maybe_single = MagicMock(return_value=chain)
    chain.execute = AsyncMock(return_value=MagicMock(data=None))

    mock_client = MagicMock()
    mock_client.table = MagicMock(return_value=chain)

    with patch.object(sc_module, "_client", mock_client):
        result = await SupabaseClient.get_user_by_id("missing")
    assert result is None


@pytest.mark.anyio
async def test_get_auth_user_returns_user_on_success():
    from app.db.supabase_client import SupabaseClient
    import app.db.supabase_client as sc_module

    fake_user = MagicMock(id="u1", email="a@b.com")
    mock_client = MagicMock()
    mock_client.auth = MagicMock()
    mock_client.auth.get_user = AsyncMock(return_value=MagicMock(user=fake_user))

    with patch.object(sc_module, "_client", mock_client):
        result = await SupabaseClient.get_auth_user("valid-token")
    assert result is fake_user


@pytest.mark.anyio
async def test_get_auth_user_returns_none_on_invalid_token():
    from app.db.supabase_client import SupabaseClient
    import app.db.supabase_client as sc_module

    mock_client = MagicMock()
    mock_client.auth = MagicMock()
    mock_client.auth.get_user = AsyncMock(side_effect=Exception("invalid JWT"))

    with patch.object(sc_module, "_client", mock_client):
        result = await SupabaseClient.get_auth_user("bad-token")
    assert result is None


@pytest.mark.anyio
async def test_get_auth_user_raises_supabase_unavailable_on_transport_error():
    """
    A transient Supabase outage (network timeout, DNS error, 5xx) must be
    distinguishable from a rejected token — gotrue surfaces these as
    AuthRetryableError. get_auth_user should re-raise as
    SupabaseUnavailableError instead of collapsing it into `None`.
    """
    from gotrue.errors import AuthRetryableError
    from app.db.supabase_client import SupabaseClient, SupabaseUnavailableError
    import app.db.supabase_client as sc_module

    mock_client = MagicMock()
    mock_client.auth = MagicMock()
    mock_client.auth.get_user = AsyncMock(
        side_effect=AuthRetryableError("Connection timed out", 0)
    )

    with patch.object(sc_module, "_client", mock_client):
        with pytest.raises(SupabaseUnavailableError):
            await SupabaseClient.get_auth_user("some-token")


@pytest.mark.anyio
async def test_get_supabase_raises_when_not_configured():
    from app.db.supabase_client import SupabaseClient
    import app.db.supabase_client as sc_module

    with patch.object(sc_module, "_client", None):
        with pytest.raises(RuntimeError, match="Supabase not configured"):
            SupabaseClient._get()


@pytest.mark.anyio
async def test_create_invite_key_uses_correct_table():
    from app.db.supabase_client import SupabaseClient
    import app.db.supabase_client as sc_module

    mock_client = _mock_supabase_client()
    with patch.object(sc_module, "_client", mock_client):
        await SupabaseClient.create_invite_key(
            key_hash="abc123hash",
            role_to_grant="expert_contributor",
            created_by="usr_admin_001",
        )
    mock_client.table.assert_called_with("admin_invite_keys")


@pytest.mark.anyio
async def test_log_action_uses_audit_logs_table():
    from app.db.supabase_client import SupabaseClient
    import app.db.supabase_client as sc_module

    mock_client = _mock_supabase_client()
    with patch.object(sc_module, "_client", mock_client):
        await SupabaseClient.log_action(
            action="review_decision",
            target_type="review",
            target_id="rev_001",
            actor_id="usr_admin_001",
            actor_role="admin",
            payload={"decision": "accept"},
        )
    mock_client.table.assert_called_with("audit_logs")
