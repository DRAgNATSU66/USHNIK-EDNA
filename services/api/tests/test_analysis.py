import pytest
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.mark.anyio
async def test_create_job_unauthenticated(client):
    resp = await client.post("/analysis/jobs", json={"upload_id": "upl_abc"})
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_create_job_upload_not_found(client, researcher_token):
    resp = await client.post(
        "/analysis/jobs",
        json={"upload_id": "upl_nonexistent"},
        headers={"Authorization": f"Bearer {researcher_token}"},
    )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_create_job_success(client, researcher_token):
    with patch("app.analysis.router.get_db") as mock_get_db:
        mock_db = MagicMock()
        mock_db.__getitem__ = MagicMock(side_effect=lambda key: _make_collection(key))
        mock_get_db.return_value = mock_db

        resp = await client.post(
            "/analysis/jobs",
            json={"upload_id": "upl_abc123", "mode": "online_full"},
            headers={"Authorization": f"Bearer {researcher_token}"},
        )
    assert resp.status_code == 202
    data = resp.json()
    assert data["job_id"].startswith("job_")
    assert data["state"] == "queued"


@pytest.mark.anyio
async def test_get_job_not_found(client, researcher_token):
    resp = await client.get(
        "/analysis/jobs/job_nonexistent",
        headers={"Authorization": f"Bearer {researcher_token}"},
    )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_get_analysis_not_found(client, researcher_token):
    resp = await client.get(
        "/analysis/ana_nonexistent",
        headers={"Authorization": f"Bearer {researcher_token}"},
    )
    assert resp.status_code == 404


def _make_collection(key):
    coll = MagicMock()
    if key == "uploads":
        coll.find_one = AsyncMock(return_value={
            "upload_id": "upl_abc123",
            "user_id": "usr_test_001",
            "original_filename": "sample.fasta",
            "file_size_bytes": 100,
            "status": "stored",
            "created_at": "2026-01-01T00:00:00",
        })
    else:
        coll.find_one = AsyncMock(return_value=None)
    coll.insert_one = AsyncMock(return_value=MagicMock(inserted_id="mock"))
    return coll
