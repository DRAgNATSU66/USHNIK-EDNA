"""
Regional views for the Legislative partner page (t-1027-3, M2).

GET /partner/hotspots  uploads with coordinates aggregated into a fixed
                       latitude/longitude grid, with flag, taxon and open-
                       review counts per cell
GET /partner/alerts    one alert per analysis that has a contamination flag,
                       a novelty flag or an open urgent review

/partner/summary already lists one marker per upload (sites[]) but carries
no taxa and no review counts per site, and nothing per analysis; a page
cannot rebuild either without fetching every report. These two endpoints
read the same collections with the same rules (summary.py: decision-first
fields, the worker's novelty-flag rule, owner + created_at scoping), so
their numbers agree with the summary and the per-analysis report pages.

Every number is counted from Mongo on the request. Nothing is ranked by a
made-up severity: an alert is "urgent" only when the analysis has an open
review whose triage_priority is urgent, which the worker (auto-queued) or a
curator (triage) set; every other alert is "flagged".
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Optional

from ..models.review import ReviewState, TriagePriority
from .models import (
    AlertsResponse, HotspotCell, HotspotCoverage, HotspotsResponse, RegionalAlert, SummaryScopeInfo,
    TaxonInCell,
)
from .summary import _ANALYSIS_PROJECTION, OPEN_REVIEW_STATES, _as_utc, _effective, date_window, is_novelty_flag

CELL_DEG_DEFAULT = 1.0
CELL_DEG_MIN = 0.1
CELL_DEG_MAX = 10.0
CELL_TOP_TAXA = 5
CELL_MAX_LABELS = 5
CELL_MAX_UPLOAD_IDS = 50

ALERTS_DEFAULT = 50
ALERTS_MAX = 200

# summary.py's projection plus contamination_type, so an alert can say what
# kind of contamination was flagged (e.g. human DNA on the human route).
_PROJECTION = {**_ANALYSIS_PROJECTION, "results.contamination_type": 1}

_UPLOAD_PROJECTION = {
    "_id": 0,
    "upload_id": 1,
    "user_id": 1,
    "created_at": 1,
    "collected_at": 1,
    "latitude": 1,
    "longitude": 1,
    "location_label": 1,
    "original_filename": 1,
}

_OPEN = {s.value for s in OPEN_REVIEW_STATES}

HOTSPOT_DEFINITIONS: dict[str, str] = {
    "scope": (
        "Uploads and analyses are selected by owner (user_id) and by their own created_at within "
        "[date_from, date_to] (UTC, both days inclusive), as in GET /partner/summary. A cell counts the "
        "in-scope analyses of the in-scope uploads that fall in it."
    ),
    "cell": (
        "Each upload with a valid latitude and longitude is placed in the grid cell "
        "[floor(lat / cell_deg) * cell_deg, +cell_deg) x [floor(lon / cell_deg) * cell_deg, +cell_deg), "
        "in degrees (WGS84 as entered at upload), computed with a 1e-9-cell tolerance so a coordinate on an "
        "edge (0.3 with cell_deg 0.1) lands in the cell it starts despite floating-point error. Latitude 90 "
        "and longitude 180 fall in the cell below. When cell_deg does not divide 90 or 180, the cells at the "
        "poles and the antimeridian are clipped to +-90 / +-180 (bounds and center are of the clipped cell). "
        "One degree of latitude is about 111 km; a degree of longitude shrinks with cos(latitude). "
        "The cell is an aggregation unit, not a detection radius or a drift model."
    ),
    "novelty_flag": "Same rule as GET /partner/summary: result_class is not known_species and it is "
                    "possible_novelty or has novelty_score >= the deployment's novelty threshold.",
    "contamination_flag": "A sequence with contamination_flagged = true (as in GET /partner/summary).",
    "taxa": (
        "distinct_taxa counts distinct (predicted_taxon, taxon_rank) pairs over the cell's sequences, read "
        "decision-first (results[].decision when the orchestrator wrote one, else results[].predicted_taxon). "
        "Sequences with no predicted taxon are not counted."
    ),
    "reviews": (
        "open_reviews: reviews of the cell's analyses in state submitted, triaged or needs_evidence. "
        "open_urgent_reviews: those with triage_priority urgent."
    ),
}

ALERT_DEFINITIONS: dict[str, str] = {
    "scope": HOTSPOT_DEFINITIONS["scope"].replace(
        " A cell counts the in-scope analyses of the in-scope uploads that fall in it.",
        " An alert is one in-scope analysis; its upload is looked up whatever its own created_at.",
    ),
    "alert": (
        "An analysis is listed when it has at least one novelty flag, one contamination flag, or one open "
        "urgent review. Analyses with none of these are not alerts."
    ),
    "priority": (
        "urgent: the analysis has at least one open review (submitted, triaged or needs_evidence) with "
        "triage_priority urgent. The worker queues a review as urgent when a sequence's novelty_score is "
        ">= 0.70 or a contamination flag is not expected for its route (human DNA on the human route is "
        "expected, so flagged but not queued); a curator can also set urgent at triage. "
        "flagged: any other alert. No other severity is assigned."
    ),
    "novelty_flag": HOTSPOT_DEFINITIONS["novelty_flag"],
    "contamination_flag": HOTSPOT_DEFINITIONS["contamination_flag"] + " contamination_types counts "
                          "results[].contamination_type over the flagged sequences ('unrecorded' when absent).",
    "order": "urgent first, then by analysis created_at, newest first.",
}


# A quotient within this many cells of a whole number is that whole number:
# 0.3 / 0.1 is 2.9999999999999996 in floating point, which floor() would put
# in cell 2 ([0.2, 0.3)) although 0.3 is the lower edge of cell 3. 1e-9 of a
# cell is under 0.012 mm at the 0.1 degree minimum, so no real coordinate is
# moved by it.
_CELL_EPS = 1e-9


def _floor_cells(x: float) -> int:
    k = round(x)
    return int(k) if abs(x - k) <= _CELL_EPS else math.floor(x)


def _ceil_cells(x: float) -> int:
    k = round(x)
    return int(k) if abs(x - k) <= _CELL_EPS else math.ceil(x)


def cell_index(lat: float, lng: float, size: float) -> tuple[int, int]:
    """Grid indices of (lat, lng): floor(coord / size), the half-open rule,
    robust to floating-point error; the top/right edges fold into the cell below."""
    i = _floor_cells(lat / size)
    j = _floor_cells(lng / size)
    # 90 / 180 exactly would open a cell that lies entirely off the globe.
    i = min(i, _ceil_cells(90 / size) - 1)
    j = min(j, _ceil_cells(180 / size) - 1)
    return i, j


def cell_bounds(i: int, j: int, size: float) -> tuple[float, float, float, float]:
    """(lat_min, lat_max, lng_min, lng_max) of cell (i, j), clipped to the
    globe: when size does not divide 90 or 180 the edge cells would otherwise
    reach past +-90 / +-180."""
    return (max(-90.0, i * size), min(90.0, (i + 1) * size),
            max(-180.0, j * size), min(180.0, (j + 1) * size))


def _valid_coords(u: dict[str, Any]) -> Optional[tuple[float, float]]:
    try:
        lat, lng = float(u["latitude"]), float(u["longitude"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (math.isfinite(lat) and math.isfinite(lng)) or not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None
    return lat, lng


def _r(x: float) -> float:
    # Cell edges are multiples of cell_deg; rounding hides 0.1 * 3 = 0.30000000000000004.
    return round(x, 6)


class _AnalysisStats:
    __slots__ = ("analysis_id", "upload_id", "created_at", "sequences", "sequences_with_taxon", "novelty_flags",
                 "contamination_flags", "contamination_types", "taxa")

    def __init__(self, doc: dict[str, Any]):
        self.analysis_id = doc.get("analysis_id")
        self.upload_id = doc.get("upload_id")
        self.created_at = _as_utc(doc.get("created_at"))
        self.sequences = 0
        self.sequences_with_taxon = 0
        self.novelty_flags = 0
        self.contamination_flags = 0
        self.contamination_types: Counter[str] = Counter()
        self.taxa: Counter[tuple[str, Optional[str]]] = Counter()
        for r in doc.get("results") or []:
            _route, rc, taxon, rank = _effective(r)
            self.sequences += 1
            if is_novelty_flag(rc, r.get("novelty_score")):
                self.novelty_flags += 1
            if r.get("contamination_flagged"):
                self.contamination_flags += 1
                self.contamination_types[r.get("contamination_type") or "unrecorded"] += 1
            if taxon:
                self.sequences_with_taxon += 1
                self.taxa[(taxon, rank)] += 1


async def _load_analyses(db, base: dict[str, Any]) -> list[_AnalysisStats]:
    return [_AnalysisStats(doc) async for doc in db["analysis_results"].find(base, _PROJECTION)]


async def _open_reviews(db, analysis_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Per analysis: open review count, open urgent count, open count by review_type."""
    out: dict[str, dict[str, Any]] = defaultdict(lambda: {"open": 0, "urgent": 0, "by_type": Counter()})
    if not analysis_ids:
        return out
    flt = {"analysis_id": {"$in": analysis_ids}}
    async for rv in db["reviews"].find(flt, {"_id": 0, "analysis_id": 1, "state": 1, "review_type": 1,
                                            "triage_priority": 1}):
        if (rv.get("state") or ReviewState.submitted.value) not in _OPEN:
            continue
        slot = out[rv.get("analysis_id")]
        slot["open"] += 1
        slot["by_type"][rv.get("review_type") or "unrecorded"] += 1
        if rv.get("triage_priority") == TriagePriority.urgent.value:
            slot["urgent"] += 1
    return out


