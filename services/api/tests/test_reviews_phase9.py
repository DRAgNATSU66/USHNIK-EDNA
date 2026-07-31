"""
Phase 9 tests — Human-in-the-loop review workflow.

Covers:
  1. ReviewDoc model extensions (review_type, triage_priority, novelty_score, etc.)
  2. Worker auto-queue helper (_build_auto_reviews) — pure function, no I/O
  3. Curation service functions (queue_stats, triage_review, add_evidence,
     create_monthly_training_batch, freeze_training_batch) — with async mock DB
  4. New API endpoints: /reviews/stats, /{id}/triage, /{id}/evidence,
     /batch/create, /batch/{id}/freeze
"""
from __future__ import annotations

import sys
import os
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.models.review import (
    ReviewDoc, ReviewState, ReviewDecision, ReviewType, TriagePriority,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_async_cursor(items: list):
    """Create a mock async cursor over a list of dicts."""
    class _Cursor:
        def __init__(self, data):
            self._data = list(data)

        def __aiter__(self):
            return self

        async def __anext__(self):
            if self._data:
                return self._data.pop(0)
            raise StopAsyncIteration

    return _Cursor(items)


def _make_mock_db(
    reviews: list[dict] | None = None,
    find_one_result: dict | None = None,
):
    """Create a mock Motor database for curation service tests."""

    class _Collection:
        def __init__(self, docs: list[dict]):
            self._docs = list(docs)
            self.inserted = []
            self.updated = []

        async def find_one(self, query):
            return find_one_result

        def find(self, query=None):
            return _make_async_cursor(list(self._docs))

        def aggregate(self, pipeline):
            return _make_async_cursor([])

        async def insert_one(self, doc):
            self.inserted.append(doc)
            return MagicMock(inserted_id="mock_id")

        async def insert_many(self, docs):
            self.inserted.extend(docs)

        async def update_one(self, query, update):
            self.updated.append((query, update))
            return MagicMock(matched_count=1)

        async def update_many(self, query, update):
            self.updated.append((query, update))
            return MagicMock(matched_count=len(self._docs))

    class _Db:
        def __init__(self):
            self._reviews = _Collection(reviews or [])
            self._logs = _Collection([])

        def __getitem__(self, name):
            if name == "reviews":
                return self._reviews
            if name == "audit_logs":
                return self._logs
            return _Collection([])

    return _Db()


def _seq_result(
    sequence_id: str = "seq_001",
    novelty_score: float = 0.0,
    contamination_flagged: bool = False,
    contamination_score: float = 0.0,
    novelty_level: str = "none",
    contamination_type: str | None = None,
) -> dict:
    return {
        "sequence_id": sequence_id,
        "novelty_score": novelty_score,
        "contamination_flagged": contamination_flagged,
        "contamination_score": contamination_score,
        "novelty_level": novelty_level,
        "contamination_type": contamination_type,
        "abyss_recommendation": "continue_sampling",
        "result_class": "unknown_needs_online_confirmation",
    }


# ---------------------------------------------------------------------------
# ReviewDoc model tests
# ---------------------------------------------------------------------------

class TestReviewDocPhase9:
    def test_default_review_type_is_manual_correction(self):
        r = ReviewDoc(
            analysis_id="ana_1", sequence_id="seq_1",
            submitted_by="usr_1", correction_type="species_correction",
        )
        assert r.review_type == ReviewType.manual_correction

    def test_default_priority_is_normal(self):
        r = ReviewDoc(
            analysis_id="ana_1", sequence_id="seq_1",
            submitted_by="usr_1", correction_type="novelty_flag",
        )
        assert r.triage_priority == TriagePriority.normal

    def test_auto_novelty_review_type(self):
        r = ReviewDoc(
            analysis_id="ana_1", sequence_id="seq_1",
            submitted_by="system", correction_type="auto_novelty_flag",
            review_type=ReviewType.auto_novelty,
            novelty_score=0.55,
            triage_priority=TriagePriority.normal,
        )
        assert r.review_type == ReviewType.auto_novelty
        assert r.novelty_score == 0.55

    def test_all_new_optional_fields_default_none(self):
        r = ReviewDoc(
            analysis_id="ana_1", sequence_id="seq_1",
            submitted_by="usr_1", correction_type="correction",
        )
        assert r.novelty_score is None
        assert r.contamination_score is None
        assert r.novelty_level is None
        assert r.abyss_recommendation is None
        assert r.triaged_by is None
        assert r.triaged_at is None
        assert r.training_batch_id is None
        assert r.evidence_attachments == []

    def test_review_type_enum_values(self):
        assert ReviewType.auto_novelty == "auto_novelty"
        assert ReviewType.auto_contamination == "auto_contamination"
        assert ReviewType.manual_correction == "manual_correction"

    def test_triage_priority_enum_values(self):
        assert TriagePriority.urgent == "urgent"
        assert TriagePriority.normal == "normal"
        assert TriagePriority.low == "low"


# ---------------------------------------------------------------------------
# Worker auto-queue helper (_build_auto_reviews)
# ---------------------------------------------------------------------------

# Note: _build_auto_reviews (worker helper) is tested in
# services/worker/tests/test_job_runner.py to avoid cross-service import conflicts.


# ---------------------------------------------------------------------------
# Curation service tests
# ---------------------------------------------------------------------------

class TestQueueStats:
    @pytest.mark.anyio
    async def test_empty_db_returns_zeros(self):
        from app.reviews.curation import queue_stats

        class _EmptyDb:
            def __getitem__(self, name):
                coll = MagicMock()
                coll.aggregate = MagicMock(return_value=_make_async_cursor([]))
                return coll

        stats = await queue_stats(_EmptyDb())
        assert stats["total_pending"] == 0
        assert stats["auto_novelty_pending"] == 0
        assert stats["auto_contamination_pending"] == 0

    @pytest.mark.anyio
    async def test_counts_novelty_pending(self):
        from app.reviews.curation import queue_stats

        agg_docs = [
            {"_id": {"state": "submitted", "review_type": "auto_novelty"}, "count": 3},
            {"_id": {"state": "triaged", "review_type": "auto_contamination"}, "count": 2},
            {"_id": {"state": "accepted", "review_type": "manual_correction"}, "count": 10},
        ]

        class _Db:
            def __getitem__(self, name):
                coll = MagicMock()
                coll.aggregate = MagicMock(return_value=_make_async_cursor(agg_docs))
                return coll

        stats = await queue_stats(_Db())
        assert stats["total_pending"] == 5  # submitted + triaged only
        assert stats["auto_novelty_pending"] == 3
        assert stats["auto_contamination_pending"] == 2
        assert stats["by_state"]["submitted"] == 3
        assert stats["by_state"]["accepted"] == 10


class TestTriageReview:
    @pytest.mark.anyio
    async def test_review_not_found_returns_none(self):
        from app.reviews.curation import triage_review
        db = _make_mock_db(find_one_result=None)
        result = await triage_review(db, "rev_missing", TriagePriority.normal, "usr_cur")
        assert result is None

    @pytest.mark.anyio
    async def test_triage_updates_state_and_priority(self):
        from app.reviews.curation import triage_review

        existing = {
            "review_id": "rev_001",
            "analysis_id": "ana_001",
            "sequence_id": "seq_001",
            "submitted_by": "system",
            "state": "submitted",
            "review_type": "auto_novelty",
            "triage_priority": "normal",
            "correction_type": "auto_novelty_flag",
        }
        db = _make_mock_db(find_one_result=existing)

        with patch("app.reviews.curation.SupabaseClient.update_review_state", new_callable=AsyncMock):
            result = await triage_review(db, "rev_001", TriagePriority.urgent, "usr_curator")

        assert result is not None
        assert result.state == ReviewState.triaged
        assert result.triage_priority == TriagePriority.urgent
        assert result.triaged_by == "usr_curator"

    @pytest.mark.anyio
    async def test_triage_supabase_failure_does_not_raise(self):
        from app.reviews.curation import triage_review

        existing = {
            "review_id": "rev_001",
            "analysis_id": "ana_001",
            "sequence_id": "seq_001",
            "submitted_by": "system",
            "state": "submitted",
            "review_type": "auto_novelty",
            "triage_priority": "normal",
            "correction_type": "auto_novelty_flag",
        }
        db = _make_mock_db(find_one_result=existing)

        with patch(
            "app.reviews.curation.SupabaseClient.update_review_state",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Supabase down"),
        ):
            result = await triage_review(db, "rev_001", TriagePriority.urgent, "usr_curator")

        assert result is not None  # still succeeds


class TestAddEvidence:
    @pytest.mark.anyio
    async def test_evidence_added_returns_updated_doc(self):
        from app.reviews.curation import add_evidence

        existing = {
            "review_id": "rev_001",
            "analysis_id": "ana_001",
            "sequence_id": "seq_001",
            "submitted_by": "usr_1",
            "state": "needs_evidence",
            "review_type": "manual_correction",
            "triage_priority": "normal",
            "correction_type": "species_correction",
            "evidence_attachments": [],
        }
        updated = {**existing, "evidence_notes": "Here is my evidence", "state": "submitted"}

        # The collection must be the same object across all __getitem__ calls
        # so side_effect state is shared between the two find_one calls.
        coll = MagicMock()
        coll.find_one = AsyncMock(side_effect=[existing, updated])
        coll.update_one = AsyncMock()

        class _Db:
            def __getitem__(self, name):
                return coll

        result = await add_evidence(_Db(), "rev_001", "Here is my evidence", [], "usr_1")
        assert result is not None
        assert result.evidence_notes == "Here is my evidence"
        assert result.state == ReviewState.submitted  # re-queued after needs_evidence

    @pytest.mark.anyio
    async def test_evidence_on_closed_review_returns_none(self):
        from app.reviews.curation import add_evidence

        closed = {
            "review_id": "rev_closed",
            "analysis_id": "ana_001",
            "sequence_id": "seq_001",
            "submitted_by": "usr_1",
            "state": "accepted",
            "review_type": "manual_correction",
            "triage_priority": "normal",
            "correction_type": "correction",
        }
        db = _make_mock_db(find_one_result=closed)
        result = await add_evidence(db, "rev_closed", "extra evidence", [], "usr_1")
        assert result is None

    @pytest.mark.anyio
    async def test_evidence_not_found_returns_none(self):
        from app.reviews.curation import add_evidence
        db = _make_mock_db(find_one_result=None)
        result = await add_evidence(db, "rev_missing", "evidence", [], "usr_1")
        assert result is None


class TestCreateMonthlyBatch:
    @pytest.mark.anyio
    async def test_empty_accepted_reviews_returns_empty_status(self):
        from app.reviews.curation import create_monthly_training_batch

        class _Db:
            def __getitem__(self, name):
                coll = MagicMock()
                coll.find = MagicMock(return_value=_make_async_cursor([]))
                coll.update_many = AsyncMock()
                coll.insert_one = AsyncMock()
                return coll

        with patch("app.reviews.curation.SupabaseClient.get_or_create_training_batch", new_callable=AsyncMock):
            result = await create_monthly_training_batch(_Db(), "fish", "2026-05", "usr_admin")

        assert result["sequence_count"] == 0
        assert result["status"] == "empty"

    @pytest.mark.anyio
    async def test_batch_includes_accepted_reviews(self):
        from app.reviews.curation import create_monthly_training_batch

        accepted_reviews = [
            {
                "review_id": "rev_001",
                "analysis_id": "ana_001",
                "sequence_id": "seq_001",
                "state": "accepted",
                "correction_type": "fish_novelty",
                "proposed_taxon": "Gadus morhua",
                "is_novelty": True,
                "novelty_score": 0.72,
                "decided_by": "usr_curator",
            },
            {
                "review_id": "rev_002",
                "analysis_id": "ana_001",
                "sequence_id": "seq_002",
                "state": "accepted",
                "correction_type": "fish_novelty",
                "is_novelty": True,
                "novelty_score": 0.68,
                "decided_by": "usr_curator",
            },
        ]

        inserted_logs = []

        class _Db:
            def __getitem__(self, name):
                coll = MagicMock()
                if name == "reviews":
                    coll.find = MagicMock(return_value=_make_async_cursor(accepted_reviews))
                    coll.update_many = AsyncMock()
                elif name == "audit_logs":
                    async def _insert_one(doc):
                        inserted_logs.append(doc)
                    coll.insert_one = _insert_one
                else:
                    coll.find = MagicMock(return_value=_make_async_cursor([]))
                    coll.update_many = AsyncMock()
                    coll.insert_one = AsyncMock()
                return coll

        with patch("app.reviews.curation.SupabaseClient.get_or_create_training_batch", new_callable=AsyncMock), \
             patch("app.reviews.curation.SupabaseClient.insert_curated_sequence", new_callable=AsyncMock):
            result = await create_monthly_training_batch(_Db(), "fish", "2026-05", "usr_admin")

        assert result["sequence_count"] == 2
        assert result["route"] == "fish"
        assert result["month_year"] == "2026-05"
        assert result["batch_id"].startswith("tbatch_")

        # Audit log should have been written
        assert len(inserted_logs) == 1
        assert inserted_logs[0]["action"] == "training_batch_created"
        assert inserted_logs[0]["sequence_count"] == 2

    @pytest.mark.anyio
    async def test_supabase_failure_falls_back_to_local_only(self):
        from app.reviews.curation import create_monthly_training_batch

        accepted = [{
            "review_id": "rev_001",
            "analysis_id": "ana_001",
            "sequence_id": "seq_001",
            "state": "accepted",
            "correction_type": "fish",
            "is_novelty": True,
            "novelty_score": 0.55,
            "decided_by": "usr_curator",
        }]

        class _Db:
            def __getitem__(self, name):
                coll = MagicMock()
                coll.find = MagicMock(return_value=_make_async_cursor(accepted))
                coll.update_many = AsyncMock()
                coll.insert_one = AsyncMock()
                return coll

        with patch(
            "app.reviews.curation.SupabaseClient.get_or_create_training_batch",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Supabase down"),
        ):
            result = await create_monthly_training_batch(_Db(), "fish", "2026-05", "usr_admin")

        assert result["sequence_count"] == 1
        assert "local_only" in result["status"]


class TestFreezeBatch:
    @pytest.mark.anyio
    async def test_freeze_writes_audit_log(self):
        from app.reviews.curation import freeze_training_batch

        inserted_logs = []

        class _Db:
            def __getitem__(self, name):
                coll = MagicMock()
                async def _insert_one(doc):
                    inserted_logs.append(doc)
                coll.insert_one = _insert_one
                return coll

        with patch("app.reviews.curation.SupabaseClient.freeze_training_batch", new_callable=AsyncMock):
            result = await freeze_training_batch(_Db(), "tbatch_202605_fish_abc123", "usr_admin")

        assert result["status"] == "frozen"
        assert result["batch_id"] == "tbatch_202605_fish_abc123"
        assert result["frozen_by"] == "usr_admin"
        assert len(inserted_logs) == 1
        assert inserted_logs[0]["action"] == "training_batch_frozen"

    @pytest.mark.anyio
    async def test_freeze_supabase_failure_does_not_raise(self):
        from app.reviews.curation import freeze_training_batch

        class _Db:
            def __getitem__(self, name):
                coll = MagicMock()
                coll.insert_one = AsyncMock()
                return coll

        with patch(
            "app.reviews.curation.SupabaseClient.freeze_training_batch",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Supabase down"),
        ):
            result = await freeze_training_batch(_Db(), "tbatch_001", "usr_admin")

        assert result["status"] == "frozen"


# ---------------------------------------------------------------------------
# Router endpoint tests (via HTTPX client)
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_stats_endpoint_requires_curator(client, researcher_token):
    resp = await client.get(
        "/reviews/stats",
        headers={"Authorization": f"Bearer {researcher_token}"},
    )
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_stats_endpoint_accessible_by_curator(client, curator_token):
    resp = await client.get(
        "/reviews/stats",
        headers={"Authorization": f"Bearer {curator_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "total_pending" in data
    assert "auto_novelty_pending" in data
    assert "auto_contamination_pending" in data


@pytest.mark.anyio
async def test_triage_endpoint_requires_curator(client, researcher_token):
    resp = await client.post(
        "/reviews/rev_001/triage",
        json={"priority": "urgent"},
        headers={"Authorization": f"Bearer {researcher_token}"},
    )
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_triage_endpoint_not_found(client, curator_token):
    # Default mock returns None for find_one
    resp = await client.post(
        "/reviews/rev_nonexistent/triage",
        json={"priority": "urgent"},
        headers={"Authorization": f"Bearer {curator_token}"},
    )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_get_review_unauthenticated(client):
    resp = await client.get("/reviews/rev_001")
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_evidence_endpoint_not_found(client, curator_token):
    resp = await client.post(
        "/reviews/rev_missing/evidence",
        json={"evidence_text": "My evidence"},
        headers={"Authorization": f"Bearer {curator_token}"},
    )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_batch_create_requires_admin(client, curator_token):
    resp = await client.post(
        "/reviews/batch/create",
        json={"route": "fish", "month_year": "2026-05"},
        headers={"Authorization": f"Bearer {curator_token}"},
    )
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_batch_create_accessible_by_admin(client, admin_token):
    resp = await client.post(
        "/reviews/batch/create",
        json={"route": "fish", "month_year": "2026-05"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "batch_id" in data
    assert "sequence_count" in data


@pytest.mark.anyio
async def test_batch_freeze_requires_admin(client, curator_token):
    resp = await client.post(
        "/reviews/batch/tbatch_001/freeze",
        headers={"Authorization": f"Bearer {curator_token}"},
    )
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_batch_freeze_accessible_by_admin(client, admin_token):
    with patch("app.reviews.curation.SupabaseClient.freeze_training_batch", new_callable=AsyncMock):
        resp = await client.post(
            "/reviews/batch/tbatch_test_001/freeze",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "frozen"
    assert data["batch_id"] == "tbatch_test_001"


@pytest.mark.anyio
async def test_review_queue_filterable_by_review_type(client, curator_token):
    resp = await client.get(
        "/reviews/queue?review_type=auto_novelty",
        headers={"Authorization": f"Bearer {curator_token}"},
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.anyio
async def test_submit_review_with_new_fields(client, researcher_token):
    resp = await client.post(
        "/reviews",
        json={
            "analysis_id": "ana_001",
            "sequence_id": "seq_001",
            "correction_type": "novelty_flag",
            "review_type": "manual_novelty",
            "is_novelty": True,
            "evidence_notes": "Novel species suspected",
        },
        headers={"Authorization": f"Bearer {researcher_token}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["review_type"] == "manual_novelty"
    assert data["is_novelty"] is True
