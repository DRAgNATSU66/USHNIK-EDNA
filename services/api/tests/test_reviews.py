import pytest


REVIEW_PAYLOAD = {
    "analysis_id": "ana_001",
    "sequence_id": "seq_001",
    "correction_type": "species_correction",
    "proposed_taxon": "Gadus morhua",
    "evidence_notes": "Strong match to reference COI barcode",
}


@pytest.mark.anyio
async def test_submit_review_unauthenticated(client):
    resp = await client.post("/reviews", json=REVIEW_PAYLOAD)
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_submit_review_authenticated(client, researcher_token):
    resp = await client.post(
        "/reviews",
        json=REVIEW_PAYLOAD,
        headers={"Authorization": f"Bearer {researcher_token}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["review_id"].startswith("rev_")
    assert data["state"] == "submitted"


@pytest.mark.anyio
async def test_review_queue_requires_curator(client, researcher_token):
    resp = await client.get(
        "/reviews/queue",
        headers={"Authorization": f"Bearer {researcher_token}"},
    )
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_review_queue_accessible_by_curator(client, curator_token):
    resp = await client.get(
        "/reviews/queue",
        headers={"Authorization": f"Bearer {curator_token}"},
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.anyio
async def test_review_decision_requires_curator(client, researcher_token):
    resp = await client.post(
        "/reviews/rev_001/decision",
        json={"decision": "accept"},
        headers={"Authorization": f"Bearer {researcher_token}"},
    )
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_review_decision_not_found(client, admin_token):
    resp = await client.post(
        "/reviews/rev_nonexistent/decision",
        json={"decision": "accept"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_reviews_by_sequence_requires_auth(client):
    resp = await client.get("/reviews/by-sequence", params={"analysis_id": "ana_001", "sequence_id": "seq_001"})
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_reviews_by_sequence_not_found(client, researcher_token):
    resp = await client.get(
        "/reviews/by-sequence",
        params={"analysis_id": "ana_nonexistent", "sequence_id": "seq_001"},
        headers={"Authorization": f"Bearer {researcher_token}"},
    )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_models_status(client):
    resp = await client.get("/models/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "routes" in data


@pytest.mark.anyio
async def test_models_registry(client):
    resp = await client.get("/models/registry")
    assert resp.status_code == 200
    data = resp.json()
    assert "models" in data
    assert isinstance(data["models"], list)
