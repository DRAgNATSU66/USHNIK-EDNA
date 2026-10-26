"""
B5 (tracker t-1024-1): measure the novelty scorer's centroid embedding term
and reference low-identity term against the old L2-norm proxy, choose K, the
two new weights and the shared NOVELTY_THRESHOLD on DEV only, then report the
TEST split once.

Run from services/worker/ with SYNTHVEDA_DATA_ROOT set, after
`python -m training.novelty_centroids embed`:

  python -m training.eval_novelty_centroid collect --split dev  [--cap 600 --seed 1024]
  python -m training.eval_novelty_centroid calibrate --out <dev json>
  python -m training.novelty_centroids fit --k <chosen K>
  (set scorer.WEIGHTS / DEFAULT_NOVELTY_THRESHOLD from the dev json)
  python -m training.eval_novelty_centroid collect --split test
  python -m training.eval_novelty_centroid report --split test --out <test json>

collect: a seeded sample of each route's rows labelled possible_novelty
(positives) and known_species / likely_taxonomic_group /
unknown_needs_online_confirmation (negatives; the last is misc's non-novel
class, as in QNA-020), up to --cap rows per route (stratified by label).
human_domestic_contamination has no possible_novelty rows: --human-cap of its
known_species rows are kept to count false flags only. Rows go through the
job's own parser + QC + router stages (eval_orchestrator._pipeline_dicts);
the QC filter may drop rows (counted). The route is then set to the row's
TRUE route (novelty is measured given correct routing; routing has its own
evaluation, QNA-021/024) unless the QC gate routed the row to low_quality
(kept: such a row is never flagged). Then the real providers run on that
route: RouteHeadProvider (served head, real embedding), ReferenceEvidence-
Provider (BLAST, reference CURRENT), ContaminationProvider. Everything is
cached so the scoring variants below cost no GPU or BLAST time.

Scoring a row = the orchestrator's own novelty provider + combiner on that
evidence (NoveltyProvider -> combiner.combine), so the flag is the one a user
sees: final (reference-gated) score >= threshold, or result_class
possible_novelty after the combiner's class rules. "old" = the pre-B5 scorer
(L2-norm proxy at weight 0.03, no reference term) at threshold 0.45; "new" =
the served scorer at the served threshold.

calibrate (dev only):
  1. K: for K in --k-grid fit centroids from the cached TRAIN embeddings and
     take the AUROC (possible_novelty vs known) of the centroid ECDF signal
     alone per route; choose the K with the best mean AUROC over the five
     routes that have novelty labels.
  2. Weights + threshold: grid over W_EMB x W_REF x T (T in [0.20, 0.69], the
     band between the none/low and medium/high level edges); criterion = the
     mean over those five routes of the possible_novelty F1 of the final flag.
     Ties -> higher pooled F1, then T closest to the old 0.45.
"""
from __future__ import annotations

import argparse
import json
import os
import pickle
import random
import sys
import time
from collections import Counter, defaultdict
from functools import partial
from pathlib import Path

import numpy as np

sys.modules.setdefault("triton", None)  # type: ignore[arg-type]

from training.novelty_centroids import (  # noqa: E402
    centroid_set_from_fit,
    data_root,
    fit_centroids,
    load_train_cache,
    read_split,
    served_entry,
)

ROUTES = ("fish", "plant", "animal_general", "bacteria_pathogen", "human_domestic_contamination", "misc_unknown")
NOVELTY_ROUTES = ("fish", "plant", "animal_general", "bacteria_pathogen", "misc_unknown")
POS = "possible_novelty"
NEG = ("known_species", "likely_taxonomic_group", "unknown_needs_online_confirmation")
OLD_THRESHOLD = 0.45
OLD_WEIGHTS = {"result_class": 0.35, "low_confidence": 0.25, "label_entropy": 0.07,
               "embedding_isolation": 0.03, "reference_low_identity": 0.0}
