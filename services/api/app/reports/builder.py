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

import csv
import io
import math
from datetime import datetime, timezone
from typing import Any

from ..config import NOVELTY_THRESHOLD
from ..models.analysis import resolve_taxon_fields
from .models import (
    AnalysisReport,
    BiodiversitySummary,
    ContaminationFlaggedTaxon,
    ContaminationWarning,
    KnownSpeciesEntry,
    ModelVersionEntry,
    PossibleNoveltyEntry,
    QCSummary,
    RankRichness,
    ReferenceDbUsage,
    ReviewStatusSummary,
    RouteDistributionEntry,
    SampleMetadata,
    TaxaSummary,
    TaxonomicAssignmentEntry,
    TopTaxonEntry,
    REPORT_DISCLAIMER,
)
from ..models.upload import OPTIONAL_METADATA_FIELDS
from ..uploads.context import MetadataContext, build_metadata_context

# Threshold for including a sequence in the contamination warnings section.
_CONTAMINATION_THRESHOLD = 0.50
# Species Correction confidence tiers (SYNTHVEDA_BUILD_SPEC.md 2.3:
# "Amber/Red = <80% confidence or contaminant flag"). Spec doesn't split
# amber vs red explicitly; red additionally requires either a contamination
# flag or a confidence low enough to be effectively unclassified.
_TIER_GREEN_MIN = 0.80
_TIER_RED_MAX = 0.50
# Rows in TaxaSummary.top_taxa; per-sequence calls are in taxonomic_assignments.
TOP_TAXA_LIMIT = 20
_LOW_QUALITY_ROUTE = "low_quality"
# Display order of TaxaSummary.richness_by_rank, finest first (the ranks the
# worker's reference lineages use, orchestrator/combiner.py _genus_of). Any
# other rank sorts after these by name, "unranked" last.
_RANK_ORDER = ("species", "genus", "family", "order", "class", "phylum", "kingdom", "superkingdom")


def _rank_order(rank: str) -> int:
    if rank in _RANK_ORDER:
        return _RANK_ORDER.index(rank)
    return len(_RANK_ORDER) + (1 if rank == "unranked" else 0)


# Distinguishes "caller did not pass an upload" (legacy call sites) from
# "upload doc was looked up and is missing" (upload=None).
_UPLOAD_NOT_PASSED: Any = object()


def build_report(
    analysis_doc: dict[str, Any],
    reviews: list[dict[str, Any]],
    source_file: str | None = None,
    location_label: str | None = None,
    depth_meters: float | None = None,
    *,
    upload: dict[str, Any] | None = _UPLOAD_NOT_PASSED,
) -> AnalysisReport:
    """
    Assemble a full AnalysisReport from a stored analysis document and its reviews.

    Args:
        analysis_doc: raw MongoDB document from the analysis_results collection.
        reviews: list of raw MongoDB review documents for this analysis_id.
        source_file: optional filename from the upload document.
        location_label: optional sample site label from the upload document.
        depth_meters: optional sampling depth from the upload document.
        upload: the raw upload document (None if it no longer exists). When
            given, every optional metadata field is copied onto
            report.metadata and report.context is built from it. Legacy
            callers that omit it get the old three fields and context=None.
    """
    results: list[dict] = analysis_doc.get("results", [])

    context: MetadataContext | None = None
    upload_fields: dict[str, Any] | None = None
    if upload is not _UPLOAD_NOT_PASSED:
        context = build_metadata_context(upload)
        upload_fields = {f: (upload or {}).get(f) for f in OPTIONAL_METADATA_FIELDS}
        if source_file is None and upload:
            source_file = upload.get("original_filename")

    metadata = _build_metadata(
        analysis_doc, source_file, location_label, depth_meters, upload_fields=upload_fields,
    )
    qc = _build_qc_summary(results)
    route_dist = _build_route_distribution(results)
    known = _build_known_species(results)
    assignments = _build_taxonomic_assignments(results)
    novelty = _build_novelty_table(results)
    contamination = _build_contamination_warnings(results)
    biodiversity = _build_biodiversity(results)
    taxa = _build_taxa(results, analysis_doc.get("orchestrator_version"))
    model_versions = _build_model_versions(results)
    review_status = _build_review_status(reviews)

    return AnalysisReport(
        metadata=metadata,
        qc_summary=qc,
        route_distribution=route_dist,
        known_species=known,
        taxonomic_assignments=assignments,
        possible_novelty=novelty,
        contamination_warnings=contamination,
        biodiversity=biodiversity,
        taxa=taxa,
        model_versions_used=model_versions,
        review_status=review_status,
        context=context,
    )


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

