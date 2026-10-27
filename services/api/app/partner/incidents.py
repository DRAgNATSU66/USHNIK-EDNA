"""
Incidents and field-log task lists for the Industrial partner page
(t-1028-2, M1).

Both are read from Mongo on the request, over the same owner + date scope as
GET /partner/summary, and both reuse the summary's per-sequence rules
(summary._effective, summary.is_novelty_flag) so a flag counted here is the
same flag counted there. Nothing is scored, weighted or estimated: an
incident is an analysis that carries pipeline flags or an open urgent
review, listed with the counts that made it one.

One exception to "same flag": contamination that is the expected finding on
its route (EXPECTED_CONTAMINATION_BY_ROUTE, human DNA on the
human_domestic_contamination route; owner decision QNA-030) stays flagged on
the result and in /partner/summary, but the worker does not queue a review
for it, so it does not make an incident either. It is counted separately as
expected_contamination_flags, so contamination_flags +
expected_contamination_flags is the summary's contamination flag count.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timezone
from typing import Any, Optional

from ..models.field_log import FieldEntryKind, TaskStatus
from ..models.review import TriagePriority
from .models import (
    FlaggedSequence, IncidentAnalysis, ListScopeInfo, PartnerIncidents, PartnerTask, PartnerTasks, UrgentReview,
)
from .summary import (
    DEFINITIONS as SUMMARY_DEFINITIONS, FIELD_LOG_ENTRIES, OPEN_REVIEW_STATES, _as_utc, _effective, _iso_date,
    date_window, is_novelty_flag,
)

# Flagged sequences returned per incident (the counts cover all of them).
FLAGGED_SEQUENCES_PER_INCIDENT = 10

# Mirror of services/worker/app/job_runner.py EXPECTED_CONTAMINATION_BY_ROUTE
# (tests/test_partner_incidents.py checks the two are equal): contamination
# types that are the expected finding on a route. Flagged, not reviewed.
EXPECTED_CONTAMINATION_BY_ROUTE: dict[str, frozenset[str]] = {
    "human_domestic_contamination": frozenset({"human_dna"}),
}


def is_expected_contamination(route: Optional[str], contamination_type: Optional[str]) -> bool:
    """True when this contamination type is what `route` exists to detect."""
    return contamination_type in EXPECTED_CONTAMINATION_BY_ROUTE.get(route or "", ())

_INCIDENT_PROJECTION = {
    "_id": 0,
    "analysis_id": 1,
    "upload_id": 1,
    "created_at": 1,
    "results.sequence_id": 1,
    "results.route": 1,
    "results.result_class": 1,
    "results.predicted_taxon": 1,
    "results.novelty_score": 1,
    "results.contamination_flagged": 1,
    "results.contamination_type": 1,
    "results.decision.final_route": 1,
    "results.decision.result_class": 1,
}

INCIDENT_DEFINITIONS: dict[str, str] = {
    "scope": SUMMARY_DEFINITIONS["scope"],
    "incident": (
        "An analysis in scope with at least one contamination flag, at least one novelty flag, or at least "
        "one open urgent review. Flags are as the pipeline raised them; a later review decision does not "
        "clear a flag, so open_reviews says how many reviews on that analysis are still open. Expected "
        "contamination (see expected_contamination) does not make an analysis an incident."
    ),
    "contamination_flag": (
        "A sequence with contamination_flagged = true whose contamination is not expected for its route. "
        "Together with expected_contamination this is /partner/summary's contamination flag count."
    ),
    "expected_contamination": (
        "A sequence with contamination_flagged = true whose contamination_type is the expected finding on "
        "its final route: "
        + "; ".join(f"{', '.join(sorted(types))} on {route}"
                    for route, types in sorted(EXPECTED_CONTAMINATION_BY_ROUTE.items()))
        + " (owner decision QNA-030: that route exists to detect it). It stays flagged on the result, but the "
        "worker queues no review for it and it is not an incident. Counted per incident as "
        "expected_contamination_flags and, over every analysis in scope, in the top-level "
        "expected_contamination_flags."
    ),
    "novelty_flag": SUMMARY_DEFINITIONS["novelty_flag"],
    "urgent_review": (
        "A review of an analysis in scope with triage_priority = urgent and state submitted, triaged or "
        "needs_evidence (open)."
    ),
    "open_review": "A review in state submitted, triaged or needs_evidence.",
}

TASK_DEFINITIONS: dict[str, str] = {
    "scope": SUMMARY_DEFINITIONS["scope"],
    "task": "A field-log entry of kind task on an analysis in scope (created in the Researcher Mode field log).",
    "overdue": "task_status is not done and due_date is before today (UTC).",
    "order": "Tasks not done first, then by due_date (earliest first, no due date last), then newest first.",
}


def _base_filter(owner_filter: dict[str, Any], scope: ListScopeInfo) -> dict[str, Any]:
    base = dict(owner_filter)
    window = date_window(scope.date_from, scope.date_to)
    if window:
        base["created_at"] = window
    return base


def _sort_key_newest(dt: Any) -> datetime:
    return _as_utc(dt) or datetime.min.replace(tzinfo=timezone.utc)


def _float(v: Any) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


async def build_incidents(
    db,
    *,
    scope: ListScopeInfo,
    owner_filter: dict[str, Any],
    limit: int,
    now: Optional[datetime] = None,
) -> PartnerIncidents:
    notes: list[str] = []
    base = _base_filter(owner_filter, scope)

    per_analysis: dict[str, IncidentAnalysis] = {}
    analysis_ids: list[str] = []
    async for doc in db["analysis_results"].find(base, _INCIDENT_PROJECTION):
        aid = doc.get("analysis_id")
        if not aid:
            continue
        analysis_ids.append(aid)
        results = doc.get("results") or []
        contamination: list[FlaggedSequence] = []
        novelty: list[FlaggedSequence] = []
        types: Counter[str] = Counter()
        expected = 0
        for r in results:
            route, rc, _taxon, _rank = _effective(r)
            if r.get("contamination_flagged") and is_expected_contamination(route, r.get("contamination_type")):
                expected += 1
            elif r.get("contamination_flagged"):
                types[r.get("contamination_type") or "unrecorded"] += 1
                contamination.append(FlaggedSequence(
                    sequence_id=r.get("sequence_id"), flag="contamination", result_class=rc,
                    contamination_type=r.get("contamination_type"), novelty_score=_float(r.get("novelty_score"))))
            if is_novelty_flag(rc, r.get("novelty_score")):
                novelty.append(FlaggedSequence(
                    sequence_id=r.get("sequence_id"), flag="novelty", result_class=rc,
                    novelty_score=_float(r.get("novelty_score"))))
        per_analysis[aid] = IncidentAnalysis(
            analysis_id=aid,
            upload_id=doc.get("upload_id"),
            created_at=_as_utc(doc.get("created_at")),
            sequences=len(results),
            contamination_flags=len(contamination),
            expected_contamination_flags=expected,
            novelty_flags=len(novelty),
            contamination_types=dict(types),
            flagged_sequences=(contamination + novelty)[:FLAGGED_SEQUENCES_PER_INCIDENT],
        )

    urgent: list[UrgentReview] = []
    if analysis_ids:
        proj = {"_id": 0, "review_id": 1, "analysis_id": 1, "sequence_id": 1, "review_type": 1, "state": 1,
                "triage_priority": 1, "novelty_score": 1, "contamination_score": 1, "created_at": 1}
        async for rv in db["reviews"].find({"analysis_id": {"$in": analysis_ids}}, proj):
            if rv.get("state") not in OPEN_REVIEW_STATES:
                continue
            inc = per_analysis.get(rv.get("analysis_id"))
            if inc is None:
                continue
            inc.open_reviews += 1
            if rv.get("triage_priority") == TriagePriority.urgent:
                inc.urgent_open_reviews += 1
                urgent.append(UrgentReview(
                    review_id=rv.get("review_id") or "", analysis_id=rv["analysis_id"],
                    sequence_id=rv.get("sequence_id"), review_type=rv.get("review_type"), state=rv["state"],
                    novelty_score=_float(rv.get("novelty_score")),
                    contamination_score=_float(rv.get("contamination_score")),
                    created_at=_as_utc(rv.get("created_at")),
                ))

    incidents = [i for i in per_analysis.values()
                 if i.contamination_flags or i.novelty_flags or i.urgent_open_reviews]
    incidents.sort(key=lambda i: _sort_key_newest(i.created_at), reverse=True)
    shown = incidents[:limit]

    # Source file and site for the incidents returned.
    upload_ids = [i.upload_id for i in shown if i.upload_id]
    if upload_ids:
        uploads: dict[str, dict[str, Any]] = {}
        proj = {"_id": 0, "upload_id": 1, "original_filename": 1, "location_label": 1, "collected_at": 1}
        async for u in db["uploads"].find({"upload_id": {"$in": upload_ids}}, proj):
            uploads[u.get("upload_id")] = u
        for i in shown:
            u = uploads.get(i.upload_id)
            if u:
                i.source_file = u.get("original_filename")
                i.location_label = u.get("location_label")
                i.collected_at = _as_utc(u.get("collected_at"))

    urgent.sort(key=lambda r: _sort_key_newest(r.created_at))

    if not analysis_ids:
        notes.append("No analyses in this scope and date range, so there are no incidents.")
    elif not incidents:
        notes.append(f"None of the {len(analysis_ids)} analyses in scope carries a flag or an open urgent review.")
    if len(incidents) > limit:
        notes.append(f"incidents lists the {limit} newest of {len(incidents)}.")
    if len(urgent) > limit:
        notes.append(f"urgent_reviews lists the {limit} oldest of {len(urgent)}.")

    return PartnerIncidents(
        generated_at=now or datetime.now(timezone.utc),
        scope=scope,
        definitions=INCIDENT_DEFINITIONS,
        notes=notes,
        analyses_in_scope=len(analysis_ids),
        total=len(incidents),
        contamination_flags=sum(i.contamination_flags for i in incidents),
        expected_contamination_flags=sum(i.expected_contamination_flags for i in per_analysis.values()),
        novelty_flags=sum(i.novelty_flags for i in incidents),
        incidents=shown,
        truncated=len(incidents) > limit,
        urgent_reviews_total=len(urgent),
        urgent_reviews=urgent[:limit],
        urgent_reviews_truncated=len(urgent) > limit,
    )


async def build_tasks(
    db,
    *,
    scope: ListScopeInfo,
    owner_filter: dict[str, Any],
    status: Optional[TaskStatus],
    limit: int,
    now: Optional[datetime] = None,
) -> PartnerTasks:
    generated = now or datetime.now(timezone.utc)
    today: date = generated.date()
    analysis_ids = [doc.get("analysis_id") async for doc in
                    db["analysis_results"].find(_base_filter(owner_filter, scope), {"_id": 0, "analysis_id": 1})]
    tasks: list[PartnerTask] = []
    if analysis_ids:
        flt: dict[str, Any] = {"kind": FieldEntryKind.task.value, "analysis_id": {"$in": analysis_ids}}
        proj = {"_id": 0, "edits": 0}
        async for t in db[FIELD_LOG_ENTRIES].find(flt, proj):
            st = t.get("task_status") or TaskStatus.open.value
            if status is not None and st != status.value:
                continue
            due = _iso_date(t.get("due_date"))
            tasks.append(PartnerTask(
                entry_id=t.get("entry_id") or "", analysis_id=t.get("analysis_id") or "", body=t.get("body") or "",
                task_status=st, due_date=t.get("due_date"), assignee=t.get("assignee"),
                author_name=t.get("author_name"), created_at=_as_utc(t.get("created_at")),
                updated_at=_as_utc(t.get("updated_at")),
                overdue=st != TaskStatus.done and due is not None and due < today,
            ))

    def order(t: PartnerTask):
        due = _iso_date(t.due_date)
        created = _sort_key_newest(t.created_at).timestamp()
        return (t.task_status == TaskStatus.done, due is None, due or date.max, -created)

    tasks.sort(key=order)
    return PartnerTasks(
        generated_at=generated,
        scope=scope,
        definitions=TASK_DEFINITIONS,
        total=len(tasks),
        tasks=tasks[:limit],
        truncated=len(tasks) > limit,
    )