T_GRID = [round(0.20 + 0.01 * i, 2) for i in range(50)]          # 0.20 .. 0.69
W_GRID = [0.0, 0.05, 0.10, 0.20, 0.35, 0.50, 0.70]


def cache_path(split: str) -> Path:
    return data_root() / "cache" / "novelty_centroids" / f"eval_{split}.pkl"


# ---------------------------------------------------------------------------
# collect
# ---------------------------------------------------------------------------

def _sample(route: str, split: str, cap: int, human_cap: int, rng: random.Random) -> list[dict]:
    rows = read_split(route, split)
    if route == "human_domestic_contamination":
        pool = [r for r in rows if r[2] == "known_species"]
        pick = rng.sample(pool, min(human_cap, len(pool)))
    else:
        pool = [r for r in rows if r[2] == POS or r[2] in NEG]
        if len(pool) <= cap:
            pick = pool
        else:  # stratified by label
            by = defaultdict(list)
            for r in pool:
                by[r[2]].append(r)
            pick = []
            for lab, rs in sorted(by.items()):
                pick += rng.sample(rs, max(1, round(cap * len(rs) / len(pool))))
    return [{"id": f"{route}:{split}:{i}", "sequence": s, "label": lab, "true_route": route}
            for i, s, lab in sorted(pick)]


def cmd_collect(args: argparse.Namespace) -> None:
    from app.config import get_worker_settings
    from app.evidence.providers import ContaminationProvider, ReferenceEvidenceProvider, RouteHeadProvider
    from app.inference.loader import unload
    from app.orchestrator.combiner import grch38_beaten_by
    from training.eval_orchestrator import _pipeline_dicts

    settings = get_worker_settings()
    rng = random.Random(args.seed)
    routes = args.routes.split(",") if args.routes else list(ROUTES)
    out_rows: list[dict] = []
    timing: dict[str, dict] = {}
    dropped: dict[str, int] = {}
    head_p, ref_p, cont_p = RouteHeadProvider(), ReferenceEvidenceProvider(settings=settings), ContaminationProvider()
    for route in routes:
        rows = _sample(route, args.split, args.cap, args.human_cap, rng)
        by_id = {r["id"]: r for r in rows}
        t0 = time.perf_counter()
        seqs = _pipeline_dicts(rows)
        dropped[route] = len(rows) - len(seqs)
        for s in seqs:
            s["router_route"] = s.get("route")
            s["route"] = "low_quality" if s.get("route") == "low_quality" else route
        live = [s for s in seqs if s["route"] == route]
        items = [(s["sequence_id"], s["sequence"]) for s in live]
        t1 = time.perf_counter()
        heads = head_p.collect(items, route) if items else []
        t2 = time.perf_counter()
        refs = ref_p.collect(items, route) if items else []
        t3 = time.perf_counter()
        cctx = []
        for s, h, r in zip(live, heads, refs):
            c = {k: v for k, v in s.items() if k != "embedding"}
            c["result_class"] = (h.payload or {}).get("result_class") if h.ok else ""
            hg = (r.payload or {}).get("human_genome") if r.ok and route == "human_domestic_contamination" else None
            c["human_genome"] = hg
            c["grch38_beaten_by"] = grch38_beaten_by(route, r.to_dict(), hg)
            cctx.append(c)
        conts = cont_p.collect(items, route, cctx) if items else []
        live_ev = {s["sequence_id"]: (h, r, c) for s, h, r, c in zip(live, heads, refs, conts)}
        for s in seqs:
            ev = live_ev.get(s["sequence_id"])
            base = {k: s.get(k) for k in ("sequence_id", "length", "n_ratio", "has_invalid_chars", "gc_ratio",
                                          "route", "router_route", "route_confidence")}
            row = {"id": s["sequence_id"], "label": by_id[s["sequence_id"]]["label"], "true_route": route,
                   "seq": base, "head": None, "embedding": None, "reference": None, "contamination": None}
            if ev:
                h, r, c = ev
                row["head"] = h.to_dict()
                emb = h.artifacts.get("embedding")
                row["embedding"] = np.asarray(emb, dtype=np.float32) if emb is not None else None
                row["reference"] = r.to_dict()
                row["contamination"] = c.to_dict()
            out_rows.append(row)
        timing[route] = {"rows": len(rows), "after_qc": len(seqs), "qc_low_quality": len(seqs) - len(live),
                         "pipeline_s": round(t1 - t0, 1), "heads_s": round(t2 - t1, 1),
                         "reference_s": round(t3 - t2, 1), "labels": dict(Counter(r["label"] for r in rows))}
        print(f"{route}: {timing[route]}", flush=True)
        entry = served_entry(route)
        unload(entry.model_id)
    p = cache_path(args.split)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "wb") as fh:
        pickle.dump({"split": args.split, "seed": args.seed, "cap": args.cap, "human_cap": args.human_cap,
                     "rows": out_rows, "timing": timing, "qc_dropped": dropped}, fh)
    print(f"saved {p} ({len(out_rows)} rows)")