def _build_metadata(
    doc: dict,
    source_file: str | None,
    location_label: str | None = None,
    depth_meters: float | None = None,
    upload_fields: dict[str, Any] | None = None,
) -> SampleMetadata:
    if upload_fields is None:
        upload_fields = {"location_label": location_label, "depth_meters": depth_meters}

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
        **upload_fields,
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
                route=r.get("route", "misc_unknown"),
                confidence=round(float(r.get("confidence", 0.0)), 4),
                model_version_used=r.get("model_version_used"),
                reason_codes=r.get("reason_codes", []),
                **resolve_taxon_fields(r),
            ))
    return entries


def _confidence_tier(confidence: float, contamination_flagged: bool) -> str:
    """Green/amber/red per SYNTHVEDA_BUILD_SPEC.md 2.3."""
    if contamination_flagged or confidence < _TIER_RED_MAX:
        return "red"
    if confidence >= _TIER_GREEN_MIN:
        return "green"
    return "amber"


def _build_taxonomic_assignments(results: list[dict]) -> list[TaxonomicAssignmentEntry]:
    """
    Every sequence's automated call, not just the "known_species" subset --
    Species Correction needs the full confidence spectrum (green/amber/red)
    to review, not a pre-filtered "confident matches only" list.
    """
    entries = []
    for r in results:
        if r.get("route") == "low_quality" or r.get("result_class") == "low_quality_unusable":
            continue
        confidence = round(float(r.get("confidence", 0.0)), 4)
        contamination_flagged = bool(r.get("contamination_flagged"))
        entries.append(TaxonomicAssignmentEntry(
            sequence_id=r.get("sequence_id", "unknown"),
            route=r.get("route", "misc_unknown"),
            result_class=r.get("result_class"),
            **resolve_taxon_fields(r),
            confidence=confidence,
            confidence_tier=_confidence_tier(confidence, contamination_flagged),
            length=int(r.get("length", 0)),
            contamination_flagged=contamination_flagged,
            model_version_used=r.get("model_version_used"),
            reason_codes=r.get("reason_codes", []),
        ))
    # Sort: most confident first (mirrors the mockup's default "Confidence score" sort).
    return sorted(entries, key=lambda e: -e.confidence)


def _build_novelty_table(results: list[dict]) -> list[PossibleNoveltyEntry]:
    entries = []
    for r in results:
        score = float(r.get("novelty_score", 0.0))
        if score >= NOVELTY_THRESHOLD:
            entries.append(PossibleNoveltyEntry(
                sequence_id=r.get("sequence_id", "unknown"),
                route=r.get("route", "misc_unknown"),
                novelty_score=round(score, 4),
                novelty_level=r.get("novelty_level", "low"),
                abyss_recommendation=r.get("abyss_recommendation", "continue_sampling"),
                requires_cloud_confirmation=bool(r.get("requires_cloud_confirmation", True)),
                reason_codes=r.get("novelty_reason_codes", r.get("reason_codes", [])),
                contamination_score=round(float(r.get("contamination_score", 0.0)), 4),
                sequence=r.get("sequence", ""),
            ))
    # Sort: highest novelty first
    return sorted(entries, key=lambda e: -e.novelty_score)


def _in_contamination_warnings(r: dict) -> bool:
    return bool(r.get("contamination_flagged")) or float(r.get("contamination_score", 0.0)) >= _CONTAMINATION_THRESHOLD


