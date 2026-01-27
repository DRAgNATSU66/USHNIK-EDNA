# SIH

## eDNA Species Classification Pipeline

Windows-safe nucleotide transformer implementation for DNA species classification.

---

## Quick Start (Local Validation)

```powershell
# 1. Activate environment
cd c:\Users\ushni\Documents\SIH_REPO
.\gpu_env\Scripts\activate

# 2. (Optional) Convert data if needed
python src/data/convert.py --input data/reference_db/reference_small_aug10.csv --output data/processed --min-length 30

# 3. Training smoke test (skip if models/trained_nt exists)
python src/species_identification/train_nt.py --train data/processed/train.jsonl --val data/processed/val.jsonl --label_map data/processed/label_map.json --output_dir models/trained_nt --epochs 1 --batch_size 4 --accumulation_steps 2

# 4. Inference smoke test
python -c "from src.species_identification.nt_inference import predict_batch; print(predict_batch(['ATGCGTACGTAGCTAGCTGACTGATCGTAGCTAGCTAGCTAG']))"

# 5. Start FastAPI server
uvicorn src.web_api.main:app --host 127.0.0.1 --port 8000

# 6. Test /analyze endpoint (in another terminal)
Invoke-RestMethod -Method POST -Uri "http://127.0.0.1:8000/analyze" -ContentType "application/json" -Body '{"sequences": [{"sequence_id": "test1", "sequence": "ATGCGTACGTAGCTAGCTGACTGATCGTAGCTAGCTAGCTAG"}]}'
```

---

## Biological Caveat

**IMPORTANT**: The current model uses `bert-base-uncased` as a Windows-safe fallback. This is a general-purpose language model, not a DNA-specialized model. For production use with real biological sequences, download and train with `InstaDeepAI/nucleotide-transformer-500m-human-ref` (requires ~2GB download):

```powershell
python src/species_identification/train_nt.py --model_name "InstaDeepAI/nucleotide-transformer-500m-human-ref" ...
```

---

## Windows Compatibility

| Setting | Value | Reason |
|---------|-------|--------|
| Base weights | Frozen | Avoids PEFT/LoRA/bitsandbytes issues |
| Precision | fp32 | fp16 unstable on some Windows CUDA |
| Workers | 0 | Windows multiprocessing issues |