# ---------------------------------------------------------------------------
# scoring
# ---------------------------------------------------------------------------

def _load(split: str) -> dict:
    with open(cache_path(split), "rb") as fh:
        return pickle.load(fh)


def _novelty_ctx(row: dict) -> dict:
    """engine._novelty_context for a single-route row."""
    h = row["head"]
    ctx = dict(row["seq"])
    if h and h["status"] == "ok":
        p = h["payload"]
        ctx.update(head_ok=True, result_class=p.get("result_class"), confidence=p.get("confidence", 0.0),
                   label_scores=p.get("label_scores") or {}, embedding=row["embedding"],
                   model_version_used=p.get("model_version_used"))
    else:
        ctx["head_ok"] = False
    c = row["contamination"]
    ctx["contamination_score"] = float(c["payload"].get("contamination_score", 0.0)) if c and c["status"] == "ok" else 0.0
    return ctx


def score_rows(rows: list[dict], *, weights: dict | None, resolver, use_reference: bool, settings) -> list[dict]:
    """(final_score, result_class, raw_score, gate_rule) per row via the real provider + combiner."""
    from app.evidence.providers import NoveltyProvider
    from app.novelty.scorer import score_sequence
    from app.orchestrator.combiner import CombineInput, combine

    nov_p = NoveltyProvider(score_fn=partial(score_sequence, weights=weights, resolver=resolver, settings=settings))
    out = []
    for row in rows:
        route = row["seq"]["route"]
        if route == "low_quality" or row["head"] is None:
            out.append({"final_score": 0.0, "result_class": "low_quality_unusable", "raw": 0.0, "gate_rule": "qc"})
            continue
        ctx = _novelty_ctx(row)
        if use_reference:
            ctx["reference"] = row["reference"]
        rec = nov_p.collect([(row["id"], "")], route, [ctx])[0].to_dict()
        c = CombineInput(final_route=route, head=row["head"], reference=row["reference"],
                         contamination=row["contamination"], novelty=rec, reference_enabled=True)
        decision, _, nov = combine(c, settings, OLD_THRESHOLD)
        out.append({"final_score": nov["final_score"] if nov["final_score"] is not None else 0.0,
                    "result_class": decision["result_class"], "raw": nov["raw_score"],
                    "gate_rule": nov["gate_rule"], "details": rec.get("payload", {}).get("details")})
    return out


def prf(y: np.ndarray, f: np.ndarray) -> dict:
    tp = int((y & f).sum()); fp = int((~y & f).sum()); fn = int((y & ~f).sum())
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * p * r / (p + r) if p + r else 0.0
    return {"precision": round(p, 4), "recall": round(r, 4), "f1": round(f1, 4), "tp": tp, "fp": fp, "fn": fn,
            "flagged": int(f.sum()), "positives": int(y.sum()), "n": int(len(y))}


