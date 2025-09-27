# src/web_api/main.py
"""
FastAPI app for eDNA analysis (paste-ready).

- Uses a lifespan handler (asynccontextmanager) and awaits init_db() to initialize Motor+Beanie.
- Model loader remains lazy and safe (tries model_wrapper, sklearn fallback, then dummy).
- /analyze accepts either:
    - multipart/form-data file (FASTA) with field name "file"
    - application/json body with {"sequences": [{ "sequence_id": "...", "sequence": "..." }, ...], "file_name": "..."}
  and returns a list of predictions for each sequence.
- After predictions, the analysis run is saved into MongoDB (collection `analyses`).
- Additional routes: /health, POST /analysis/{id}/comment, POST /analysis/{id}/propose, GET /analysis/{id}
"""

import os
import io
import time
import traceback
import asyncio
import uuid
from typing import List, Dict, Any, Optional
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, UploadFile, File, HTTPException, Request, Path
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

# load .env for dev
load_dotenv()

# Try Biopython
try:
    from Bio import SeqIO  # type: ignore
    BIOPYTHON_AVAILABLE = True
except Exception:
    BIOPYTHON_AVAILABLE = False

# Import DB init and document models (expects src/web_api/models.py exists)
try:
    from src.web_api.models import init_db, Analysis, Comment, Proposal, FileRecord, SpeciesEntry  # type: ignore
except Exception:
    # If this import fails, we still run but DB won't be initialized. init_db() will raise later.
    init_db = None
    Analysis = None
    Comment = None
    Proposal = None
    FileRecord = None
    SpeciesEntry = None

# Motor for fallback direct DB operations (if needed)
try:
    import motor.motor_asyncio as motor_asyncio  # type: ignore
except Exception:
    motor_asyncio = None

