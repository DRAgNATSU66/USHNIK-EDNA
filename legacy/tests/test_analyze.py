import io
from fastapi.testclient import TestClient
from src.web_api import main as api_main

client = TestClient(api_main.app)


def small_fasta_bytes():
    # two tiny DNA sequences (FASTA)
    return b">seq1\nATGCGTACGTAGCTAGCTAG\n>seq2\nTTGACGATCGATCGATGCAA\n"


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, (dict, str))


def test_analyze_basic():
    files = {"file": ("sample.fasta", io.BytesIO(small_fasta_bytes()), "application/octet-stream")}
    r = client.post("/analyze", files=files)
    assert r.status_code == 200
    body = r.json()
    # acceptable outputs:
    if isinstance(body, dict) and "species" in body:
        species = body["species"]
        assert isinstance(species, list)
    elif isinstance(body, list):
        assert all("sequence_id" in item or "id" in item for item in body)
    else:
        assert False, f"Unexpected response shape: {type(body)}"
