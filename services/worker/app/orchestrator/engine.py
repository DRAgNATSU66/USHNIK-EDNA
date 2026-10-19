"""
Orchestrator engine (Day 9, tracker t-1022-2; decision Q7).

Per sequence: a plan (planner.py), evidence from several providers
(app/evidence/), one combined answer (combiner.py) and a stored decision
trace. Deterministic, no LLM, no randomness: the same routed input and the
same models/reference DB give the same decision.

Execution order for a batch (Orchestrator.run, synchronous; job_runner runs
it in the thread pool so the event loop is not blocked):

  1. plan       plan_sequence() for every sequence
  2. reference  the primary route's reference lookup, one batched
                BLAST/vsearch call per route (the provider holds the host
                search lock, so two jobs never search at once)
  3. expand     expand_plan() on that evidence (reference_miss /
                reference_lineage_route)
  4. reference  the other planned routes' lookups, batched per route
  5. heads      every planned route's head, grouped by route so each backbone
                is loaded once per batch
  6. route      select_route()
  7. contamination, then novelty, on the final route (novelty reads the
                contamination score, as the scorer's own gate does)
  8. combine    combine() -> "decision"; the trace is assembled

Output per sequence (the shared result contract): "decision" and
"decision_trace" = {orchestrator_version, plan, evidence, combine}, plus the
legacy fields the API and reports already read (route = final route,
result_class, predicted_taxon, confidence, novelty_score, contamination_*,
...). The trace holds EvidenceRecord.to_dict() records only: bounded hit
lists, no embeddings, plain Python types (BSON-encodable).
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

from app.evidence.base import EVIDENCE_SKIPPED, EvidenceRecord, plain, unavailable_records
from app.novelty.scorer import _novelty_level
from app.orchestrator.combiner import CombineInput, combine, select_route
from app.orchestrator.planner import LOW_QUALITY_ROUTE, Plan, expand_plan, plan_sequence

logger = logging.getLogger(__name__)

# Bump when a planner/combiner rule or the trace shape changes: a stored
# decision is only comparable with decisions of the same version.
ORCHESTRATOR_VERSION = "orchestrator-1.0.0"

HUMAN_ROUTE = "human_domestic_contamination"


@dataclass
class _SeqState:
    seq: dict
    plan: Plan
    heads: dict[str, EvidenceRecord] = field(default_factory=dict)
    refs: dict[str, EvidenceRecord] = field(default_factory=dict)
    contamination: EvidenceRecord | None = None
    novelty: EvidenceRecord | None = None
    final_route: str | None = None
    route_steps: list[dict] = field(default_factory=list)

    @property
    def sid(self) -> str:
        return str(self.seq.get("sequence_id"))

    @property
    def items(self) -> tuple[str, str]:
        return self.sid, str(self.seq.get("sequence") or "")


class Orchestrator:
    """Runs the providers per plan and combines their evidence.

    Providers are injectable (tests pass fakes); by default they wrap the
    real inference, reference lookup, contamination and novelty code."""

    def __init__(self, settings: Any = None, *, head: Any = None, reference: Any = None,
                 contamination: Any = None, novelty: Any = None, novelty_threshold: float | None = None):
        if settings is None:
            from app.config import get_worker_settings
            settings = get_worker_settings()
        from app.evidence.providers import (
            ContaminationProvider,
            NoveltyProvider,
            ReferenceEvidenceProvider,
            RouteHeadProvider,
        )
        self.settings = settings
        self.head = head or RouteHeadProvider()
        self.reference = reference or ReferenceEvidenceProvider(settings=settings)
        self.contamination = contamination or ContaminationProvider()
        self.novelty = novelty or NoveltyProvider()
        if novelty_threshold is None:
            from app.config import NOVELTY_THRESHOLD
            novelty_threshold = NOVELTY_THRESHOLD
        self.novelty_threshold = float(novelty_threshold)

    # -- helpers ---------------------------------------------------------------

    @staticmethod
    def _by_route(states: Sequence[_SeqState], route_of: Callable[[_SeqState], list[str]]
                  ) -> dict[str, list[_SeqState]]:
        groups: dict[str, list[_SeqState]] = {}
        for st in states:
            for r in route_of(st):
                groups.setdefault(r, []).append(st)
        return groups

    def _collect(self, provider: Any, route: str, group: list[_SeqState],
                 context: list[dict] | None = None) -> list[EvidenceRecord]:
        items = [st.items for st in group]
        try:
            recs = provider.collect(items, route, context)
        except Exception as exc:   # a provider must not raise; if one does, it is unavailable
            logger.warning("provider %s on %s raised: %r", getattr(provider, "name", provider), route, exc)
            return unavailable_records(provider, items, route, f"provider raised {type(exc).__name__}: {exc}"[:300])
        if len(recs) != len(items):
            return unavailable_records(provider, items, route,
                                       f"provider returned {len(recs)} records for {len(items)} inputs")
        return recs

    def _reference(self, states: list[_SeqState], route_of: Callable[[_SeqState], list[str]]) -> None:
        for route, group in self._by_route(states, route_of).items():
            for st, rec in zip(group, self._collect(self.reference, route, group)):
                st.refs[route] = rec

    def _reference_disabled(self, st: _SeqState) -> None:
        for r in st.plan.routes:
            if r not in st.refs:
                st.refs[r] = EvidenceRecord(self.reference.name, self.reference.version, st.sid, r, EVIDENCE_SKIPPED,
                                            reason="reference lookup disabled (ORCHESTRATOR_REFERENCE_ENABLED=false)")

    # -- main --------------------------------------------------------------------

    def run(self, sequences: list[dict], on_phase: Callable[[str], None] | None = None) -> dict:
        """Decide every sequence in place (adds decision, decision_trace and
        the legacy fields to each dict). Returns run statistics.

        on_phase(name) is called with "evidence" before the first provider
        runs and "scoring" before contamination/novelty, so the job runner
        can move job.state through inferencing -> novelty_scoring."""
        t0 = time.perf_counter()
        s = self.settings
        stats: dict[str, Any] = {"orchestrator_version": ORCHESTRATOR_VERSION, "sequences": len(sequences)}
        if not sequences:
            return stats
        states = [_SeqState(seq=seq, plan=plan_sequence(seq, s)) for seq in sequences]
        if on_phase:
            on_phase("evidence")

        # 2-4. reference lookups: primary first, expand, then the rest.
        routable = [st for st in states if st.plan.primary_route != LOW_QUALITY_ROUTE]
        if s.orchestrator_reference_enabled:
            self._reference(routable, lambda st: [st.plan.primary_route])
            for st in routable:
                prim = st.refs.get(st.plan.primary_route)
                expand_plan(st.plan, st.seq, prim.to_dict() if prim else None, s)
            self._reference(routable, lambda st: [r for r in st.plan.routes if r not in st.refs])
        else:
            for st in routable:
                self._reference_disabled(st)

        # 5. heads, grouped by route.
        for route, group in self._by_route(states, lambda st: list(st.plan.routes)).items():
            for st, rec in zip(group, self._collect(self.head, route, group)):
                st.heads[route] = rec

        # 6. final route.
        for st in states:
            st.final_route, st.route_steps = select_route(
                st.plan, {r: rec.to_dict() for r, rec in st.heads.items()},
                {r: rec.to_dict() for r, rec in st.refs.items()}, s)

        if on_phase:
            on_phase("scoring")

        # 7. contamination, then novelty, on the final route.
        by_final = self._by_route(states, lambda st: [st.final_route])
        for route, group in by_final.items():
            ctx = [self._contamination_context(st) for st in group]
            for st, rec in zip(group, self._collect(self.contamination, route, group, ctx)):
                st.contamination = rec
        for route, group in by_final.items():
            ctx = [self._novelty_context(st) for st in group]
            for st, rec in zip(group, self._collect(self.novelty, route, group, ctx)):
                st.novelty = rec

        # 8. combine + write back.
        for st in states:
            self._finish(st)

        elapsed = time.perf_counter() - t0
        stats.update(elapsed_seconds=round(elapsed, 3),
                     per_sequence_ms=round(1000.0 * elapsed / len(states), 2))
        return stats

    # -- contexts ----------------------------------------------------------------

    def _head_fields(self, st: _SeqState) -> dict:
        rec = st.heads.get(st.final_route)
        if rec is None or not rec.ok:
            return {"head_ok": False}
        p = rec.payload
        return {"head_ok": True, "result_class": p.get("result_class"), "confidence": p.get("confidence", 0.0),
                "label_scores": p.get("label_scores") or {}, "embedding": rec.artifacts.get("embedding")}

    def _human_genome(self, st: _SeqState) -> dict | None:
        rec = st.refs.get(HUMAN_ROUTE)
        if rec is None or not rec.ok:
            return None
        return (rec.payload or {}).get("human_genome")

    def _contamination_context(self, st: _SeqState) -> dict:
        ctx = dict(st.seq)
        ctx.pop("embedding", None)
        h = self._head_fields(st)
        ctx["result_class"] = h.get("result_class") or ""
        ctx["human_genome"] = self._human_genome(st)
        return ctx

    def _novelty_context(self, st: _SeqState) -> dict:
        ctx = dict(st.seq)
        ctx.update(self._head_fields(st))
        c = st.contamination
        ctx["contamination_score"] = float(c.payload.get("contamination_score", 0.0)) if c is not None and c.ok else 0.0
        return ctx

    # -- output ------------------------------------------------------------------

    def _finish(self, st: _SeqState) -> None:
        s = self.settings
        route = st.final_route or st.plan.primary_route
        head = st.heads.get(route)
        ref = st.refs.get(route)
        c = CombineInput(final_route=route,
                         head=head.to_dict() if head else None,
                         reference=ref.to_dict() if ref else None,
                         contamination=st.contamination.to_dict() if st.contamination else None,
                         novelty=st.novelty.to_dict() if st.novelty else None,
                         reference_enabled=bool(s.orchestrator_reference_enabled))
        decision, steps, nov = combine(c, s, self.novelty_threshold)

        evidence: list[dict] = []
        for r in st.plan.routes:
            for rec in (st.heads.get(r), st.refs.get(r)):
                if rec is not None:
                    evidence.append(rec.to_dict())
        for rec in (st.contamination, st.novelty):
            if rec is not None:
                evidence.append(rec.to_dict())
        trace = plain({
            "orchestrator_version": ORCHESTRATOR_VERSION,
            "plan": st.plan.to_dict(),
            "evidence": evidence,
            "combine": st.route_steps + steps,
        })
        self._write_legacy(st, route, head, decision, nov)
        st.seq["decision"] = plain(decision)
        st.seq["decision_trace"] = trace

    def _write_legacy(self, st: _SeqState, route: str, head: EvidenceRecord | None, decision: dict,
                      nov: dict) -> None:
        """The pre-orchestrator per-sequence fields, now taken from the
        decision, so the API, reports and review queue keep working."""
        seq = st.seq
        router_route = st.plan.primary_route
        seq["router_route"] = router_route
        seq["route"] = route
        probs = seq.get("route_probabilities") or {}
        if route != router_route and route in probs:
            # route_confidence is the router's probability for `route`.
            seq["route_confidence"] = float(probs[route])
        if route != router_route:
            seq["reason_codes"] = list(seq.get("reason_codes") or []) + ["orchestrator_route_changed"]

        hp = head.payload if head is not None else {}
        seq["result_class"] = decision["result_class"]
        seq["predicted_taxon"] = decision["predicted_taxon"]
        seq["confidence"] = float(decision["confidence"]) if decision["confidence"] is not None else 0.0
        seq["model_version_used"] = hp.get("model_version_used") or ("low_quality" if route == LOW_QUALITY_ROUTE else None)
        seq["inference_mode"] = hp.get("inference_mode") or ("low_quality" if route == LOW_QUALITY_ROUTE else "stub")
        seq["stub_reason"] = hp.get("stub_reason")
        seq["label_scores"] = hp.get("label_scores") or {}
        seq["embedding"] = head.artifacts.get("embedding") if head is not None else None

        cp = st.contamination.payload if st.contamination is not None and st.contamination.ok else {}
        seq["contamination_score"] = float(cp.get("contamination_score", 0.0))
        seq["contamination_flagged"] = bool(cp.get("flagged", False))
        seq["contamination_type"] = cp.get("contamination_type")
        seq["contamination_reason_codes"] = list(cp.get("reason_codes") or [])

        np_ = st.novelty.payload if st.novelty is not None and st.novelty.ok else {}
        # novelty_score is the gated score (combiner.py); 0.0 when the scorer
        # did not run (no head prediction), which the reason codes say.
        seq["novelty_score"] = float(nov["final_score"]) if nov.get("final_score") is not None else 0.0
        seq["novelty_raw_score"] = nov.get("raw_score")
        seq["novelty_gate_rule"] = nov.get("gate_rule")
        seq["novelty_level"] = str(_novelty_level(seq["novelty_score"])) if np_ else "none"
        seq["novelty_signals"] = np_.get("signals") or {}
        codes = list(np_.get("reason_codes") or ["novelty_unscored"])
        if nov.get("gate_rule"):
            codes.append(nov["gate_rule"])
        seq["novelty_reason_codes"] = codes
        seq["abyss_recommendation"] = np_.get("abyss_recommendation") or "return_for_full_analysis"
        seq["requires_cloud_confirmation"] = bool(np_.get("requires_cloud_confirmation", False))


def run_orchestrator(sequences: list[dict], settings: Any = None,
                     on_phase: Callable[[str], None] | None = None) -> dict:
    """Convenience wrapper with the real providers (job_runner's entry)."""
    return Orchestrator(settings).run(sequences, on_phase=on_phase)