# ---------------------------
# Model loading (same safe logic as before)
# ---------------------------
def _load_model_safe():
    """
    Try to load get_best_model() from model_wrapper; fall back to sklearn species_clf.pkl then a DummyModel.
    The returned object must implement predict_batch(sequences: List[Dict]) -> List[Dict].
    """
    # Preferred: model_wrapper
    try:
        from src.species_identification.model_wrapper import get_best_model  # type: ignore
        return get_best_model()
    except Exception:
        pass

    # Try sklearn fallback
    try:
        import joblib  # type: ignore
        p = os.path.join("models", "species_clf.pkl")
        if os.path.exists(p):
            obj = joblib.load(p)
            model = obj.get("model") if isinstance(obj, dict) else obj
            vectorizer = obj.get("vectorizer") if isinstance(obj, dict) else None

            class SklearnAdapter:
                def __init__(self, model, vectorizer):
                    self.model = model
                    self.vectorizer = vectorizer

                def predict_batch(self, sequences: List[Dict]) -> List[Dict]:
                    texts = [s.get("sequence", "") for s in sequences]
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

    # Dummy fallback
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
# FASTA parsing: Biopython if available, fallback otherwise
# ---------------------------
def parse_fasta_bytes(content: bytes) -> List[Dict[str, str]]:
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
            pass

    # fallback parser (simple)
    current_id = None
    current_seq_lines: List[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith(">"):
            if current_id is not None:
                sequences.append({"sequence_id": current_id, "sequence": "".join(current_seq_lines)})
            current_id = line[1:].split()[0] if len(line) > 1 else f"unknown_{len(sequences)+1}"
            current_seq_lines = []
        else:
            current_seq_lines.append(line.strip())
    if current_id is not None:
        sequences.append({"sequence_id": current_id, "sequence": "".join(current_seq_lines)})
    # filter empty
    sequences = [s for s in sequences if s.get("sequence")]
    return sequences


# ---------------------------
# FastAPI app & lifespan (initialize DB + model)
# ---------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Startup: init_db() (awaited) and load model safe.
    We set:
      app.state.model  -> loaded model adapter
      app.state.db_ready -> True/False depending on init_db success
      app.state.motor_client -> motor client for fallback operations (optional)
    """
    # DB init
    app.state.db_ready = False
    # create motor client for fallback writes if motor available
    MONGO_URI = os.getenv("MONGODB_URI") or os.getenv("MONGO_URI")
    MONGO_DB = os.getenv("MONGODB_DB") or os.getenv("MONGODB_DB_NAME") or "sih_db"
    if motor_asyncio and MONGO_URI:
        try:
            app.state.motor_client = motor_asyncio.AsyncIOMotorClient(MONGO_URI)
            app.state.motor_dbname = MONGO_DB
        except Exception:
            app.state.motor_client = None
    else:
        app.state.motor_client = None

    if init_db is None:
        print("[startup] init_db import failed (models.py not found). DB won't be initialized via Beanie.")
    else:
        try:
            print("[startup] initializing DB (await init_db)...")
            await init_db()
            app.state.db_ready = True
            print("[startup] DB initialized via models.init_db().")
        except Exception:
            traceback.print_exc()
            print("[startup] DB initialization failed (init_db). continuing without Beanie DB.")
            app.state.db_ready = False

    # Model load (safe)
    try:
        print("[startup] loading model (safe load)...")
        app.state.model = _load_model_safe()
        print("[startup] model loaded:", type(app.state.model).__name__)
    except Exception:
        traceback.print_exc()
        app.state.model = _load_model_safe()

    try:
        yield
    finally:
        # cleanup: call model.close if present
        try:
            model = getattr(app.state, "model", None)
            if model is not None and hasattr(model, "close"):
                try:
                    model.close()
                except Exception:
                    pass
        except Exception:
            pass
        # close motor client if created
        try:
            mc = getattr(app.state, "motor_client", None)
            if mc:
                mc.close()
        except Exception:
            pass
        print("[shutdown] app shutting down.")


app = FastAPI(lifespan=lifespan, title="SIH eDNA Analysis API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("ALLOW_ORIGINS", "*").split(",") if os.getenv("ALLOW_ORIGINS") else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------
# Response models for FastAPI
# ---------------------------
class AnalyzeResult(BaseModel):
    sequence_id: str
    sequence: str
    predicted_species: str
    confidence: float
    source: str


class CommentPayload(BaseModel):
    commentText: str
    meta: Optional[Dict[str, Any]] = None


class ProposePayload(BaseModel):
    proposedSpecies: str
    reason: Optional[str] = None
    by: Optional[str] = None


# ---------------------------
# Health endpoint
# ---------------------------
@app.get("/health")
async def health():
    model_name = getattr(getattr(app.state, "model", None), "__class__", None)
    model_name = model_name.__name__ if model_name else None
    return {"status": "ok", "model": model_name, "db_ready": bool(getattr(app.state, "db_ready", False))}


# ---------------------------
# Analyze endpoint (accepts FASTA file OR JSON sequences)
# ---------------------------
@app.post("/analyze", response_model=List[AnalyzeResult])
async def analyze(request: Request, file: Optional[UploadFile] = File(None)):
    """
    Accepts either:
      - multipart/form-data with a FASTA file (field name 'file'), or
      - application/json body: {"sequences": [{sequence_id, sequence}, ...], "file_name": ...}
    Flow:
      - parse sequences
      - run model.predict_batch in executor (non-blocking)
      - save Analysis record to DB (if DB initialized)
      - return normalized results list
    """
    # Determine content type
    try:
        ctype = request.headers.get("content-type", "")
    except Exception:
        ctype = ""

    sequences: List[Dict[str, Any]] = []
    file_name: Optional[str] = None

    # If JSON body
    if "application/json" in ctype:
        try:
            body = await request.json()
            # Accept either {"sequences": [...] } or an array directly
            if isinstance(body, dict) and "sequences" in body and isinstance(body["sequences"], list):
                sequences = body["sequences"]
            elif isinstance(body, list):
                sequences = body
            elif isinstance(body, dict) and "fasta" in body:
                # support {"fasta": "string..."} - convert using parse_fasta_bytes
                fasta_text = body.get("fasta", "")
                sequences = parse_fasta_bytes(fasta_text.encode("utf-8"))
            else:
                raise HTTPException(status_code=400, detail="Invalid JSON payload: expected 'sequences' list or array or 'fasta' string")
            file_name = body.get("file_name") if isinstance(body, dict) else None
        except HTTPException as he:
            raise he
        except Exception:
            traceback.print_exc()
            raise HTTPException(status_code=400, detail="Failed to parse JSON body")
    else:
        # Expect a file (FASTA) upload
        if file is None:
            raise HTTPException(status_code=400, detail="Missing file upload or JSON payload")
        try:
            content = await file.read()
            file_name = getattr(file, "filename", None)
            sequences = parse_fasta_bytes(content)
        except Exception:
            traceback.print_exc()
            raise HTTPException(status_code=400, detail="Failed to read or parse uploaded FASTA")

    if not sequences:
        raise HTTPException(status_code=400, detail="No valid sequences found in input")

    # ensure sequence_id present
    for idx, s in enumerate(sequences):
        if not s.get("sequence_id"):
            s["sequence_id"] = f"seq_{idx+1}"

    # Run predictions in threadpool if blocking
    model = getattr(app.state, "model", None)
    if model is None:
        model = _load_model_safe()

    loop = asyncio.get_running_loop()
    try:
        predict = getattr(model, "predict_batch", None)
        if not callable(predict):
            raise RuntimeError("Loaded model does not expose predict_batch(sequences)")
        results = await loop.run_in_executor(None, lambda: predict(sequences))
    except Exception:
        traceback.print_exc()
        # return Unknown per sequence
        results = []
        for s in sequences:
            results.append({
                "sequence_id": s.get("sequence_id"),
                "sequence": s.get("sequence"),
                "predicted_species": "Unknown",
                "confidence": 0.0,
                "source": "error",
            })

    # Normalize results
    normalized = []
    for r in results:
        normalized.append({
            "sequence_id": r.get("sequence_id") or r.get("id") or "",
            "sequence": r.get("sequence") or "",
            "predicted_species": r.get("predicted_species") or r.get("label") or "Unknown",
            "confidence": float(r.get("confidence") or r.get("score") or 0.0),
            "source": r.get("source") or "unknown",
        })

    # Save Analysis to DB if available (try Beanie first, fallback to Motor)
    saved = False
    analysis_id_str = str(uuid.uuid4())
    if getattr(app.state, "db_ready", False) and Analysis is not None:
        try:
            # Build species entries using SpeciesEntry if available
            species_objs = []
            if SpeciesEntry is not None:
                for r in normalized:
                    try:
                        se = SpeciesEntry(
                            sequence_id = r["sequence_id"],
                            name = r["predicted_species"],
                            confidence = r["confidence"],
                            sequence = r["sequence"],
                            source = r["source"]
                        )
                        species_objs.append(se)
                    except Exception:
                        # fallback to plain dict
                        species_objs.append({
                            "sequence_id": r["sequence_id"],
                            "name": r["predicted_species"],
                            "confidence": r["confidence"],
                            "sequence": r["sequence"],
                            "source": r["source"]
                        })
            else:
                species_objs = [{
                    "sequence_id": r["sequence_id"],
                    "name": r["predicted_species"],
                    "confidence": r["confidence"],
                    "sequence": r["sequence"],
                    "source": r["source"]
                } for r in normalized]

            analysis_doc = Analysis(
                analysis_id = analysis_id_str,
                uploaded_by = None,
                metrics = {
                    "totalSpecies": len(normalized),
                },
                species = species_objs,
                original_json = {"sequences_count": len(sequences)},
                file_name = file_name
            )
            await analysis_doc.insert()
            saved = True
        except Exception:
            traceback.print_exc()
            saved = False
    else:
        # fallback: use motor if available on app.state.motor_client
        mc = getattr(app.state, "motor_client", None)
        dbname = getattr(app.state, "motor_dbname", None)
        if mc and dbname:
            try:
                coll = mc[dbname].analyses
                doc = {
                    "analysis_id": analysis_id_str,
                    "created_at": datetime.utcnow(),
                    "metrics": {"totalSpecies": len(normalized)},
                    "species": normalized,
                    "original_json": {"sequences_count": len(sequences)},
                    "file_name": file_name,
                }
                await coll.insert_one(doc)
                saved = True
            except Exception:
                traceback.print_exc()
                saved = False

    # return normalized results list (same shape as response_model)
    # but include analysis_id in headers? We return plain list per your response_model contract.
    # Optionally, client can call GET /analysis/{analysis_id} to fetch saved document.
    # We'll include the analysis_id in a custom header via Response is harder here; instead, for convenience,
    # attach analysis_id to each result as metadata if desired; but we must match the response_model. We'll not modify response_model.
    # Instead, add the analysis id into the FastAPI Response headers is better, but the route has response_model=List[AnalyzeResult].
    # Simpler: return the normalized list (clients get analysis id from DB directly or call separate endpoint).
    # To keep backward compatibility with prior front-end: return normalized list only.
    # If you want analysis id returned, change response_model accordingly.
    # For now: return normalized list
    return normalized


# ---------------------------
# Helper: low-level motor fetch for GET/updates (if Beanie not present)
# ---------------------------
async def _motor_get_analysis(app: FastAPI, analysis_id: str) -> Optional[Dict[str, Any]]:
    mc = getattr(app.state, "motor_client", None)
    dbname = getattr(app.state, "motor_dbname", None)
    if not mc or not dbname:
        return None
    try:
        doc = await mc[dbname].analyses.find_one({"analysis_id": analysis_id})
        if not doc:
            return None
        # Convert ObjectId & datetimes to strings
        doc["_id"] = str(doc.get("_id"))
        if isinstance(doc.get("created_at"), datetime):
            doc["created_at"] = doc["created_at"].isoformat()
        return doc
    except Exception:
        traceback.print_exc()
        return None


# ---------------------------
# GET Analysis by ID
# ---------------------------
@app.get("/analysis/{analysis_id}")
async def get_analysis(analysis_id: str = Path(..., description="analysis id")):
    # Try Beanie Analysis model if available
    if Analysis is not None:
        try:
            # Attempt to find by analysis_id (assuming Analysis.analysis_id field)
            obj = await Analysis.find_one({"analysis_id": analysis_id})
            if obj:
                d = obj.dict()
                # convert any non-serializable fields
                return d
        except Exception:
            traceback.print_exc()

    # fallback to motor
    motor_doc = await _motor_get_analysis(app, analysis_id)
    if motor_doc:
        return motor_doc

    raise HTTPException(status_code=404, detail="Analysis not found")


# ---------------------------
# POST comment to an analysis
# ---------------------------
@app.post("/analysis/{analysis_id}/comment")
async def post_comment(analysis_id: str, payload: CommentPayload):
    """
    Add a comment to a saved analysis.
    Body: { "commentText": "...", "meta": { fullName, job, goal, ... } }
    """
    # Normalize incoming comment
    comment_doc = {
        "commentText": payload.commentText,
        "meta": payload.meta or {},
        "created_at": datetime.utcnow()
    }

    # Try Beanie path
    if Analysis is not None and Comment is not None:
        try:
            obj = await Analysis.find_one({"analysis_id": analysis_id})
            if not obj:
                raise HTTPException(status_code=404, detail="Analysis not found")
            # Create Comment instance if possible and append
            try:
                comment_obj = Comment(**comment_doc)
                if getattr(obj, "comments", None) is None:
                    obj.comments = [comment_obj]
                else:
                    obj.comments.append(comment_obj)
                await obj.save()
                return {"ok": True, "saved": True}
            except Exception:
                # fallback to dict append
                if getattr(obj, "comments", None) is None:
                    obj.comments = [comment_doc]
                else:
                    obj.comments.append(comment_doc)
                await obj.save()
                return {"ok": True, "saved": True}
        except HTTPException:
            raise
        except Exception:
            traceback.print_exc()

    # Motor fallback: push into analyses.comments array
    mc = getattr(app.state, "motor_client", None)
    dbname = getattr(app.state, "motor_dbname", None)
    if mc and dbname:
        try:
            res = await mc[dbname].analyses.update_one(
                {"analysis_id": analysis_id},
                {"$push": {"comments": comment_doc}}
            )
            if res.matched_count == 0:
                raise HTTPException(status_code=404, detail="Analysis not found")
            return {"ok": True, "saved": True}
        except HTTPException:
            raise
        except Exception:
            traceback.print_exc()

    raise HTTPException(status_code=503, detail="Database not available to save comment")


# ---------------------------
# POST propose correction for an analysis novelty
# ---------------------------
@app.post("/analysis/{analysis_id}/propose")
async def post_propose(analysis_id: str, payload: ProposePayload):
    """
    Add a proposal to a saved analysis.
    Body: { "proposedSpecies": "...", "reason": "...", "by": "..." }
    """
    proposal_doc = {
        "proposedSpecies": payload.proposedSpecies,
        "reason": payload.reason or "",
        "by": payload.by or "",
        "created_at": datetime.utcnow()
    }

    # Beanie path
    if Analysis is not None and Proposal is not None:
        try:
            obj = await Analysis.find_one({"analysis_id": analysis_id})
            if not obj:
                raise HTTPException(status_code=404, detail="Analysis not found")
            try:
                prop_obj = Proposal(**proposal_doc)
                if getattr(obj, "proposals", None) is None:
                    obj.proposals = [prop_obj]
                else:
                    obj.proposals.append(prop_obj)
                await obj.save()
                return {"ok": True, "saved": True}
            except Exception:
                if getattr(obj, "proposals", None) is None:
                    obj.proposals = [proposal_doc]
                else:
                    obj.proposals.append(proposal_doc)
                await obj.save()
                return {"ok": True, "saved": True}
        except HTTPException:
            raise
        except Exception:
            traceback.print_exc()

    # Motor fallback
    mc = getattr(app.state, "motor_client", None)
    dbname = getattr(app.state, "motor_dbname", None)
    if mc and dbname:
        try:
            res = await mc[dbname].analyses.update_one(
                {"analysis_id": analysis_id},
                {"$push": {"proposals": proposal_doc}}
            )
            if res.matched_count == 0:
                raise HTTPException(status_code=404, detail="Analysis not found")
            return {"ok": True, "saved": True}
        except HTTPException:
            raise
        except Exception:
            traceback.print_exc()

    raise HTTPException(status_code=503, detail="Database not available to save proposal")
