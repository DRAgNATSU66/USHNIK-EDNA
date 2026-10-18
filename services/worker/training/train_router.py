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

Strand (B23, declared before the v2 sweep was run): eDNA reads can come from
either strand, so a router must route a read and its reverse complement equally
well. --strand picks how:
  * forward     features of the read as given (v1). Not strand-invariant: v1
                scored 0.1655 on reverse-complemented test reads.
  * canonical   a k-mer and its reverse complement share one feature, so both
                strands get the identical vector by construction.
  * rc_augment  forward features, with every training row also added as its
                reverse complement. Invariant only as far as the fit makes it.
The sweep scores every configuration on dev forward AND on dev reverse
complement, and selects among the strand-invariant modes (canonical,
rc_augment) by the WORSE of the two balanced accuracies ("worst-strand dev
balanced accuracy"). Forward configurations are listed for reference only and
are never selected.

Run from services/worker/:
    SYNTHVEDA_DATA_ROOT=... python -m training.train_router --version v2 --sweep --sweep-out sweep.json
    python -m training.train_router --version v2 --k 8 --strand canonical --sweep-table sweep.json
    # score an existing artifact on the current processed/ test split, no training:
    python -m training.train_router --eval-artifact .../router/v1/router.npz --eval-out v1_on_new.json \
        --seen-train-processed .../processed_v0
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
# Strand handling (B23)
# ---------------------------------------------------------------------------

STRANDS = ("forward", "canonical", "rc_augment")
STRAND_INVARIANT = ("canonical", "rc_augment")


def featurise(seqs: list[str], k: int, strand: str):
    return kmer_matrix(seqs, k, canonical=(strand == "canonical"))


def train_matrix(seqs: list[str], y: np.ndarray, k: int, strand: str):
    """Training design matrix. rc_augment stacks every row's reverse complement
    under the forward rows (same label)."""
    if strand == "rc_augment":
        import scipy.sparse as sp

        A = sp.vstack([featurise(seqs, k, strand), featurise([revcomp(s) for s in seqs], k, strand)]).tocsr()
        return A, np.concatenate([y, y])
    return featurise(seqs, k, strand), y


def confidence_stats(p: np.ndarray, y: np.ndarray) -> dict:
    """Mean calibrated top-label probability on wrong and on right predictions."""
    conf = p.max(axis=1)
    wrong = p.argmax(axis=1) != y
    return {
        "n_errors": int(wrong.sum()),
        "mean_confidence_on_errors": float(conf[wrong].mean()) if wrong.any() else None,
        "mean_confidence_on_correct": float(conf[~wrong].mean()) if (~wrong).any() else None,
        "errors_with_confidence_ge_0_7": int((wrong & (conf >= 0.7)).sum()),
    }


def heldout_block(z: np.ndarray, y: np.ndarray, T: float, subsets: dict[str, np.ndarray] | None = None) -> dict:
    """Metrics for one set of held-out logits: accuracy, per-route, ECE before
    and after T, confidence on errors, and the same for each boolean subset."""
    pred = z.argmax(1)
    p = softmax(z, T)
    out = report(y, pred, p)
    out["ece_uncalibrated"] = ece(softmax(z), y)
    out.update(confidence_stats(p, y))
    for name, m in (subsets or {}).items():
        if m.any():
            sub = report(y[m], pred[m], p[m])
            sub.update(confidence_stats(p[m], y[m]))
            out[name] = sub
    return out


# ---------------------------------------------------------------------------
# Evaluation of a loaded router (used for a freshly trained model and for
# --eval-artifact, so v1 and v2 are scored by exactly the same code)
# ---------------------------------------------------------------------------

def evaluate_model(model, data, routes_of, splits_of, protocol_n: int, seed: int,
                   seen: set[str] | None = None) -> dict:
    """Score `model` (a learned.LearnedRouterModel) on the test split of `data`.

    Forward and reverse-complement are scored separately, on every
    non-low-quality test row and on the QNA-001 protocol rows (through the full
    route_sequence() path, with the heuristic on the same rows). `seen` is an
    optional set of sequences the model was trained on; rows not in it are also
    reported as a separate subset.
    """
    from app.model_router import learned
    from app.model_router.router import route_sequence, route_sequence_heuristic
    from app.model_router.models import RouterInput
    from app.fastx_parser import compute_qc

    W, b, T = model.weights, model.bias, model.temperature

    def scores(seqs):
        return np.asarray(kmer_matrix(seqs, model.k, model.canonical) @ W) + b

    Xte, yte, cte, lte = build_heldout(data, routes_of, splits_of, "test")
    subsets = {"clean_subset": cte}
    unseen = None
    if seen is not None:
        unseen = np.array([q not in seen for q in Xte])
        subsets["unseen_by_model_training"] = unseen
    zf = scores(Xte)
    zr = scores([revcomp(s) for s in Xte])
    fwd = heldout_block(zf, yte, T, subsets)
    rc = heldout_block(zr, yte, T, subsets)
    by_label = {}
    pred_f = zf.argmax(1)
    pred_r = zr.argmax(1)
    for i, r in enumerate(ROUTES):
        for lab in sorted({l for l, yy in zip(lte, yte) if yy == i}):
            m = np.array([(yy == i and l == lab) for l, yy in zip(lte, yte)])
            by_label[f"{r}/{lab}"] = {"n": int(m.sum()), "accuracy_forward": float((pred_f[m] == i).mean()),
                                      "accuracy_reverse_complement": float((pred_r[m] == i).mean())}

    # ---- QNA-001 protocol through route_sequence() --------------------------
    learned.set_learned_router(model)
    rng = random.Random(seed)
    protocol = []
    for r in ROUTES:
        rows = [q for q, lab in data[(r, "test")] if lab != LQ_LABEL]
        protocol += [(q, r) for q in rng.sample(rows, min(protocol_n, len(rows)))]
    ytrue = np.array([ROUTES.index(r) for _, r in protocol])
    clean_p = np.array([len(routes_of[q]) == 1 and splits_of[q] == {"test"} for q, _ in protocol])
    unseen_p = None if seen is None else np.array([q not in seen for q, _ in protocol])

    def to_input(i, q):
        gc, nr, _, sha = compute_qc(q)
        return RouterInput(sequence_id=f"t{i}", sequence=q, length=len(q), gc_ratio=gc, n_ratio=nr, sha256=sha)

    def e2e(fn, inputs):
        t0 = time.perf_counter()
        res = [fn(x) for x in inputs]
        dt = (time.perf_counter() - t0) / len(inputs)
        pred_ = np.array([ROUTES.index(str(x.route)) if str(x.route) in ROUTES else -1 for x in res])
        return res, pred_, dt, dict(collections.Counter(x.router_method for x in res))

    def proto_block(res, pred_, dt, methods, with_probs: bool):
        out = report(ytrue, pred_)
        out.update(router_methods=methods, seconds_per_sequence=dt,
                   clean_subset=report(ytrue[clean_p], pred_[clean_p]))
        if unseen_p is not None:
            out["unseen_by_model_training"] = report(ytrue[unseen_p], pred_[unseen_p])
        if with_probs:
            scored = np.array([x.router_method == "learned" for x in res])
            if scored.any():
                p = np.array([[x.route_probabilities.get(r, 0.0) for r in ROUTES] for x, s in zip(res, scored) if s])
                z = np.array([[x.raw_scores[r] for r in ROUTES] for x, s in zip(res, scored) if s])
                ys = ytrue[scored]
                out["learned_scored_n"] = int(scored.sum())
                out["ece_uncalibrated_scored"] = ece(softmax(z), ys)
                out["ece_calibrated_scored"] = ece(p, ys)
                out.update(confidence_stats(p, ys))
            tiers = collections.Counter(str(x.confidence_tier) for x in res)
            out["confidence_tiers"] = dict(tiers)
            out["accuracy_by_tier"] = {t: float(np.mean([pl == yt for x, pl, yt in zip(res, pred_, ytrue)
                                                         if str(x.confidence_tier) == t])) for t in tiers}
            out["top2_accuracy"] = float(np.mean([
                ROUTES[yt] in sorted(x.route_probabilities, key=x.route_probabilities.get, reverse=True)[:2]
                for x, yt in zip(res, ytrue)]))
        return out

    protocol_out = {
        "description": f"{protocol_n} non-low-quality test rows per route, random.Random({seed}).sample, "
                       "through route_sequence() (low-quality gate included); the reverse_complement "
                       "blocks route the reverse complement of the same rows",
        "n": len(protocol),
        "clean_n": int(clean_p.sum()),
    }
    if unseen_p is not None:
        protocol_out["unseen_n"] = int(unseen_p.sum())
    for strand_name, seqs in (("forward", [q for q, _ in protocol]),
                              ("reverse_complement", [revcomp(q) for q, _ in protocol])):
        inputs = [to_input(i, q) for i, q in enumerate(seqs)]
        res_l, pred_l, dt_l, meth_l = e2e(route_sequence, inputs)
        res_h, pred_h, dt_h, meth_h = e2e(route_sequence_heuristic, inputs)
        protocol_out[strand_name] = {
            "learned": proto_block(res_l, pred_l, dt_l, meth_l, True),
            "heuristic": proto_block(res_h, pred_h, dt_h, meth_h, False),
        }

    lq_rows = [q for r in ROUTES for q, lab in data[(r, "test")] if lab == LQ_LABEL]
    lq_res = [route_sequence(to_input(i, q)) for i, q in enumerate(lq_rows)]
    learned.reset_learned_router()

    out = {
        "model_id": model.model_id,
        "version": model.version,
        "k": model.k,
        "canonical": model.canonical,
        "temperature": T,
        "test_rows_non_low_quality": int(len(yte)),
        "test_rows_clean": int(cte.sum()),
        "test_forward": fwd,
        "test_reverse_complement": rc,
        "test_strand_agreement": float((pred_f == pred_r).mean()),
        "test_by_route_and_label": by_label,
        "protocol_qna001": protocol_out,
        "low_quality_test_rows_routes": {"n": len(lq_rows),
                                         "routes": dict(collections.Counter(str(x.route) for x in lq_res))},
    }
    if unseen is not None:
        out["test_rows_seen_in_model_training"] = int((~unseen).sum())
    return out


def dev_sweep(Xtr, ytr, Xdv, ydv, ks, seed: int) -> dict:
    """Dev-only grid over k x strand x model. Selection: among strand-invariant
    modes, the highest worst-strand dev balanced accuracy."""
    Xdv_rc = [revcomp(s) for s in Xdv]
    rows = []
    for k in ks:
        for strand in STRANDS:
            t0 = time.time()
            A, yA = train_matrix(Xtr, ytr, k, strand)
            Bf, Br = featurise(Xdv, k, strand), featurise(Xdv_rc, k, strand)
            feat_s = time.time() - t0
            for kind, Cs in (("svm", (0.1, 1.0)), ("logreg", (10.0,))):
                for C in Cs:
                    t0 = time.time()
                    m = make_model(kind, C, seed).fit(A, yA)
                    fit_s = time.time() - t0
                    rf, rr = report(ydv, m.predict(Bf)), report(ydv, m.predict(Br))
                    row = {"k": k, "strand": strand, "model": kind, "C": C,
                           "strand_invariant": strand in STRAND_INVARIANT,
                           "dev_fwd_accuracy": rf["accuracy"], "dev_fwd_macro_f1": rf["macro_f1"],
                           "dev_fwd_balanced_accuracy": rf["balanced_accuracy"],
                           "dev_rc_accuracy": rr["accuracy"], "dev_rc_macro_f1": rr["macro_f1"],
                           "dev_rc_balanced_accuracy": rr["balanced_accuracy"],
                           "dev_worst_strand_balanced_accuracy": min(rf["balanced_accuracy"], rr["balanced_accuracy"]),
                           "dev_fwd_per_route_accuracy": rf["per_route_accuracy"],
                           "dev_rc_per_route_accuracy": rr["per_route_accuracy"],
                           "train_rows_fitted": int(A.shape[0]), "featurise_seconds": feat_s, "fit_seconds": fit_s}
                    rows.append(row)
                    print(json.dumps({x: (round(v, 4) if isinstance(v, float) else v) for x, v in row.items()
                                      if not x.endswith("per_route_accuracy")}), flush=True)
                    del m
            del A, Bf, Br
    eligible = [r for r in rows if r["strand_invariant"]]
    best = max(eligible, key=lambda x: x["dev_worst_strand_balanced_accuracy"])
    best_fwd = max((r for r in rows if r["strand"] == "forward"), key=lambda x: x["dev_fwd_balanced_accuracy"])
    return {
        "criterion": "max dev_worst_strand_balanced_accuracy over strand-invariant configs (canonical, rc_augment); "
                     "forward configs are reference only",
        "grid": {"k": list(ks), "strand": list(STRANDS), "models": "svm C=0.1, svm C=1.0, logreg C=10"},
        "dev_rows_non_low_quality": int(len(ydv)),
        "train_rows": int(len(ytr)),
        "rows": rows,
        "best": best,
        "best_forward_reference": best_fwd,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-root", default=os.environ.get("SYNTHVEDA_DATA_ROOT"))
    ap.add_argument("--version", help="artifact version, e.g. v2 (required unless --eval-artifact)")
    ap.add_argument("--k", type=int, default=8)
    ap.add_argument("--model", choices=["svm", "logreg"], default="svm")
    ap.add_argument("--C", type=float, default=1.0)
    ap.add_argument("--strand", choices=STRANDS, default=None, help="see 'Strand' above (default forward)")
    ap.add_argument("--canonical", action="store_true", help="same as --strand canonical (kept for v1 commands)")
    ap.add_argument("--cap", type=int, default=8000, help="max training rows per route")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--protocol-n", type=int, default=300, help="test rows per route for the QNA-001 protocol")
    ap.add_argument("--sweep", action="store_true", help="dev-only sweep over k/strand/model/C; no artifact written")
    ap.add_argument("--sweep-k", default="4,5,6,7,8", help="comma-separated k values for --sweep")
    ap.add_argument("--sweep-out", help="write the sweep table (JSON) here")
    ap.add_argument("--sweep-table", help="sweep JSON to embed in eval_report.json of a training run")
    ap.add_argument("--eval-artifact", help="score this router.npz on the test split; no training")
    ap.add_argument("--eval-out", help="with --eval-artifact: write the report (JSON) here")
    ap.add_argument("--seen-train-processed",
                    help="with --eval-artifact: processed/ dir the artifact was trained on; its training rows are "
                         "rebuilt with --cap/--seed and test rows among them are reported separately")
    ap.add_argument("--force", action="store_true", help="overwrite an existing version directory")
    args = ap.parse_args(argv)

    if args.canonical and args.strand not in (None, "canonical"):
        ap.error("--canonical conflicts with --strand " + args.strand)
    strand = "canonical" if args.canonical else (args.strand or "forward")
    if not args.data_root:
        ap.error("--data-root or SYNTHVEDA_DATA_ROOT is required")
    root = Path(args.data_root)
    processed = root / "processed"

    t_start = time.time()
    data = load_splits(processed)
    routes_of, splits_of = occurrence_index(data)

    # ---- score an existing artifact ------------------------------------------
    if args.eval_artifact:
        from app.model_router import learned

        npz = Path(args.eval_artifact)
        model = learned.load_router_artifact(npz)
        seen = None
        if args.seen_train_processed:
            old = load_splits(Path(args.seen_train_processed))
            o_routes, o_splits = occurrence_index(old)
            seen = set(build_train(old, o_routes, o_splits, args.cap, args.seed)[0])
        out = evaluate_model(model, data, routes_of, splits_of, args.protocol_n, args.seed, seen)
        out["artifact"] = {"path": str(npz), "sha256": file_sha256(npz)}
        out["evaluated_on"] = {f"{r}/{s}.csv": file_sha256(processed / r / f"{s}.csv") for r in ROUTES for s in SPLITS}
        if seen is not None:
            out["seen_train_rebuilt_from"] = {"processed": args.seen_train_processed, "cap": args.cap,
                                              "seed": args.seed, "train_rows": len(seen)}
        out["created_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        out["command"] = " ".join([Path(sys.argv[0]).name] + (argv if argv is not None else sys.argv[1:]))
        f, r_ = out["test_forward"], out["test_reverse_complement"]
        print(f"[router] {model.model_id}: test fwd {f['accuracy']:.4f} rc {r_['accuracy']:.4f}; protocol fwd "
              f"{out['protocol_qna001']['forward']['learned']['accuracy']:.4f} rc "
              f"{out['protocol_qna001']['reverse_complement']['learned']['accuracy']:.4f}"
              + (f"; seen test rows {out['test_rows_seen_in_model_training']}" if seen is not None else ""))
        if args.eval_out:
            Path(args.eval_out).write_text(json.dumps(out, indent=2))
            print(f"[router] wrote {args.eval_out}")
        return 0

    if not args.version:
        ap.error("--version is required")
    out_dir = root / "checkpoints" / "router" / args.version
    if out_dir.exists() and not args.force and not args.sweep:
        ap.error(f"{out_dir} exists; pick a new --version or pass --force")

    leakage = leakage_audit(data, routes_of)
    print(f"[router] {leakage['total_rows']} rows, {leakage['unique_sequences']} unique, "
          f"{leakage['unique_sequences_in_more_than_one_route']} in more than one route")

    Xtr, ytr, train_counts = build_train(data, routes_of, splits_of, args.cap, args.seed)
    Xdv, ydv, cdv, _ = build_heldout(data, routes_of, splits_of, "dev")
    print(f"[router] train {len(Xtr)} rows: " + ", ".join(f"{r}={c['used']}" for r, c in train_counts.items()))

    if args.sweep:
        ks = [int(x) for x in args.sweep_k.split(",") if x.strip()]
        sweep = dev_sweep(Xtr, ytr, Xdv, ydv, ks, args.seed)
        print("[router] best strand-invariant config by worst-strand dev balanced accuracy:",
              json.dumps({x: v for x, v in sweep["best"].items() if not x.endswith("per_route_accuracy")}))
        if args.sweep_out:
            sweep["leakage"] = leakage
            sweep["train_counts"] = train_counts
            Path(args.sweep_out).write_text(json.dumps(sweep, indent=2))
            print(f"[router] wrote {args.sweep_out}")
        return 0

    # ---- fit -------------------------------------------------------------
    t0 = time.time()
    A, yA = train_matrix(Xtr, ytr, args.k, strand)
    feat_s = time.time() - t0
    t0 = time.time()
    model = make_model(args.model, args.C, args.seed).fit(A, yA)
    fit_s = time.time() - t0
    del A
    W = np.ascontiguousarray(model.coef_.T.astype(np.float32))      # (4**k, C)
    b = model.intercept_.astype(np.float32)
    print(f"[router] strand {strand}: featurise {feat_s:.1f}s, fit {fit_s:.1f}s")

    def scores(seqs):
        return np.asarray(featurise(seqs, args.k, strand) @ W) + b

    # ---- calibrate on dev, both orientations pooled -------------------------
    # For canonical features the reverse-complement logits equal the forward
    # ones, so this is the same T as fitting on forward dev alone (v1's method).
    zdv_f = scores(Xdv)
    zdv_r = scores([revcomp(s) for s in Xdv])
    zdv = np.vstack([zdv_f, zdv_r])
    ydv2 = np.concatenate([ydv, ydv])
    T = fit_temperature(zdv, ydv2)
    dev_before, dev_after = report(ydv2, zdv.argmax(1), softmax(zdv)), report(ydv2, zdv.argmax(1), softmax(zdv, T))
    dev_fwd = heldout_block(zdv_f, ydv, T)
    dev_rc = heldout_block(zdv_r, ydv, T)
    print(f"[router] temperature {T:.4f}; dev ECE {dev_before['ece']:.4f} -> {dev_after['ece']:.4f}; "
          f"dev bal fwd {dev_fwd['balanced_accuracy']:.4f} rc {dev_rc['balanced_accuracy']:.4f}")

    # ---- save artifact -------------------------------------------------------
    out_dir.mkdir(parents=True, exist_ok=True)
    config = {
        "model_id": f"kmer_router_{args.version}",
        "version": args.version,
        "routes": ROUTES,
        "k": args.k,
        "canonical": strand == "canonical",
        "strand": strand,
        "train_augmentation": "reverse_complement" if strand == "rc_augment" else None,
        "features": "exact k-mer counts, non-ACGT windows skipped, L2-normalised (app/model_router/kmer.py)",
        "model": args.model,
        "C": args.C,
        "temperature": T,
        "min_kmers": 1,
    }
    npz_path = out_dir / "router.npz"
    np.savez_compressed(npz_path, weights=W, bias=b, config_json=np.array(json.dumps(config)))
    checksum = file_sha256(npz_path)

    # ---- evaluate on test (once), through the saved artifact ------------------
    from app.model_router import learned

    loaded = learned.load_router_artifact(npz_path, model_id=config["model_id"], expected_sha256=checksum)
    ev = evaluate_model(loaded, data, routes_of, splits_of, args.protocol_n, args.seed)
    tf, tr = ev["test_forward"], ev["test_reverse_complement"]
    pf, pr = ev["protocol_qna001"]["forward"], ev["protocol_qna001"]["reverse_complement"]
    print(f"[router] test fwd acc {tf['accuracy']:.4f} (bal {tf['balanced_accuracy']:.4f}, ECE "
          f"{tf['ece_uncalibrated']:.4f} -> {tf['ece']:.4f}); rc acc {tr['accuracy']:.4f}; "
          f"protocol learned fwd {pf['learned']['accuracy']:.4f} rc {pr['learned']['accuracy']:.4f} vs heuristic "
          f"fwd {pf['heuristic']['accuracy']:.4f} rc {pr['heuristic']['accuracy']:.4f}")

    sweep = json.loads(Path(args.sweep_table).read_text()) if args.sweep_table else None
    if sweep:
        sweep.pop("leakage", None)
    eval_report = {
        "model_id": config["model_id"],
        "version": args.version,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "config": config,
        "artifact": {"file": "router.npz", "sha256": checksum, "bytes": npz_path.stat().st_size},
        "data": {
            "processed_dir_sha256": {f"{r}/{s}.csv": file_sha256(processed / r / f"{s}.csv") for r in ROUTES for s in SPLITS},
            "train_rows": train_counts,
            "train_rows_fitted": int(len(yA)),
            "dev_rows_non_low_quality": int(len(ydv)),
            "test_rows_non_low_quality": ev["test_rows_non_low_quality"],
            "test_rows_clean": ev["test_rows_clean"],
        },
        "leakage": leakage,
        "calibration": {
            "method": "temperature scaling, NLL on dev (non-low-quality rows, forward + reverse complement pooled)",
            "temperature": T,
            "dev": {"ece_before": dev_before["ece"], "ece_after": dev_after["ece"],
                    "nll_before": dev_before["nll"], "nll_after": dev_after["nll"]},
            "test_forward": {"ece_before": tf["ece_uncalibrated"], "ece_after": tf["ece"]},
            "test_reverse_complement": {"ece_before": tr["ece_uncalibrated"], "ece_after": tr["ece"]},
            "ece_bins": 15,
        },
        "dev_forward": dev_fwd,
        "dev_reverse_complement": dev_rc,
        **{k_: v for k_, v in ev.items() if k_ not in ("model_id", "version", "k", "canonical", "temperature")},
        "sweep": sweep,
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
        "strand": strand,
        "model": args.model,
        "C": args.C,
        "temperature": T,
        "test_accuracy": tf["accuracy"],
        "test_macro_f1": tf["macro_f1"],
        "test_balanced_accuracy": tf["balanced_accuracy"],
        "test_clean_accuracy": tf["clean_subset"]["accuracy"] if "clean_subset" in tf else None,
        "test_reverse_complement_accuracy": tr["accuracy"],
        "test_strand_agreement": ev["test_strand_agreement"],
        "test_mean_confidence_on_errors": tf["mean_confidence_on_errors"],
        "test_ece_before": tf["ece_uncalibrated"],
        "test_ece_after": tf["ece"],
        "protocol_accuracy_learned": pf["learned"]["accuracy"],
        "protocol_macro_f1_learned": pf["learned"]["macro_f1"],
        "protocol_accuracy_learned_reverse_complement": pr["learned"]["accuracy"],
        "protocol_accuracy_heuristic": pf["heuristic"]["accuracy"],
        "protocol_accuracy_heuristic_reverse_complement": pr["heuristic"]["accuracy"],
        "seconds_per_sequence": pf["learned"]["seconds_per_sequence"],
        "train_size": int(len(ytr)),
        "dev_size": int(len(ydv)),
        "test_size": ev["test_rows_non_low_quality"],
        "checksum": checksum,
    }
    (out_dir / "eval_report.json").write_text(json.dumps(eval_report, indent=2))
    (out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2))
    print(f"[router] wrote {out_dir} (router.npz sha256 {checksum})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