def _build_contamination_warnings(results: list[dict]) -> list[ContaminationWarning]:
    entries = []
    for r in results:
        if _in_contamination_warnings(r):
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

    novelty_count = sum(1 for r in results if float(r.get("novelty_score", 0.0)) >= NOVELTY_THRESHOLD)
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


TAXA_DEFINITIONS: dict[str, str] = {
    "taxon": (
        "Per sequence: results[].decision.predicted_taxon at results[].decision.taxon_rank, the "
        "orchestrator's combined answer (after the plant genus cap). Sequences without a decision "
        "(written before the orchestrator) are not counted; a decision with a null taxon counts "
        "as without taxon. Contamination-flagged sequences (see contamination_flagged) are not "
        "observed taxa and are excluded from sequences_with/without_taxon, richness_by_rank and top_taxa."
    ),
    "contamination_flagged": (
        "A decided sequence is contamination-flagged when it is in this report's contamination_warnings "
        f"(results[].contamination_flagged, or contamination_score >= {_CONTAMINATION_THRESHOLD}) or its "
        "decision.result_class is possible_contamination. sequences_contamination_flagged counts them; "
        "the taxa they named are listed in contamination_flagged_taxa, not in richness or top taxa. "
        "sequences_with_taxon + sequences_without_taxon + sequences_contamination_flagged = "
        "sequences_with_decision."
    ),
    "fraction_with_taxon": (
        "sequences_with_taxon / (sequences_with_decision - sequences_contamination_flagged); null when "
        "every decided sequence is contamination-flagged. Low-quality sequences are in the "
        "denominator (they never get a taxon) and listed under without_taxon_reasons."
    ),
    "without_taxon_reasons": (
        "For each decided, not contamination-flagged sequence with no taxon: 'low_quality' when decision.final_route is "
        "low_quality, otherwise the rule of the taxon step in decision_trace.combine "
        "(':' + its outcome when that is a status string, e.g. no_reference_assignment:below_threshold), "
        "or 'not_recorded' when the trace has no taxon step."
    ),
    "richness_by_rank": (
        "For each taxon_rank, the number of distinct predicted_taxon names decided at that rank, over "
        "sequences that are not contamination-flagged (contaminants are not counted as observed taxa). "
        "Ranks are never mixed or summed into one richness: a genus-level call and a species of that "
        "genus are counted separately, each at its own rank. A taxon without a rank is 'unranked'. "
        "Listed finest rank first (species, genus, family, order, class, phylum, kingdom, superkingdom), "
        "other ranks after by name, 'unranked' last."
    ),
    "top_taxa": (
        f"(taxon, rank) groups of not contamination-flagged sequences by sequence count, ties by name, "
        f"first {TOP_TAXA_LIMIT}; fraction_of_assigned = sequences / sequences_with_taxon. "
        "mean/min/max_percent_identity are over the group's sequences whose decision carries a "
        "percent_identity (arithmetic mean, 2 dp); taxon_groups counts every group before the cut "
        "(a row count, not a richness estimate)."
    ),
    "reference_dbs": (
        "Distinct (decision.reference_db, decision.reference_db_version) pairs, counted per sequence; "
        "a decision names the reference DB whenever the lookup ran, assigned or not. This is DB usage, "
        "so contamination-flagged sequences are included."
    ),
}


def _without_taxon_reason(r: dict, decision: dict) -> str:
    if decision.get("final_route") == _LOW_QUALITY_ROUTE:
        return "low_quality"
    trace = r.get("decision_trace")
    combine = trace.get("combine") if isinstance(trace, dict) else None
    for step in combine if isinstance(combine, list) else []:
        if isinstance(step, dict) and step.get("step") == "taxon":
            rule = str(step.get("rule") or "unnamed_rule")
            outcome = step.get("outcome")
            return f"{rule}:{outcome}" if isinstance(outcome, str) and outcome else rule
    return "not_recorded"


def _ref_label(d: dict) -> str:
    return (f"{d.get('reference_db') or 'reference DB not recorded'} "
            f"{d.get('reference_db_version') or 'version not recorded'}")


def _is_contamination_flagged(r: dict, decision: dict) -> bool:
    return _in_contamination_warnings(r) or decision.get("result_class") == "possible_contamination"


