"""
Community aggregates for the Academia page (t-1027-1, M3).

GET /partner/cooccurrence    taxon pairs detected together in the same sample
GET /partner/rhythms         uploads / detections by hour of day and day of week

Both work on *samples*: one sample = one upload in scope, represented by its
newest stored analysis (re-running a sample must not count its taxa twice).
Uploads are selected exactly like GET /partner/summary selects them (owner +
upload created_at in [date_from, date_to], UTC, both days inclusive); the
analyses read are those whose upload_id is one of the selected uploads.

Per-sequence taxa are read decision-first, the same rule as the summary
(summary._effective): results[].decision.predicted_taxon / taxon_rank when the
orchestrator wrote a decision, else the legacy results[].predicted_taxon with
no rank. Sequences with contamination_flagged = true are not detections of the
sample's community and are left out of both aggregates (their count is
returned).

Everything is counted from Mongo on the request; nothing is cached, sampled or
estimated. Co-occurrence is co-presence counting -- how many samples contain
both taxa -- not a statistical association test.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from itertools import combinations
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from .summary import _as_utc, _effective, date_window

# Ranks the reference lookup assigns (services/worker/app/evidence/
# reference_lookup.py RANKS), plus "any" = every taxon at whatever rank it was
# recorded (legacy results have no rank).
TAXON_RANKS = ("superkingdom", "kingdom", "phylum", "class", "order", "family", "genus", "species")
CooccurrenceRank = Literal["superkingdom", "kingdom", "phylum", "class", "order", "family", "genus", "species", "any"]
UNRECORDED_RANK = "unrecorded"

PAIRS_DEFAULT = 50
PAIRS_MAX = 50
# Pairs grow with the square of taxa per sample. Above this many taxa in one
# sample only the ones with the most sequences are paired (and a note says so).
MAX_TAXA_PER_SAMPLE = 300

WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

_UPLOAD_PROJECTION = {"_id": 0, "upload_id": 1, "user_id": 1, "created_at": 1, "collected_at": 1}
_ANALYSIS_PROJECTION = {
    "_id": 0,
    "analysis_id": 1,
    "upload_id": 1,
    "created_at": 1,
    "results.predicted_taxon": 1,
    "results.contamination_flagged": 1,
    "results.decision.predicted_taxon": 1,
    "results.decision.taxon_rank": 1,
}

SAMPLE_DEFINITION = (
    "One sample = one upload in scope (owner, upload created_at within [date_from, date_to], UTC, both "
    "days inclusive), represented by its newest stored analysis; older re-runs of the same upload are "
    "not counted."
)
TAXON_DEFINITION = (
    "Per sequence: results[].decision.predicted_taxon with decision.taxon_rank when the orchestrator wrote "
    "a decision, otherwise the legacy results[].predicted_taxon (rank not recorded). Sequences with "
    "contamination_flagged = true are excluded. A taxon is present in a sample when at least one "
    "remaining sequence is assigned to it."
)


class CommunityScopeInfo(BaseModel):
    mode: Literal["mine", "all", "user"]
    user_id: Optional[str] = None
    date_from: Optional[date] = None
    date_to: Optional[date] = None


class CooccurrencePair(BaseModel):
    taxon_a: str  # alphabetically first of the two
    rank_a: str
    taxon_b: str
    rank_b: str
    samples_together: int  # samples containing both
    samples_a: int  # samples containing taxon_a
    samples_b: int
    # samples_together / samples with either: 1.0 = always found together.
    jaccard: float


class CooccurrenceTaxon(BaseModel):
    taxon: str
    rank: str
    samples: int  # samples containing it
    sequences: int  # assigned sequences across those samples


class CooccurrenceResponse(BaseModel):
    generated_at: datetime
    scope: CommunityScopeInfo
    rank: CooccurrenceRank
    definitions: dict[str, str]
    notes: list[str] = Field(default_factory=list)
    uploads_in_scope: int = 0
    samples: int = 0  # uploads in scope with at least one stored analysis
    samples_with_taxa: int = 0  # samples with >= 1 taxon at the requested rank
    taxa: int = 0  # distinct taxa at the requested rank
    # Distinct taxa per recorded rank over all samples, whatever rank was
    # requested -- tells the page which ranks are worth offering.
    taxa_by_rank: dict[str, int] = Field(default_factory=dict)
    contamination_sequences_excluded: int = 0
    pairs_total: int = 0  # distinct pairs before the limit
    pairs: list[CooccurrencePair] = Field(default_factory=list)
    # Every taxon named in `pairs`.
    nodes: list[CooccurrenceTaxon] = Field(default_factory=list)


class RhythmBin(BaseModel):
    bin: int  # hour 0-23 (UTC) or weekday 0-6 (Mon-Sun, UTC)
    label: str
    uploads: int = 0
    uploads_collected_at: int = 0  # timed by collected_at
    uploads_upload_time: int = 0  # no collected_at, timed by upload created_at
    detections: int = 0  # sequences with a taxon, attributed to the sample's time


class RhythmTotals(BaseModel):
    uploads: int = 0
    uploads_collected_at: int = 0
    uploads_upload_time: int = 0
    uploads_without_timestamp: int = 0
    samples_analysed: int = 0  # uploads with at least one stored analysis
    detections: int = 0
    contamination_sequences_excluded: int = 0


class RhythmsResponse(BaseModel):
    generated_at: datetime
    scope: CommunityScopeInfo
    timezone: Literal["UTC"] = "UTC"
    definitions: dict[str, str]
    notes: list[str] = Field(default_factory=list)
    totals: RhythmTotals
    by_hour: list[RhythmBin]
    by_weekday: list[RhythmBin]


@dataclass
class _Sample:
    upload: dict[str, Any]
    analysis_id: Optional[str] = None
    analysis_at: Optional[datetime] = None
    # (taxon, rank) -> assigned sequences
    taxa: Counter = field(default_factory=Counter)
    contamination_excluded: int = 0


async def _load_samples(db, owner_filter: dict[str, Any], date_from: Optional[date],
                        date_to: Optional[date]) -> dict[str, _Sample]:
    flt: dict[str, Any] = dict(owner_filter)
    window = date_window(date_from, date_to)
    if window:
        flt["created_at"] = window
    samples: dict[str, _Sample] = {}
    async for u in db["uploads"].find(flt, _UPLOAD_PROJECTION):
        u.pop("_id", None)
        if u.get("upload_id"):
            samples[u["upload_id"]] = _Sample(upload=u)
    if not samples:
        return samples

    aflt: dict[str, Any] = {"upload_id": {"$in": list(samples)}}
    aflt.update(owner_filter)
    async for doc in db["analysis_results"].find(aflt, _ANALYSIS_PROJECTION):
        s = samples.get(doc.get("upload_id"))
        if s is None:
            continue
        at = _as_utc(doc.get("created_at"))
        newest = s.analysis_id is None or (
            at is not None and (s.analysis_at is None or at > s.analysis_at
                                or (at == s.analysis_at and str(doc.get("analysis_id")) > str(s.analysis_id))))
        if not newest:
            continue
        taxa: Counter = Counter()
        excluded = 0
        for r in doc.get("results") or []:
            if r.get("contamination_flagged"):
                excluded += 1
                continue
            _route, _rc, taxon, rank = _effective(r)
            if taxon:
                taxa[(taxon, rank or UNRECORDED_RANK)] += 1
        s.analysis_id, s.analysis_at, s.taxa, s.contamination_excluded = doc.get("analysis_id"), at, taxa, excluded
    return samples


def _now(now: Optional[datetime]) -> datetime:
    return now or datetime.now(timezone.utc)


async def build_cooccurrence(db, *, scope: CommunityScopeInfo, owner_filter: dict[str, Any],
                             rank: str = "species", limit: int = PAIRS_DEFAULT,
                             now: Optional[datetime] = None) -> CooccurrenceResponse:
    samples = await _load_samples(db, owner_filter, scope.date_from, scope.date_to)
    analysed = [s for s in samples.values() if s.analysis_id is not None]
    notes: list[str] = []

    by_rank: dict[str, set[str]] = {}
    present: Counter = Counter()  # (taxon, rank) -> samples
    seqs: Counter = Counter()
    pairs: Counter = Counter()
    with_taxa = 0
    capped = 0
    for s in analysed:
        for (t, r) in s.taxa:
            by_rank.setdefault(r, set()).add(t)
        chosen = [(k, n) for k, n in s.taxa.items() if rank == "any" or k[1] == rank]
        if not chosen:
            continue
        with_taxa += 1
        if len(chosen) > MAX_TAXA_PER_SAMPLE:
            capped += 1
            chosen = sorted(chosen, key=lambda kn: (-kn[1], kn[0][0]))[:MAX_TAXA_PER_SAMPLE]
        for k, n in chosen:
            present[k] += 1
            seqs[k] += n
        keys = sorted(k for k, _ in chosen)
        for a, b in combinations(keys, 2):
            pairs[(a, b)] += 1

    def jaccard(a, b, both):
        either = present[a] + present[b] - both
        return round(both / either, 4) if either else 0.0

    ranked = sorted(
        ((a, b, n, jaccard(a, b, n)) for (a, b), n in pairs.items()),
        key=lambda x: (-x[2], -x[3], x[0][0], x[0][1], x[1][0], x[1][1]),
    )
    top = ranked[:limit]
    out_pairs = [
        CooccurrencePair(taxon_a=a[0], rank_a=a[1], taxon_b=b[0], rank_b=b[1], samples_together=n,
                         samples_a=present[a], samples_b=present[b], jaccard=j)
        for a, b, n, j in top
    ]
    named = sorted({a for a, *_ in top} | {b for _, b, *_ in top})
    nodes = [CooccurrenceTaxon(taxon=t, rank=r, samples=present[(t, r)], sequences=seqs[(t, r)]) for t, r in named]

    excluded = sum(s.contamination_excluded for s in analysed)
    rank_label = "any recorded rank" if rank == "any" else f"rank {rank}"
    if not samples:
        notes.append("No uploads in this scope and date range.")
    elif not analysed:
        notes.append("Uploads exist in this scope but none has a stored analysis yet.")
    elif not present:
        notes.append(f"No sample in scope has a taxon assigned at {rank_label}, so there are no pairs.")
    elif not pairs:
        notes.append(f"No sample in scope has two or more taxa at {rank_label}, so there are no pairs.")
    if with_taxa == 1 and pairs:
        notes.append(f"Only one sample has taxa at {rank_label}: every pair is seen in that one sample, so the "
                     "counts cannot separate taxa that tend to occur together from ones that happened to share it.")
    if len(ranked) > limit:
        notes.append(f"pairs lists the top {limit} of {len(ranked)} pairs.")
        last, nxt = ranked[limit - 1], ranked[limit]
        if (last[2], last[3]) == (nxt[2], nxt[3]):
            notes.append(f"The cut at {limit} falls inside a tie (samples_together {last[2]}, jaccard "
                         f"{last[3]}); tied pairs are ordered alphabetically, so which of them are listed is "
                         "not meaningful.")
    if capped:
        notes.append(f"{capped} sample{'s have' if capped != 1 else ' has'} more than {MAX_TAXA_PER_SAMPLE} taxa at "
                     f"{rank_label}; only the {MAX_TAXA_PER_SAMPLE} with the most sequences in each were paired.")
    if rank != "any" and by_rank.get(UNRECORDED_RANK):
        notes.append(f"{len(by_rank[UNRECORDED_RANK])} taxa come from results without a recorded rank (stored "
                     "before the orchestrator) and are only included with rank=any.")

    return CooccurrenceResponse(
        generated_at=_now(now),
        scope=scope,
        rank=rank,
        definitions={
            "sample": SAMPLE_DEFINITION,
            "taxon": TAXON_DEFINITION,
            "rank": ("Only taxa whose recorded rank equals the requested rank are paired; rank=any pairs every "
                     "taxon at whatever rank it was recorded, so a genus can pair with a species."),
            "samples_together": "Number of samples in which both taxa are present (co-presence count).",
            "jaccard": "samples_together / samples containing either taxon.",
            "order": "samples_together descending, then jaccard descending, then taxon names alphabetically.",
            "interpretation": ("Co-presence in the same sample is not a statistical association and not a "
                               "biological interaction."),
        },
        notes=notes,
        uploads_in_scope=len(samples),
        samples=len(analysed),
        samples_with_taxa=with_taxa,
        taxa=len(present),
        taxa_by_rank={r: len(ts) for r, ts in sorted(by_rank.items())},
        contamination_sequences_excluded=excluded,
        pairs_total=len(ranked),
        pairs=out_pairs,
        nodes=nodes,
    )


async def build_rhythms(db, *, scope: CommunityScopeInfo, owner_filter: dict[str, Any],
                        now: Optional[datetime] = None) -> RhythmsResponse:
    samples = await _load_samples(db, owner_filter, scope.date_from, scope.date_to)
    hours = [RhythmBin(bin=h, label=f"{h:02d}:00") for h in range(24)]
    days = [RhythmBin(bin=d, label=WEEKDAYS[d]) for d in range(7)]
    totals = RhythmTotals(uploads=len(samples))
    notes: list[str] = []

    for s in samples.values():
        detections = sum(s.taxa.values())
        if s.analysis_id is not None:
            totals.samples_analysed += 1
            totals.detections += detections
            totals.contamination_sequences_excluded += s.contamination_excluded
        collected = _as_utc(s.upload.get("collected_at"))
        ts = collected or _as_utc(s.upload.get("created_at"))
        if ts is None:
            totals.uploads_without_timestamp += 1
            continue
        basis = "uploads_collected_at" if collected else "uploads_upload_time"
        setattr(totals, basis, getattr(totals, basis) + 1)
        for b in (hours[ts.hour], days[ts.weekday()]):
            b.uploads += 1
            setattr(b, basis, getattr(b, basis) + 1)
            b.detections += detections

    if not samples:
        notes.append("No uploads in this scope and date range; every count is zero.")
    else:
        if totals.uploads_upload_time:
            notes.append(f"{totals.uploads_upload_time} of {totals.uploads} uploads have no collected_at and are "
                         "placed by when they were uploaded, which reflects the uploader's working hours rather "
                         "than when the sample was taken.")
        if totals.uploads_without_timestamp:
            notes.append(f"{totals.uploads_without_timestamp} uploads have neither collected_at nor created_at and "
                         "are not placed.")
        if totals.samples_analysed == 0:
            notes.append("No upload in scope has a stored analysis yet, so detections are zero.")
        elif totals.uploads < 20:
            notes.append(f"Only {totals.uploads} uploads are in scope; a time-of-day pattern from this few samples "
                         "reflects when they happened to be taken, not an activity rhythm.")

    return RhythmsResponse(
        generated_at=_now(now),
        scope=scope,
        definitions={
            "sample": SAMPLE_DEFINITION,
            "timestamp": ("Each upload is placed by its collected_at when recorded, otherwise by its upload "
                          "created_at; the two are counted separately (uploads_collected_at / "
                          "uploads_upload_time)."),
            "timezone": ("Hours and weekdays are in UTC, not local or solar time at the sampling site. A "
                         "collection date entered without a time is stored as local midnight of the uploader's "
                         "browser, converted to UTC."),
            "detections": (TAXON_DEFINITION + " Detections are those sequences in the sample's newest analysis, "
                           "counted at the sample's timestamp."),
            "interpretation": ("Counts of when samples were taken and what they contained. A daily or weekly "
                               "pattern here describes the sampling schedule unless sampling was evenly spread; "
                               "it is not by itself evidence of an organism's activity cycle."),
        },
        notes=notes,
        totals=totals,
        by_hour=hours,
        by_weekday=days,
    )
