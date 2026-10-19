"""
Partner summary aggregation (t-1026-2, B16).

Every number is counted from Mongo at request time: uploads, analysis_results
(per-sequence results, projected to the handful of fields counted here so the
embeddings never leave the database), reviews and environment_contexts. There
is no cache and no placeholder: an empty scope yields zeros, empty lists and a
note saying so.

Per-sequence fields are read decision-first: when the orchestrator (task A,
results[].decision) wrote a combined answer its final_route / result_class /
predicted_taxon / taxon_rank are used, otherwise the legacy top-level route /
result_class / predicted_taxon. Flags follow the worker's own summary rule
(services/worker/app/job_runner.py _stage_report) so these totals agree with
the per-analysis summaries shown on report pages.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Iterable, Optional

from ..config import NOVELTY_THRESHOLD
from ..environment import service as env_service
from ..environment.models import VARIABLES, USER_FIELDS
from ..environment.providers import ALL_PROVIDERS
from ..models.analysis import SequenceResultClass, TaxonomicRoute
from ..models.review import ReviewState
from .models import (
    EnvironmentCoverage, EnvironmentSourceCount, PartnerSummary, ReviewSummary, SiteSummary,
    SummaryScopeInfo, SummaryTotals, TaxonCount, TimeSeriesPoint,
)

TOP_TAXA_DEFAULT = 10
TOP_TAXA_MAX = 50
# Map markers returned, newest upload first.
MAX_SITES = 500
# Above this many periods the series is returned sparse (only periods with
# data) instead of gap-filled with zeros.
MAX_FILLED_PERIODS = 1000

OPEN_REVIEW_STATES = (ReviewState.submitted, ReviewState.triaged, ReviewState.needs_evidence)

# Only these per-sequence fields are fetched; results[] also carries
# embeddings and evidence that would make the summary read megabytes.
_ANALYSIS_PROJECTION = {
    "_id": 0,
    "analysis_id": 1,
    "upload_id": 1,
    "user_id": 1,
    "created_at": 1,
    "results.route": 1,
    "results.result_class": 1,
    "results.predicted_taxon": 1,
    "results.novelty_score": 1,
    "results.contamination_flagged": 1,
    "results.decision.final_route": 1,
    "results.decision.result_class": 1,
    "results.decision.predicted_taxon": 1,
    "results.decision.taxon_rank": 1,
}

_UPLOAD_PROJECTION = {
    "_id": 0,
    "upload_id": 1,
    "user_id": 1,
    "created_at": 1,
    "collected_at": 1,
    "latitude": 1,
    "longitude": 1,
    "location_label": 1,
    "depth_meters": 1,
    # User-entered values environment.service.build_response merges in.
    **{field: 1 for field, _ in USER_FIELDS.values()},
}

DEFINITIONS: dict[str, str] = {
    "scope": (
        "Uploads and analyses are selected by owner (user_id) and by their own created_at "
        "within [date_from, date_to] (UTC, both days inclusive). Reviews are those of the "
        "selected analyses; sites and environmental coverage are the selected uploads."
    ),
    "route": (
        "Per sequence: results[].decision.final_route when the orchestrator wrote a decision, "
        "otherwise results[].route."
    ),
    "result_class": (
        "Per sequence: results[].decision.result_class when present, otherwise results[].result_class."
    ),
    "taxon": (
        "Per sequence: results[].decision.predicted_taxon (with taxon_rank) when a decision exists, "
        "otherwise results[].predicted_taxon. Null taxa are not counted."
    ),
    "novelty_flag": (
        f"A sequence whose result_class is not known_species and that is either possible_novelty "
        f"or has novelty_score >= {NOVELTY_THRESHOLD} (the worker's per-analysis summary rule)."
    ),
    "contamination_flag": "A sequence with contamination_flagged = true.",
    "low_quality": "A sequence whose result_class is low_quality_unusable.",
    "time_series": (
        "Uploads bucketed by upload created_at; analyses, sequences and flags by analysis "
        "created_at. period_start is the first day of the UTC day, ISO week (Monday) or month."
    ),
    "environment": (
        "Read from environment_contexts with the same merge as GET /environment/uploads/{id}: "
        "a user-entered value counts as user_provided, a public value as ok."
    ),
}


def _as_utc(dt: Any) -> Optional[datetime]:
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt)
        except ValueError:
            return None
    if not isinstance(dt, datetime):
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def date_window(date_from: Optional[date], date_to: Optional[date]) -> dict[str, datetime]:
    """Mongo created_at filter for [date_from, date_to] inclusive, UTC.
    Naive datetimes: pymongo stores and compares them as UTC."""
    flt: dict[str, datetime] = {}
    if date_from is not None:
        flt["$gte"] = datetime.combine(date_from, time.min)
    if date_to is not None:
        flt["$lt"] = datetime.combine(date_to + timedelta(days=1), time.min)
    return flt


def period_start(d: date, interval: str) -> date:
    if interval == "week":
        return d - timedelta(days=d.weekday())
    if interval == "month":
        return d.replace(day=1)
    return d


def _next_period(d: date, interval: str) -> date:
    if interval == "week":
        return d + timedelta(days=7)
    if interval == "month":
        return date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return d + timedelta(days=1)


def _effective(result: dict[str, Any]) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """(route, result_class, taxon, taxon_rank), decision-first."""
    dec = result.get("decision")
    if isinstance(dec, dict):
        return (
            dec.get("final_route") or result.get("route"),
            dec.get("result_class") or result.get("result_class"),
            dec.get("predicted_taxon"),
            dec.get("taxon_rank"),
        )
    return result.get("route"), result.get("result_class"), result.get("predicted_taxon"), None


def is_novelty_flag(result_class: Optional[str], novelty_score: Any) -> bool:
    if result_class == SequenceResultClass.known_species:
        return False
    try:
        score = float(novelty_score) if novelty_score is not None else 0.0
    except (TypeError, ValueError):
        score = 0.0
    return result_class == SequenceResultClass.possible_novelty or score >= NOVELTY_THRESHOLD


class _Bucket:
    __slots__ = ("uploads", "analyses", "sequences", "novelty_flags", "contamination_flags")

    def __init__(self) -> None:
        self.uploads = self.analyses = self.sequences = self.novelty_flags = self.contamination_flags = 0


def _series(buckets: dict[date, _Bucket], interval: str, date_from: Optional[date],
            date_to: Optional[date], notes: list[str]) -> list[TimeSeriesPoint]:
    if not buckets and (date_from is None or date_to is None):
        return []
    lo = period_start(date_from, interval) if date_from else min(buckets)
    hi = period_start(date_to, interval) if date_to else max(buckets)
    if buckets:
        lo, hi = min(lo, min(buckets)), max(hi, max(buckets))
    keys: Iterable[date]
    filled: list[date] = []
    d = lo
    while d <= hi and len(filled) <= MAX_FILLED_PERIODS:
        filled.append(d)
        d = _next_period(d, interval)
    if len(filled) > MAX_FILLED_PERIODS:
        keys = sorted(buckets)
        notes.append(
            f"time_series spans more than {MAX_FILLED_PERIODS} {interval}s, so only periods with data "
            "are listed (gaps are not zero-filled); use a coarser interval or a narrower date range."
        )
    else:
        keys = filled
    out = []
    for k in keys:
        b = buckets.get(k) or _Bucket()
        out.append(TimeSeriesPoint(period_start=k, uploads=b.uploads, analyses=b.analyses, sequences=b.sequences,
                                   novelty_flags=b.novelty_flags, contamination_flags=b.contamination_flags))
    return out


async def build_summary(
    db,
    *,
    scope: SummaryScopeInfo,
    owner_filter: dict[str, Any],
    top_taxa: int = TOP_TAXA_DEFAULT,
    now: Optional[datetime] = None,
) -> PartnerSummary:
    """Aggregate everything in scope. `owner_filter` is {} (all users) or
    {"user_id": ...}; access has already been decided by the router."""
    notes: list[str] = []
    window = date_window(scope.date_from, scope.date_to)
    base: dict[str, Any] = dict(owner_filter)
    if window:
        base["created_at"] = window

    buckets: dict[date, _Bucket] = defaultdict(_Bucket)

    def bucket_for(dt: Any) -> Optional[_Bucket]:
        u = _as_utc(dt)
        return buckets[period_start(u.date(), scope.interval)] if u else None

    # -- uploads -----------------------------------------------------------
    uploads: list[dict[str, Any]] = []
    async for doc in db["uploads"].find(base, _UPLOAD_PROJECTION):
        doc.pop("_id", None)
        uploads.append(doc)
        b = bucket_for(doc.get("created_at"))
        if b:
            b.uploads += 1

    # -- analyses + per-sequence results ----------------------------------
    totals = SummaryTotals(uploads=len(uploads))
    routes: Counter[str] = Counter({r.value: 0 for r in TaxonomicRoute})
    classes: Counter[str] = Counter({c.value: 0 for c in SequenceResultClass})
    taxa_seq: Counter[tuple[str, Optional[str]]] = Counter()
    taxa_ana: Counter[tuple[str, Optional[str]]] = Counter()
    per_upload: dict[str, dict[str, int]] = defaultdict(
        lambda: {"analyses": 0, "sequences": 0, "novelty_flags": 0, "contamination_flags": 0})
    analysis_ids: list[str] = []

    async for doc in db["analysis_results"].find(base, _ANALYSIS_PROJECTION):
        analysis_ids.append(doc.get("analysis_id"))
        results = doc.get("results") or []
        totals.analyses += 1
        totals.sequences += len(results)
        nov = con = 0
        seen_taxa: set[tuple[str, Optional[str]]] = set()
        for r in results:
            route, rc, taxon, rank = _effective(r)
            routes[route or "unrecorded"] += 1
            classes[rc or "unrecorded"] += 1
            if rc == SequenceResultClass.low_quality_unusable:
                totals.low_quality += 1
            if is_novelty_flag(rc, r.get("novelty_score")):
                nov += 1
            if r.get("contamination_flagged"):
                con += 1
            if taxon:
                totals.sequences_with_taxon += 1
                taxa_seq[(taxon, rank)] += 1
                seen_taxa.add((taxon, rank))
        for key in seen_taxa:
            taxa_ana[key] += 1
        totals.novelty_flags += nov
        totals.contamination_flags += con
        totals.analyses_with_novelty_flags += int(nov > 0)
        totals.analyses_with_contamination_flags += int(con > 0)
        b = bucket_for(doc.get("created_at"))
        if b:
            b.analyses += 1
            b.sequences += len(results)
            b.novelty_flags += nov
            b.contamination_flags += con
        site = per_upload[doc.get("upload_id")]
        site["analyses"] += 1
        site["sequences"] += len(results)
        site["novelty_flags"] += nov
        site["contamination_flags"] += con

    top = [
        TaxonCount(taxon=t, taxon_rank=rank, sequences=n, analyses=taxa_ana[(t, rank)])
        for (t, rank), n in sorted(taxa_seq.items(), key=lambda kv: (-kv[1], kv[0][0], kv[0][1] or ""))[:top_taxa]
    ]

    # -- reviews of the analyses in scope ----------------------------------
    reviews = ReviewSummary(by_state={s.value: 0 for s in ReviewState})
    by_type: Counter[str] = Counter()
    if analysis_ids:
        async for rv in db["reviews"].find({"analysis_id": {"$in": analysis_ids}},
                                            {"_id": 0, "state": 1, "review_type": 1}):
            state = rv.get("state") or "unrecorded"
            reviews.total += 1
            reviews.by_state[state] = reviews.by_state.get(state, 0) + 1
            by_type[rv.get("review_type") or "unrecorded"] += 1
            if state in OPEN_REVIEW_STATES:
                reviews.open += 1
    reviews.by_type = dict(by_type)

    # -- environmental context + sites --------------------------------------
    environment, env_by_upload = await _environment(db, uploads)
    uploads_sorted = sorted(uploads, key=lambda u: _as_utc(u.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc),
                            reverse=True)
    with_coords = [u for u in uploads_sorted if u.get("latitude") is not None and u.get("longitude") is not None]
    sites = []
    for u in with_coords[:MAX_SITES]:
        env = env_by_upload.get(u["upload_id"], {})
        counts = per_upload.get(u["upload_id"]) or {}
        sites.append(SiteSummary(
            upload_id=u["upload_id"], latitude=float(u["latitude"]), longitude=float(u["longitude"]),
            location_label=u.get("location_label"), collected_at=_as_utc(u.get("collected_at")),
            created_at=_as_utc(u.get("created_at")),
            analyses=counts.get("analyses", 0), sequences=counts.get("sequences", 0),
            novelty_flags=counts.get("novelty_flags", 0), contamination_flags=counts.get("contamination_flags", 0),
            environment_status=env.get("status", "not_applicable"),
            environment_retrieved_at=env.get("retrieved_at"),
            environment_providers=env.get("providers", []),
        ))
    truncated = len(with_coords) > MAX_SITES
    if truncated:
        notes.append(f"sites lists the {MAX_SITES} newest of {len(with_coords)} uploads with coordinates.")

    # -- notes ----------------------------------------------------------------
    if not uploads and not totals.analyses:
        notes.append("No uploads or analyses in this scope and date range; every count is zero.")
    elif totals.sequences and not totals.sequences_with_taxon:
        notes.append(
            f"None of the {totals.sequences} sequences in scope carries a predicted taxon, so top_taxa is empty."
        )
    elif totals.analyses == 0:
        notes.append("Uploads exist in this scope but none has a stored analysis yet.")
    if uploads and not environment.eligible:
        notes.append(
            "No upload in scope has latitude, longitude and collected_at, so no environmental context exists."
        )
    if not reviews.total and totals.analyses:
        notes.append("No reviews exist for the analyses in scope.")

    return PartnerSummary(
        generated_at=now or datetime.now(timezone.utc),
        scope=scope,
        definitions=DEFINITIONS,
        notes=notes,
        totals=totals,
        time_series=_series(buckets, scope.interval, scope.date_from, scope.date_to, notes),
        route_distribution={k: v for k, v in routes.items() if v or k in TaxonomicRoute.__members__},
        result_class_distribution={k: v for k, v in classes.items() if v or k in SequenceResultClass.__members__},
        top_taxa=top,
        reviews=reviews,
        environment=environment,
        sites=sites,
        sites_truncated=truncated,
    )


async def _environment(db, uploads: list[dict[str, Any]]) -> tuple[EnvironmentCoverage, dict[str, dict[str, Any]]]:
    """Coverage over the uploads in scope, plus per-upload status for sites."""
    cov = EnvironmentCoverage(
        uploads_in_scope=len(uploads),
        by_status={s: 0 for s in ("complete", "partial", "pending", "failed", "not_requested")},
        variables={v: {"ok": 0, "user_provided": 0, "unavailable": 0} for v in VARIABLES},
    )
    per_upload: dict[str, dict[str, Any]] = {}
    eligible = [u for u in uploads if env_service.build_query(u) is not None]
    cov.eligible = len(eligible)
    cov.not_applicable = len(uploads) - len(eligible)
    for u in uploads:
        per_upload[u["upload_id"]] = {"status": "not_applicable"}
    if not eligible:
        return cov, per_upload

    docs: dict[str, dict[str, Any]] = {}
    async for d in db[env_service.CONTEXTS].find({"upload_id": {"$in": [u["upload_id"] for u in eligible]}}):
        d.pop("_id", None)
        docs[d["upload_id"]] = d

    source_uploads: Counter[str] = Counter()
    source_latest: dict[str, datetime] = {}
    for u in eligible:
        doc = docs.get(u["upload_id"])
        resp = env_service.build_response(u, doc)
        status = "not_requested" if doc is None else resp.status
        cov.by_status[status] = cov.by_status.get(status, 0) + 1
        retrieved = _as_utc(resp.retrieved_at) if doc is not None else None
        providers = sorted({v.public.provider for v in resp.variables.values() if v.public is not None})
        per_upload[u["upload_id"]] = {"status": status, "retrieved_at": retrieved, "providers": providers}
        for var, ctx in resp.variables.items():
            cov.variables.setdefault(var, {"ok": 0, "user_provided": 0, "unavailable": 0})
            cov.variables[var][ctx.status] += 1
        for p in providers:
            source_uploads[p] += 1
            if retrieved and (p not in source_latest or retrieved > source_latest[p]):
                source_latest[p] = retrieved
        if retrieved and (cov.latest_retrieved_at is None or retrieved > cov.latest_retrieved_at):
            cov.latest_retrieved_at = retrieved

    for p, n in sorted(source_uploads.items()):
        info = ALL_PROVIDERS[p].info if p in ALL_PROVIDERS else None
        cov.sources.append(EnvironmentSourceCount(
            provider=p, source=info.source if info else p, licence=info.licence if info else "unknown",
            attribution=info.attribution if info else "unknown", uploads=n, latest_retrieved_at=source_latest.get(p),
        ))
    return cov, per_upload
