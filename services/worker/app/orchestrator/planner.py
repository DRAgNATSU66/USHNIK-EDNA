"""
Planner: which routes' evidence to collect for one sequence.

Router v2 is confidently wrong on 368 of its 701 test errors (QNA-021 Q4), so
planning several routes only when the router is unsure would miss half its
mistakes. A wide plan is triggered by ANY of these rules (PLAN_RULES, in
order; every rule that fires is recorded in the plan):

  rule                  fires when                                    setting
  --------------------  --------------------------------------------  ---------------------------------
  router_uncalibrated   the heuristic router decided (its scores are  -
                        not calibrated probabilities)
  low_confidence        top-1 probability < threshold                 ORCHESTRATOR_CONFIDENCE_THRESHOLD
  narrow_margin         top-1 minus top-2 probability < threshold     ORCHESTRATOR_MARGIN_THRESHOLD
  weak_route            top-1 route is in the weak-route set          ORCHESTRATOR_WEAK_ROUTES

A wide plan is the router's top ORCHESTRATOR_MAX_ROUTES routes by
probability, not only those above some floor: when the router is
confidently wrong the true route's probability is small, and on dev the true
route is ranked 2nd for 385 and 3rd for 139 of 673 errors. No rule fires ->
"confident_router", one route. The QC gate's low_quality route is planned
alone ("low_quality_gate") and never expanded.

Second pass (expand_plan, after the primary route's reference lookup, when
ORCHESTRATOR_REFERENCE_EXPANSION is on and the cap leaves room):

  reference_miss            the primary route's reference DB has no assignable hit
                            (no_hit / below_threshold / no_consensus) -> add the
                            router's next-ranked route not yet planned
  reference_lineage_route   the primary route's best assignment has a lineage
                            that maps to another route (lineage_to_route) ->
                            add that route

Pure functions; the orchestrator does the I/O.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from app.orchestrator.lineage import implied_route

LOW_QUALITY_ROUTE = "low_quality"
REFERENCE_MISS_STATUSES = frozenset({"no_hit", "below_threshold", "no_consensus"})


@dataclass
class RouterView:
    """What the planner reads from the routing stage's sequence dict."""
    primary: str
    ranked: list[tuple[str, float]]   # every route, descending probability
    method: str | None
    version: str | None
    calibrated: bool

    @property
    def top_probability(self) -> float:
        return self.ranked[0][1] if self.ranked else 0.0

    @property
    def margin(self) -> float:
        if len(self.ranked) < 2:
            return self.top_probability
        return self.ranked[0][1] - self.ranked[1][1]

    @classmethod
    def from_sequence(cls, seq: dict) -> "RouterView":
        primary = str(seq.get("route") or "misc_unknown")
        probs = seq.get("route_probabilities") or {}
        ranked = sorted(((str(r), float(p)) for r, p in probs.items() if r != LOW_QUALITY_ROUTE),
                        key=lambda rp: (-rp[1], rp[0]))
        if not ranked and primary != LOW_QUALITY_ROUTE:
            # No probabilities (old result shape): the primary at its
            # confidence, then the router's fallbacks with unknown probability.
            ranked = [(primary, float(seq.get("route_confidence") or 0.0))]
            ranked += [(str(r), 0.0) for r in seq.get("fallback_routes") or [] if r != primary]
        # The primary leads even if a tie put another route first.
        if ranked and ranked[0][0] != primary and primary != LOW_QUALITY_ROUTE:
            ranked = sorted(ranked, key=lambda rp: rp[0] != primary)
        return cls(primary=primary, ranked=ranked, method=seq.get("router_method"),
                   version=seq.get("router_version"),
                   calibrated=bool(seq.get("route_probabilities_calibrated")))


@dataclass
class Plan:
    primary_route: str
    routes: list[str]
    rules_fired: list[dict] = field(default_factory=list)
    router: dict = field(default_factory=dict)
    max_routes: int = 1

    @property
    def wide(self) -> bool:
        return len(self.routes) > 1

    def to_dict(self) -> dict:
        return {
            "primary_route": self.primary_route,
            "routes": list(self.routes),
            "rules_fired": [dict(r) for r in self.rules_fired],
            "router": dict(self.router),
            "max_routes": self.max_routes,
        }


# (name, predicate(view, settings) -> detail string or None)
PlanRule = tuple[str, Callable[[RouterView, Any], "str | None"]]


def _uncalibrated(v: RouterView, s: Any) -> str | None:
    if v.method in ("heuristic", "heuristic_fallback") or not v.calibrated:
        return f"router method {v.method or 'unknown'}: probabilities are not calibrated"
    return None