def auroc(y: np.ndarray, s: np.ndarray) -> float | None:
    if y.all() or (~y).all():
        return None
    from sklearn.metrics import roc_auc_score
    return round(float(roc_auc_score(y, s)), 4)


def flags(scored: list[dict], t: float) -> np.ndarray:
    return np.array([(x["final_score"] >= t) or x["result_class"] == POS for x in scored])


def per_route_metrics(rows: list[dict], scored: list[dict], t: float) -> dict:
    out = {}
    f = flags(scored, t)
    y = np.array([r["label"] == POS for r in rows])
    rt = np.array([r["true_route"] for r in rows])
    for route in ROUTES:
        m = rt == route
        if m.any():
            out[route] = prf(y[m], f[m])
    nov = np.isin(rt, NOVELTY_ROUTES)
    out["_pooled_novelty_routes"] = prf(y[nov], f[nov])
    out["_mean_f1_novelty_routes"] = round(float(np.mean([out[r]["f1"] for r in NOVELTY_ROUTES if r in out])), 4)
    return out


def score_only_mean_f1(rows: list[dict], scored: list[dict], t: float) -> float:
    """Secondary view: the flag that the auto_novelty review and the report's
    novelty table use (final gated score >= T only, no result_class OR)."""
    y = np.array([r["label"] == POS for r in rows])
    rt = np.array([r["true_route"] for r in rows])
    f = np.array([x["final_score"] >= t for x in scored])
    return round(float(np.mean([prf(y[rt == r], f[rt == r])["f1"] for r in NOVELTY_ROUTES])), 4)


def raw_score_auroc(rows: list[dict], scored: list[dict]) -> dict:
    """AUROC of the scorer's raw (pre-reference-gate) score, per route."""
    y = np.array([r["label"] == POS for r in rows])
    rt = np.array([r["true_route"] for r in rows])
    s = np.array([x["raw"] or 0.0 for x in scored])
    out = {r: auroc(y[rt == r], s[rt == r]) for r in NOVELTY_ROUTES}
    vals = [v for v in out.values() if v is not None]
    out["_mean"] = round(float(np.mean(vals)), 4) if vals else None
    return out


def legacy_resolver(_model_id):
    return None, "legacy_eval"


def _resolvers_for_k(k: int, calib_frac: float, seed: int) -> tuple[dict, dict]:
    sets, fits = {}, {}
    for route in ROUTES:
        entry = served_entry(route)
        emb, labels, _ = load_train_cache(entry.model_id)
        fit = fit_centroids(emb, labels, k, calib_frac, seed)
        sets[entry.model_id] = centroid_set_from_fit(fit, entry.model_id, route)
        fits[route] = {"k_by_class": fit["k_by_class"], "calib_distance": fit["calib_distance"]}
    return sets, fits


def _signal_auroc(rows: list[dict], fn) -> dict:
    out = {}
    for route in NOVELTY_ROUTES:
        rs = [r for r in rows if r["true_route"] == route and r["embedding"] is not None
              and r["head"] and r["head"]["status"] == "ok"]
        y = np.array([r["label"] == POS for r in rs])
        s = np.array([fn(r) for r in rs])
        out[route] = auroc(y, s)
    vals = [v for v in out.values() if v is not None]
    out["_mean"] = round(float(np.mean(vals)), 4) if vals else None
    return out


def _proxy_signal(r):
    from app.novelty.signals import _norm_proxy
    return _norm_proxy(r["embedding"])


def _centroid_signal(sets):
    def fn(r):
        cs = sets[r["head"]["payload"]["model_version_used"]]
        d, _ = cs.nearest(r["embedding"])
        return cs.ecdf(d)
    return fn


