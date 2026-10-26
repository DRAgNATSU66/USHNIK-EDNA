"""
Generate the API fixtures the frontend Playwright suite mocks with
(web_frontend/e2e/fixtures/api/*.json, roadmap t-1029-2).

The fixtures are not hand-written. This script seeds an in-memory stand-in
for MongoDB with one researcher's analysis (upload, results, reviews, field
log, an expedition, two jobs), mounts the real FastAPI app over ASGI, signs
real JWTs for a researcher, a curator and an admin, and records what each GET
endpoint the frontend calls actually returns -- response_model filtering,
datetime serialisation and all. So a fixture can only drift from the API if
someone edits the JSON by hand, and tests/test_e2e_fixtures.py fails API CI
when the committed files no longer match what this script produces.

Only two kinds of value are normalised, both volatile per request:
`generated_at` on reports (default_factory=utcnow) and `created_at` on
/auth/me (the profile is rebuilt from JWT claims on every call).

Usage (from the repo root):
    services/api/.venv/bin/python services/api/scripts/gen_e2e_fixtures.py
"""
from __future__ import annotations

import asyncio
import copy
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

API_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = API_DIR.parents[1]
OUT_DIR = REPO_ROOT / "web_frontend" / "e2e" / "fixtures" / "api"
sys.path.insert(0, str(API_DIR))

from httpx import ASGITransport, AsyncClient  # noqa: E402

import app.custody.chain as custody_chain  # noqa: E402
import app.db.mongo as mongo_module  # noqa: E402
import app.main as main_module  # noqa: E402
from app.auth.jwt import create_access_token  # noqa: E402
from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402

FIXED_TS = "2026-10-16T09:00:00"
# checked_at: when GET /reports/{id}/custody re-verified the chain.
VOLATILE_KEYS = {"generated_at", "checked_at"}

ANALYSIS_ID = "ana_e2e0000000001"
UPLOAD_ID = "upl_e2e0000000001"
JOB_RUNNING_ID = "job_e2e_running01"
JOB_DONE_ID = "job_e2e_complete1"
EXPEDITION_ID = "exp_e2e0000000001"

USERS = {
    "researcher": {"sub": "usr_e2e_researcher", "email": "researcher@e2e.test", "name": "Rhea Researcher", "role": "researcher"},
    "curator": {"sub": "usr_e2e_curator", "email": "curator@e2e.test", "name": "Cyrus Curator", "role": "curator"},
    "admin": {"sub": "usr_e2e_admin", "email": "admin@e2e.test", "name": "Ada Admin", "role": "admin"},
}
OWNER = USERS["researcher"]["sub"]


def _ts(day: int, hour: int = 9, minute: int = 0) -> datetime:
    # Naive UTC, as Motor returns stored datetimes (db/mongo.py does not set
    # tz_aware), so serialised timestamps look exactly like production's.
    return datetime(2026, 10, day, hour, minute)


# ---------------------------------------------------------------------------
# In-memory Mongo stand-in: just the operations the GET routes use.
# ---------------------------------------------------------------------------

def _matches(doc: dict, query: dict) -> bool:
    for key, cond in query.items():
        val = doc.get(key)
        if isinstance(cond, dict) and "$in" in cond:
            if val not in cond["$in"]:
                return False
        elif val != cond:
            return False
    return True


class _Cursor:
    def __init__(self, docs: list[dict]):
        self._docs = docs

    def sort(self, key, direction: int = 1):
        keys = key if isinstance(key, list) else [(key, direction)]
        for k, d in reversed(keys):
            self._docs.sort(key=lambda doc: (doc.get(k) is None, doc.get(k)), reverse=d < 0)
        return self

    def skip(self, n: int):
        self._docs = self._docs[n:]
        return self

    def limit(self, n: int):
        self._docs = self._docs[:n] if n else self._docs
        return self

    def __aiter__(self):
        self._it = iter(self._docs)
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration


class _Collection:
    def __init__(self, docs: list[dict] | None = None):
        self.docs = docs or []

    async def find_one(self, query: dict, projection: Any = None, sort: Any = None):
        docs = [d for d in self.docs if _matches(d, query)]
        if sort:  # custody/chain.py append_event: head of the chain by seq
            docs = _Cursor(docs).sort(sort)._docs
        return copy.deepcopy(docs[0]) if docs else None

    async def insert_one(self, doc: dict):
        # custody/chain.py append_event (GET /reports/{id}/custody derives events)
        self.docs.append(copy.deepcopy(doc))

    def find(self, query: dict | None = None, projection: Any = None):
        return _Cursor([copy.deepcopy(d) for d in self.docs if _matches(d, query or {})])

    def aggregate(self, pipeline: list[dict]):
        first = pipeline[0]
        if "$group" in first:  # reviews/curation.py queue_stats
            counts: dict[tuple, int] = {}
            for d in self.docs:
                k = (d["state"], d["review_type"])
                counts[k] = counts.get(k, 0) + 1
            return _Cursor([{"_id": {"state": s, "review_type": t}, "count": c} for (s, t), c in counts.items()])
        # reviews/router.py get_review_queue: $match, urgent-first, created_at.
        docs = [copy.deepcopy(d) for d in self.docs if _matches(d, first["$match"])]
        order = {"urgent": 0, "normal": 1}
        docs.sort(key=lambda d: (order.get(d.get("triage_priority"), 2), d.get("created_at")))
        return _Cursor(docs)


class _Db:
    def __init__(self, seed: dict[str, list[dict]]):
        self._cols = {name: _Collection(docs) for name, docs in seed.items()}

    def __getitem__(self, name: str) -> _Collection:
        return self._cols.setdefault(name, _Collection())


# ---------------------------------------------------------------------------
# Seed data: one deep-sea sample with every result class the pages render.
# ---------------------------------------------------------------------------

