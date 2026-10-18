"""
Day 5 metadata contract (ROADMAP_REAL_DATA.md F5, F6, F7; decisions.md
2026-10-14 Q2 + Q4):

  - POST /uploads accepts and validates the optional sample metadata, and an
    upload with only a file still works.
  - Every result/report carries a `context` block: optional fields provided
    vs missing, partner-report readiness (date + coordinates), and the
    negative-control flag.
  - FieldLog's existing read paths (GET /reports/{id} metadata,
    GET /uploads/{id}) return the real values.
  - OPTIONAL_METADATA_FIELDS is the single source of truth for the list.
"""
from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone
from io import BytesIO
from unittest.mock import patch

import pytest

import app.db.mongo as _mongo_module
from app.config import get_settings
from app.models.upload import (
    OPTIONAL_METADATA_FIELDS,
    PARTNER_REPORT_REQUIRED_FIELDS,
    UploadDoc,
)
from app.reports.builder import build_report
from app.reports.models import SampleMetadata
from app.reports.router import _report_summary
from app.uploads.context import (
    NEGATIVE_CONTROL_NOT_RECORDED_MESSAGE,
    NO_NEGATIVE_CONTROL_MESSAGE,
    build_metadata_context,
)
from app.uploads.router import create_upload

SAMPLE_FASTA = b">seq_001\nATCGATCGATCGATCGATCG\n"

FULL_FORM = {
    "collected_at": "2026-08-12T06:40:00+05:30",
    "latitude": "-18.432",
    "longitude": "73.211",
    "location_label": "Indian Ocean, Site 7",
    "depth_meters": "2500",
    "source_type": "seawater",
    "habitat": "hydrothermal_vent",
    "salinity_ppt": "35.2",
    "temperature_celsius": "4.5",
    "dissolved_oxygen_mg_l": "6.8",
    "ph": "8.1",
    "methodology": "Metabarcoding",
    "negative_control_included": "true",
    "collector": "A. Researcher",
}

FULL_UPLOAD_DOC = {
    "upload_id": "upl_full",
    "user_id": "usr_test_001",
    "original_filename": "stn7.fasta",
    "file_size_bytes": 10,
    "status": "stored",
    "collected_at": datetime(2026, 8, 12, 1, 10, tzinfo=timezone.utc),
    "latitude": -18.432,
    "longitude": 73.211,
    "location_label": "Indian Ocean, Site 7",
    "depth_meters": 2500.0,
    "source_type": "seawater",
    "habitat": "hydrothermal_vent",
    "salinity_ppt": 35.2,
    "temperature_celsius": 4.5,
    "dissolved_oxygen_mg_l": 6.8,
    "ph": 8.1,
    "methodology": "Metabarcoding",
    "negative_control_included": True,
    "collector": "A. Researcher",
}


# ---------------------------------------------------------------------------
# Minimal in-memory Mongo stand-in (the shared conftest mock returns a fresh
# empty collection per access, so it can neither persist nor seed docs).
# ---------------------------------------------------------------------------

class _Cursor:
    def __init__(self, items):
        self._items = list(items)

    def sort(self, *a, **k):
        return self

    def limit(self, n):
        return self

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._items:
            return self._items.pop(0)
        raise StopAsyncIteration


class _Collection:
    def __init__(self):
        self.docs: list[dict] = []

    @staticmethod
    def _match(doc, query):
        return all(doc.get(k) == v for k, v in query.items())

    async def find_one(self, query):
        for d in self.docs:
            if self._match(d, query):
                return dict(d)
        return None

    async def insert_one(self, doc):
        self.docs.append(dict(doc))

    def find(self, query=None):
        return _Cursor(dict(d) for d in self.docs if self._match(d, query or {}))


class _FakeDb:
    def __init__(self):
        self.collections: dict[str, _Collection] = {}

    def __getitem__(self, name):
        return self.collections.setdefault(name, _Collection())


@pytest.fixture
def fake_db():
    db = _FakeDb()
    with patch.object(_mongo_module, "_db", db):
        yield db


@pytest.fixture
def tmp_upload_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "upload_storage_dir", str(tmp_path))
    return tmp_path


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


async def _post_upload(client, token, data=None):
    return await client.post(
        "/uploads",
        files={"file": ("sample.fasta", BytesIO(SAMPLE_FASTA), "text/plain")},
        data=data or {},
        headers=_auth(token),
    )


