"""
Train/dev/test leakage check for processed/<route>/{train,dev,test}.csv
(sprint Day 7, t-1020-1). Reruns the THEORY_README §3 check that found the
2026-08-05 leak, and adds the near-duplicate measure QNA-011 Q4 asked for.

Exact (THEORY_README §3; must be zero, exit status 1 otherwise):
  * per route, unique sequences shared by train/dev, train/test, dev/test
  * per route, duplicate rows inside one split and sequences with two labels
Near-duplicate (reported, not gating; training/near_dup.py, 16-mer Jaccard
estimate >= threshold):
  * dev rows with a near-duplicate in train, test rows with one in train or dev
Cross-route (reported): unique sequences present in more than one route; the
learned router takes the route from the folder, so these are contradictory
router supervision (QNA-011 Q4).

*.leaky.csv files (the pre-dedup archive kept from 2026-08-05) are listed and
ignored, as fetch_supplementary.check_overlap does.

    cd services/worker
    python -m training.check_leakage --processed <root>/processed [--json out.json]
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

from training import near_dup

SPLITS = ("train", "dev", "test")


def load(processed: Path) -> tuple[dict[str, dict[str, list[tuple[str, str]]]], list[str]]:
    csv.field_size_limit(sys.maxsize)
    data: dict[str, dict[str, list[tuple[str, str]]]] = {}
    leaky = sorted(str(p.relative_to(processed)) for p in processed.glob("*/*.leaky.csv"))
    for route_dir in sorted(p for p in processed.iterdir() if p.is_dir()):
        splits = {}
        for s in SPLITS:
            f = route_dir / f"{s}.csv"
            if f.exists():
                with open(f, newline="", encoding="utf-8") as fh:
                    splits[s] = [(r["sequence"].strip().upper(), r["label"]) for r in csv.DictReader(fh)]
        if splits:
            data[route_dir.name] = splits
    return data, leaky


def check(processed: Path, near: bool = True, threshold: float = near_dup.DEFAULT_THRESHOLD) -> dict:
    data, leaky = load(processed)
    routes: dict[str, dict] = {}
    exact_total = 0
    for route, splits in data.items():
        uniq = {s: {q for q, _ in rows} for s, rows in splits.items()}
        get = lambda s: uniq.get(s, set())  # noqa: E731
        labels_of: dict[str, set[str]] = defaultdict(set)
        for rows in splits.values():
            for q, lab in rows:
                labels_of[q].add(lab)
        exact = {
            "train_dev": len(get("train") & get("dev")),
            "train_test": len(get("train") & get("test")),
            "dev_test": len(get("dev") & get("test")),
        }
        exact_total += sum(exact.values())
        info = {
            "rows": {s: len(r) for s, r in splits.items()},
            "by_label": {s: dict(sorted(Counter(lab for _, lab in r).items())) for s, r in splits.items()},
            "exact_cross_split_unique_sequences": exact,
            "within_split_duplicate_rows": {s: len(r) - len(uniq[s]) for s, r in splits.items()},
            "sequences_with_conflicting_labels": sum(1 for v in labels_of.values() if len(v) > 1),
        }
        if near:
            tr = [q for q, _ in splits.get("train", [])]
            dv = [q for q, _ in splits.get("dev", [])]
            te = [q for q, _ in splits.get("test", [])]
            dev_in_train = near_dup.cross_set_near_duplicates(dv, tr, threshold)
            test_in_train = near_dup.cross_set_near_duplicates(te, tr, threshold)
            test_in_dev = near_dup.cross_set_near_duplicates(te, dv, threshold)
            info["near_duplicate"] = {
                "threshold": threshold,
                "dev_rows_with_near_dup_in_train": int(dev_in_train.sum()),
                "test_rows_with_near_dup_in_train": int(test_in_train.sum()),
                "test_rows_with_near_dup_in_dev": int(test_in_dev.sum()),
                "test_rows_with_near_dup_in_train_or_dev": int((test_in_train | test_in_dev).sum()),
                "test_rows_with_near_dup_in_train_by_label": dict(sorted(Counter(
                    lab for (q, lab), hit in zip(splits.get("test", []), test_in_train) if hit).items())),
            }
        routes[route] = info

    routes_of: dict[str, set[str]] = defaultdict(set)
    for route, splits in data.items():
        for rows in splits.values():
            for q, _ in rows:
                routes_of[q].add(route)
    multi = {q for q, rs in routes_of.items() if len(rs) > 1}
    return {
        "processed": str(processed),
        "ignored_leaky_archives": leaky,
        "exact_cross_split_total": exact_total,
        "cross_route_unique_sequences": len(multi),
        "cross_route_route_sets": dict(Counter("+".join(sorted(routes_of[q])) for q in multi).most_common()),
        "routes": routes,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    default_root = os.environ.get("TRAINING_DATA_DIR") or os.environ.get("SYNTHVEDA_DATA_ROOT") \
        or str(Path(__file__).resolve().parents[3] / "synthveda-data")
    ap.add_argument("--processed", default=str(Path(default_root) / "processed"))
    ap.add_argument("--no-near-dup", action="store_true")
    ap.add_argument("--threshold", type=float, default=near_dup.DEFAULT_THRESHOLD)
    ap.add_argument("--json", default=None, help="also write the report here")
    args = ap.parse_args(argv)

    report = check(Path(args.processed), near=not args.no_near_dup, threshold=args.threshold)
    for route, info in report["routes"].items():
        line = f"{route:30s} rows={info['rows']} exact={info['exact_cross_split_unique_sequences']} " \
               f"dup_rows={info['within_split_duplicate_rows']} conflicts={info['sequences_with_conflicting_labels']}"
        if "near_duplicate" in info:
            nd = info["near_duplicate"]
            line += (f" near: dev~train={nd['dev_rows_with_near_dup_in_train']}"
                     f" test~train={nd['test_rows_with_near_dup_in_train']}"
                     f" test~dev={nd['test_rows_with_near_dup_in_dev']}")
        print(line)
    print(f"ignored *.leaky.csv: {report['ignored_leaky_archives']}")
    print(f"cross-route unique sequences: {report['cross_route_unique_sequences']} {report['cross_route_route_sets']}")
    print(f"EXACT CROSS-SPLIT TOTAL: {report['exact_cross_split_total']}")
    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 1 if report["exact_cross_split_total"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
