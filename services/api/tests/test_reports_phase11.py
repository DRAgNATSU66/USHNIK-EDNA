"""
Phase 11 tests — Backend Reports and Export.

Covers:
  1. Report model fields and defaults
  2. builder.py section builders — pure functions, no I/O
  3. BiodiversitySummary Shannon index
  4. API endpoints: /reports/{id}, /summary, /novelty, /contamination, /export/json
"""
from __future__ import annotations

import json
import math
import sys
import os
import pytest
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.reports.models import (
    AnalysisReport,
    QCSummary,
    BiodiversitySummary,
    REPORT_DISCLAIMER,
)
from app.reports.builder import (
    build_report,
    _build_qc_summary,
    _build_route_distribution,
    _build_known_species,
    _build_novelty_table,
    _build_contamination_warnings,
    _build_biodiversity,
    _build_model_versions,
    _build_review_status,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seq(
    sequence_id: str = "seq_001",
    route: str = "fish",
    result_class: str = "unknown_needs_online_confirmation",
    length: int = 300,
    gc_ratio: float = 0.50,
    n_ratio: float = 0.01,
    has_invalid_chars: bool = False,
    confidence: float = 0.55,
    predicted_taxon: str | None = None,
    novelty_score: float = 0.10,
    novelty_level: str = "none",
    contamination_score: float = 0.0,
    contamination_flagged: bool = False,
    contamination_type: str | None = None,
    model_version_used: str = "stub_none",
    reason_codes: list | None = None,
    abyss_recommendation: str = "continue_sampling",
    requires_cloud_confirmation: bool = False,
) -> dict:
    return {
        "sequence_id": sequence_id,
        "sequence": "ATCG" * (length // 4),
        "route": route,
        "result_class": result_class,
        "length": length,
        "gc_ratio": gc_ratio,
        "n_ratio": n_ratio,
        "has_invalid_chars": has_invalid_chars,
        "confidence": confidence,
        "predicted_taxon": predicted_taxon,
        "novelty_score": novelty_score,
        "novelty_level": novelty_level,
        "abyss_recommendation": abyss_recommendation,
        "requires_cloud_confirmation": requires_cloud_confirmation,
        "contamination_score": contamination_score,
        "contamination_flagged": contamination_flagged,
        "contamination_type": contamination_type,
        "model_version_used": model_version_used,
        "reason_codes": reason_codes or [],
        "novelty_reason_codes": reason_codes or [],
        "contamination_reason_codes": reason_codes or [],
    }


def _analysis_doc(results: list[dict] | None = None) -> dict:
    return {
        "analysis_id": "ana_test001",
        "job_id": "job_test001",
        "upload_id": "upl_test001",
        "user_id": "usr_test001",
        "mode": "online_full",
        "model_version_set": "stub_none",
        "results": results or [],
        "created_at": datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
    }


def _review(state: str = "submitted", review_type: str = "auto_novelty") -> dict:
    return {
        "review_id": "rev_001",
        "analysis_id": "ana_test001",
        "sequence_id": "seq_001",
        "state": state,
        "review_type": review_type,
    }


# ---------------------------------------------------------------------------
# QC summary
# ---------------------------------------------------------------------------

class TestQCSummary:
    def test_empty_results(self):
        qc = _build_qc_summary([])
        assert qc.total_sequences == 0
        assert qc.mean_length == 0.0

    def test_counts_low_quality(self):
        results = [
            _seq("s1", route="low_quality", result_class="low_quality_unusable"),
            _seq("s2", route="fish"),
        ]
        qc = _build_qc_summary(results)
        assert qc.total_sequences == 2
        assert qc.low_quality_count == 1
        assert qc.passed_qc == 1

    def test_mean_length(self):
        results = [_seq("s1", length=100), _seq("s2", length=300)]
        qc = _build_qc_summary(results)
        assert qc.mean_length == 200.0

    def test_mean_gc_ratio(self):
        results = [_seq("s1", gc_ratio=0.40), _seq("s2", gc_ratio=0.60)]
        qc = _build_qc_summary(results)
        assert qc.mean_gc_ratio == pytest.approx(0.50, abs=0.001)

    def test_invalid_chars_counted(self):
        results = [_seq("s1", has_invalid_chars=True), _seq("s2")]
        qc = _build_qc_summary(results)
        assert qc.has_invalid_chars_count == 1


# ---------------------------------------------------------------------------
# Route distribution
# ---------------------------------------------------------------------------

class TestRouteDistribution:
    def test_single_route(self):
        results = [_seq("s1", route="fish"), _seq("s2", route="fish")]
        dist = _build_route_distribution(results)
        assert len(dist) == 1
        assert dist[0].route == "fish"
        assert dist[0].count == 2
        assert dist[0].fraction == 1.0

    def test_multiple_routes_sorted_descending(self):
        results = [
            _seq("s1", route="fish"), _seq("s2", route="fish"),
            _seq("s3", route="plant"),
        ]
        dist = _build_route_distribution(results)
        assert dist[0].route == "fish"
        assert dist[0].count == 2
        assert dist[1].route == "plant"

    def test_fractions_sum_to_one(self):
        results = [_seq(f"s{i}", route=["fish", "plant", "bacteria_pathogen"][i % 3]) for i in range(9)]
        dist = _build_route_distribution(results)
        assert sum(e.fraction for e in dist) == pytest.approx(1.0, abs=0.001)


# ---------------------------------------------------------------------------
# Known species
# ---------------------------------------------------------------------------

class TestKnownSpecies:
    def test_only_known_species_included(self):
        results = [
            _seq("s1", result_class="known_species", predicted_taxon="Gadus morhua"),
            _seq("s2", result_class="possible_novelty"),
            _seq("s3", result_class="unknown_needs_online_confirmation"),
        ]
        known = _build_known_species(results)
        assert len(known) == 1
        assert known[0].predicted_taxon == "Gadus morhua"

    def test_empty_when_no_known_species(self):
        results = [_seq("s1", result_class="possible_novelty")]
        assert _build_known_species(results) == []


# ---------------------------------------------------------------------------
# Novelty table
# ---------------------------------------------------------------------------

class TestNoveltyTable:
    def test_threshold_045_included(self):
        results = [
            _seq("s1", novelty_score=0.45),
            _seq("s2", novelty_score=0.44),
        ]
        table = _build_novelty_table(results)
        assert len(table) == 1
        assert table[0].sequence_id == "s1"

    def test_sorted_highest_first(self):
        results = [
            _seq("s1", novelty_score=0.50),
            _seq("s2", novelty_score=0.80),
            _seq("s3", novelty_score=0.60),
        ]
        table = _build_novelty_table(results)
        scores = [e.novelty_score for e in table]
        assert scores == sorted(scores, reverse=True)

    def test_empty_when_no_novelty(self):
        results = [_seq("s1", novelty_score=0.10)]
        assert _build_novelty_table(results) == []


# ---------------------------------------------------------------------------
# Contamination warnings
# ---------------------------------------------------------------------------

class TestContaminationWarnings:
    def test_flagged_sequences_included(self):
        results = [
            _seq("s1", contamination_flagged=True, contamination_score=0.85,
                 contamination_type="lab_reagent"),
            _seq("s2", contamination_flagged=False, contamination_score=0.10),
        ]
        warnings = _build_contamination_warnings(results)
        assert len(warnings) == 1
        assert warnings[0].sequence_id == "s1"
        assert warnings[0].contamination_type == "lab_reagent"

    def test_high_score_without_flag_included(self):
        results = [_seq("s1", contamination_score=0.55)]
        warnings = _build_contamination_warnings(results)
        assert len(warnings) == 1

    def test_sorted_highest_score_first(self):
        results = [
            _seq("s1", contamination_flagged=True, contamination_score=0.70),
            _seq("s2", contamination_flagged=True, contamination_score=0.90),
        ]
        warnings = _build_contamination_warnings(results)
        assert warnings[0].contamination_score > warnings[1].contamination_score


# ---------------------------------------------------------------------------
# Biodiversity
# ---------------------------------------------------------------------------

class TestBiodiversity:
    def test_empty_results(self):
        bio = _build_biodiversity([])
        assert bio.total_sequences == 0
        assert bio.shannon_diversity_index == 0.0

    def test_single_route_shannon_zero(self):
        results = [_seq(f"s{i}", route="fish") for i in range(5)]
        bio = _build_biodiversity(results)
        assert bio.shannon_diversity_index == pytest.approx(0.0, abs=0.001)

    def test_two_equal_routes_shannon(self):
        # Two equally split routes → H = -2*(0.5*ln(0.5)) = ln(2) ≈ 0.693
        results = (
            [_seq(f"s{i}", route="fish") for i in range(5)]
            + [_seq(f"p{i}", route="plant") for i in range(5)]
        )
        bio = _build_biodiversity(results)
        assert bio.shannon_diversity_index == pytest.approx(math.log(2), abs=0.01)

    def test_dominant_route(self):
        results = [_seq("s1", route="fish")] * 3 + [_seq("s2", route="plant")]
        bio = _build_biodiversity(results)
        assert bio.dominant_route == "fish"

    def test_low_quality_excluded_from_richness(self):
        results = [
            _seq("s1", route="fish"),
            _seq("s2", route="low_quality", result_class="low_quality_unusable"),
        ]
        bio = _build_biodiversity(results)
        assert bio.route_richness == 1  # only fish counted

    def test_novelty_fraction(self):
        results = [
            _seq("s1", novelty_score=0.55),
            _seq("s2", novelty_score=0.10),
            _seq("s3", novelty_score=0.70),
            _seq("s4", novelty_score=0.10),
        ]
        bio = _build_biodiversity(results)
        assert bio.novelty_fraction == pytest.approx(0.5, abs=0.01)


# ---------------------------------------------------------------------------
# Model versions
# ---------------------------------------------------------------------------

class TestModelVersions:
    def test_aggregates_by_version_and_route(self):
        results = [
            _seq("s1", model_version_used="dnabert2_fish_v1", route="fish"),
            _seq("s2", model_version_used="dnabert2_fish_v1", route="fish"),
            _seq("s3", model_version_used="stub_none", route="misc_unknown"),
        ]
        versions = _build_model_versions(results)
        fish_entry = next(v for v in versions if v.route == "fish")
        assert fish_entry.sequence_count == 2
        assert fish_entry.model_version_used == "dnabert2_fish_v1"

    def test_none_version_defaults_to_stub_none(self):
        results = [_seq("s1", model_version_used=None)]
        versions = _build_model_versions(results)
        assert versions[0].model_version_used == "stub_none"


# ---------------------------------------------------------------------------
# Review status
# ---------------------------------------------------------------------------

class TestReviewStatus:
    def test_empty_reviews(self):
        status = _build_review_status([])
        assert status.total_reviews == 0
        assert status.submitted == 0

    def test_counts_states(self):
        reviews = [
            _review(state="submitted", review_type="auto_novelty"),
            _review(state="accepted", review_type="manual_correction"),
            _review(state="submitted", review_type="auto_contamination"),
        ]
        status = _build_review_status(reviews)
        assert status.total_reviews == 3
        assert status.submitted == 2
        assert status.accepted == 1
        assert status.auto_novelty_reviews == 1
        assert status.auto_contamination_reviews == 1


# ---------------------------------------------------------------------------
# Full build_report integration
# ---------------------------------------------------------------------------

class TestBuildReport:
    def test_build_full_report(self):
        results = [
            _seq("s1", route="fish", result_class="known_species",
                 predicted_taxon="Gadus morhua", confidence=0.90),
            _seq("s2", novelty_score=0.65, novelty_level="medium",
                 abyss_recommendation="preserve_sample", requires_cloud_confirmation=True),
            _seq("s3", contamination_flagged=True, contamination_score=0.85,
                 contamination_type="lab_reagent", route="human_domestic_contamination"),
        ]
        doc = _analysis_doc(results)
        reviews = [_review("submitted", "auto_novelty")]
        report = build_report(doc, reviews, source_file="sample.fasta")

        assert report.metadata.analysis_id == "ana_test001"
        assert report.metadata.source_file == "sample.fasta"
        assert report.qc_summary.total_sequences == 3
        assert len(report.known_species) == 1
        assert report.known_species[0].predicted_taxon == "Gadus morhua"
        assert len(report.possible_novelty) == 1
        assert report.possible_novelty[0].novelty_score == 0.65
        assert len(report.contamination_warnings) == 1
        assert report.contamination_warnings[0].contamination_type == "lab_reagent"
        assert report.review_status.total_reviews == 1
        assert report.review_status.auto_novelty_reviews == 1
        assert "field-triage" not in report.disclaimer  # not Abyss disclaimer
        assert "preliminary" in report.disclaimer

    def test_report_has_all_sections(self):
        report = build_report(_analysis_doc(), [], None)
        assert hasattr(report, "metadata")
        assert hasattr(report, "qc_summary")
        assert hasattr(report, "route_distribution")
        assert hasattr(report, "known_species")
        assert hasattr(report, "possible_novelty")
        assert hasattr(report, "contamination_warnings")
        assert hasattr(report, "biodiversity")
        assert hasattr(report, "model_versions_used")
        assert hasattr(report, "review_status")
        assert hasattr(report, "disclaimer")

    def test_report_model_dump_serializable(self):
        results = [_seq("s1"), _seq("s2", novelty_score=0.50)]
        report = build_report(_analysis_doc(results), [], None)
        dumped = report.model_dump()
        # Should be JSON-serializable (with datetime default)
        json_str = json.dumps(dumped, default=str)
        parsed = json.loads(json_str)
        assert parsed["metadata"]["analysis_id"] == "ana_test001"


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_report_requires_auth(client):
    resp = await client.get("/reports/ana_001")
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_report_not_found(client, researcher_token):
    resp = await client.get(
        "/reports/ana_nonexistent",
        headers={"Authorization": f"Bearer {researcher_token}"},
    )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_report_summary_requires_auth(client):
    resp = await client.get("/reports/ana_001/summary")
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_report_novelty_requires_auth(client):
    resp = await client.get("/reports/ana_001/novelty")
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_report_contamination_requires_auth(client):
    resp = await client.get("/reports/ana_001/contamination")
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_report_export_json_requires_auth(client):
    resp = await client.get("/reports/ana_001/export/json")
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_report_summary_not_found(client, researcher_token):
    resp = await client.get(
        "/reports/ana_nonexistent/summary",
        headers={"Authorization": f"Bearer {researcher_token}"},
    )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_report_novelty_not_found(client, researcher_token):
    resp = await client.get(
        "/reports/ana_nonexistent/novelty",
        headers={"Authorization": f"Bearer {researcher_token}"},
    )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_analysis_report_endpoint_delegates_to_builder(client, researcher_token):
    """GET /analysis/{id}/report now delegates to the Phase 11 report builder."""
    resp = await client.get(
        "/analysis/ana_nonexistent/report",
        headers={"Authorization": f"Bearer {researcher_token}"},
    )
    assert resp.status_code == 404
