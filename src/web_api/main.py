from dotenv import load_dotenv
import os

load_dotenv()

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Dict, Any
import io
from Bio import SeqIO

# Import Hugging Face model functions
from src.species_identification.hf_model import load_hf_model, predict_sequences

app = FastAPI(title="eDNA API - Beta (HuggingFace)")

# Allow all origins for development; lock down for production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Load model at startup (may download on first run)
try:
    MODEL = load_hf_model()
except Exception as e:
    print("Model load failed at startup:", e)
    MODEL = None


@app.get("/health")
def health():
    return {
        "status": "ok",
        "model_loaded": MODEL is not None and MODEL.get("pipeline") is not None,
        "device": MODEL.get("device") if MODEL else "none",
        "label_map": MODEL.get("id2label", {}) if MODEL else {},
    }


def parse_fasta_bytes(file_bytes: bytes) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    fh = io.BytesIO(file_bytes)

    # try Bio.SeqIO.parse first (normal case)
    try:
        for rec in SeqIO.parse(fh, "fasta"):
            seq = str(rec.seq).strip()
            if seq:
                records.append({"id": rec.id, "sequence": seq})
    except Exception:
        pass

    if records:
        return records

    # fallback heuristic
    try:
        text = file_bytes.decode("utf-8", errors="ignore").strip()
    except Exception:
        text = file_bytes.decode("latin-1", errors="ignore").strip()

    if text.startswith("\ufeff"):
        text = text.lstrip("\ufeff")

    if ">" in text:
        parts = [p.strip() for p in text.split(">") if p.strip()]
        for p in parts:
            lines = [l.strip() for l in p.splitlines() if l.strip()]
            if not lines:
                continue
            header = lines[0].split()[0] if lines[0] else f"seq{len(records)+1}"
            seq = "".join(lines[1:]).replace(" ", "").replace("\r", "").replace("\n", "")
            if seq:
                records.append({"id": header, "sequence": seq})
    else:
        blocks = [b for b in (line.strip() for line in text.splitlines()) if b != ""]
        if len(blocks) > 1:
            for i, b in enumerate(blocks, 1):
                seq = b.replace(" ", "").replace("\r", "").replace("\n", "")
                if seq:
                    records.append({"id": f"seq{i}", "sequence": seq})
        else:
            seq = blocks[0].replace(" ", "").replace("\r", "").replace("\n", "")
            if seq:
                records.append({"id": "seq1", "sequence": seq})

    return records


@app.post("/analyze")
async def analyze(file: UploadFile = File(...)):
    """
    Returns stable JSON object:
    {
      "sequence_count": int,
      "predictions": [ {sequence_id, sequence, predicted_species, confidence}, ... ],
      "device": "cpu"/"cuda",
      "label_map": { "LABEL_0": "Homo sapiens", ... }
    }
    """
    content = await file.read()
    sequences = parse_fasta_bytes(content)

    if not sequences:
        raise HTTPException(status_code=400, detail="No sequences found in uploaded file")

    if MODEL is None or MODEL.get("pipeline") is None:
        # fallback unknowns
        preds = []
        for rec in sequences:
            preds.append({"sequence_id": rec.get("id"), "sequence": rec.get("sequence"), "predicted_species": "Unknown", "confidence": 0.0})
        return {"sequence_count": len(preds), "predictions": preds, "device": "none", "label_map": {}}

    preds = predict_sequences(MODEL, sequences)
    return {"sequence_count": len(preds), "predictions": preds, "device": MODEL.get("device", "cpu"), "label_map": MODEL.get("id2label", {})}