def _low_confidence(v: RouterView, s: Any) -> str | None:
    t = s.orchestrator_confidence_threshold
    return f"top probability {v.top_probability:.4f} < {t:g}" if v.top_probability < t else None


def _narrow_margin(v: RouterView, s: Any) -> str | None:
    t = s.orchestrator_margin_threshold
    return f"top-2 margin {v.margin:.4f} < {t:g}" if v.margin < t else None


def _weak_route(v: RouterView, s: Any) -> str | None:
    weak = set(s.orchestrator_weak_routes or [])
    return f"{v.primary} is a weak route for the router" if v.primary in weak else None


PLAN_RULES: list[PlanRule] = [
    ("router_uncalibrated", _uncalibrated),
    ("low_confidence", _low_confidence),
    ("narrow_margin", _narrow_margin),
    ("weak_route", _weak_route),
]


def plan_sequence(seq: dict, settings: Any) -> Plan:
    v = RouterView.from_sequence(seq)
    cap = max(1, int(settings.orchestrator_max_routes))
    router = {
        "method": v.method,
        "version": v.version,
        "calibrated": v.calibrated,
        "top_probability": round(v.top_probability, 4),
        "margin": round(v.margin, 4),
        "ranked": [[r, round(p, 4)] for r, p in v.ranked[:max(cap + 1, 3)]],
    }
    if v.primary == LOW_QUALITY_ROUTE:
        return Plan(primary_route=v.primary, routes=[v.primary], router=router, max_routes=cap,
                    rules_fired=[{"rule": "low_quality_gate", "stage": "router",
                                  "detail": "QC gate routed the sequence to low_quality", "added": []}])
    fired = [(name, detail) for name, pred in PLAN_RULES if (detail := pred(v, settings))]
    routes = [v.primary]
    if fired and cap > 1:
        for r, _ in v.ranked:
            if len(routes) >= cap:
                break
            if r not in routes:
                routes.append(r)
    added = routes[1:]
    if not fired:
        rules = [{"rule": "confident_router", "stage": "router",
                  "detail": "no wide-plan rule fired", "added": []}]
    else:
        # The routes a wide plan adds are the same whichever rule fired, so
        # the first rule lists them and the rest say they also fired.
        rules = [{"rule": name, "stage": "router", "detail": detail, "added": added if i == 0 else []}
                 for i, (name, detail) in enumerate(fired)]
        if cap <= 1:
            rules.append({"rule": "route_cap", "stage": "router",
                          "detail": "ORCHESTRATOR_MAX_ROUTES=1: no extra route planned", "added": []})
    return Plan(primary_route=v.primary, routes=routes, rules_fired=rules, router=router, max_routes=cap)


def expand_plan(plan: Plan, seq: dict, primary_reference: dict | None, settings: Any) -> list[str]:
    """Second pass on the primary route's reference evidence (an
    EvidenceRecord.to_dict()). Appends routes to plan.routes and records the
    rule; returns the routes added."""
    if plan.primary_route == LOW_QUALITY_ROUTE or not settings.orchestrator_reference_expansion:
        return []
    if not primary_reference or primary_reference.get("status") != "ok":
        return []
    payload = primary_reference.get("payload") or {}
    status = payload.get("status")
    wanted: list[tuple[str, str, str]] = []   # (rule, route, detail)
    if status in REFERENCE_MISS_STATUSES:
        v = RouterView.from_sequence(seq)
        nxt = next((r for r, _ in v.ranked if r not in plan.routes), None)
        if nxt:
            wanted.append(("reference_miss", nxt,
                           f"{plan.primary_route} reference: {status}; adding the router's next route {nxt}"))
    elif status == "assigned":
        imp = implied_route(payload.get("lineage"))
        if imp and imp != plan.primary_route and imp not in plan.routes:
            wanted.append(("reference_lineage_route", imp,
                           f"{plan.primary_route} reference hit {payload.get('taxon')} ({payload.get('rank')}) "
                           f"has a lineage of route {imp}"))
    added: list[str] = []
    for rule, route, detail in wanted:
        if len(plan.routes) >= plan.max_routes:
            plan.rules_fired.append({"rule": rule, "stage": "post_reference", "detail": detail + " -- not added, route cap reached",
                                     "added": []})
            continue
        plan.routes.append(route)
        added.append(route)
        plan.rules_fired.append({"rule": rule, "stage": "post_reference", "detail": detail, "added": [route]})
    return added