def _base_filter(scope: SummaryScopeInfo, owner_filter: dict[str, Any]) -> dict[str, Any]:
    base: dict[str, Any] = dict(owner_filter)
    window = date_window(scope.date_from, scope.date_to)
    if window:
        base["created_at"] = window
    return base


def _newest_first(items, key):
    floor = datetime.min.replace(tzinfo=timezone.utc)
    return sorted(items, key=lambda x: key(x) or floor, reverse=True)


async def build_hotspots(
    db,
    *,
    scope: SummaryScopeInfo,
    owner_filter: dict[str, Any],
    cell_deg: float = CELL_DEG_DEFAULT,
    now: Optional[datetime] = None,
) -> HotspotsResponse:
    base = _base_filter(scope, owner_filter)
    uploads = [u async for u in db["uploads"].find(base, _UPLOAD_PROJECTION)]
    for u in uploads:
        u.pop("_id", None)
    analyses = await _load_analyses(db, base)
    reviews = await _open_reviews(db, [a.analysis_id for a in analyses])
    by_upload: dict[str, list[_AnalysisStats]] = defaultdict(list)
    for a in analyses:
        by_upload[a.upload_id].append(a)

    coverage = HotspotCoverage(uploads_in_scope=len(uploads), analyses_in_scope=len(analyses))
    cells: dict[tuple[int, int], dict[str, Any]] = {}
    for u in _newest_first(uploads, lambda u: _as_utc(u.get("created_at"))):
        if u.get("latitude") is None or u.get("longitude") is None:
            coverage.uploads_without_coordinates += 1
            continue
        coords = _valid_coords(u)
        if coords is None:
            coverage.uploads_invalid_coordinates += 1
            continue
        coverage.uploads_with_coordinates += 1
        key = cell_index(*coords, cell_deg)
        c = cells.setdefault(key, {
            "uploads": [], "labels": [], "collected": [], "analyses": 0, "sequences": 0,
            "sequences_with_taxon": 0, "novelty_flags": 0, "contamination_flags": 0, "taxa": Counter(),
            "open_reviews": 0, "open_urgent_reviews": 0,
        })
        c["uploads"].append(u["upload_id"])
        label = u.get("location_label")
        if label and label not in c["labels"]:
            c["labels"].append(label)
        collected = _as_utc(u.get("collected_at"))
        if collected:
            c["collected"].append(collected)
        for a in by_upload.get(u["upload_id"], []):
            coverage.analyses_mapped += 1
            c["analyses"] += 1
            c["sequences"] += a.sequences
            c["sequences_with_taxon"] += a.sequences_with_taxon
            c["novelty_flags"] += a.novelty_flags
            c["contamination_flags"] += a.contamination_flags
            c["taxa"].update(a.taxa)
            rv = reviews.get(a.analysis_id)
            if rv:
                c["open_reviews"] += rv["open"]
                c["open_urgent_reviews"] += rv["urgent"]

    out_cells = []
    for (i, j), c in cells.items():
        lat_min, lat_max, lng_min, lng_max = cell_bounds(i, j, cell_deg)
        top = sorted(c["taxa"].items(), key=lambda kv: (-kv[1], kv[0][0], kv[0][1] or ""))[:CELL_TOP_TAXA]
        out_cells.append(HotspotCell(
            cell_id=f"{i}:{j}",
            lat_min=_r(lat_min), lat_max=_r(lat_max),
            lng_min=_r(lng_min), lng_max=_r(lng_max),
            center_lat=_r((lat_min + lat_max) / 2), center_lng=_r((lng_min + lng_max) / 2),
            uploads=len(c["uploads"]),
            analyses=c["analyses"],
            sequences=c["sequences"],
            sequences_with_taxon=c["sequences_with_taxon"],
            distinct_taxa=len(c["taxa"]),
            novelty_flags=c["novelty_flags"],
            contamination_flags=c["contamination_flags"],
            open_reviews=c["open_reviews"],
            open_urgent_reviews=c["open_urgent_reviews"],
            top_taxa=[TaxonInCell(taxon=t, taxon_rank=rank, sequences=n) for (t, rank), n in top],
            location_labels=c["labels"][:CELL_MAX_LABELS],
            upload_ids=c["uploads"][:CELL_MAX_UPLOAD_IDS],
            first_collected_at=min(c["collected"]) if c["collected"] else None,
            last_collected_at=max(c["collected"]) if c["collected"] else None,
        ))
    out_cells.sort(key=lambda c: (-(c.open_urgent_reviews), -(c.contamination_flags + c.novelty_flags),
                                  -c.uploads, c.cell_id))

    notes: list[str] = []
    if not uploads:
        notes.append("No uploads in this scope and date range, so there are no cells.")
    elif not coverage.uploads_with_coordinates:
        notes.append(f"None of the {len(uploads)} uploads in scope has valid coordinates, so there are no cells.")
    if coverage.uploads_without_coordinates and coverage.uploads_with_coordinates:
        notes.append(f"{coverage.uploads_without_coordinates} upload(s) in scope have no coordinates and are not mapped.")
    if coverage.uploads_invalid_coordinates:
        notes.append(f"{coverage.uploads_invalid_coordinates} upload(s) have coordinates outside "
                     "[-90, 90] x [-180, 180] and are not mapped.")
    unmapped = coverage.analyses_in_scope - coverage.analyses_mapped
    if unmapped:
        notes.append(f"{unmapped} analysis(es) in scope belong to uploads that are unmapped or outside the "
                     "date range, so they are not counted in any cell.")
    if any(len(c["uploads"]) > CELL_MAX_UPLOAD_IDS for c in cells.values()):
        notes.append(f"upload_ids lists at most the {CELL_MAX_UPLOAD_IDS} newest uploads per cell; "
                     "uploads is the full count.")

    return HotspotsResponse(
        generated_at=now or datetime.now(timezone.utc),
        scope=scope,
        cell_deg=cell_deg,
        definitions=HOTSPOT_DEFINITIONS,
        notes=notes,
        coverage=coverage,
        cells=out_cells,
    )


