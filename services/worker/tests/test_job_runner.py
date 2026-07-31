"""
Tests for Phase 9 worker auto-queue helper in job_runner._build_auto_reviews.

The function is pure (no I/O) so these are straightforward unit tests.
"""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.job_runner import _build_auto_reviews


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seq(
    sequence_id: str = "seq_001",
    novelty_score: float = 0.0,
    contamination_flagged: bool = False,
    contamination_score: float = 0.0,
    novelty_level: str = "none",
    contamination_type: str | None = None,
    abyss_recommendation: str = "continue_sampling",
) -> dict:
    return {
        "sequence_id": sequence_id,
        "novelty_score": novelty_score,
        "contamination_flagged": contamination_flagged,
        "contamination_score": contamination_score,
        "novelty_level": novelty_level,
        "contamination_type": contamination_type,
        "abyss_recommendation": abyss_recommendation,
        "result_class": "unknown_needs_online_confirmation",
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestBuildAutoReviews:
    def test_no_flags_returns_empty(self):
        results = [_seq(novelty_score=0.10, contamination_flagged=False)]
        reviews = _build_auto_reviews("ana_001", "job_001", results)
        assert reviews == []

    def test_empty_results_returns_empty(self):
        assert _build_auto_reviews("ana_001", "job_001", []) == []

    def test_novelty_flag_creates_auto_novelty_review(self):
        results = [_seq(sequence_id="s1", novelty_score=0.55)]
        reviews = _build_auto_reviews("ana_001", "job_001", results)
        assert len(reviews) == 1
        r = reviews[0]
        assert r["review_type"] == "auto_novelty"
        assert r["sequence_id"] == "s1"
        assert r["analysis_id"] == "ana_001"
        assert r["submitted_by"] == "system"
        assert r["state"] == "submitted"
        assert r["novelty_score"] == 0.55
        assert r["is_novelty"] is True

    def test_high_novelty_gets_urgent_priority(self):
        results = [_seq(novelty_score=0.70)]
        reviews = _build_auto_reviews("ana_001", "job_001", results)
        assert reviews[0]["triage_priority"] == "urgent"

    def test_novelty_just_above_threshold_gets_normal_priority(self):
        results = [_seq(novelty_score=0.50)]
        reviews = _build_auto_reviews("ana_001", "job_001", results)
        assert reviews[0]["triage_priority"] == "normal"

    def test_exact_threshold_045_triggers(self):
        results = [_seq(novelty_score=0.45)]
        reviews = _build_auto_reviews("ana_001", "job_001", results)
        assert len(reviews) == 1
        assert reviews[0]["review_type"] == "auto_novelty"

    def test_below_threshold_no_trigger(self):
        # 0.449 rounds below 0.45 — should not trigger
        results = [_seq(novelty_score=0.449)]
        reviews = _build_auto_reviews("ana_001", "job_001", results)
        assert reviews == []

    def test_contamination_flag_creates_auto_contamination_review(self):
        results = [_seq(contamination_flagged=True, contamination_score=0.85)]
        reviews = _build_auto_reviews("ana_001", "job_001", results)
        assert len(reviews) == 1
        r = reviews[0]
        assert r["review_type"] == "auto_contamination"
        assert r["triage_priority"] == "urgent"
        assert r["contamination_score"] == 0.85
        assert r["is_contamination"] is True

    def test_both_flags_creates_two_reviews(self):
        results = [_seq(novelty_score=0.55, contamination_flagged=True, contamination_score=0.7)]
        reviews = _build_auto_reviews("ana_001", "job_001", results)
        assert len(reviews) == 2
        types = {r["review_type"] for r in reviews}
        assert types == {"auto_novelty", "auto_contamination"}

    def test_multiple_sequences_mixed_flags(self):
        results = [
            _seq(sequence_id="s1", novelty_score=0.60),
            _seq(sequence_id="s2", contamination_flagged=True),
            _seq(sequence_id="s3", novelty_score=0.10),  # below threshold
        ]
        reviews = _build_auto_reviews("ana_001", "job_001", results)
        assert len(reviews) == 2
        seq_ids = [r["sequence_id"] for r in reviews]
        assert "s1" in seq_ids
        assert "s2" in seq_ids
        assert "s3" not in seq_ids

    def test_review_ids_are_unique(self):
        results = [
            _seq(sequence_id=f"s{i}", novelty_score=0.50) for i in range(5)
        ]
        reviews = _build_auto_reviews("ana_001", "job_001", results)
        ids = [r["review_id"] for r in reviews]
        assert len(ids) == len(set(ids)), "review_ids must be unique"

    def test_review_id_format(self):
        results = [_seq(novelty_score=0.50)]
        reviews = _build_auto_reviews("ana_001", "job_001", results)
        assert reviews[0]["review_id"].startswith("rev_")

    def test_contamination_type_propagated(self):
        results = [_seq(contamination_flagged=True, contamination_type="lab_reagent")]
        reviews = _build_auto_reviews("ana_001", "job_001", results)
        assert reviews[0]["contamination_type"] == "lab_reagent"

    def test_abyss_recommendation_propagated(self):
        results = [_seq(novelty_score=0.55, abyss_recommendation="preserve_sample")]
        reviews = _build_auto_reviews("ana_001", "job_001", results)
        assert reviews[0]["abyss_recommendation"] == "preserve_sample"

    def test_novelty_level_propagated(self):
        results = [_seq(novelty_score=0.55, novelty_level="medium")]
        reviews = _build_auto_reviews("ana_001", "job_001", results)
        assert reviews[0]["novelty_level"] == "medium"

    def test_evidence_attachments_empty_by_default(self):
        results = [_seq(novelty_score=0.50)]
        reviews = _build_auto_reviews("ana_001", "job_001", results)
        assert reviews[0]["evidence_attachments"] == []

    def test_training_batch_id_none_by_default(self):
        results = [_seq(novelty_score=0.50)]
        reviews = _build_auto_reviews("ana_001", "job_001", results)
        assert reviews[0]["training_batch_id"] is None

    def test_contamination_also_sets_novelty_flag_when_above_threshold(self):
        results = [_seq(novelty_score=0.55, contamination_flagged=True)]
        reviews = _build_auto_reviews("ana_001", "job_001", results)
        cont_review = next(r for r in reviews if r["review_type"] == "auto_contamination")
        assert cont_review["is_novelty"] is True

    def test_contamination_sets_is_novelty_false_when_below_threshold(self):
        results = [_seq(novelty_score=0.10, contamination_flagged=True)]
        reviews = _build_auto_reviews("ana_001", "job_001", results)
        assert len(reviews) == 1
        assert reviews[0]["is_novelty"] is False
