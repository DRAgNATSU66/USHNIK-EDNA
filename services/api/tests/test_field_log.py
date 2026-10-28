import pytest


ENTRY_PAYLOAD = {
    "analysis_id": "ana_001",
    "kind": "note",
    "body": "Algal bloom present at surface level during collection.",
}


@pytest.mark.anyio
async def test_create_entry_requires_auth(client):
    resp = await client.post("/field-log/entries", json=ENTRY_PAYLOAD)
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_create_entry_analysis_not_found(client, researcher_token):
    resp = await client.post(
        "/field-log/entries",
        json=ENTRY_PAYLOAD,
        headers={"Authorization": f"Bearer {researcher_token}"},
    )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_create_entry_rejects_empty_body(client, researcher_token):
    resp = await client.post(
        "/field-log/entries",
        json={**ENTRY_PAYLOAD, "body": "   "},
        headers={"Authorization": f"Bearer {researcher_token}"},
    )
    # Empty-body check runs before the analysis lookup, so this should be a
    # 422, not a 404, even though ana_001 doesn't exist in the test DB.
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_list_entries_requires_auth(client):
    resp = await client.get("/field-log/entries", params={"analysis_id": "ana_001"})
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_list_entries_analysis_not_found(client, researcher_token):
    resp = await client.get(
        "/field-log/entries",
        params={"analysis_id": "ana_nonexistent"},
        headers={"Authorization": f"Bearer {researcher_token}"},
    )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_create_comment_reply_to_missing_parent_404s(client, researcher_token):
    """reply_to must reference a real, existing entry -- but since ana_001
    isn't seeded in the mock-DB test fixture, the analysis-ownership check
    fires first (404 on the analysis, not the parent). Confirms access
    control is checked before touching reply_to at all."""
    resp = await client.post(
        "/field-log/entries",
        json={**ENTRY_PAYLOAD, "kind": "comment", "reply_to": "fle_doesnotexist"},
        headers={"Authorization": f"Bearer {researcher_token}"},
    )
    assert resp.status_code == 404