async def build_alerts(
    db,
    *,
    scope: SummaryScopeInfo,
    owner_filter: dict[str, Any],
    limit: int = ALERTS_DEFAULT,
    now: Optional[datetime] = None,
) -> AlertsResponse:
    analyses = await _load_analyses(db, _base_filter(scope, owner_filter))
    reviews = await _open_reviews(db, [a.analysis_id for a in analyses])

    flagged = []
    for a in analyses:
        rv = reviews.get(a.analysis_id) or {"open": 0, "urgent": 0, "by_type": Counter()}
        if a.novelty_flags or a.contamination_flags or rv["urgent"]:
            flagged.append((a, rv))

    upload_ids = sorted({a.upload_id for a, _ in flagged if a.upload_id})
    uploads: dict[str, dict[str, Any]] = {}
    if upload_ids:
        async for u in db["uploads"].find({"upload_id": {"$in": upload_ids}}, _UPLOAD_PROJECTION):
            u.pop("_id", None)
            uploads[u["upload_id"]] = u

    alerts = []
    for a, rv in flagged:
        u = uploads.get(a.upload_id) or {}
        coords = _valid_coords(u) if u else None
        reasons = []
        if rv["urgent"]:
            reasons.append("open_urgent_review")
        if a.contamination_flags:
            reasons.append("contamination_flags")
        if a.novelty_flags:
            reasons.append("novelty_flags")
        alerts.append(RegionalAlert(
            analysis_id=a.analysis_id,
            upload_id=a.upload_id,
            priority="urgent" if rv["urgent"] else "flagged",
            reasons=reasons,
            analysis_created_at=a.created_at,
            upload_found=bool(u),
            original_filename=u.get("original_filename"),
            location_label=u.get("location_label"),
            latitude=coords[0] if coords else None,
            longitude=coords[1] if coords else None,
            collected_at=_as_utc(u.get("collected_at")),
            sequences=a.sequences,
            novelty_flags=a.novelty_flags,
            contamination_flags=a.contamination_flags,
            contamination_types=dict(sorted(a.contamination_types.items())),
            open_reviews=rv["open"],
            open_urgent_reviews=rv["urgent"],
            open_reviews_by_type=dict(sorted(rv["by_type"].items())),
        ))

    floor = datetime.min.replace(tzinfo=timezone.utc)
    alerts.sort(key=lambda x: (x.priority != "urgent", -(x.analysis_created_at or floor).timestamp(), x.analysis_id or ""))

    notes: list[str] = []
    if not analyses:
        notes.append("No analyses in this scope and date range, so there are no alerts.")
    elif not alerts:
        notes.append(f"None of the {len(analyses)} analyses in scope has a novelty flag, a contamination flag "
                     "or an open urgent review.")
    missing = sum(1 for x in alerts if not x.upload_found)
    if missing:
        notes.append(f"{missing} alert(s) reference an upload record that no longer exists; location is unknown.")
    truncated = len(alerts) > limit
    if truncated:
        notes.append(f"alerts lists the first {limit} of {len(alerts)} (urgent first, then newest).")

    return AlertsResponse(
        generated_at=now or datetime.now(timezone.utc),
        scope=scope,
        definitions=ALERT_DEFINITIONS,
        notes=notes,
        analyses_in_scope=len(analyses),
        total=len(alerts),
        urgent=sum(1 for x in alerts if x.priority == "urgent"),
        truncated=truncated,
        alerts=alerts[:limit],
    )
