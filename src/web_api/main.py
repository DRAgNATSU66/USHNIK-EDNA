# src/web_api/main.py
import os
import io
import logging
import traceback
from typing import List, Dict, Any, Optional

from fastapi import FastAPI, UploadFile, File, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from Bio import SeqIO

# load .env (if present)
load_dotenv()

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("edna_api")

# Attempt to import a model manager abstraction (optional, recommended)
# MODEL_MANAGER is an object that implements:
#   - get_status() -> dict
#   - predict(sequences: List[dict], metadata: dict) -> List[dict]  (can be async)
#   - set_custom_pipeline(path: str) -> bool
MODEL_MANAGER = None
try:
    # This is optional: a separate module that handles HF loading, local models, and custom packages
    from src.pipelines.model_manager import MODEL_MANAGER  # type: ignore
    logger.info("Loaded src.pipelines.model_manager.MODEL_MANAGER")
except Exception as e:
    MODEL_MANAGER = None
    logger.info("No external MODEL_MANAGER found (this is ok). Import error: %s", e)

app = FastAPI(title="eDNA API - Robust")

# Development CORS (allow everything). Lock down for prod.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def parse_fasta_bytes(file_bytes: bytes) -> List[Dict[str, Any]]:
    """
    Parse FASTA bytes using Biopython with a compact robust fallback parser.

    Returns list of dicts: { 'id': <id>, 'sequence': <sequence str> }
    """
    records: List[Dict[str, Any]] = []
    # Try Biopython FASTA parsing first
    try:
        fh = io.BytesIO(file_bytes)
        for rec in SeqIO.parse(fh, "fasta"):
            seq = str(rec.seq).strip()
            if seq:
                records.append({"id": rec.id, "sequence": seq})
    except Exception:
        # ignore and fallback below
        pass

    if records:
        return records

    # Fallback simple parsing (robust)
    try:
        text = file_bytes.decode("utf-8", errors="ignore").strip()
    except Exception:
        text = file_bytes.decode("latin-1", errors="ignore").strip()

    if not text:
        return []

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
        # no headers -> each non-empty line is a sequence
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        for i, l in enumerate(lines, 1):
            records.append({"id": f"seq{i}", "sequence": l.replace(" ", "")})
    return records


@app.on_event("startup")
def startup_event():
    logger.info("Application startup complete. MODEL_MANAGER present: %s", MODEL_MANAGER is not None)


@app.get("/health")
def health():
    """
    Returns overall API health and model manager status.
    """
    mm_status: Dict[str, Any] = {"loaded": False}
    if MODEL_MANAGER is None:
        mm_status = {"loaded": False, "error": "MODEL_MANAGER not available"}
    else:
        try:
            # MODEL_MANAGER.get_status may raise; catch and return error details
            mm_status = MODEL_MANAGER.get_status()
        except Exception as e:
            mm_status = {"loaded": False, "error": str(e)}
            logger.exception("MODEL_MANAGER.get_status failed: %s", e)

    return {"status": "ok", "model_manager": mm_status}


@app.post("/admin/load_custom")
def load_custom_model_package(path: str = Body(..., embed=True)):
    """
    Admin endpoint to load a custom model package (Sandipan/Arya).
    `path` should be a filesystem path accessible to the server containing a
    model_interface.py and the packaged models.

    Example JSON body:
      { "path": "/home/ubuntu/sandipan_models" }
    """
    if MODEL_MANAGER is None:
        raise HTTPException(status_code=500, detail="Model manager not available on server")

    if not os.path.exists(path):
        raise HTTPException(status_code=400, detail=f"Path not found: {path}")

    try:
        ok = MODEL_MANAGER.set_custom_pipeline(path)
    except Exception as e:
        logger.exception("MODEL_MANAGER.set_custom_pipeline failed: %s", e)
        raise HTTPException(status_code=500, detail="Failed to load custom model package. Check server logs.")

    if not ok:
        raise HTTPException(status_code=500, detail="MODEL_MANAGER reported failure loading the package")

    return {"status": "ok", "message": "Custom model package loaded", "path": path}


