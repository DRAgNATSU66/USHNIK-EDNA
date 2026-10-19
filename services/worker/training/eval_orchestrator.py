"""
Held-out smoke measurement of the Day 9 orchestrator (tracker t-1022-2;
decision Q7). Two modes, run from services/worker/ with SYNTHVEDA_DATA_ROOT
set:

  python -m training.eval_orchestrator planner --split dev --out <json>
      Router only (cheap): routes every row of processed/<route>/<split>.csv
      with the served router, then for a grid of ORCHESTRATOR_MARGIN_THRESHOLD
      values (confidence and weak-route rules on, ORCHESTRATOR_MAX_ROUTES
      routes per wide plan) counts how many router errors get the true route
      into the plan and what share of sequences is planned wide. This is how
      the margin default was chosen; it reads dev only, never test.

  python -m training.eval_orchestrator run [--split test] --per-route 100 --seed 1019 --out <json>
      The full orchestrator with the real served heads (GPU when present) and
      the reference DB (CURRENT), over a seeded sample of N test rows per
      route. The rows go through the job's own stages: a FASTA file ->
      app.fastx_parser -> job_runner._stage_qc -> job_runner._stage_route ->
      Orchestrator.run (one batch, as one upload). The summary has, per true
      route: plan breadth and rules fired, head-vs-reference agreement on the
      final route, router-vs-reference-lineage disagreements, final
      result_class vs label (and the legacy router+head answer on the same
      rows), final_route accuracy vs router-only accuracy, novelty flags the
      reference suppressed or downgraded (split by label), plant names capped
      at genus, contamination flags (by label; human_dna by final route; GRCh38
      hits beaten by a closer assignment), wall time per sequence, peak GPU
      memory, peak RSS, and the BSON size of the stored trace.

The processed CSVs carry sequence,label only; the true route is the
directory the row came from (the route training.routing assigned it).
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import random
import resource
import statistics
import sys
import tempfile
import time
from collections import Counter, defaultdict
from pathlib import Path

ROUTES = ("fish", "plant", "animal_general", "bacteria_pathogen", "human_domestic_contamination", "misc_unknown")


def _data_root() -> Path:
    return Path(os.environ.get("SYNTHVEDA_DATA_ROOT", "synthveda-data")).resolve()


def _read(route: str, split: str) -> list[tuple[int, str, str]]:
    csv.field_size_limit(sys.maxsize)
    with open(_data_root() / "processed" / route / f"{split}.csv", encoding="utf-8", newline="") as fh:
        return [(i, r["sequence"].strip().upper(), r["label"]) for i, r in enumerate(csv.DictReader(fh))]


def _write_fasta(path: Path, rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(f">{r['id']}\n{r['sequence']}\n")


def _pipeline_dicts(rows: list[dict]) -> list[dict]:
    """FASTA -> parser -> job_runner QC and routing stages, as a job runs them."""
    from app import job_runner
    from app.fastx_parser import parse_and_batch_auto

    with tempfile.TemporaryDirectory(prefix="synthveda-evalorch-") as tmp:
        fa = Path(tmp) / "sample.fasta"
        _write_fasta(fa, rows)
        batches, _ = parse_and_batch_auto(str(fa), batch_size=1000, min_length=10)
    seqs = [rec.__dict__ for b in batches for rec in b]
    seqs = asyncio.run(job_runner._stage_qc(seqs))
    return asyncio.run(job_runner._stage_route(seqs))


# ---------------------------------------------------------------------------
# planner sweep (dev)
# ---------------------------------------------------------------------------

def cmd_planner(args: argparse.Namespace) -> None:
    from app.config import get_worker_settings
    from app.orchestrator.planner import plan_sequence

    base = get_worker_settings()
    rows: list[dict] = []
    for route in ROUTES:
        for i, seq, label in _read(route, args.split):
            rows.append({"id": f"{route}:{args.split}:{i}", "sequence": seq, "label": label, "true_route": route})
    truth = {r["id"]: r["true_route"] for r in rows}
    by_label = {r["id"]: r["label"] for r in rows}
    t0 = time.perf_counter()
    all_seqs = _pipeline_dicts(rows)
    route_s = time.perf_counter() - t0
    # The QC gate's low_quality route is planned alone by design; the sweep
    # is over the sequences the router actually placed.
    gated = [s for s in all_seqs if s["route"] == "low_quality"]
    seqs = [s for s in all_seqs if s["route"] != "low_quality"]
    errors = [s for s in seqs if s["route"] != truth[s["sequence_id"]]]
    n_conf_errors = sum(1 for s in errors if float(s.get("route_confidence") or 0) >= base.orchestrator_confidence_threshold)
    # Rank of the true route among the router's probabilities, for the errors.
    rank = Counter()
    for s in errors:
        ranked = sorted((s.get("route_probabilities") or {}).items(), key=lambda kv: -kv[1])
        names = [r for r, _ in ranked]
        rank[names.index(truth[s["sequence_id"]]) + 1 if truth[s["sequence_id"]] in names else "absent"] += 1

    def sweep(**over) -> dict:
        st = base.model_copy(update=over)
        wide = covered = 0
        for s in seqs:
            p = plan_sequence(s, st)
            wide += p.wide
            if s["route"] != truth[s["sequence_id"]] and truth[s["sequence_id"]] in p.routes:
                covered += 1
        return {"wide_share": round(wide / len(seqs), 4), "errors_with_true_route_in_plan": covered}

    grid = {}
    for m in (0.0, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8):
        grid[f"margin<{m}"] = sweep(orchestrator_margin_threshold=m)
    out = {
        "split": args.split, "input_rows": len(rows), "after_qc": len(all_seqs),
        "qc_gated_low_quality": len(gated),
        "qc_gated_labels": dict(Counter(by_label[s["sequence_id"]] for s in gated)),
        "sequences": len(seqs),
        "router_errors": len(errors), "router_accuracy": round(1 - len(errors) / len(seqs), 4),
        "router_errors_at_or_above_confidence_threshold": n_conf_errors,
        "router_seconds": round(route_s, 1),
        "true_route_rank_among_errors": {str(k): v for k, v in sorted(rank.items(), key=lambda kv: str(kv[0]))},
        "errors_by_predicted_route": dict(Counter(s["route"] for s in errors)),
        "settings": {"confidence_threshold": base.orchestrator_confidence_threshold,
                     "weak_routes": base.orchestrator_weak_routes, "max_routes": base.orchestrator_max_routes},
        "confidence_rule_only": sweep(orchestrator_margin_threshold=0.0, orchestrator_weak_routes=[]),
        "confidence_and_weak_route_only": sweep(orchestrator_margin_threshold=0.0),
        "grid_all_rules": grid,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))


# ---------------------------------------------------------------------------
# full run (test sample)
# ---------------------------------------------------------------------------

class _RecordingLookup:
    """Wraps ReferenceLookupProvider to keep each batch's run info (search
    seconds, peak RSS of the search process), which the trace leaves out."""

    def __init__(self, inner):
        self.inner = inner
        self.runs: list[dict] = []

    def lookup(self, items, route):
        ev = self.inner.lookup(items, route)
        if ev:
            self.runs.append({"route": route, "n": len(items), "available": ev[0].available,
                              "reason": ev[0].reason, **(ev[0].run or {})})
        return ev


def _gpu_peak_mb() -> float | None:
    try:
        import torch
        if torch.cuda.is_available():
            return round(torch.cuda.max_memory_allocated() / 2**20, 1)
    except ImportError:
        pass
    return None


def _steps(seq: dict, step: str | None = None) -> list[dict]:
    return [c for c in seq["decision_trace"]["combine"] if step is None or c["step"] == step]


def _ev(seq: dict, provider: str, route: str | None = None) -> dict | None:
    for e in seq["decision_trace"]["evidence"]:
        if e["provider"] == provider and (route is None or e["route"] == route):
            return e
    return None


def cmd_run(args: argparse.Namespace) -> None:
    import bson

    from app.config import get_worker_settings
    from app.evidence.providers import ReferenceEvidenceProvider
    from app.evidence.reference_lookup import ReferenceLookupProvider
    from app.orchestrator import ORCHESTRATOR_VERSION, Orchestrator

    settings = get_worker_settings()
    rng = random.Random(args.seed)
    rows: list[dict] = []
    for route in ROUTES:
        pool = _read(route, args.split)
        for i, seq, label in sorted(rng.sample(pool, min(args.per_route, len(pool)))):
            rows.append({"id": f"{route}:{args.split}:{i}", "sequence": seq, "label": label, "true_route": route})
    by_id = {r["id"]: r for r in rows}

    t0 = time.perf_counter()
    seqs = _pipeline_dicts(rows)
    route_s = time.perf_counter() - t0
    recording = _RecordingLookup(ReferenceLookupProvider(settings))
    orch = Orchestrator(settings, reference=ReferenceEvidenceProvider(recording, settings=settings))
    phases: dict[str, float] = {}
    t1 = time.perf_counter()
    stats = orch.run(seqs, on_phase=lambda p: phases.setdefault(p, round(time.perf_counter() - t1, 2)))
    orch_s = time.perf_counter() - t1

    # Every trace must be BSON-encodable; measure its size.
    sizes = [len(bson.BSON.encode({"t": s["decision_trace"], "d": s["decision"]})) for s in seqs]

    per: dict[str, dict] = {}
    provider_ms: dict[str, list[float]] = defaultdict(list)
    for s in seqs:
        for e in s["decision_trace"]["evidence"]:
            provider_ms[e["provider"]].append(e["elapsed_ms"])
    grouped: dict[str, list[dict]] = defaultdict(list)
    for s in seqs:
        grouped[by_id[s["sequence_id"]]["true_route"]].append(s)

    def summarise(group: list[dict]) -> dict:
        n = len(group)
        truth = [by_id[s["sequence_id"]] for s in group]
        rules = Counter()
        post_rules = Counter()
        for s in group:
            for r in s["decision_trace"]["plan"]["rules_fired"]:
                (rules if r["stage"] == "router" else post_rules)[r["rule"]] += 1
        router_ok = sum(s["router_route"] == t["true_route"] for s, t in zip(group, truth))
        final_ok = sum(s["route"] == t["true_route"] for s, t in zip(group, truth))
        in_plan = sum(t["true_route"] in s["decision_trace"]["plan"]["routes"] for s, t in zip(group, truth))
        changed = [(s, t) for s, t in zip(group, truth) if s["route"] != s["router_route"]]
        route_rule = Counter(c["rule"] for s in group for c in _steps(s, "route"))
        # head (final route) vs reference (final route)
        xtab = Counter()
        agree = disagree = 0
        for s in group:
            h = _ev(s, "route_head", s["route"])
            r = _ev(s, "reference_lookup", s["route"])
            hc = (h or {}).get("payload", {}).get("result_class") if h and h["status"] == "ok" else f"head_{(h or {}).get('status', 'none')}"
            rs = (r or {}).get("payload", {}).get("status") if r and r["status"] == "ok" else f"ref_{(r or {}).get('status', 'none')}"
            rr = (r or {}).get("payload", {}).get("rank") if rs == "assigned" else None
            xtab[f"{hc} | {rs}{'/' + rr if rr else ''}"] += 1
            if hc == "known_species" and rs == "assigned":
                agree += 1
            elif hc == "possible_novelty" and rs in ("no_hit", "below_threshold"):
                agree += 1
            elif hc == "known_species" and rs in ("no_hit", "below_threshold", "no_consensus"):
                disagree += 1
            elif hc == "possible_novelty" and rs == "assigned" and rr == "species":
                disagree += 1
        lineage_dis = [s for s in group if any(c["rule"] == "reference_lineage_vs_router" for c in _steps(s, "disagreement"))]
        lineage_true = sum(any(c["outcome"]["implied_route"] == by_id[s["sequence_id"]]["true_route"]
                               for c in _steps(s, "disagreement") if c["rule"] == "reference_lineage_vs_router")
                           for s in lineage_dis)
        heads_dis = sum(any(c["rule"] == "heads_disagree" for c in _steps(s, "disagreement")) for s in group)
        # classes
        conf = Counter((t["label"], s["result_class"]) for s, t in zip(group, truth))
        cls_ok = sum(s["result_class"] == t["label"] for s, t in zip(group, truth))
        legacy = []
        for s, t in zip(group, truth):
            h = _ev(s, "route_head", s["router_route"])
            legacy.append(h["payload"]["result_class"] if h and h.get("payload", {}).get("result_class") and h["status"] == "ok"
                          else ("low_quality_unusable" if s["router_route"] == "low_quality" else "unknown_needs_online_confirmation"))
        legacy_ok = sum(lc == t["label"] for lc, t in zip(legacy, truth))
        nov = [next((c["outcome"] for c in _steps(s, "novelty")), {}) or {} for s in group]
        suppressed = Counter(t["label"] for o, t in zip(nov, truth) if o.get("suppressed_by_reference"))
        downgraded = Counter(t["label"] for o, t in zip(nov, truth) if o.get("downgraded_by_reference"))
        raw_flags = Counter(t["label"] for o, t in zip(nov, truth) if o.get("raw_flag"))
        final_flags = Counter(t["label"] for o, t in zip(nov, truth) if o.get("final_flag"))
        class_rules = Counter(c["rule"] for s in group for c in _steps(s, "class"))
        capped = sum(any(c["rule"] == "genus_cap" for c in _steps(s, "taxon")) for s in group)
        heads_only = sum(any(c["rule"] == "heads_only" for c in _steps(s, "taxon")) for s in group)
        named = Counter(s["decision"]["taxon_rank"] for s in group if s["decision"]["predicted_taxon"])
        # contamination as stored in the legacy fields (these drive the
        # auto_contamination review), split by label and by final route
        cflag = [(s, t) for s, t in zip(group, truth) if s.get("contamination_flagged")]
        human_dna = [(s, t) for s, t in cflag if s.get("contamination_type") == "human_dna"]
        beaten = sum("grch38_beaten_by_closer_assignment" in (s.get("contamination_reason_codes") or []) for s in group)
        return {
            "n": n,
            "labels": dict(Counter(t["label"] for t in truth)),
            "routed_low_quality": sum(s["router_route"] == "low_quality" for s in group),
            "plan": {
                "wide": sum(len(s["decision_trace"]["plan"]["routes"]) > 1 for s in group),
                "wide_share": round(sum(len(s["decision_trace"]["plan"]["routes"]) > 1 for s in group) / n, 4),
                "routes_planned_mean": round(statistics.mean(len(s["decision_trace"]["plan"]["routes"]) for s in group), 3),
                "rules_fired_router_stage": dict(rules),
                "rules_fired_post_reference": dict(post_rules),
                "true_route_in_plan": in_plan,
            },
            "route": {
                "router_correct": router_ok, "router_accuracy": round(router_ok / n, 4),
                "final_correct": final_ok, "final_accuracy": round(final_ok / n, 4),
                "final_route_changed": len(changed),
                "changed_wrong_to_right": sum(s["router_route"] != t["true_route"] and s["route"] == t["true_route"] for s, t in changed),
                "changed_right_to_wrong": sum(s["router_route"] == t["true_route"] and s["route"] != t["true_route"] for s, t in changed),
                "changed_wrong_to_wrong": sum(s["router_route"] != t["true_route"] and s["route"] != t["true_route"] for s, t in changed),
                "route_rule": dict(route_rule),
            },
            "head_vs_reference_final_route": {"agree": agree, "disagree": disagree,
                                              "crosstab_head_class|reference_status": dict(xtab.most_common())},
            "disagreements": {"router_vs_reference_lineage": len(lineage_dis),
                              "of_which_lineage_implies_true_route": lineage_true,
                              "heads_disagree": heads_dis},
            "result_class": {
                "final_correct": cls_ok, "final_accuracy": round(cls_ok / n, 4),
                "legacy_router_head_correct": legacy_ok, "legacy_router_head_accuracy": round(legacy_ok / n, 4),
                "final_distribution": dict(Counter(s["result_class"] for s in group)),
                "confusion_label->final": {f"{a} -> {b}": v for (a, b), v in sorted(conf.items())},
                "class_rule": dict(class_rules),
            },
            "novelty": {"raw_flags_by_label": dict(raw_flags), "final_flags_by_label": dict(final_flags),
                        "suppressed_by_reference_by_label": dict(suppressed),
                        "downgraded_by_reference_by_label": dict(downgraded)},
            "contamination": {"flagged": len(cflag), "flagged_by_label": dict(Counter(t["label"] for _, t in cflag)),
                              "human_dna": len(human_dna),
                              "human_dna_by_final_route": dict(Counter(s["route"] for s, _ in human_dna)),
                              "grch38_beaten_by_closer_assignment": beaten},
            "taxon": {"named": sum(named.values()), "named_by_rank": dict(named),
                      "plant_names_capped_at_genus": capped, "heads_only_no_reference": heads_only},
        }

    for route in ROUTES:
        if grouped.get(route):
            per[route] = summarise(grouped[route])
    overall = summarise(seqs)
    out = {
        "orchestrator_version": ORCHESTRATOR_VERSION,
        "date": time.strftime("%Y-%m-%d"),
        "command": " ".join(["python -m training.eval_orchestrator"] + sys.argv[1:]),
        "sample": {"split": args.split, "per_route": args.per_route, "seed": args.seed,
                   "input_rows": len(rows), "after_qc": len(seqs)},
        "settings": {k: v for k, v in settings.model_dump().items() if k.startswith(("orchestrator_", "reference_"))
                     and "key" not in k},
        "reference_db_version": next((e["payload"].get("reference_db_version") for s in seqs
                                      for e in s["decision_trace"]["evidence"]
                                      if e["provider"] == "reference_lookup" and e["status"] == "ok"), None),
        "models": dict(Counter(f"{s['route']}:{s.get('model_version_used')}" for s in seqs)),
        "timing": {"routing_seconds": round(route_s, 2), "orchestrator_seconds": round(orch_s, 2),
                   "orchestrator_ms_per_sequence": round(1000 * orch_s / max(1, len(seqs)), 1),
                   "phase_started_at_seconds": phases,
                   "provider_ms_sum": {k: round(sum(v), 1) for k, v in provider_ms.items()},
                   "reference_batches": recording.runs, "stats": stats},
        "memory": {"peak_gpu_allocated_mb": _gpu_peak_mb(),
                   "peak_rss_mb_python": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
                   "peak_rss_mb_search_process": max((r.get("peak_rss_mb") or 0) for r in recording.runs) if recording.runs else None,
                   "peak_rss_mb_grch38": max((r.get("grch38_peak_rss_mb") or 0) for r in recording.runs) if recording.runs else None},
        "trace_bson_bytes": {"mean": round(statistics.mean(sizes)), "max": max(sizes)},
        "overall": overall,
        "per_route": per,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2, default=str))
    if args.rows_out:
        with open(args.rows_out, "w", encoding="utf-8") as fh:
            for s in seqs:
                t = by_id[s["sequence_id"]]
                fh.write(json.dumps({"id": s["sequence_id"], "label": t["label"], "true_route": t["true_route"],
                                     "decision": s["decision"], "decision_trace": s["decision_trace"]},
                                    default=str) + "\n")
    print(json.dumps({k: out[k] for k in ("sample", "timing", "memory", "trace_bson_bytes")}, indent=2, default=str))
    print(json.dumps(overall, indent=2))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("planner")
    p.add_argument("--split", default="dev", choices=("dev",))   # test is never used to tune the planner
    p.add_argument("--out", required=True)
    r = sub.add_parser("run")
    r.add_argument("--split", default="test", choices=("dev", "test"))   # dev: rule checks; test: the reported run
    r.add_argument("--per-route", type=int, default=100)
    r.add_argument("--seed", type=int, default=1019)
    r.add_argument("--out", required=True)
    r.add_argument("--rows-out", default=None, help="optional JSONL of every decision + trace")
    args = ap.parse_args()
    {"planner": cmd_planner, "run": cmd_run}[args.cmd](args)


if __name__ == "__main__":
    main()
