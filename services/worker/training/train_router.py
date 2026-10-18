"""
Trains, calibrates and evaluates the learned k-mer route classifier (roadmap
B19), and writes it as a versioned artifact:

    $SYNTHVEDA_DATA_ROOT/checkpoints/router/<version>/
        router.npz         weights (4**k x routes), bias, config_json  <- loaded by the worker
        metrics.json       headline numbers
        eval_report.json   per-route accuracy, macro-F1, confusion matrices, ECE,
                           leakage counts, heuristic baseline, latency, sweep table

Data: processed/<route>/{train,dev,test}.csv; the route is the folder.

Protocol (all decided before looking at test):
  * Training rows: label != low_quality_unusable (those rows are short or
    N-rich; 3,993/3,997 of misc_unknown's and 49/49 of fish's are caught by the
    router's low-quality gate and never reach the classifier), exact duplicates
    removed, and any sequence that also occurs in another route (any split) or
    in any dev/test file removed, so supervision is unambiguous and dev/test are
    held out. At most --cap rows per route (seeded sample) so bacteria_pathogen
    (32,865 rows) does not swamp the rest; class_weight="balanced" on top.
  * Model selection (k, model, C) on dev only (--sweep). Temperature fitted on
    dev by minimising NLL. Test is touched once, by the final evaluation.
  * Test metrics on (a) every non-low-quality test row, (b) the "clean" subset:
    rows whose sequence occurs in no other route and in no train/dev file, and
    (c) the QNA-001 protocol: 300 non-low-quality test rows per route, seeded
    sample, through the full route_sequence() path (gate included), learned vs
    heuristic.

Run from services/worker/:
    SYNTHVEDA_DATA_ROOT=... python -m training.train_router --version v1
    python -m training.train_router --version v1 --sweep     # dev sweep first
"""
from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import json
import os
import platform
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from app.model_router.kmer import kmer_matrix

ROUTES = [
    "fish",
    "plant",
    "bacteria_pathogen",
    "animal_general",
    "human_domestic_contamination",
    "misc_unknown",
]
LQ_LABEL = "low_quality_unusable"
SPLITS = ("train", "dev", "test")


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

def load_splits(processed: Path) -> dict[tuple[str, str], list[tuple[str, str]]]:
    data = {}
    for r in ROUTES:
        for s in SPLITS:
            with open(processed / r / f"{s}.csv", newline="", encoding="utf-8") as fh:
                data[(r, s)] = [(row["sequence"].upper(), row["label"]) for row in csv.DictReader(fh)]
    return data


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def occurrence_index(data):
    routes_of: dict[str, set] = collections.defaultdict(set)
    splits_of: dict[str, set] = collections.defaultdict(set)
    for (r, s), rows in data.items():
        for q, _ in rows:
            routes_of[q].add(r)
            splits_of[q].add(s)
    return routes_of, splits_of


def leakage_audit(data, routes_of) -> dict:
    """Exact-duplicate counts across routes and across splits (QNA-001 open item)."""
    multi = {q for q, rs in routes_of.items() if len(rs) > 1}
    pairs = collections.Counter("+".join(sorted(routes_of[q])) for q in multi)
    train_routes: dict[str, set] = collections.defaultdict(set)
    for r in ROUTES:
        for q, _ in data[(r, "train")]:
            train_routes[q].add(r)
    per_route = {}
    for r in ROUTES:
        tr = {q for q, _ in data[(r, "train")]}
        dv = {q for q, _ in data[(r, "dev")]}
        te = {q for q, _ in data[(r, "test")]}
        test_rows = data[(r, "test")]
        per_route[r] = {
            "within_route_unique_train_and_test": len(tr & te),
            "within_route_unique_train_and_dev": len(tr & dv),
            "within_route_unique_dev_and_test": len(dv & te),
            "train_internal_duplicate_rows": len(data[(r, "train")]) - len(tr),
            "test_rows": len(test_rows),
            "test_rows_in_same_route_train": sum(1 for q, _ in test_rows if r in train_routes.get(q, ())),
            "test_rows_in_other_route_train": sum(1 for q, _ in test_rows if train_routes.get(q, set()) - {r}),
            "test_rows_in_other_route_any_split": sum(1 for q, _ in test_rows if routes_of[q] - {r}),
        }
    cross_labels = collections.Counter()
    for (r, s), rows in data.items():
        for q, lab in rows:
            if q in multi:
                cross_labels[f"{r}/{s}/{lab}"] += 1
    return {
        "total_rows": sum(len(v) for v in data.values()),
        "unique_sequences": len(routes_of),
        "unique_sequences_in_more_than_one_route": len(multi),
        "unique_train_sequences_in_more_than_one_route_train": sum(1 for v in train_routes.values() if len(v) > 1),
        "cross_route_route_sets": dict(pairs.most_common()),
        "cross_route_rows_by_route_split_label": dict(sorted(cross_labels.items())),
        "per_route": per_route,
    }