@app.post("/analyze")
async def analyze(file: UploadFile = File(...)):
    """
    Accept a FASTA file upload and return predictions:
      [{sequence_id, sequence, predicted_species, confidence, source}, ...]
    Source values: "custom" | "nucleotide" | "esm2" | "sklearn_local" | "unknown" | "error"
    """
    content = await file.read()
    sequences = parse_fasta_bytes(content)

    if not sequences:
        raise HTTPException(status_code=400, detail="No sequences found in uploaded file")

    # If MODEL_MANAGER available, prefer it (it may handle HF/local/custom switching)
    if MODEL_MANAGER is not None:
        try:
            # allow MODEL_MANAGER.predict to be sync or async
            pred = MODEL_MANAGER.predict(sequences, metadata={})
            if hasattr(pred, "__await__"):  # coroutine
                results = await pred  # type: ignore
            else:
                results = pred
        except Exception as e:
            logger.exception("ModelManager.predict failed: %s", e)
            # fallback to unknowns on error
            results = [{
                "sequence_id": r.get("id", f"seq{i+1}"),
                "sequence": r.get("sequence", ""),
                "predicted_species": "Unknown",
                "confidence": 0.0,
                "source": "error"
            } for i, r in enumerate(sequences)]
    else:
        # No MODEL_MANAGER: attempt a simple local sklearn-style fallback if a model exists in ../models
        # This keeps behavior similar to the original lightweight script.
        # Look for a joblib/pickle at ../models/species_clf.pkl
        local_path = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "models", "species_clf.pkl"))
        local_bundle = None
        try:
            import joblib, pickle
            if os.path.exists(local_path):
                try:
                    data = joblib.load(local_path)
                except Exception:
                    with open(local_path, "rb") as f:
                        data = pickle.load(f)
                bundle = {"vectorizer": None, "classifier": None}
                if isinstance(data, dict):
                    bundle["vectorizer"] = data.get("vectorizer")
                    bundle["classifier"] = data.get("classifier", data.get("clf", None))
                else:
                    bundle["classifier"] = data
                local_bundle = bundle
        except Exception as e:
            logger.info("No local model bundle available or failed to load: %s", e)

        if local_bundle and local_bundle.get("classifier") is not None:
            clf = local_bundle.get("classifier")
            vec = local_bundle.get("vectorizer")
            results = []
            for i, rec in enumerate(sequences):
                seq = rec.get("sequence", "")
                seq_id = rec.get("id", f"seq{i+1}")
                try:
                    if vec is not None:
                        x = vec.transform([seq])
                        pred = clf.predict(x)
                        if hasattr(clf, "predict_proba"):
                            prob = float(max(clf.predict_proba(x)[0]))
                        else:
                            prob = 1.0
                        label = pred[0] if isinstance(pred, (list, tuple)) else str(pred)
                    else:
                        pred = clf.predict([seq])
                        label = pred[0]
                        prob = 1.0
                except Exception:
                    label = "Unknown"
                    prob = 0.0
                results.append({
                    "sequence_id": seq_id,
                    "sequence": seq,
                    "predicted_species": label,
                    "confidence": float(prob),
                    "source": "sklearn_local"
                })
        else:
            # Last-resort: return Unknowns so frontend doesn't break
            results = [{
                "sequence_id": r.get("id", f"seq{i+1}"),
                "sequence": r.get("sequence", ""),
                "predicted_species": "Unknown",
                "confidence": 0.0,
                "source": "unknown"
            } for i, r in enumerate(sequences)]

    # Normalize/validate output shape before returning to frontend
    normalized: List[Dict[str, Any]] = []
    for r in results:
        seq_id = r.get("sequence_id") or r.get("id") or r.get("sequenceId") or ""
        seq = r.get("sequence") or r.get("seq") or ""
        pred = r.get("predicted_species") or r.get("label") or r.get("prediction") or "Unknown"
        conf = r.get("confidence") or r.get("score") or 0.0
        src = r.get("source") or "unknown"
        try:
            conf = float(conf)
        except Exception:
            conf = 0.0
        normalized.append({
            "sequence_id": seq_id,
            "sequence": seq,
            "predicted_species": pred,
            "confidence": conf,
            "source": src
        })

    return normalized