def _seq(sequence_id: str, route: str, result_class: str, *, length: int = 300, gc: float = 0.48,
         n_ratio: float = 0.0, confidence: float = 0.0, taxon: str | None = None,
         novelty: float = 0.1, novelty_level: str = "none", contamination: float = 0.0,
         contaminated: bool = False, contamination_type: str | None = None,
         model: str = "dnabert2_fish_v1", reasons: list[str] | None = None,
         recommendation: str = "continue_sampling", cloud: bool = False) -> dict:
    return {
        "sequence_id": sequence_id,
        "sequence": ("ACGTTGCA" * (length // 8 + 1))[:length],
        "route": route,
        "result_class": result_class,
        "length": length,
        "gc_ratio": gc,
        "n_ratio": n_ratio,
        "has_invalid_chars": False,
        "confidence": confidence,
        "predicted_taxon": taxon,
        "novelty_score": novelty,
        "novelty_level": novelty_level,
        "abyss_recommendation": recommendation,
        "requires_cloud_confirmation": cloud,
        "contamination_score": contamination,
        "contamination_flagged": contaminated,
        "contamination_type": contamination_type,
        "model_version_used": model,
        "reason_codes": reasons or [],
        "novelty_reason_codes": reasons or [],
        "contamination_reason_codes": reasons or [],
    }


RESULTS = [
    _seq("seq_e2e_tuna_001", "fish", "known_species", confidence=0.91, taxon="Thunnus albacares", gc=0.46),
    _seq("seq_e2e_lantern_002", "fish", "known_species", confidence=0.62, taxon="Myctophum punctatum", gc=0.44),
    _seq("seq_e2e_novel_003", "fish", "possible_novel_taxon", confidence=0.21, novelty=0.83,
         novelty_level="high", reasons=["low_reference_similarity"], recommendation="preserve_sample", cloud=True),
    _seq("seq_e2e_novel_004", "bacteria", "possible_novel_taxon", confidence=0.18, novelty=0.67,
         novelty_level="medium", model="dnabert2_bacteria_v1", reasons=["low_reference_similarity"],
         recommendation="return_for_full_analysis", cloud=True),
    _seq("seq_e2e_contam_005", "human_domestic", "possible_contaminant", confidence=0.88, taxon="Homo sapiens",
         contamination=0.94, contaminated=True, contamination_type="human", model="dnabert2_human_domestic_v1",
         reasons=["human_contaminant_match"]),
    _seq("seq_e2e_plant_006", "plant", "unknown_needs_online_confirmation", confidence=0.35, novelty=0.3,
         novelty_level="low", model="dnabert2_plant_v1"),
    _seq("seq_e2e_lowq_007", "low_quality", "low_quality_unusable", length=80, n_ratio=0.6, model="stub_none"),
]

UPLOAD = {
    "upload_id": UPLOAD_ID,
    "user_id": OWNER,
    "original_filename": "e2e_arabian_sea_station7.fasta",
    "file_size_bytes": 18_432,
    "status": "stored",
    "collected_at": _ts(9, 6, 30),
    "latitude": 15.52,
    "longitude": 68.21,
    "location_label": "Arabian Sea, Station 7",
    "depth_meters": 1850.0,
    "source_type": "seawater",
    "habitat": "bathypelagic",
    "temperature_celsius": 4.2,
    "methodology": "metabarcoding",
    "negative_control_included": False,
    "collector": "RV Sagar Nidhi crew",
    "created_at": _ts(10, 8),
}

ANALYSIS = {
    "analysis_id": ANALYSIS_ID,
    "job_id": JOB_DONE_ID,
    "upload_id": UPLOAD_ID,
    "user_id": OWNER,
    "mode": "online_full",
    "model_version_set": "dnabert2_v1_set",
    "results": RESULTS,
    "created_at": _ts(10, 8, 5),
}

REVIEWS = [
    {"review_id": "rev_e2e_novelty01", "analysis_id": ANALYSIS_ID, "sequence_id": "seq_e2e_novel_003",
     "submitted_by": "system", "state": "submitted", "review_type": "auto_novelty", "triage_priority": "urgent",
     "novelty_score": 0.83, "novelty_level": "high", "abyss_recommendation": "preserve_sample",
     "correction_type": "novelty_flag", "is_novelty": True, "created_at": _ts(10, 8, 6)},
    {"review_id": "rev_e2e_contam01", "analysis_id": ANALYSIS_ID, "sequence_id": "seq_e2e_contam_005",
     "submitted_by": "system", "state": "submitted", "review_type": "auto_contamination",
     "triage_priority": "normal", "contamination_score": 0.94, "correction_type": "contamination_flag",
     "is_contamination": True, "created_at": _ts(10, 8, 7)},
    {"review_id": "rev_e2e_correct01", "analysis_id": ANALYSIS_ID, "sequence_id": "seq_e2e_lantern_002",
     "submitted_by": OWNER, "state": "accepted", "review_type": "manual_correction", "triage_priority": "normal",
     "correction_type": "species_correction", "proposed_taxon": "Myctophum nitidulum",
     "evidence_notes": "Photophore pattern matches M. nitidulum.", "decided_by": USERS["curator"]["sub"],
     "decided_at": _ts(11, 14), "created_at": _ts(10, 12)},
]

FIELD_ENTRIES = [
    {"entry_id": "fle_e2e_note0001", "analysis_id": ANALYSIS_ID, "kind": "note", "author_id": OWNER,
     "author_name": "Rhea Researcher", "body": "CTD cast showed an oxygen minimum near 1,200 m.",
     "anchor_sequence_id": None, "reply_to": None, "created_at": _ts(10, 9), "updated_at": _ts(10, 10),
     "edits": [{"edit_id": "fle_edit_e2e0001", "editor_id": OWNER, "editor_name": "Rhea Researcher",
                "edited_at": _ts(10, 10), "changes": [{"field": "body", "old": "CTD cast showed low oxygen.",
                                                       "new": "CTD cast showed an oxygen minimum near 1,200 m."}]}]},
    {"entry_id": "fle_e2e_cmt00001", "analysis_id": ANALYSIS_ID, "kind": "comment",
     "author_id": USERS["curator"]["sub"], "author_name": "Cyrus Curator",
     "body": "seq_e2e_novel_003 looks worth a voucher specimen.", "anchor_sequence_id": "seq_e2e_novel_003",
     "reply_to": None, "created_at": _ts(11, 9), "updated_at": None, "edits": []},
    {"entry_id": "fle_e2e_cmt00002", "analysis_id": ANALYSIS_ID, "kind": "comment", "author_id": OWNER,
     "author_name": "Rhea Researcher", "body": "Agreed, sample preserved in ethanol.", "anchor_sequence_id": None,
     "reply_to": "fle_e2e_cmt00001", "created_at": _ts(11, 10), "updated_at": None, "edits": []},
    # Field-log tasks (Industrial page). Due dates far in the past / future so
    # "overdue" does not depend on the day the fixtures are generated.
    {"entry_id": "fle_e2e_task0001", "analysis_id": ANALYSIS_ID, "kind": "task", "author_id": OWNER,
     "author_name": "Rhea Researcher", "body": "Re-extract seq_e2e_contam_005 with a fresh negative control.",
     "anchor_sequence_id": None, "reply_to": None, "task_status": "open", "due_date": "2020-01-15",
     "assignee": "Wet lab", "created_at": _ts(11, 11), "updated_at": None, "edits": []},
    {"entry_id": "fle_e2e_task0002", "analysis_id": ANALYSIS_ID, "kind": "task", "author_id": OWNER,
     "author_name": "Rhea Researcher", "body": "Send voucher request for seq_e2e_novel_003.",
     "anchor_sequence_id": None, "reply_to": None, "task_status": "done", "due_date": None,
     "assignee": None, "created_at": _ts(11, 12), "updated_at": None, "edits": []},
]

# Partner audits (Industrial page).
AUDITS = [
    {"audit_id": "aud_e2e000000001", "target": {"kind": "analysis", "ref": ANALYSIS_ID, "label": "Station 7 run"},
     "scope": "Contamination controls for the Station 7 extraction batch",
     "findings": [{"severity": "high", "description": "No negative control included", "reference": None}],
     "status": "scheduled", "due_date": "2099-03-01", "completed_at": None, "created_by": OWNER,
     "created_by_name": "Rhea Researcher", "created_at": _ts(12, 9)},
]

ATTACHMENTS = [
    {"attachment_id": "fla_e2e_ctd00001", "analysis_id": ANALYSIS_ID, "entry_id": "fle_e2e_note0001",
     "uploader_id": OWNER, "uploader_name": "Rhea Researcher", "original_filename": "ctd_cast_station7.pdf",
     "content_type": "application/pdf", "size_bytes": 248_113,
     "checksum_sha256": "4f2c9a" + "0" * 58, "created_at": _ts(10, 9, 30),
     # Server-side only: list_attachments' response_model strips these.
     "storage_uri": "local://field-log/fla_e2e_ctd00001.pdf", "storage_key": "field-log/fla_e2e_ctd00001.pdf"},
]

JOBS = [
    {"job_id": JOB_RUNNING_ID, "upload_id": UPLOAD_ID, "user_id": OWNER, "state": "inferencing",
     "analysis_id": None, "error_message": None, "queued_at": _ts(16, 8), "started_at": _ts(16, 8, 1),
     "completed_at": None, "mode": "online_full"},
    {"job_id": JOB_DONE_ID, "upload_id": UPLOAD_ID, "user_id": OWNER, "state": "completed",
     "analysis_id": ANALYSIS_ID, "error_message": None, "queued_at": _ts(10, 8), "started_at": _ts(10, 8, 1),
     "completed_at": _ts(10, 8, 5), "mode": "online_full"},
]

EXPEDITIONS = [
    {"expedition_id": EXPEDITION_ID, "name": "Carlsberg Ridge Survey", "description": "Hydrothermal vent eDNA",
     "created_by": OWNER, "status": "pre_departure", "planned_start": _ts(20), "planned_end": _ts(30),
     "vessel": "RV Sagar Nidhi", "target_depth_meters": 3200.0, "location_label": "Carlsberg Ridge",
     "offline_license_issued": False, "offline_license_expires_at": None, "synced_at": None,
     "sync_job_count": 0, "created_at": _ts(12)},
]

AUDIT_LOGS = [
    {"action": "model_registered", "model_id": "dnabert2_fish_v1", "route": "fish",
     "registry_file": "dnabert2_fish_v1.json", "checksum": "sha256:e2e", "artifact_uri": "data:heads/fish.pt",
     "training_dataset_version": "tb_2026_09_fish", "metrics": {"test_accuracy": 0.81},
     "actor_id": USERS["admin"]["sub"], "actor_email": USERS["admin"]["email"], "actor_role": "admin",
     "timestamp": _ts(14, 11)},
]


# ---------------------------------------------------------------------------
# Academia page (t-1027-1): a second, older sample whose results carry
# orchestrator decisions (so species co-occurrence has pairs), its
# environmental context, and a third upload with no coordinates or date.
# ---------------------------------------------------------------------------

ANALYSIS_BAY_ID = "ana_e2e0000000002"
UPLOAD_BAY_ID = "upl_e2e0000000002"
UPLOAD_BARE_ID = "upl_e2e0000000003"
# Real provider responses recorded live on 2026-10-18 for 15.6 N, 82.3 E,
# 2026-10-01, surface (tests/fixtures/environment/record_fixtures.py); the
# upload below is placed at exactly that point so the context is its own.
ENV_RECORDING = API_DIR / "tests" / "fixtures" / "environment" / "bay_of_bengal" / "live_results.json"


def _decided(sequence_id: str, taxon: str | None, rank: str | None, **kw) -> dict:
    r = _seq(sequence_id, kw.pop("route", "fish"), kw.pop("result_class", "known_species"), taxon=taxon, **kw)
    r["decision"] = {
        "final_route": r["route"], "result_class": r["result_class"], "predicted_taxon": taxon,
        "taxon_rank": rank, "percent_identity": None, "reference_db": None, "reference_db_version": None,
        "confidence": r["confidence"], "rule": "e2e_fixture",
    }
    return r


UPLOAD_BAY = {
    "upload_id": UPLOAD_BAY_ID,
    "user_id": OWNER,
    "original_filename": "e2e_bay_of_bengal_vizag.fasta",
    "file_size_bytes": 9_216,
    "status": "stored",
    "collected_at": datetime(2026, 10, 1, 6, 0),
    "latitude": 15.6,
    "longitude": 82.3,
    "location_label": "Bay of Bengal, off Visakhapatnam",
    "source_type": "seawater",
    "methodology": "metabarcoding",
    "created_at": _ts(2, 11),
}

UPLOAD_BARE = {
    "upload_id": UPLOAD_BARE_ID,
    "user_id": OWNER,
    "original_filename": "e2e_no_metadata.fasta",
    "file_size_bytes": 4_096,
    "status": "stored",
    "created_at": _ts(12, 14, 20),
}

ANALYSIS_BAY = {
    "analysis_id": ANALYSIS_BAY_ID,
    "job_id": "job_e2e_bay00001",
    "upload_id": UPLOAD_BAY_ID,
    "user_id": OWNER,
    "mode": "online_full",
    "model_version_set": "orchestrator-1.2.0",
    "results": [
        _decided("seq_e2e_bay_001", "Sardinella longiceps", "species", confidence=0.93),
        _decided("seq_e2e_bay_002", "Sardinella longiceps", "species", confidence=0.9),
        _decided("seq_e2e_bay_003", "Rastrelliger kanagurta", "species", confidence=0.88),
        _decided("seq_e2e_bay_004", "Thunnus albacares", "species", confidence=0.86),
        _decided("seq_e2e_bay_005", "Stolephorus", "genus", confidence=0.7),
        _decided("seq_e2e_bay_006", "Homo sapiens", "species", route="human_domestic",
                 result_class="possible_contaminant", confidence=0.97, contamination=0.95, contaminated=True,
                 contamination_type="human", model="dnabert2_human_domestic_v1"),
    ],
    "created_at": _ts(2, 11, 6),
}


def _env_context_bay() -> dict:
    public = {k: v for k, v in json.loads(ENV_RECORDING.read_text(encoding="utf-8"))["surface"].items()
              if k != "transient"}
    ok = sum(1 for v in public.values() if v["status"] == "ok")
    return {
        "upload_id": UPLOAD_BAY_ID, "user_id": OWNER, "status": "complete" if ok == len(public) else "partial",
        "query": {"latitude": 15.6, "longitude": 82.3, "lookup_latitude": 15.6, "lookup_longitude": 82.3,
                  "collected_at": "2026-10-01T06:00:00+00:00", "date": "2026-10-01", "depth_m": None,
                  "target_level": "surface"},
        "cache_key": "v1:15.60:82.30:2026-10-01:surface", "cache_hit": False, "public": public,
        "requested_at": datetime(2026, 10, 18, 13, 4, 30), "retrieved_at": datetime(2026, 10, 18, 13, 4, 41),
    }


def _seed() -> dict[str, list[dict]]:
    return {
        "uploads": [UPLOAD, UPLOAD_BAY, UPLOAD_BARE],
        "analysis_results": [ANALYSIS, ANALYSIS_BAY],
        "environment_contexts": [_env_context_bay()],
        "reviews": REVIEWS,
        "field_log_entries": FIELD_ENTRIES,
        "field_log_attachments": ATTACHMENTS,
        "analysis_jobs": JOBS,
        "abyss_expeditions": EXPEDITIONS,
        "audit_logs": AUDIT_LOGS,
        "audits": AUDITS,
    }


# (fixture file, role, path) -- every GET the routed pages make.
CAPTURES: list[tuple[str, str, str]] = [
    ("health", "researcher", "/health"),
    ("auth_me_researcher", "researcher", "/auth/me"),
    ("auth_me_curator", "curator", "/auth/me"),
    ("auth_me_admin", "admin", "/auth/me"),
    ("reports_list", "researcher", "/reports?limit=1"),
    ("report", "researcher", f"/reports/{ANALYSIS_ID}"),
    ("report_summary", "researcher", f"/reports/{ANALYSIS_ID}/summary"),
    ("report_novelty", "researcher", f"/reports/{ANALYSIS_ID}/novelty"),
    ("report_contamination", "researcher", f"/reports/{ANALYSIS_ID}/contamination"),
    ("reviews_by_sequence", "researcher",
     f"/reviews/by-sequence?analysis_id={ANALYSIS_ID}&sequence_id=seq_e2e_lantern_002"),
    ("reviews_stats", "curator", "/reviews/stats"),
    ("reviews_queue_submitted", "curator", "/reviews/queue?state=submitted"),
    ("field_entries_note", "researcher", f"/field-log/entries?analysis_id={ANALYSIS_ID}&kind=note"),
    ("field_entries_comment", "researcher", f"/field-log/entries?analysis_id={ANALYSIS_ID}&kind=comment"),
    ("field_attachments", "researcher", f"/field-log/attachments?analysis_id={ANALYSIS_ID}"),
    ("job_running", "researcher", f"/analysis/jobs/{JOB_RUNNING_ID}"),
    ("job_completed", "researcher", f"/analysis/jobs/{JOB_DONE_ID}"),
    ("models_registry", "admin", "/models/registry"),
    ("models_promotions", "admin", "/models/promotions?limit=10"),
    ("abyss_expeditions", "researcher", "/abyss/expeditions"),
    # Academia page (t-1027-1)
    ("environment_context", "researcher", f"/environment/uploads/{UPLOAD_ID}"),
    ("environment_context_bay", "researcher", f"/environment/uploads/{UPLOAD_BAY_ID}"),
    ("environment_not_applicable", "researcher", f"/environment/uploads/{UPLOAD_BARE_ID}"),
    ("partner_summary", "researcher", "/partner/summary"),
    ("partner_cooccurrence", "researcher", "/partner/cooccurrence?rank=species&limit=50"),
    ("partner_cooccurrence_any", "researcher", "/partner/cooccurrence?rank=any&limit=50"),
    ("partner_rhythms", "researcher", "/partner/rhythms"),
    # Legislative page (t-1027-3)
    ("partner_hotspots", "researcher", "/partner/hotspots?cell_deg=1"),
    ("partner_alerts", "researcher", "/partner/alerts?limit=100"),
    ("partner_summary_week", "researcher", "/partner/summary?interval=week&top_taxa=1"),
    # Industrial page (t-1028-2)
    ("partner_incidents", "researcher", "/partner/incidents?scope=mine"),
    ("partner_tasks", "researcher", "/partner/tasks?scope=mine"),
    ("partner_audits", "researcher", f"/partner/audits?created_by={OWNER}"),
    # Last: it appends the derived custody events to the in-memory DB.
    ("report_custody", "researcher", f"/reports/{ANALYSIS_ID}/custody"),
]

# (fixture file, role, path, JSON body, expected status) -- POSTs whose error
# responses a page renders. Only requests the API refuses before touching the
# database, so the in-memory stand-in needs no write support.
POST_CAPTURES: list[tuple[str, str, str, dict, int]] = [
    # Industrial page audit form: blank label and scope, analysis target without ref.
    ("partner_audit_create_422", "researcher", "/partner/audits",
     {"target": {"kind": "analysis", "label": ""}, "scope": "", "status": "scheduled", "findings": []}, 422),
]


def _normalise(name: str, body: Any) -> Any:
    def walk(node):
        if isinstance(node, dict):
            return {k: (FIXED_TS if k in VOLATILE_KEYS else walk(v)) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    body = walk(body)
    if name.startswith("auth_me_"):
        body["created_at"] = FIXED_TS
    return body


async def generate() -> dict[str, Any]:
    """Return {fixture name: response JSON} from the real app."""
    tokens = {
        role: create_access_token(u["sub"], {"email": u["email"], "name": u["name"], "role": u["role"]})
        for role, u in USERS.items()
    }
    out: dict[str, Any] = {}
    # /health echoes settings (max_upload_size_mb); build the app from code
    # defaults so a developer's services/api/.env cannot make fixtures differ
    # between machines.
    defaults = Settings(_env_file=None)
    # GET /environment/uploads/{id} would schedule a live provider lookup for
    # an upload without a context doc; the recorder never goes online, so it
    # records the API's own "lookups disabled" answer instead.
    no_env_lookups = defaults.model_copy(update={"environment_context_enabled": False})
    with patch.object(mongo_module, "_db", _Db(_seed())), \
            patch.object(main_module, "get_settings", lambda: defaults), \
            patch("app.environment.router.get_settings", lambda: no_env_lookups), \
            patch.object(custody_chain, "_utc_now_iso", lambda: f"{FIXED_TS}+00:00"):
        transport = ASGITransport(app=create_app())
        async with AsyncClient(transport=transport, base_url="http://api.test") as client:
            for name, role, path in CAPTURES:
                resp = await client.get(path, headers={"Authorization": f"Bearer {tokens[role]}"})
                if resp.status_code != 200:
                    raise RuntimeError(f"{path} as {role}: HTTP {resp.status_code} {resp.text[:300]}")
                out[name] = _normalise(name, resp.json())
            for name, role, path, payload, expected in POST_CAPTURES:
                resp = await client.post(path, json=payload, headers={"Authorization": f"Bearer {tokens[role]}"})
                if resp.status_code != expected:
                    raise RuntimeError(f"POST {path} as {role}: HTTP {resp.status_code}, expected {expected}")
                out[name] = _normalise(name, resp.json())
    return out


def dumps(body: Any) -> str:
    return json.dumps(body, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> None:
    fixtures = asyncio.run(generate())
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, body in fixtures.items():
        (OUT_DIR / f"{name}.json").write_text(dumps(body), encoding="utf-8")
    print(f"wrote {len(fixtures)} fixtures to {OUT_DIR.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