def _build_taxa(results: list[dict], orchestrator_version: str | None) -> TaxaSummary:
    """
    Taxon richness by rank, top taxa and reference DB usage (t-1023-1), from
    results[].decision only. Analyses without any decision are unavailable
    with a reason; their counts are None, never 0. See TAXA_DEFINITIONS.
    """
    total = len(results)
    decided = [(r, r["decision"]) for r in results if isinstance(r.get("decision"), dict)]
    if not decided:
        if total == 0:
            reason = "The analysis has no sequences."
        else:
            reason = (
                "No sequence carries an orchestrator decision: this analysis predates the orchestrator, "
                "so taxon rank, percent identity and reference DB were never recorded. "
                "Re-run the analysis to get taxa."
            )
            legacy_named = sum(1 for r in results if r.get("predicted_taxon"))
            if legacy_named:
                reason += (f" {legacy_named} of {total} sequences carry a legacy predicted_taxon without "
                           "a rank; it is shown per sequence but not aggregated.")
        return TaxaSummary(
            available=False, unavailable_reason=reason, orchestrator_version=orchestrator_version,
            total_sequences=total, sequences_with_decision=0, top_taxa_limit=TOP_TAXA_LIMIT,
            definitions=TAXA_DEFINITIONS,
        )

    without_reasons: dict[str, int] = {}
    groups: dict[tuple[str, str | None], list[dict]] = {}
    refs: dict[tuple[str | None, str | None], list[int]] = {}
    flagged = 0
    flagged_groups: dict[tuple[str, str | None], list[tuple[dict, dict]]] = {}
    for r, dec in decided:
        taxon = dec.get("predicted_taxon")
        db, ver = dec.get("reference_db"), dec.get("reference_db_version")
        if db or ver:
            counts = refs.setdefault((db, ver), [0, 0])
            counts[0] += 1
            counts[1] += 1 if taxon else 0
        if _is_contamination_flagged(r, dec):
            flagged += 1
            if taxon:
                flagged_groups.setdefault((taxon, dec.get("taxon_rank")), []).append((r, dec))
            continue
        if not taxon:
            reason = _without_taxon_reason(r, dec)
            without_reasons[reason] = without_reasons.get(reason, 0) + 1
            continue
        groups.setdefault((taxon, dec.get("taxon_rank")), []).append(dec)

    with_taxon = sum(len(g) for g in groups.values())
    n_decided = len(decided)
    n_counted = n_decided - flagged

    by_rank: dict[str, list[int]] = {}
    for (_taxon, rank), decs in groups.items():
        counts = by_rank.setdefault(rank or "unranked", [0, 0])
        counts[0] += 1
        counts[1] += len(decs)
    richness = [
        RankRichness(rank=rank, distinct_taxa=d, sequences=n)
        for rank, (d, n) in sorted(by_rank.items(), key=lambda x: (_rank_order(x[0]), x[0]))
    ]

    ranked = sorted(groups.items(), key=lambda x: (-len(x[1]), x[0][0], x[0][1] or ""))
    top: list[TopTaxonEntry] = []
    for (taxon, rank), decs in ranked[:TOP_TAXA_LIMIT]:
        ids = [float(d["percent_identity"]) for d in decs if d.get("percent_identity") is not None]
        top.append(TopTaxonEntry(
            taxon=taxon,
            taxon_rank=rank,
            sequences=len(decs),
            fraction_of_assigned=round(len(decs) / with_taxon, 4),  # with_taxon >= len(decs) > 0
            mean_percent_identity=round(sum(ids) / len(ids), 2) if ids else None,
            min_percent_identity=min(ids) if ids else None,
            max_percent_identity=max(ids) if ids else None,
            sequences_with_identity=len(ids),
            routes=sorted({d["final_route"] for d in decs if d.get("final_route")}),
            reference_db_versions=sorted({
                _ref_label(d) for d in decs if d.get("reference_db") or d.get("reference_db_version")
            }),
        ))

    return TaxaSummary(
        available=True,
        orchestrator_version=orchestrator_version,
        total_sequences=total,
        sequences_with_decision=n_decided,
        sequences_with_taxon=with_taxon,
        sequences_without_taxon=n_counted - with_taxon,
        sequences_contamination_flagged=flagged,
        sequences_contamination_flagged_with_taxon=sum(len(g) for g in flagged_groups.values()),
        fraction_with_taxon=round(with_taxon / n_counted, 4) if n_counted else None,
        without_taxon_reasons=dict(sorted(without_reasons.items(), key=lambda x: (-x[1], x[0]))),
        richness_by_rank=richness,
        top_taxa=top,
        top_taxa_limit=TOP_TAXA_LIMIT,
        taxon_groups=len(groups),
        contamination_flagged_taxa=[
            ContaminationFlaggedTaxon(
                taxon=taxon, taxon_rank=rank, sequences=len(members),
                result_classes=sorted({d["result_class"] for _, d in members if d.get("result_class")}),
                contamination_types=sorted({r["contamination_type"] for r, _ in members
                                            if r.get("contamination_type")}),
            )
            for (taxon, rank), members in sorted(flagged_groups.items(), key=lambda x: (x[0][0], x[0][1] or ""))
        ],
        reference_dbs=[
            ReferenceDbUsage(reference_db=db, reference_db_version=ver, sequences=n, sequences_with_taxon=t)
            for (db, ver), (n, t) in sorted(refs.items(), key=lambda x: (x[0][0] or "", x[0][1] or ""))
        ],
        definitions=TAXA_DEFINITIONS,
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


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------

_CSV_COLUMNS = [
    "sequence_id", "route", "category", "predicted_taxon", "confidence",
    "novelty_score", "novelty_level", "contamination_score", "contamination_type",
    "model_version_used", "reason_codes",
    # t-1023-1, appended so existing column positions are unchanged.
    "taxon_rank", "percent_identity", "reference_db", "reference_db_version",
]


def build_report_csv(report: AnalysisReport) -> str:
    """
    Flatten a report's per-sequence sections (known species, possible
    novelty, contamination warnings) into one CSV, one row per sequence.
    A sequence flagged in more than one section (e.g. both novel and
    contaminated) gets a single merged row with a comma-joined category
    list, rather than being duplicated per section.
    """
    rows: dict[str, dict[str, Any]] = {}

    def _row(sequence_id: str) -> dict[str, Any]:
        return rows.setdefault(sequence_id, {col: "" for col in _CSV_COLUMNS} | {
            "sequence_id": sequence_id, "category": set(),
        })

    for e in report.known_species:
        r = _row(e.sequence_id)
        r["category"].add("known_species")
        r["route"] = e.route
        r["predicted_taxon"] = e.predicted_taxon or ""
        r["confidence"] = e.confidence
        r["model_version_used"] = e.model_version_used or ""
        r["reason_codes"] = "; ".join(e.reason_codes)
        r["taxon_rank"] = e.taxon_rank or ""
        r["percent_identity"] = "" if e.percent_identity is None else e.percent_identity
        r["reference_db"] = e.reference_db or ""
        r["reference_db_version"] = e.reference_db_version or ""

    for e in report.possible_novelty:
        r = _row(e.sequence_id)
        r["category"].add("possible_novelty")
        r["route"] = e.route
        r["novelty_score"] = e.novelty_score
        r["novelty_level"] = e.novelty_level
        r["reason_codes"] = "; ".join(e.reason_codes) or r["reason_codes"]

    for e in report.contamination_warnings:
        r = _row(e.sequence_id)
        r["category"].add("contamination")
        r["route"] = e.route
        r["contamination_score"] = e.contamination_score
        r["contamination_type"] = e.contamination_type or ""
        r["reason_codes"] = "; ".join(e.reason_codes) or r["reason_codes"]

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_CSV_COLUMNS)
    writer.writeheader()
    for r in sorted(rows.values(), key=lambda r: r["sequence_id"]):
        r["category"] = ", ".join(sorted(r["category"]))
        writer.writerow(r)
    return buf.getvalue()
