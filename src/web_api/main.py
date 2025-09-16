"""
FastAPI app for eDNA analysis.

Features:
- Lifespan handler instead of deprecated @app.on_event.
- Lazy/priority model loader: tries to use src.species_identification.model_wrapper.get_best_model()
  if available, otherwise falls back to a dummy predictor or sklearn model if present.
- /health and /analyze endpoints.
- FASTA parsing via Biopython with a simple fallback parser.
- CORS middleware enabled for dev (allow_origins=["*"]).
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict, Any
import os
import io
import asyncio
import time
import traceback

# Load environment variables from .env
from dotenv import load_dotenv
load_dotenv()

# Try to import Biopython SeqIO; if missing, we'll use fallback
try:
    from Bio import SeqIO  # type: ignore
    BIOPYTHON_AVAILABLE = True
except Exception:
    BIOPYTHON_AVAILABLE = False


# ---------------------------
# Simple model fallback logic
# ---------------------------
def _load_model_safe():
    """
    Try to import get_best_model() from model_wrapper. If not present,
    fall back to:
      - models/species_clf.pkl (sklearn) if exists
      - Dummy model that returns "Unknown"
    """
    # Try preferred model_wrapper if present
    try:
        from src.species_identification.model_wrapper import get_best_model  # type: ignore
        return get_best_model()
    except Exception:
        # continue to other fallbacks
        pass

    # Try to load sklearn model if available at models/species_clf.pkl
    try:
        import joblib  # type: ignore
        p = os.path.join("models", "species_clf.pkl")
        if os.path.exists(p):
            obj = joblib.load(p)
            # If saved as dict, get model and optional vectorizer
            model = obj.get("model") if isinstance(obj, dict) else obj
            vectorizer = obj.get("vectorizer") if isinstance(obj, dict) else None

            class SklearnAdapter:
                def __init__(self, model, vectorizer):
                    self.model = model
                    self.vectorizer = vectorizer

                def predict_batch(self, sequences: List[Dict]) -> List[Dict]:
                    texts = [s["sequence"] for s in sequences]
                    try:
                        X = self.vectorizer.transform(texts) if self.vectorizer else texts
                    except Exception:
                        X = texts
                    try:
                        preds = self.model.predict(X)
                    except Exception:
                        preds = ["Unknown"] * len(texts)
                    probs = None
                    try:
                        if hasattr(self.model, "predict_proba"):
                            probs = self.model.predict_proba(X)
                    except Exception:
                        probs = None
                    out = []
                    for i, s in enumerate(sequences):
                        predicted = str(preds[i])
                        confidence = float(max(probs[i]) if probs is not None else 0.0)
                        out.append({
                            "sequence_id": s.get("sequence_id"),
                            "sequence": s.get("sequence"),
                            "predicted_species": predicted,
                            "confidence": confidence,
                            "source": "sklearn_local",
                        })
                    return out

            return SklearnAdapter(model, vectorizer)
    except Exception:
        pass

    # Dummy fallback model
    class DummyModel:
        def predict_batch(self, sequences: List[Dict]) -> List[Dict]:
            out = []
            for s in sequences:
                out.append({
                    "sequence_id": s.get("sequence_id"),
                    "sequence": s.get("sequence"),
                    "predicted_species": "Unknown",
                    "confidence": 0.0,
                    "source": "none",
                })
            return out

    return DummyModel()


# ---------------------------
# FASTA parsing utilities
# ---------------------------
def parse_fasta_bytes(content: bytes) -> List[Dict[str, str]]:
    """
    Parse FASTA content into a list of dicts: {'sequence_id': id, 'sequence': seq}
    Uses Biopython SeqIO if available; otherwise uses a tiny fallback parser.
    """
    text = content.decode("utf-8", errors="ignore")
    sequences = []
    if BIOPYTHON_AVAILABLE:
        try:
            fh = io.StringIO(text)
            for rec in SeqIO.parse(fh, "fasta"):
                seq = str(rec.seq).strip()
                seqid = str(rec.id)
                if seq:
                    sequences.append({"sequence_id": seqid, "sequence": seq})
            return sequences
        except Exception:
            # fallthrough to fallback parser
            pass

    # Simple fallback parser (not as robust as Biopython)
    current_id = None
    current_seq_lines = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith(">"):
            if current_id is not None:
                sequences.append({"sequence_id": current_id, "sequence": "".join(current_seq_lines)})
            current_id = line[1:].split()[0] if len(line) > 1 else "unknown"
            current_seq_lines = []
        else:
            current_seq_lines.append(line.strip())
    if current_id is not None:
        sequences.append({"sequence_id": current_id, "sequence": "".join(current_seq_lines)})
    # Remove empty sequences
    sequences = [s for s in sequences if s.get("sequence")]
    return sequences


# ---------------------------
# App and lifespan
# ---------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Run once at startup: load best model (safe).
    Store it on app.state.model for handlers to use.
    """
    print("Starting app - initializing model (safe load).")
    start = time.time()
    try:
        app.state.model = _load_model_safe()
        elapsed = time.time() - start
        print(f"Model loader finished in {elapsed:.2f}s. Model: {type(app.state.model).__name__}")
    except Exception as e:
        traceback.print_exc()
        app.state.model = _load_model_safe()
    try:
        yield
    finally:
        # If model has cleanup close/dispose attributes, call them
        try:
            model = getattr(app.state, "model", None)
            if model is not None and hasattr(model, "close"):
                try:
                    model.close()
                except Exception:
                    pass
        except Exception:
            pass
        print("Shutting down app.")


