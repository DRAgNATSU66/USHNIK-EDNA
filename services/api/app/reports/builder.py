"""
Report builder — Phase 11.

Assembles an AnalysisReport from:
  - The raw analysis result document (MongoDB dict, stored by the worker)
  - The MongoDB reviews collection (queried by analysis_id)

The builder is a pure function — it takes dicts and returns a typed model.
No I/O is performed here; callers are responsible for fetching the docs.

Design note: the worker stores results as a flat list of raw sequence dicts
rather than typed SequenceResult objects, so this builder uses .get() throughout
and is tolerant of missing or extra keys.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from .models import (
    AnalysisReport,
    BiodiversitySummary,
    ContaminationWarning,
    KnownSpeciesEntry,
    ModelVersionEntry,
    PossibleNoveltyEntry,
    QCSummary,
    ReviewStatusSummary,
    RouteDistributionEntry,
    SampleMetadata,
    REPORT_DISCLAIMER,
)

# Threshold for flagging a sequence as possible novelty in the report.
_NOVELTY_THRESHOLD = 0.45
# Threshold for including a sequence in the contamination warnings section.
_CONTAMINATION_THRESHOLD = 0.50


def build_report(
    analysis_doc: dict[str, Any],
    reviews: list[dict[str, Any]],
    source_file: str | None = None,
) -> AnalysisReport:
    """
    Assemble a full AnalysisReport from a stored analysis document and its reviews.

    Args:
        analysis_doc: raw MongoDB document from the analysis_results collection.
        reviews: list of raw MongoDB review documents for this analysis_id.
        source_file: optional filename from the upload document.
    """
    results: list[dict] = analysis_doc.get("results", [])

    metadata = _build_metadata(analysis_doc, source_file)
    qc = _build_qc_summary(results)
    route_dist = _build_route_distribution(results)
    known = _build_known_species(results)
    novelty = _build_novelty_table(results)
    contamination = _build_contamination_warnings(results)
    biodiversity = _build_biodiversity(results)
    model_versions = _build_model_versions(results)
    review_status = _build_review_status(reviews)

    return AnalysisReport(
        metadata=metadata,
        qc_summary=qc,
        route_distribution=route_dist,
        known_species=known,
        possible_novelty=novelty,
        contamination_warnings=contamination,
        biodiversity=biodiversity,
        model_versions_used=model_versions,
        review_status=review_status,
    )


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

def _build_metadata(doc: dict, source_file: str | None) -> SampleMetadata:
    created_at = doc.get("created_at")
    if isinstance(created_at, str):
        created_at = datetime.fromisoformat(created_at)
    elif created_at is None:
        created_at = datetime.now(timezone.utc)

    return SampleMetadata(
        analysis_id=doc.get("analysis_id", "unknown"),
        job_id=doc.get("job_id", "unknown"),
        upload_id=doc.get("upload_id", "unknown"),
        user_id=doc.get("user_id"),
        mode=doc.get("mode", "online_full"),
        source_file=source_file,
        created_at=created_at,
        model_version_set=doc.get("model_version_set"),
    )


def _build_qc_summary(results: list[dict]) -> QCSummary:
    total = len(results)
    if total == 0:
        return QCSummary(
            total_sequences=0, passed_qc=0, failed_qc=0, low_quality_count=0,
            mean_length=0.0, mean_gc_ratio=0.0, mean_n_ratio=0.0,
            has_invalid_chars_count=0,
        )

    low_quality = [r for r in results if r.get("route") == "low_quality"
                   or r.get("result_class") == "low_quality_unusable"]
    high_n = [r for r in results if r.get("n_ratio", 0.0) >= 0.50]
    invalid = [r for r in results if r.get("has_invalid_chars")]

    failed_qc = len({r.get("sequence_id") for r in low_quality + high_n + invalid})
    passed_qc = total - len(low_quality)

    lengths = [r.get("length", 0) for r in results]
    gc_ratios = [r.get("gc_ratio", 0.0) for r in results]
    n_ratios = [r.get("n_ratio", 0.0) for r in results]

    return QCSummary(
        total_sequences=total,
        passed_qc=passed_qc,
        failed_qc=failed_qc,
        low_quality_count=len(low_quality),
        mean_length=round(sum(lengths) / total, 1),
        mean_gc_ratio=round(sum(gc_ratios) / total, 4),
        mean_n_ratio=round(sum(n_ratios) / total, 4),
        has_invalid_chars_count=len(invalid),
    )


def _build_route_distribution(results: list[dict]) -> list[RouteDistributionEntry]:
    total = len(results)
    counts: dict[str, int] = {}
    for r in results:
        route = r.get("route", "misc_unknown")
        counts[route] = counts.get(route, 0) + 1

    entries = [
        RouteDistributionEntry(
            route=route,
            count=count,
            fraction=round(count / total, 4) if total > 0 else 0.0,
        )
        for route, count in sorted(counts.items(), key=lambda x: -x[1])
    ]
    return entries


def _build_known_species(results: list[dict]) -> list[KnownSpeciesEntry]:
    entries = []
    for r in results:
        if r.get("result_class") == "known_species":
            entries.append(KnownSpeciesEntry(
                sequence_id=r.get("sequence_id", "unknown"),
                predicted_taxon=r.get("predicted_taxon"),
                route=r.get("route", "misc_unknown"),
                confidence=round(float(r.get("confidence", 0.0)), 4),
                model_version_used=r.get("model_version_used"),
                reason_codes=r.get("reason_codes", []),
            ))
    return entries


def _build_novelty_table(results: list[dict]) -> list[PossibleNoveltyEntry]:
    entries = []
    for r in results:
        score = float(r.get("novelty_score", 0.0))
        if score >= _NOVELTY_THRESHOLD:
            entries.append(PossibleNoveltyEntry(
                sequence_id=r.get("sequence_id", "unknown"),
                route=r.get("route", "misc_unknown"),
                novelty_score=round(score, 4),
                novelty_level=r.get("novelty_level", "low"),
                abyss_recommendation=r.get("abyss_recommendation", "continue_sampling"),
                requires_cloud_confirmation=bool(r.get("requires_cloud_confirmation", True)),
                reason_codes=r.get("novelty_reason_codes", r.get("reason_codes", [])),
                contamination_score=round(float(r.get("contamination_score", 0.0)), 4),
            ))
    # Sort: highest novelty first
    return sorted(entries, key=lambda e: -e.novelty_score)


def _build_contamination_warnings(results: list[dict]) -> list[ContaminationWarning]:
    entries = []
    for r in results:
        if r.get("contamination_flagged") or float(r.get("contamination_score", 0.0)) >= _CONTAMINATION_THRESHOLD:
            entries.append(ContaminationWarning(
                sequence_id=r.get("sequence_id", "unknown"),
                contamination_type=r.get("contamination_type"),
                contamination_score=round(float(r.get("contamination_score", 0.0)), 4),
                route=r.get("route", "misc_unknown"),
                reason_codes=r.get("contamination_reason_codes", r.get("reason_codes", [])),
            ))
    return sorted(entries, key=lambda e: -e.contamination_score)


def _build_biodiversity(results: list[dict]) -> BiodiversitySummary:
    total = len(results)
    if total == 0:
        return BiodiversitySummary(
            total_sequences=0, route_richness=0, predicted_taxon_richness=0,
            shannon_diversity_index=0.0, dominant_route=None,
            novelty_fraction=0.0, contamination_fraction=0.0,
        )

    # Exclude low-quality from biodiversity metrics
    usable = [r for r in results if r.get("route") != "low_quality"
              and r.get("result_class") != "low_quality_unusable"]

    route_counts: dict[str, int] = {}
    taxa: set[str] = set()
    for r in usable:
        route = r.get("route", "misc_unknown")
        route_counts[route] = route_counts.get(route, 0) + 1
        taxon = r.get("predicted_taxon")
        if taxon:
            taxa.add(taxon)

    # Shannon diversity over route groups (proxy for taxonomic diversity)
    n = len(usable)
    shannon = 0.0
    if n > 0:
        for count in route_counts.values():
            p = count / n
            if p > 0:
                shannon -= p * math.log(p)

    dominant = max(route_counts, key=route_counts.get) if route_counts else None

    novelty_count = sum(1 for r in results if float(r.get("novelty_score", 0.0)) >= _NOVELTY_THRESHOLD)
    contamination_count = sum(1 for r in results if r.get("contamination_flagged"))

    return BiodiversitySummary(
        total_sequences=total,
        route_richness=len(route_counts),
        predicted_taxon_richness=len(taxa),
        shannon_diversity_index=round(shannon, 4),
        dominant_route=dominant,
        novelty_fraction=round(novelty_count / total, 4) if total > 0 else 0.0,
        contamination_fraction=round(contamination_count / total, 4) if total > 0 else 0.0,
    )


def _build_model_versions(results: list[dict]) -> list[ModelVersionEntry]:
    # Aggregate: (model_version_used, route) → count
    version_route_counts: dict[tuple[str, str], int] = {}
    for r in results:
        version = r.get("model_version_used") or "stub_none"
        route = r.get("route", "misc_unknown")
        key = (version, route)
        version_route_counts[key] = version_route_counts.get(key, 0) + 1

    return [
        ModelVersionEntry(
            model_version_used=version,
            route=route,
            sequence_count=count,
        )
        for (version, route), count in sorted(
            version_route_counts.items(), key=lambda x: -x[1]
        )
    ]


def _build_review_status(reviews: list[dict]) -> ReviewStatusSummary:
    state_counts: dict[str, int] = {}
    auto_novelty = 0
    auto_contamination = 0

    for rev in reviews:
        state = rev.get("state", "submitted")
        state_counts[state] = state_counts.get(state, 0) + 1
        if rev.get("review_type") == "auto_novelty":
            auto_novelty += 1
        elif rev.get("review_type") == "auto_contamination":
            auto_contamination += 1

    return ReviewStatusSummary(
        total_reviews=len(reviews),
        submitted=state_counts.get("submitted", 0),
        triaged=state_counts.get("triaged", 0),
        needs_evidence=state_counts.get("needs_evidence", 0),
        accepted=state_counts.get("accepted", 0),
        rejected=state_counts.get("rejected", 0),
        duplicate=state_counts.get("duplicate", 0),
        company_verified=state_counts.get("company_verified", 0),
        included_in_training_batch=state_counts.get("included_in_training_batch", 0),
        auto_novelty_reviews=auto_novelty,
        auto_contamination_reviews=auto_contamination,
    )