def build_train(data, routes_of, splits_of, cap: int, seed: int):
    rng = random.Random(seed)
    X, y, counts = [], [], {}
    for i, r in enumerate(ROUTES):
        seen, rows = set(), []
        dropped = collections.Counter()
        for q, lab in data[(r, "train")]:
            if lab == LQ_LABEL:
                dropped["low_quality"] += 1
            elif q in seen:
                dropped["duplicate_within_train"] += 1
            elif len(routes_of[q]) > 1:
                dropped["also_in_other_route"] += 1
            elif splits_of[q] != {"train"}:
                dropped["also_in_dev_or_test"] += 1
            else:
                seen.add(q)
                rows.append(q)
        eligible = len(rows)
        rng.shuffle(rows)
        rows = rows[:cap]
        X += rows
        y += [i] * len(rows)
        counts[r] = {"raw_rows": len(data[(r, "train")]), "eligible": eligible, "used": len(rows), "dropped": dict(dropped)}
    return X, np.asarray(y), counts


def build_heldout(data, routes_of, splits_of, split: str):
    X, y, clean, labels = [], [], [], []
    for i, r in enumerate(ROUTES):
        for q, lab in data[(r, split)]:
            if lab == LQ_LABEL:
                continue
            X.append(q)
            y.append(i)
            labels.append(lab)
            clean.append(len(routes_of[q]) == 1 and splits_of[q] == {split})
    return X, np.asarray(y), np.asarray(clean), labels


# ---------------------------------------------------------------------------
# Models, calibration, metrics
# ---------------------------------------------------------------------------

def make_model(kind: str, C: float, seed: int):
    if kind == "svm":
        from sklearn.svm import LinearSVC
        return LinearSVC(C=C, class_weight="balanced", random_state=seed, max_iter=5000)
    if kind == "logreg":
        from sklearn.linear_model import LogisticRegression
        return LogisticRegression(C=C, class_weight="balanced", max_iter=1000)
    raise ValueError(kind)


def softmax(z: np.ndarray, T: float = 1.0) -> np.ndarray:
    z = z / T
    z = z - z.max(axis=1, keepdims=True)
    p = np.exp(z)
    return p / p.sum(axis=1, keepdims=True)


def fit_temperature(z: np.ndarray, y: np.ndarray) -> float:
    """Temperature minimising dev NLL (one scalar; argmax unchanged)."""
    from scipy.optimize import minimize_scalar

    def nll(logT):
        p = softmax(z, float(np.exp(logT)))
        return -np.mean(np.log(np.clip(p[np.arange(len(y)), y], 1e-12, None)))

    res = minimize_scalar(nll, bounds=(-6.0, 4.0), method="bounded")
    return float(np.exp(res.x))