def _analysis_doc(upload_id="upl_full", user_id="usr_test_001"):
    return {
        "analysis_id": "ana_ctx001",
        "job_id": "job_ctx001",
        "upload_id": upload_id,
        "user_id": user_id,
        "mode": "online_full",
        "model_version_set": "stub_none",
        "results": [],
        "created_at": datetime(2026, 10, 18, tzinfo=timezone.utc),
    }


# ---------------------------------------------------------------------------
# Single source of truth
# ---------------------------------------------------------------------------

class TestSingleSourceOfTruth:
    def test_upload_doc_has_every_optional_field(self):
        assert set(OPTIONAL_METADATA_FIELDS) <= set(UploadDoc.model_fields)

    def test_post_uploads_accepts_exactly_the_optional_fields(self):
        params = set(inspect.signature(create_upload).parameters) - {
            "current_user", "file", "background_tasks",  # background_tasks: Q5 env lookup
        }
        assert params == set(OPTIONAL_METADATA_FIELDS)

    def test_report_metadata_carries_every_optional_field(self):
        assert set(OPTIONAL_METADATA_FIELDS) <= set(SampleMetadata.model_fields)

    def test_partner_required_fields_are_optional_fields(self):
        assert set(PARTNER_REPORT_REQUIRED_FIELDS) <= set(OPTIONAL_METADATA_FIELDS)

    def test_context_lists_every_optional_field_once(self):
        ctx = build_metadata_context({})
        assert ctx.provided + ctx.missing == list(OPTIONAL_METADATA_FIELDS)
        assert ctx.labels == OPTIONAL_METADATA_FIELDS


# ---------------------------------------------------------------------------
# POST /uploads
# ---------------------------------------------------------------------------

