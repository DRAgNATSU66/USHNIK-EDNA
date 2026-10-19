"""
The four evidence providers the orchestrator combines (tracker t-1022-1).
Each wraps existing code; none re-implements a scorer.

  route_head        app/inference run_inference() for ANY route, so the
                    orchestrator can run the head of a route other than the
                    router's top pick. One call per sequence, grouped by
                    route by the orchestrator so each route's backbone is
                    loaded once per batch (the loader caches 4 backbones; a
                    batched forward pass belongs in app/inference).
  reference_lookup  ReferenceLookupProvider.lookup() (QNA-020): one batched
                    BLAST/vsearch call per route under the host search lock;
                    on the human route it also carries the GRCh38 evidence.
  contamination     app/novelty/contamination.contamination_score(), plus the
                    GRCh38 HumanGenomeEvidence from the human route's
                    reference lookup when the orchestrator ran it.
  novelty           app/novelty/scorer.score_sequence(). Needs the head's
                    prediction on the same route: without one it is
                    "skipped" (the scorer would read a stub's confidence 0.0
                    as maximal uncertainty and call it novel).

Statuses: see app/evidence/base.py.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable, Sequence

from app.evidence.base import (
    EVIDENCE_OK,
    EVIDENCE_SKIPPED,
    EVIDENCE_UNAVAILABLE,
    EvidenceRecord,
    elapsed_ms_since,
    plain,
    unavailable_records,
)

logger = logging.getLogger(__name__)

LOW_QUALITY_ROUTE = "low_quality"
HUMAN_ROUTE = "human_domestic_contamination"


def _context_at(context: Sequence[dict] | None, i: int) -> dict:
    if context is None or i >= len(context) or context[i] is None:
        return {}
    return context[i]


# ---------------------------------------------------------------------------
# route head
# ---------------------------------------------------------------------------

class RouteHeadProvider:
    """The classifier head of `route`, whatever the router picked."""

    name = "route_head"
    version = "1.0"

    def __init__(self, infer_fn: Callable[..., Any] | None = None):
        # infer_fn(sequence_id, sequence, route) -> PredictionResult; tests inject a fake.
        if infer_fn is None:
            from app.inference import run_inference
            infer_fn = run_inference
        self._infer = infer_fn

    def collect(self, items: Sequence[tuple[str, str]], route: str,
                context: Sequence[dict] | None = None) -> list[EvidenceRecord]:
        out: list[EvidenceRecord] = []
        for sid, seq in items:
            t0 = time.perf_counter()
            if route == LOW_QUALITY_ROUTE:
                out.append(EvidenceRecord(self.name, self.version, str(sid), route, EVIDENCE_SKIPPED,
                                          reason="low_quality route: no head runs"))
                continue
            try:
                pred = self._infer(sequence_id=str(sid), sequence=seq, route=route)
            except Exception as exc:  # never raise for one sequence
                logger.warning("route_head %s on %s failed: %r", route, sid, exc)
                out.append(EvidenceRecord(self.name, self.version, str(sid), route, EVIDENCE_UNAVAILABLE,
                                          reason=f"inference raised {type(exc).__name__}: {exc}"[:300],
                                          elapsed_ms=elapsed_ms_since(t0)))
                continue
            mode = str(pred.inference_mode)
            payload = plain({
                "result_class": str(pred.result_class),
                "confidence": round(float(pred.confidence), 4),
                "label_scores": {str(k): round(float(v), 4) for k, v in (pred.label_scores or {}).items()},
                "model_version_used": pred.model_version_used,
                "inference_mode": mode,
                "stub_reason": pred.stub_reason,
            })
            if mode == "model":
                status, reason = EVIDENCE_OK, None
            elif mode == "low_quality":
                status, reason = EVIDENCE_SKIPPED, "low_quality route: no head runs"
            else:
                status, reason = EVIDENCE_UNAVAILABLE, f"no model prediction for {route}: {pred.stub_reason or 'stub'}"
            out.append(EvidenceRecord(self.name, self.version, str(sid), route, status, payload=payload,
                                      elapsed_ms=elapsed_ms_since(t0), reason=reason,
                                      artifacts={"embedding": pred.embedding}))
        return out


# ---------------------------------------------------------------------------
# reference lookup
# ---------------------------------------------------------------------------

_HIT_FIELDS = ("accession", "source", "marker", "identity", "query_coverage", "alignment_length", "taxon", "rank")


class ReferenceEvidenceProvider:
    """Adapter from ReferenceLookupProvider (QNA-020) to the common record."""

    name = "reference_lookup"
    version = "1.0"

    def __init__(self, lookup_provider: Any = None, *, max_hits: int | None = None, settings: Any = None):
        if settings is None:
            from app.config import get_worker_settings
            settings = get_worker_settings()
        self._settings = settings
        self._lookup = lookup_provider
        self.max_hits = settings.orchestrator_trace_max_hits if max_hits is None else max_hits

    @property
    def lookup_provider(self) -> Any:
        if self._lookup is None:
            from app.evidence.reference_lookup import ReferenceLookupProvider
            self._lookup = ReferenceLookupProvider(self._settings)
        return self._lookup

    def collect(self, items: Sequence[tuple[str, str]], route: str,
                context: Sequence[dict] | None = None) -> list[EvidenceRecord]:
        if not items:
            return []
        t0 = time.perf_counter()
        if route == LOW_QUALITY_ROUTE:
            return [EvidenceRecord(self.name, self.version, str(sid), route, EVIDENCE_SKIPPED,
                                   reason="low_quality route: no reference lookup") for sid, _ in items]
        try:
            evidence = self.lookup_provider.lookup(list(items), route)
        except Exception as exc:  # the lookup is written not to raise; belt and braces
            logger.warning("reference lookup on %s raised: %r", route, exc)
            return unavailable_records(self, items, route, f"reference lookup raised {type(exc).__name__}: {exc}"[:300],
                                       elapsed_ms_since(t0))
        per = elapsed_ms_since(t0) / len(items)
        out: list[EvidenceRecord] = []
        for (sid, _), ev in zip(items, evidence):
            payload = self.compact(ev.to_dict())
            status = EVIDENCE_OK if ev.available else EVIDENCE_UNAVAILABLE
            out.append(EvidenceRecord(self.name, self.version, str(sid), route, status, payload=payload,
                                      elapsed_ms=per, reason=None if ev.available else ev.reason))
        return out

    def compact(self, d: dict) -> dict:
        """The bounded part of ReferenceEvidence.to_dict() kept in a trace."""
        a = d.get("assignment") or {}
        run = d.get("run") or {}
        return plain({
            "status": d.get("status"),
            "taxon": d.get("taxon"),
            "rank": d.get("rank"),
            "identity": d.get("identity"),
            "query_coverage": a.get("query_coverage"),
            "identity_rank": a.get("identity_rank"),
            "lineage": a.get("lineage") or {},
            "tied_hits": a.get("tied_hits"),
            "tied_taxa": a.get("tied_taxa"),
            "lca_applied": a.get("lca_applied"),
            "reason": d.get("reason"),
            "hits": [{k: h.get(k) for k in _HIT_FIELDS} for h in (d.get("hits") or [])[: self.max_hits]],
            "method": d.get("method"),
            "reference_db": d.get("reference_db"),
            "reference_db_version": d.get("reference_db_version"),
            "reference_db_sha256": d.get("reference_db_sha256"),
            "batch_seconds": run.get("elapsed_seconds"),
            "human_genome": d.get("human_genome"),
        })


# ---------------------------------------------------------------------------
# contamination
# ---------------------------------------------------------------------------

class ContaminationProvider:
    """Heuristic contamination score plus GRCh38 evidence.

    context[i] is the sequence's pipeline dict (sequence, gc_ratio, length,
    fallback_routes, ...) with "result_class" from the head of `route` and,
    when the human route's reference lookup ran, "human_genome" (the
    HumanGenomeEvidence dict). A GRCh38 hit that the lookup marked as
    contamination (>= REFERENCE_HUMAN_GENOME_IDENTITY over the coverage
    floor, no better non-human assignment) flags the sequence as human_dna
    even when the heuristic does not."""

    name = "contamination"
    version = "1.0"

    def __init__(self, score_fn: Callable[[dict], Any] | None = None):
        if score_fn is None:
            from app.novelty.contamination import contamination_score
            score_fn = contamination_score
        self._score = score_fn

    def collect(self, items: Sequence[tuple[str, str]], route: str,
                context: Sequence[dict] | None = None) -> list[EvidenceRecord]:
        out: list[EvidenceRecord] = []
        for i, (sid, seq) in enumerate(items):
            t0 = time.perf_counter()
            ctx = dict(_context_at(context, i))
            ctx.update(sequence_id=str(sid), sequence=seq, route=route)
            try:
                cr = self._score(ctx)
            except Exception as exc:
                out.append(EvidenceRecord(self.name, self.version, str(sid), route, EVIDENCE_UNAVAILABLE,
                                          reason=f"contamination scorer raised {type(exc).__name__}: {exc}"[:300],
                                          elapsed_ms=elapsed_ms_since(t0)))
                continue
            hg = ctx.get("human_genome") or None
            grch38 = bool(hg and hg.get("contamination"))
            flagged = bool(cr.is_flagged) or grch38
            ctype = "human_dna" if grch38 else cr.contamination_type
            codes = list(cr.reason_codes)
            if grch38:
                codes.append("grch38_human_hit")
                if "contamination_flagged" not in codes:
                    codes.append("contamination_flagged")
                codes = [c for c in codes if c != "clean_sequence"]
            payload = plain({
                "contamination_score": round(float(cr.contamination_score), 4),
                "heuristic_flagged": bool(cr.is_flagged),
                "grch38_contamination": grch38,
                "flagged": flagged,
                "contamination_type": ctype,
                "signals": {k: round(float(v), 4) for k, v in cr.signals.items()},
                "reason_codes": codes,
                "human_genome": hg,
            })
            out.append(EvidenceRecord(self.name, self.version, str(sid), route, EVIDENCE_OK, payload=payload,
                                      elapsed_ms=elapsed_ms_since(t0)))
        return out


# ---------------------------------------------------------------------------
# novelty
# ---------------------------------------------------------------------------

class NoveltyProvider:
    """The multi-signal novelty scorer, on the head prediction of `route`.

    context[i] must carry the head's result_class, confidence, label_scores
    (and embedding when there is one) for this route, plus the contamination
    provider's contamination_score; "head_ok" False -> skipped."""

    name = "novelty"
    version = "1.0"

    def __init__(self, score_fn: Callable[[dict], Any] | None = None):
        if score_fn is None:
            from app.novelty.scorer import score_sequence
            score_fn = score_sequence
        self._score = score_fn

    def collect(self, items: Sequence[tuple[str, str]], route: str,
                context: Sequence[dict] | None = None) -> list[EvidenceRecord]:
        out: list[EvidenceRecord] = []
        for i, (sid, seq) in enumerate(items):
            t0 = time.perf_counter()
            ctx = dict(_context_at(context, i))
            # The scorer itself scores the low_quality route (0.0, "resample").
            if route != LOW_QUALITY_ROUTE and not ctx.get("head_ok"):
                out.append(EvidenceRecord(self.name, self.version, str(sid), route, EVIDENCE_SKIPPED,
                                          reason=f"no model prediction on {route}: the novelty scorer needs one"))
                continue
            ctx.update(sequence_id=str(sid), sequence=seq, route=route)
            try:
                nr = self._score(ctx)
            except Exception as exc:
                out.append(EvidenceRecord(self.name, self.version, str(sid), route, EVIDENCE_UNAVAILABLE,
                                          reason=f"novelty scorer raised {type(exc).__name__}: {exc}"[:300],
                                          elapsed_ms=elapsed_ms_since(t0)))
                continue
            payload = plain({
                "novelty_score": round(float(nr.novelty_score), 4),
                "novelty_level": str(nr.novelty_level),
                "signals": {k: round(float(v), 4) for k, v in nr.signals.items()},
                "reason_codes": list(nr.reason_codes),
                "abyss_recommendation": str(nr.abyss_recommendation),
                "requires_cloud_confirmation": bool(nr.requires_cloud_confirmation),
            })
            out.append(EvidenceRecord(self.name, self.version, str(sid), route, EVIDENCE_OK, payload=payload,
                                      elapsed_ms=elapsed_ms_since(t0)))
        return out