def ece(p: np.ndarray, y: np.ndarray, n_bins: int = 15) -> float:
    """Top-label expected calibration error, equal-width bins."""
    conf = p.max(axis=1)
    correct = (p.argmax(axis=1) == y).astype(float)
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    total = 0.0
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (conf > lo) & (conf <= hi)
        if m.any():
            total += m.mean() * abs(correct[m].mean() - conf[m].mean())
    return float(total)


def nll(p: np.ndarray, y: np.ndarray) -> float:
    return float(-np.mean(np.log(np.clip(p[np.arange(len(y)), y], 1e-12, None))))


def report(y: np.ndarray, pred: np.ndarray, p: np.ndarray | None = None) -> dict:
    from sklearn.metrics import confusion_matrix, f1_score

    labels = list(range(len(ROUTES)))
    out = {
        "n": int(len(y)),
        "accuracy": float((pred == y).mean()) if len(y) else 0.0,
        "macro_f1": float(f1_score(y, pred, labels=labels, average="macro", zero_division=0)),
        "balanced_accuracy": float(np.mean([(pred[y == i] == i).mean() for i in labels if (y == i).any()])),
        "per_route_accuracy": {r: (float((pred[y == i] == i).mean()) if (y == i).any() else None) for i, r in enumerate(ROUTES)},
        "per_route_n": {r: int((y == i).sum()) for i, r in enumerate(ROUTES)},
        "per_route_f1": dict(zip(ROUTES, map(float, f1_score(y, pred, labels=labels, average=None, zero_division=0)))),
        "confusion_matrix": confusion_matrix(y, pred, labels=labels).tolist(),
        "label_order": ROUTES,
    }
    if p is not None:
        out["ece"] = ece(p, y)
        out["nll"] = nll(p, y)
    return out