app = FastAPI(lifespan=lifespan, title="SIH eDNA Analysis API")

# CORS (dev). Narrow origins for production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("ALLOW_ORIGINS", "*").split(",") if os.getenv("ALLOW_ORIGINS") else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------
# Simple health endpoint
# ---------------------------
@app.get("/health")
async def health():
    # Can expand to include model info, uptime, etc.
    model_name = getattr(getattr(app.state, "model", None), "__class__", None)
    model_name = model_name.__name__ if model_name else None
    return {"status": "ok", "model": model_name}


# ---------------------------
# Analyze endpoint
# ---------------------------
class AnalyzeResult(BaseModel):
    sequence_id: str
    sequence: str
    predicted_species: str
    confidence: float
    source: str


@app.post("/analyze", response_model=List[AnalyzeResult])
async def analyze(request: Request, file: UploadFile = File(...)):
    """
    Accept a multipart/form-data upload with a FASTA file named 'file'.
    Returns a list of results for each sequence:
      [{sequence_id, sequence, predicted_species, confidence, source}, ...]
    """
    # read bytes (safe for small-to-medium files)
    try:
        content = await file.read()
    except Exception:
        raise HTTPException(status_code=400, detail="Failed to read uploaded file")

    # parse FASTA
    sequences = parse_fasta_bytes(content)
    if not sequences:
        raise HTTPException(status_code=400, detail="No valid sequences found in uploaded FASTA")

    # Ensure sequence_id exists
    for idx, s in enumerate(sequences):
        if not s.get("sequence_id"):
            s["sequence_id"] = f"seq_{idx+1}"

    # Predict using the loaded model
    model = getattr(app.state, "model", None)
    if model is None:
        model = _load_model_safe()

    # If model.predict_batch is blocking / heavy, run in threadpool to avoid blocking event loop
    loop = asyncio.get_running_loop()
    try:
        predict = getattr(model, "predict_batch", None)
        if not callable(predict):
            raise RuntimeError("Loaded model does not expose predict_batch(sequences)")
        # run in executor
        results = await loop.run_in_executor(None, lambda: predict(sequences))
    except Exception:
        # Return per-sequence Unknown results if model failed unexpectedly
        traceback.print_exc()
        results = []
        for s in sequences:
            results.append({
                "sequence_id": s.get("sequence_id"),
                "sequence": s.get("sequence"),
                "predicted_species": "Unknown",
                "confidence": 0.0,
                "source": "error",
            })

    # Normalize results: ensure keys exist and types are correct
    normalized = []
    for r in results:
        normalized.append({
            "sequence_id": r.get("sequence_id") or r.get("id") or "",
            "sequence": r.get("sequence") or "",
            "predicted_species": r.get("predicted_species") or r.get("label") or "Unknown",
            "confidence": float(r.get("confidence") or r.get("score") or 0.0),
            "source": r.get("source") or "unknown",
        })

    return normalized