def _ref_signal(settings):
    from app.novelty.signals import reference_low_identity

    def fn(r):
        s, _, _ = reference_low_identity({"reference": r["reference"]}, settings.reference_family_identity,
                                         settings.reference_search_min_identity)
        return -1.0 if s is None else s
    return fn


def cmd_calibrate(args: argparse.Namespace) -> None:
    from app.config import get_worker_settings
    settings = get_worker_settings()
    data = _load("dev")
    rows = data["rows"]
    t0 = time.perf_counter()

    # Old configuration on dev (for reference).
    old_scored = score_rows(rows, weights=OLD_WEIGHTS, resolver=legacy_resolver, use_reference=False, settings=settings)
    old_dev = per_route_metrics(rows, old_scored, OLD_THRESHOLD)
    old_best_t = max(T_GRID, key=lambda t: per_route_metrics(rows, old_scored, t)["_mean_f1_novelty_routes"])

    # 1. K by signal AUROC.
    k_grid = [int(k) for k in args.k_grid.split(",")]
    k_results, sets_by_k = {}, {}
    for k in k_grid:
        sets, fits = _resolvers_for_k(k, args.calib_frac, args.seed)
        sets_by_k[k] = sets
        k_results[k] = {"auroc": _signal_auroc(rows, _centroid_signal(sets)), "fits": fits}
        print(f"K={k}: centroid AUROC {k_results[k]['auroc']}", flush=True)
    best_k = max(k_grid, key=lambda k: (k_results[k]["auroc"]["_mean"] or 0, -k))
    sets = sets_by_k[best_k]
    resolver = lambda mid: (sets.get(mid), None if mid in sets else "not_in_eval")  # noqa: E731
    proxy_auroc = _signal_auroc(rows, _proxy_signal)
    ref_auroc = _signal_auroc(rows, _ref_signal(settings))

    # 2. Weights x threshold.
    grid = []
    for we in W_GRID:
        for wr in W_GRID:
            w = {"result_class": 0.35, "low_confidence": 0.25, "label_entropy": 0.07,
                 "embedding_isolation": we, "reference_low_identity": wr}
            scored = score_rows(rows, weights=w, resolver=resolver, use_reference=True, settings=settings)
            raw_auc = raw_score_auroc(rows, scored)
            for t in T_GRID:
                m = per_route_metrics(rows, scored, t)
                so = score_only_mean_f1(rows, scored, t)
                grid.append({"w_emb": we, "w_ref": wr, "threshold": t,
                             "mean_f1": m["_mean_f1_novelty_routes"],
                             "pooled_f1": m["_pooled_novelty_routes"]["f1"],
                             "per_route_f1": {r: m[r]["f1"] for r in NOVELTY_ROUTES},
                             "score_only_mean_f1": so, "raw_score_auroc_mean": raw_auc["_mean"]})
        print(f"w_emb={we} done ({time.perf_counter() - t0:.0f}s)", flush=True)
    best = max(grid, key=lambda g: (g["mean_f1"], g["pooled_f1"], -abs(g["threshold"] - OLD_THRESHOLD)))
    w_best = {"result_class": 0.35, "low_confidence": 0.25, "label_entropy": 0.07,
              "embedding_isolation": best["w_emb"], "reference_low_identity": best["w_ref"]}
    new_scored = score_rows(rows, weights=w_best, resolver=resolver, use_reference=True, settings=settings)
    new_dev = per_route_metrics(rows, new_scored, best["threshold"])
    # Ablations at their own dev-best threshold: centroid only, reference only.
    ablations = {}
    for name, we, wr in (("centroid_only", best["w_emb"], 0.0), ("reference_only", 0.0, best["w_ref"])):
        cand = [g for g in grid if g["w_emb"] == we and g["w_ref"] == wr]
        if cand:
            b = max(cand, key=lambda g: (g["mean_f1"], g["pooled_f1"]))
            ablations[name] = {"w_emb": we, "w_ref": wr, "threshold": b["threshold"], "mean_f1": b["mean_f1"],
                               "per_route_f1": b["per_route_f1"]}
    top = sorted(grid, key=lambda g: (-g["mean_f1"], -g["pooled_f1"]))[:15]
    # For the record (not the choice): the best grid point that gives BOTH new
    # terms a weight, and the best by the score-only flag.
    both = [g for g in grid if g["w_emb"] > 0 and g["w_ref"] > 0]
    best_both = max(both, key=lambda g: (g["mean_f1"], g["pooled_f1"])) if both else None
    best_score_only = max(grid, key=lambda g: (g["score_only_mean_f1"], g["mean_f1"]))
    old_so = score_only_mean_f1(rows, old_scored, OLD_THRESHOLD)
    old_raw_auc = raw_score_auroc(rows, old_scored)
    out = {
        "split": "dev", "rows": len(rows), "seed": data["seed"], "cap": data["cap"],
        "collect_timing": data["timing"], "qc_dropped": data["qc_dropped"],
        "criterion": "max mean over routes (fish, plant, animal_general, bacteria_pathogen, misc_unknown) of the "
                     "possible_novelty F1 of the final flag (gated score >= T or final result_class "
                     "possible_novelty); ties -> pooled F1, then T closest to 0.45",
        "k_grid": {str(k): v for k, v in k_results.items()}, "chosen_k": best_k,
        "signal_auroc": {"norm_proxy": proxy_auroc, f"centroid_k{best_k}": k_results[best_k]["auroc"],
                         "reference_low_identity": ref_auroc},
        "old": {"weights": OLD_WEIGHTS, "threshold": OLD_THRESHOLD, "metrics": old_dev,
                "old_scorer_dev_best_threshold": old_best_t},
        "chosen": {"weights": w_best, "threshold": best["threshold"], "metrics": new_dev},
        "ablations": ablations, "top15": top, "grid_size": len(grid),
        "best_with_both_new_terms": best_both, "best_by_score_only_flag": best_score_only,
        "old_score_only_mean_f1_at_045": old_so, "old_raw_score_auroc": old_raw_auc,
        "seconds": round(time.perf_counter() - t0, 1),
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2))
    print(json.dumps({k: out[k] for k in ("chosen_k", "signal_auroc", "chosen", "ablations")}, indent=2))
    print("old dev:", json.dumps({r: old_dev[r] for r in old_dev}, indent=None))


