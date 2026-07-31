import pytest
from io import BytesIO


SAMPLE_FASTA = b">seq_001\nATCGATCGATCGATCGATCG\n>seq_002\nGCATGCATGCATGCAT\n"


@pytest.mark.anyio
async def test_upload_unauthenticated(client):
    resp = await client.post("/uploads", files={"file": ("sample.fasta", BytesIO(SAMPLE_FASTA))})
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_upload_fasta(client, researcher_token):
    resp = await client.post(
        "/uploads",
        files={"file": ("sample.fasta", BytesIO(SAMPLE_FASTA), "text/plain")},
        headers={"Authorization": f"Bearer {researcher_token}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["upload_id"].startswith("upl_")
    assert data["original_filename"] == "sample.fasta"
    assert data["status"] == "stored"


@pytest.mark.anyio
async def test_upload_rejects_unknown_extension(client, researcher_token):
    resp = await client.post(
        "/uploads",
        files={"file": ("data.csv", BytesIO(b"col1,col2"), "text/csv")},
        headers={"Authorization": f"Bearer {researcher_token}"},
    )
    assert resp.status_code == 400


@pytest.mark.anyio
async def test_get_upload_not_found(client, researcher_token):
    resp = await client.get(
        "/uploads/upl_nonexistent",
        headers={"Authorization": f"Bearer {researcher_token}"},
    )
    assert resp.status_code == 404