def revcomp(s: str) -> str:
    return s.translate(str.maketrans("ACGTUN", "TGCAAN"))[::-1]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-root", default=os.environ.get("SYNTHVEDA_DATA_ROOT"))
    ap.add_argument("--version", required=True, help="artifact version, e.g. v1")
    ap.add_argument("--k", type=int, default=8)
    ap.add_argument("--model", choices=["svm", "logreg"], default="svm")
    ap.add_argument("--C", type=float, default=1.0)
    ap.add_argument("--canonical", action="store_true", help="strand-invariant canonical k-mers")
    ap.add_argument("--cap", type=int, default=8000, help="max training rows per route")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--protocol-n", type=int, default=300, help="test rows per route for the QNA-001 protocol")
    ap.add_argument("--sweep", action="store_true", help="dev-only sweep over k/model/C; no artifact written")
    ap.add_argument("--force", action="store_true", help="overwrite an existing version directory")
    args = ap.parse_args(argv)

    if not args.data_root:
        ap.error("--data-root or SYNTHVEDA_DATA_ROOT is required")
    root = Path(args.data_root)
    processed = root / "processed"
    out_dir = root / "checkpoints" / "router" / args.version
    if out_dir.exists() and not args.force and not args.sweep:
        ap.error(f"{out_dir} exists; pick a new --version or pass --force")

    t_start = time.time()
    data = load_splits(processed)
    routes_of, splits_of = occurrence_index(data)
    leakage = leakage_audit(data, routes_of)
    print(f"[router] {leakage['total_rows']} rows, {leakage['unique_sequences']} unique, "
          f"{leakage['unique_sequences_in_more_than_one_route']} in more than one route")

    Xtr, ytr, train_counts = build_train(data, routes_of, splits_of, args.cap, args.seed)
    Xdv, ydv, cdv, _ = build_heldout(data, routes_of, splits_of, "dev")
    print(f"[router] train {len(Xtr)} rows: " + ", ".join(f"{r}={c['used']}" for r, c in train_counts.items()))

    if args.sweep:
        rows = []
        for k in (4, 5, 6, 7, 8):
            for canonical in (False, True):
                A, B = kmer_matrix(Xtr, k, canonical), kmer_matrix(Xdv, k, canonical)
                for kind, Cs in (("svm", (0.1, 1.0)), ("logreg", (10.0,))):
                    for C in Cs:
                        t0 = time.time()
                        m = make_model(kind, C, args.seed).fit(A, ytr)
                        fit_s = time.time() - t0
                        pred = m.predict(B)
                        r = report(ydv, pred)
                        row = {"k": k, "canonical": canonical, "model": kind, "C": C,
                               "dev_accuracy": r["accuracy"], "dev_macro_f1": r["macro_f1"],
                               "dev_balanced_accuracy": r["balanced_accuracy"],
                               "dev_per_route_accuracy": r["per_route_accuracy"], "fit_seconds": fit_s}
                        rows.append(row)
                        print(json.dumps(row), flush=True)
        best = max(rows, key=lambda x: x["dev_balanced_accuracy"])
        print("[router] best by dev balanced accuracy:", json.dumps(best))
        return 0

    # ---- fit -------------------------------------------------------------
    t0 = time.time()
    A = kmer_matrix(Xtr, args.k, args.canonical)
    feat_s = time.time() - t0
    t0 = time.time()
    model = make_model(args.model, args.C, args.seed).fit(A, ytr)
    fit_s = time.time() - t0
    W = np.ascontiguousarray(model.coef_.T.astype(np.float32))      # (4**k, C)
    b = model.intercept_.astype(np.float32)
    print(f"[router] featurise {feat_s:.1f}s, fit {fit_s:.1f}s")

    def scores(seqs):
        return np.asarray(kmer_matrix(seqs, args.k, args.canonical) @ W) + b

    # ---- calibrate on dev --------------------------------------------------
    zdv = scores(Xdv)
    T = fit_temperature(zdv, ydv)
    dev_before, dev_after = report(ydv, zdv.argmax(1), softmax(zdv)), report(ydv, zdv.argmax(1), softmax(zdv, T))
    print(f"[router] temperature {T:.4f}; dev ECE {dev_before['ece']:.4f} -> {dev_after['ece']:.4f}")

    # ---- evaluate on test (once) ------------------------------------------
    Xte, yte, cte, lte = build_heldout(data, routes_of, splits_of, "test")
    zte = scores(Xte)
    pte_raw, pte = softmax(zte), softmax(zte, T)
    pred = zte.argmax(1)
    test_all = report(yte, pred, pte)
    test_all["ece_uncalibrated"] = ece(pte_raw, yte)
    test_clean = report(yte[cte], pred[cte], pte[cte])
    test_dups = report(yte[~cte], pred[~cte], pte[~cte]) if (~cte).any() else None
    by_label = {}
    for i, r in enumerate(ROUTES):
        for lab in sorted({l for l, yy in zip(lte, yte) if yy == i}):
            m = np.array([(yy == i and l == lab) for l, yy in zip(lte, yte)])
            by_label[f"{r}/{lab}"] = {"n": int(m.sum()), "accuracy": float((pred[m] == i).mean())}
    # Reverse-complement robustness (eDNA reads can come from either strand).
    zrc = scores([revcomp(s) for s in Xte])
    test_rc = report(yte, zrc.argmax(1), softmax(zrc, T))
    print(f"[router] test acc {test_all['accuracy']:.4f} macroF1 {test_all['macro_f1']:.4f} "
          f"bal {test_all['balanced_accuracy']:.4f} ECE {test_all['ece_uncalibrated']:.4f} -> {test_all['ece']:.4f}; "
          f"clean acc {test_clean['accuracy']:.4f} (n={test_clean['n']}); revcomp acc {test_rc['accuracy']:.4f}")

    # ---- save artifact -------------------------------------------------------
    out_dir.mkdir(parents=True, exist_ok=True)
    config = {
        "model_id": f"kmer_router_{args.version}",
        "version": args.version,
        "routes": ROUTES,
        "k": args.k,
        "canonical": args.canonical,
        "features": "exact k-mer counts, non-ACGT windows skipped, L2-normalised (app/model_router/kmer.py)",
        "model": args.model,
        "C": args.C,
        "temperature": T,
        "min_kmers": 1,
    }
    npz_path = out_dir / "router.npz"
    np.savez_compressed(npz_path, weights=W, bias=b, config_json=np.array(json.dumps(config)))
    checksum = file_sha256(npz_path)

    # ---- end-to-end protocol through route_sequence() ----------------------
    from app.model_router import learned
    from app.model_router.router import route_sequence, route_sequence_heuristic
    from app.model_router.models import RouterInput
    from app.fastx_parser import compute_qc

    loaded = learned.load_router_artifact(npz_path, model_id=config["model_id"], expected_sha256=checksum)
    learned.set_learned_router(loaded)
    rng = random.Random(args.seed)
    protocol = []
    for r in ROUTES:
        rows = [q for q, lab in data[(r, "test")] if lab != LQ_LABEL]
        protocol += [(q, r) for q in rng.sample(rows, min(args.protocol_n, len(rows)))]

    def to_input(i, q):
        gc, nr, _, sha = compute_qc(q)
        return RouterInput(sequence_id=f"t{i}", sequence=q, length=len(q), gc_ratio=gc, n_ratio=nr, sha256=sha)

    inputs = [to_input(i, q) for i, (q, _) in enumerate(protocol)]
    ytrue = np.array([ROUTES.index(r) for _, r in protocol])
    clean_p = np.array([len(routes_of[q]) == 1 and splits_of[q] == {"test"} for q, _ in protocol])

    def e2e(fn):
        t0 = time.perf_counter()
        res = [fn(x) for x in inputs]
        dt = (time.perf_counter() - t0) / len(inputs)
        pred_ = np.array([ROUTES.index(str(x.route)) if str(x.route) in ROUTES else -1 for x in res])
        methods = collections.Counter(x.router_method for x in res)
        return res, pred_, dt, methods

    res_l, pred_l, dt_l, meth_l = e2e(route_sequence)
    res_h, pred_h, dt_h, meth_h = e2e(route_sequence_heuristic)
    p_l = np.array([[x.route_probabilities.get(r, 0.0) for r in ROUTES] for x in res_l])
    proto_learned = report(ytrue, pred_l, p_l if (p_l.sum(1) > 0).all() else None)
    # ECE before temperature scaling on the same rows: softmax of the raw logits
    # (rows the learned model did not score, e.g. gated low-quality, are skipped).
    scored_l = np.array([x.router_method == "learned" for x in res_l])
    if scored_l.any():
        z_l = np.array([[x.raw_scores[r] for r in ROUTES] for x, s in zip(res_l, scored_l) if s])
        proto_learned["learned_scored_n"] = int(scored_l.sum())
        proto_learned["ece_uncalibrated_scored"] = ece(softmax(z_l), ytrue[scored_l])
        proto_learned["ece_calibrated_scored"] = ece(softmax(z_l, T), ytrue[scored_l])
    proto_learned.update(router_methods=dict(meth_l), seconds_per_sequence=dt_l,
                         clean_subset=report(ytrue[clean_p], pred_l[clean_p]))
    proto_heur = report(ytrue, pred_h)
    proto_heur.update(router_methods=dict(meth_h), seconds_per_sequence=dt_h,
                      clean_subset=report(ytrue[clean_p], pred_h[clean_p]))
    tiers = collections.Counter(str(x.confidence_tier) for x in res_l)
    tier_acc = {t: float(np.mean([pl == yt for x, pl, yt in zip(res_l, pred_l, ytrue) if str(x.confidence_tier) == t]))
                for t in tiers}
    top2 = float(np.mean([ROUTES[yt] in sorted(x.route_probabilities, key=x.route_probabilities.get, reverse=True)[:2]
                          for x, yt in zip(res_l, ytrue)]))
    print(f"[router] protocol ({len(protocol)} seqs): learned {proto_learned['accuracy']:.4f} "
          f"({dt_l*1e3:.3f} ms/seq) vs heuristic {proto_heur['accuracy']:.4f} ({dt_h*1e3:.3f} ms/seq)")

    # Low-quality test rows: what happens to them end to end.
    lq_rows = [q for r in ROUTES for q, lab in data[(r, "test")] if lab == LQ_LABEL]
    lq_res = [route_sequence(to_input(i, q)) for i, q in enumerate(lq_rows)]
    lq_summary = dict(collections.Counter(str(x.route) for x in lq_res))

    learned.reset_learned_router()

    eval_report = {
        "model_id": config["model_id"],
        "version": args.version,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "config": config,
        "artifact": {"file": "router.npz", "sha256": checksum, "bytes": npz_path.stat().st_size},
        "data": {
            "processed_dir_sha256": {f"{r}/{s}.csv": file_sha256(processed / r / f"{s}.csv") for r in ROUTES for s in SPLITS},
            "train_rows": train_counts,
            "dev_rows_non_low_quality": int(len(ydv)),
            "test_rows_non_low_quality": int(len(yte)),
            "test_rows_clean": int(cte.sum()),
        },
        "leakage": leakage,
        "calibration": {
            "method": "temperature scaling, NLL on dev (non-low-quality rows)",
            "temperature": T,
            "dev": {"ece_before": dev_before["ece"], "ece_after": dev_after["ece"],
                    "nll_before": dev_before["nll"], "nll_after": dev_after["nll"]},
            "test": {"ece_before": test_all["ece_uncalibrated"], "ece_after": test_all["ece"]},
            "ece_bins": 15,
        },
        "dev": dev_after,
        "test_all_non_low_quality": test_all,
        "test_clean_no_cross_route_or_cross_split_duplicates": test_clean,
        "test_duplicates_only": test_dups,
        "test_by_route_and_label": by_label,
        "test_reverse_complement": test_rc,
        "protocol_qna001": {
            "description": f"{args.protocol_n} non-low-quality test rows per route, random.Random({args.seed}).sample, "
                           "through route_sequence() (low-quality gate included)",
            "n": len(protocol),
            "clean_n": int(clean_p.sum()),
            "learned": proto_learned,
            "heuristic": proto_heur,
            "learned_confidence_tiers": dict(tiers),
            "learned_accuracy_by_tier": tier_acc,
            "learned_top2_accuracy": top2,
        },
        "low_quality_test_rows_routes": {"n": len(lq_rows), "routes": lq_summary},
        "environment": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "sklearn": __import__("sklearn").__version__,
            "featurise_seconds": feat_s,
            "fit_seconds": fit_s,
            "total_seconds": time.time() - t_start,
        },
        "command": " ".join([Path(sys.argv[0]).name] + (argv if argv is not None else sys.argv[1:])),
    }
    metrics = {
        "model_id": config["model_id"],
        "version": args.version,
        "k": args.k,
        "model": args.model,
        "temperature": T,
        "test_accuracy": test_all["accuracy"],
        "test_macro_f1": test_all["macro_f1"],
        "test_balanced_accuracy": test_all["balanced_accuracy"],
        "test_clean_accuracy": test_clean["accuracy"],
        "test_ece_before": test_all["ece_uncalibrated"],
        "test_ece_after": test_all["ece"],
        "protocol_accuracy_learned": proto_learned["accuracy"],
        "protocol_macro_f1_learned": proto_learned["macro_f1"],
        "protocol_accuracy_heuristic": proto_heur["accuracy"],
        "seconds_per_sequence": dt_l,
        "train_size": int(len(ytr)),
        "dev_size": int(len(ydv)),
        "test_size": int(len(yte)),
        "checksum": checksum,
    }
    (out_dir / "eval_report.json").write_text(json.dumps(eval_report, indent=2))
    (out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2))
    print(f"[router] wrote {out_dir} (router.npz sha256 {checksum})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
