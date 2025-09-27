# src/web_api/models.py
"""
Beanie/Motor models for SIH eDNA project.
This version uses pydantic.BaseModel for embedded documents (works with recent beanie).
Defines:
 - SpeciesEntry (embedded-like pydantic model)
 - Analysis (Beanie Document)
 - Comment (Beanie Document)
 - Proposal (Beanie Document)
 - FileRecord (Beanie Document, simple)
Also provides `init_db()` to initialize Motor + Beanie.
"""

import os
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from beanie import Document, init_beanie
from motor.motor_asyncio import AsyncIOMotorClient


class SpeciesEntry(BaseModel):
    sequence_id: str = Field(...)
    name: str = Field(..., description="Predicted species name or label")
    confidence: float = Field(0.0, description="Confidence (0.0-1.0)")
    sequence: Optional[str] = Field(None, description="Raw sequence (optional)")
    source: Optional[str] = Field(None, description="Model/source that produced this label")


class Analysis(Document):
    """
    Stores one analysis run. Collection name will be 'analyses'.
    """
    analysis_id: str = Field(..., description="UUID/unique id for this analysis")
    uploaded_by: Optional[str] = None
    metrics: Dict[str, Any] = {}
    species: List[SpeciesEntry] = []
    original_json: Optional[Dict[str, Any]] = None
    file_name: Optional[str] = None

    class Settings:
        name = "analyses"


class Comment(Document):
    """
    Comments attached to an analysis
    """
    analysis_id: str = Field(..., description="Associated Analysis.analysis_id")
    author_name: Optional[str] = None
    job: Optional[str] = None
    goal: Optional[str] = None
    comment_text: Optional[str] = None
    familiarity_pct: Optional[float] = None
    unfamiliarity_pct: Optional[float] = None

    class Settings:
        name = "comments"


class Proposal(Document):
    """
    Species correction proposals
    """
    analysis_id: str = Field(..., description="Associated Analysis.analysis_id")
    from_novelty: Optional[Dict[str, Any]] = None
    to: Optional[str] = None
    reason: Optional[str] = None
    by: Optional[str] = None
    status: str = Field("pending")  # pending/accepted/rejected

    class Settings:
        name = "proposals"


class FileRecord(Document):
    """
    Optional: store file metadata or small JSON payloads
    """
    file_name: Optional[str] = None
    uploaded_by: Optional[str] = None
    meta: Optional[Dict[str, Any]] = None

    class Settings:
        name = "files"


async def init_db():
    """
    Initialize Motor client and Beanie. Reads MONGO_URI and optional MONGO_DB_NAME from env.
    Example .env keys:
      MONGO_URI="mongodb+srv://user:pass@cluster.example.net/?retryWrites=true&w=majority"
      MONGO_DB_NAME="sih_db"
    """
    mongo_uri = os.getenv("MONGO_URI")
    if not mongo_uri:
        raise RuntimeError("MONGO_URI not set in environment")

    db_name = os.getenv("MONGO_DB_NAME", "sih_db")
    client = AsyncIOMotorClient(mongo_uri)
    # ensure the DB connection works (this will not throw on lazy connect but next ops will)
    db = client[db_name]

    # Initialize beanie with all document models
    await init_beanie(database=db, document_models=[Analysis, Comment, Proposal, FileRecord])
    return True