class TestUploadEndpoint:
    @pytest.mark.anyio
    async def test_file_only_upload_still_works(self, client, researcher_token, fake_db, tmp_upload_dir):
        resp = await _post_upload(client, researcher_token)
        assert resp.status_code == 201
        data = resp.json()
        for field in OPTIONAL_METADATA_FIELDS:
            assert data[field] is None, field
        stored = fake_db["uploads"].docs[0]
        assert all(stored[f] is None for f in OPTIONAL_METADATA_FIELDS)

    @pytest.mark.anyio
    async def test_all_fields_are_returned_and_persisted(self, client, researcher_token, fake_db, tmp_upload_dir):
        resp = await _post_upload(client, researcher_token, FULL_FORM)
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["ph"] == 8.1
        assert data["dissolved_oxygen_mg_l"] == 6.8
        assert data["methodology"] == "Metabarcoding"
        assert data["collector"] == "A. Researcher"
        assert data["negative_control_included"] is True
        assert datetime.fromisoformat(data["collected_at"]) == datetime(
            2026, 8, 12, 1, 10, tzinfo=timezone.utc
        )

        stored = fake_db["uploads"].docs[0]
        for field in OPTIONAL_METADATA_FIELDS:
            assert stored[field] is not None, field
        assert stored["negative_control_included"] is True
        assert isinstance(stored["collected_at"], datetime)

    @pytest.mark.anyio
    async def test_negative_control_false_is_kept_as_false(self, client, researcher_token, fake_db, tmp_upload_dir):
        resp = await _post_upload(client, researcher_token, {"negative_control_included": "false"})
        assert resp.status_code == 201
        assert resp.json()["negative_control_included"] is False

    @pytest.mark.anyio
    async def test_blank_text_means_not_provided(self, client, researcher_token, fake_db, tmp_upload_dir):
        resp = await _post_upload(
            client, researcher_token,
            {"methodology": "   ", "collector": "", "habitat": " "},
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["methodology"] is None
        assert data["collector"] is None
        assert data["habitat"] is None

    @pytest.mark.anyio
    async def test_empty_number_or_date_is_rejected_not_guessed(self, client, researcher_token, fake_db, tmp_upload_dir):
        """Clients omit a number/date they don't have; "" is a 422 (same as
        depth_meters before Day 5), never silently read as 0 or "now"."""
        resp = await _post_upload(client, researcher_token, {"ph": "", "collected_at": ""})
        assert resp.status_code == 422

    @pytest.mark.anyio
    @pytest.mark.parametrize("form", [
        {"ph": "14.5"},
        {"ph": "-0.1"},
        {"ph": "acidic"},
        {"dissolved_oxygen_mg_l": "-1"},
        {"latitude": "91", "longitude": "0"},
        {"latitude": "0", "longitude": "-181"},
        {"latitude": "10"},
        {"longitude": "10"},
        {"collected_at": "yesterday"},
        {"negative_control_included": "maybe"},
        {"depth_meters": "-5"},
    ])
    async def test_rejects_implausible_values(self, client, researcher_token, fake_db, tmp_upload_dir, form):
        resp = await _post_upload(client, researcher_token, form)
        assert resp.status_code == 422, (form, resp.text)
        assert fake_db["uploads"].docs == []

    @pytest.mark.anyio
    async def test_rejects_collection_date_in_the_future(self, client, researcher_token, fake_db, tmp_upload_dir):
        future = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
        resp = await _post_upload(client, researcher_token, {"collected_at": future})
        assert resp.status_code == 422
        assert "future" in resp.text

    @pytest.mark.anyio
    async def test_accepts_boundary_values(self, client, researcher_token, fake_db, tmp_upload_dir):
        resp = await _post_upload(
            client, researcher_token,
            {"ph": "0", "dissolved_oxygen_mg_l": "0", "latitude": "-90", "longitude": "180"},
        )
        assert resp.status_code == 201, resp.text


# ---------------------------------------------------------------------------
# Context block (pure)
# ---------------------------------------------------------------------------

class TestMetadataContext:
    def test_file_only_upload(self):
        ctx = build_metadata_context({"upload_id": "upl_x", "original_filename": "a.fasta"})
        assert ctx.upload_found is True
        assert ctx.provided == []
        assert ctx.missing == list(OPTIONAL_METADATA_FIELDS)
        assert ctx.partner_report.available is False
        assert ctx.partner_report.missing_required == ["collected_at", "latitude", "longitude"]
        assert ctx.negative_control == "not_recorded"
        codes = [f.code for f in ctx.flags]
        assert codes == ["partner_report_unavailable", "no_negative_control"]
        assert f"0 of {len(OPTIONAL_METADATA_FIELDS)} optional context fields" in ctx.accuracy_note
        assert "can reduce accuracy" in ctx.accuracy_note
        assert "Partner report not available" in ctx.accuracy_note
        assert NEGATIVE_CONTROL_NOT_RECORDED_MESSAGE in ctx.accuracy_note

    def test_full_upload(self):
        ctx = build_metadata_context(FULL_UPLOAD_DOC)
        assert ctx.missing == []
        assert ctx.provided == list(OPTIONAL_METADATA_FIELDS)
        assert ctx.partner_report.available is True
        assert ctx.partner_report.reason is None
        assert ctx.negative_control == "included"
        assert ctx.flags == []
        assert ctx.accuracy_note == f"All {len(OPTIONAL_METADATA_FIELDS)} optional context fields were provided."

    def test_date_and_coordinates_alone_unlock_partner_report(self):
        ctx = build_metadata_context({
            "collected_at": datetime(2026, 8, 12), "latitude": 0.0, "longitude": 0.0,
        })
        # 0.0 is a real coordinate, not "missing".
        assert ctx.partner_report.available is True
        assert ctx.negative_control == "not_recorded"
        assert [f.code for f in ctx.flags] == ["no_negative_control"]

    def test_half_coordinates_block_partner_report(self):
        ctx = build_metadata_context({"collected_at": datetime(2026, 8, 12), "latitude": 10.0})
        assert ctx.partner_report.available is False
        assert ctx.partner_report.missing_required == ["longitude"]
        assert "longitude" in ctx.partner_report.reason

    def test_negative_control_false_is_provided_but_flagged(self):
        ctx = build_metadata_context({"negative_control_included": False})
        assert "negative_control_included" in ctx.provided
        assert ctx.negative_control == "not_included"
        flag = next(f for f in ctx.flags if f.code == "no_negative_control")
        assert flag.message == NO_NEGATIVE_CONTROL_MESSAGE
        assert "contamination not ruled out" in flag.message

    def test_blank_string_is_missing(self):
        ctx = build_metadata_context({"methodology": "  ", "collector": "M. F."})
        assert "methodology" in ctx.missing
        assert "collector" in ctx.provided

    def test_missing_upload_doc(self):
        ctx = build_metadata_context(None)
        assert ctx.upload_found is False
        assert ctx.flags[0].code == "upload_not_found"
        assert ctx.partner_report.available is False


# ---------------------------------------------------------------------------
# Report builder + endpoints (where the frontend reads it)
# ---------------------------------------------------------------------------

class TestReportCarriesContext:
    def test_builder_copies_metadata_and_builds_context(self):
        report = build_report(_analysis_doc(), [], upload=FULL_UPLOAD_DOC)
        assert report.metadata.source_file == "stn7.fasta"
        assert report.metadata.methodology == "Metabarcoding"
        assert report.metadata.negative_control_included is True
        assert report.metadata.collector == "A. Researcher"
        assert report.metadata.ph == 8.1
        assert report.context is not None
        assert report.context.partner_report.available is True

    def test_builder_with_missing_upload_states_it(self):
        report = build_report(_analysis_doc(), [], upload=None)
        assert report.context.upload_found is False
        assert report.metadata.negative_control_included is None

    def test_legacy_call_without_upload_has_no_context(self):
        report = build_report(_analysis_doc(), [], "x.fasta", "Bay", 10.0)
        assert report.context is None
        assert report.metadata.location_label == "Bay"

    def test_report_list_row_flags_partner_readiness(self):
        assert _report_summary(_analysis_doc(), FULL_UPLOAD_DOC)["partner_report_available"] is True
        assert _report_summary(_analysis_doc(), {"original_filename": "a"})["partner_report_available"] is False
        assert _report_summary(_analysis_doc(), None)["partner_report_available"] is False

    @pytest.mark.anyio
    async def test_get_report_returns_context_and_metadata(self, client, researcher_token, fake_db):
        fake_db["uploads"].docs.append(FULL_UPLOAD_DOC)
        fake_db["analysis_results"].docs.append(_analysis_doc())
        resp = await client.get("/reports/ana_ctx001", headers=_auth(researcher_token))
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["context"]["partner_report"]["available"] is True
        assert body["context"]["missing"] == []
        meta = body["metadata"]
        assert meta["negative_control_included"] is True
        assert meta["methodology"] == "Metabarcoding"
        assert meta["collector"] == "A. Researcher"
        assert meta["collected_at"].startswith("2026-08-12T01:10:00")

    @pytest.mark.anyio
    async def test_get_report_file_only_upload_flags_gaps(self, client, researcher_token, fake_db):
        fake_db["uploads"].docs.append({
            "upload_id": "upl_bare", "user_id": "usr_test_001",
            "original_filename": "bare.fasta", "file_size_bytes": 1, "status": "stored",
        })
        fake_db["analysis_results"].docs.append(_analysis_doc(upload_id="upl_bare"))
        resp = await client.get("/reports/ana_ctx001", headers=_auth(researcher_token))
        assert resp.status_code == 200
        ctx = resp.json()["context"]
        assert ctx["partner_report"]["available"] is False
        assert ctx["negative_control"] == "not_recorded"
        assert {f["code"] for f in ctx["flags"]} == {"partner_report_unavailable", "no_negative_control"}

    @pytest.mark.anyio
    async def test_summary_endpoint_includes_context(self, client, researcher_token, fake_db):
        fake_db["uploads"].docs.append(FULL_UPLOAD_DOC)
        fake_db["analysis_results"].docs.append(_analysis_doc())
        resp = await client.get("/reports/ana_ctx001/summary", headers=_auth(researcher_token))
        assert resp.status_code == 200
        assert resp.json()["context"]["negative_control"] == "included"

    @pytest.mark.anyio
    async def test_get_analysis_includes_context(self, client, researcher_token, fake_db):
        fake_db["uploads"].docs.append({**FULL_UPLOAD_DOC, "negative_control_included": None})
        fake_db["analysis_results"].docs.append(_analysis_doc())
        resp = await client.get("/analysis/ana_ctx001", headers=_auth(researcher_token))
        assert resp.status_code == 200, resp.text
        ctx = resp.json()["context"]
        assert ctx["missing"] == ["negative_control_included"]
        assert ctx["partner_report"]["available"] is True

    @pytest.mark.anyio
    async def test_curator_reads_metadata_via_report(self, client, curator_token, fake_db):
        """FieldLog lets curators in; GET /uploads/{id} does not, so the
        report's metadata block is the read path that works for every role."""
        fake_db["uploads"].docs.append(FULL_UPLOAD_DOC)
        fake_db["analysis_results"].docs.append(_analysis_doc())
        resp = await client.get("/reports/ana_ctx001", headers=_auth(curator_token))
        assert resp.status_code == 200
        assert resp.json()["metadata"]["collector"] == "A. Researcher"

    @pytest.mark.anyio
    async def test_get_upload_returns_new_fields(self, client, researcher_token, fake_db):
        fake_db["uploads"].docs.append(FULL_UPLOAD_DOC)
        resp = await client.get("/uploads/upl_full", headers=_auth(researcher_token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["methodology"] == "Metabarcoding"
        assert data["negative_control_included"] is True
        assert data["dissolved_oxygen_mg_l"] == 6.8
