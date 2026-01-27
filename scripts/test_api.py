# scripts/test_api.py
"""Quick test to verify FastAPI /analyze returns real species predictions."""

import os
import io
import sys

# Set environment
os.environ["USE_HF"] = "true"
os.environ["HF_MODEL_PATH"] = "models/trained_dnabert"

from fastapi.testclient import TestClient
from src.web_api.main import app

client = TestClient(app)

print("=" * 60)
print("FASTAPI ENDPOINT VERIFICATION")
print("=" * 60)

# Test health
print("\n1. Testing /health endpoint...")
r = client.get("/health")
print(f"   Status: {r.status_code}")
print(f"   Response: {r.json()}")

# Test analyze with FASTA
print("\n2. Testing /analyze endpoint with FASTA file...")
fasta = b">seq1\nATGCGTACGTAGCTAGCTGACTGATCGTAGCTAGCTAGCTAG\n>seq2\nGCTAGCTAGCATCGATCGATCGATGCTAGCTAGCATCGATCG\n>seq3\nTTTTAAAACCCGGGGAAATTTTCCCCGGGGAAAATTTTCCCC\n"
r = client.post("/analyze", files={"file": ("test.fasta", io.BytesIO(fasta), "application/octet-stream")})
print(f"   Status: {r.status_code}")

if r.status_code == 200:
    results = r.json()
    print("\n   Predictions:")
    for item in results:
        print(f"     {item['sequence_id']}: {item['predicted_species']} ({item['confidence']:.2%}) - {item['source']}")
    
    # Verify predictions are NOT mock values
    mock_species = ["Panthera tigris", "Canis lupus", "Homo sapiens", "HF_Species_A", "Unknown"]
    real_species = ["FishA", "FishB", "PlantA"]
    
    all_real = all(item["predicted_species"] in real_species for item in results)
    no_mocks = all(item["predicted_species"] not in mock_species for item in results)
    
    print("\n   Verification:")
    print(f"     All predictions are real species: {all_real}")
    print(f"     No mock species detected: {no_mocks}")
    print(f"     Source is trained model: {all(item['source'] == 'huggingface_trained' for item in results)}")
    
    if all_real and no_mocks:
        print("\n" + "=" * 60)
        print("✅ SUCCESS: API returns REAL species predictions!")
        print("=" * 60)
    else:
        print("\n❌ FAILED: Still returning mock predictions")
        sys.exit(1)
else:
    print(f"   Error: {r.text}")
    sys.exit(1)