def cmd_report(args: argparse.Namespace) -> None:
    """Old scorer @0.45 vs the SERVED scorer (artifacts on disk, WEIGHTS,
    NOVELTY_THRESHOLD) on one split. Run once on test."""
    from app.config import NOVELTY_THRESHOLD, get_worker_settings
    from app.novelty import scorer
    from app.novelty.centroids import centroids_for_model

    settings = get_worker_settings()
    data = _load(args.split)
    rows = data["rows"]
    old_scored = score_rows(rows, weights=OLD_WEIGHTS, resolver=legacy_resolver, use_reference=False, settings=settings)
    new_scored = score_rows(rows, weights=None, resolver=None, use_reference=True, settings=settings)
    methods = Counter((x.get("details") or {}).get("embedding_isolation", {}).get("method") for x in new_scored)
    fallbacks = Counter((x.get("details") or {}).get("embedding_isolation", {}).get("fallback_reason")
                        for x in new_scored if (x.get("details") or {}).get("embedding_isolation", {}).get("method") == "norm_proxy")
    sets = {}
    for route in ROUTES:
        e = served_entry(route)
        cs, why = centroids_for_model(e.model_id)
        if cs is None:
            raise SystemExit(f"{route}: served centroids unavailable ({why})")
        sets[e.model_id] = cs
    out = {
        "split": args.split, "rows": len(rows), "seed": data["seed"], "cap": data["cap"],
        "human_cap": data["human_cap"], "collect_timing": data["timing"], "qc_dropped": data["qc_dropped"],
        "old": {"weights": OLD_WEIGHTS, "threshold": OLD_THRESHOLD,
                "metrics": per_route_metrics(rows, old_scored, OLD_THRESHOLD)},
        "new": {"weights": dict(scorer.WEIGHTS), "threshold": NOVELTY_THRESHOLD,
                "metrics": per_route_metrics(rows, new_scored, NOVELTY_THRESHOLD),
                "embedding_method_counts": dict(methods), "proxy_fallback_reasons": dict(fallbacks),
                "centroids": {m: {"sha256": cs.sha256, "k": int(cs.centroids.shape[0])} for m, cs in sets.items()}},
        "new_scorer_at_old_threshold": per_route_metrics(rows, new_scored, OLD_THRESHOLD),
        "old_scorer_at_new_threshold": per_route_metrics(rows, old_scored, NOVELTY_THRESHOLD),
        "signal_auroc": {"norm_proxy": _signal_auroc(rows, _proxy_signal),
                         "centroid": _signal_auroc(rows, _centroid_signal(sets)),
                         "reference_low_identity": _signal_auroc(rows, _ref_signal(settings))},
        "raw_score_auroc": {"old": raw_score_auroc(rows, old_scored), "new": raw_score_auroc(rows, new_scored)},
        "score_only_mean_f1": {"old@0.45": score_only_mean_f1(rows, old_scored, OLD_THRESHOLD),
                               "new@served": score_only_mean_f1(rows, new_scored, NOVELTY_THRESHOLD)},
        "gate_rules_new": dict(Counter(x["gate_rule"] for x in new_scored)),
        "result_class_counts": dict(Counter(x["result_class"] for x in new_scored)),
    }
    if args.dev_json:
        # Secondary, fixed on dev before this split was scored: the best dev
        # grid point that gives both new terms a weight (not served).
        alt = json.loads(Path(args.dev_json).read_text()).get("best_with_both_new_terms")
        if alt:
            w = {"result_class": 0.35, "low_confidence": 0.25, "label_entropy": 0.07,
                 "embedding_isolation": alt["w_emb"], "reference_low_identity": alt["w_ref"]}
            alt_scored = score_rows(rows, weights=w, resolver=None, use_reference=True, settings=settings)
            out["alt_both_terms_not_served"] = {
                "weights": w, "threshold": alt["threshold"],
                "metrics": per_route_metrics(rows, alt_scored, alt["threshold"]),
                "raw_score_auroc": raw_score_auroc(rows, alt_scored)}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2))
    for name in ("old", "new"):
        print(name, json.dumps({r: (m["precision"], m["recall"], m["f1"]) if isinstance(m, dict) else m
                                for r, m in out[name]["metrics"].items()}))
    print("auroc", json.dumps(out["signal_auroc"]))


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect")
    c.add_argument("--split", required=True, choices=["dev", "test"])
    c.add_argument("--cap", type=int, default=600)
    c.add_argument("--human-cap", type=int, default=300)
    c.add_argument("--seed", type=int, default=1024)
    c.add_argument("--routes", default="")
    k = sub.add_parser("calibrate")
    k.add_argument("--out", required=True)
    k.add_argument("--k-grid", default="1,4,16,32,64")
    k.add_argument("--calib-frac", type=float, default=0.1)
    k.add_argument("--seed", type=int, default=1024)
    r = sub.add_parser("report")
    r.add_argument("--split", default="test", choices=["dev", "test"])
    r.add_argument("--out", required=True)
    r.add_argument("--dev-json", default="", help="calibrate output; adds its best_with_both_new_terms as a secondary row")
    args = ap.parse_args()
    {"collect": cmd_collect, "calibrate": cmd_calibrate, "report": cmd_report}[args.cmd](args)


if __name__ == "__main__":
    main()
