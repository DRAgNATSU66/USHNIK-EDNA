"""
Builds per-route train/dev/test CSVs (sequence,label) for fine-tuning the
route classification heads (DNABERT-2 main / DNABERT-S fallback for Abyss
Mode). Walks every source under TRAINING_DATA_DIR/raw, routes each record
via routing.lineage_to_route, labels it via labeling.assign_label, caps
how much any one route/label/source can contribute, then writes CSVs to
TRAINING_DATA_DIR/processed/<route>/{train,dev,test}.csv.

Run from services/worker/ so the `app` and `training` packages resolve:
    python -m training.build_dataset
"""
from __future__ import annotations

import argparse
import csv
import os
import random
from collections import Counter, defaultdict
from pathlib import Path

from app.inference.models import ROUTE_LABEL_SETS, SequenceResultClass
from training import sources
from training.labeling import assign_label
from training.routing import ROUTES, lineage_to_route
from training.taxonomy import TaxonomyResolver

MAX_SEQ_LEN = 2000     # sequences longer than this get chunked into windows
CHUNK_LEN = 400
CHUNK_STRIDE = 800
MAX_PER_LABEL = 5000    # cap per (route, label) combination
MAX_SCAN_PER_SOURCE = 2_000_000  # safety valve so one huge DB can't run forever


def chunk_long_sequence(seq: str) -> list[str]:
    if len(seq) <= MAX_SEQ_LEN:
        return [seq]
    return [seq[i:i + CHUNK_LEN] for i in range(0, len(seq) - CHUNK_LEN, CHUNK_STRIDE)][:5]


class Collector:
    """Accumulates records per (route, label), capped, with reservoir-style
    replacement so late-arriving sources still get a fair shot once early
    ones fill a bucket."""

    def __init__(self, cap: int):
        self.cap = cap
        self.buckets: dict[tuple[str, str], list[str]] = defaultdict(list)
        self.seen_counts: Counter = Counter()

    def add(self, route: str, label: str, sequence: str) -> None:
        key = (route, label)
        self.seen_counts[key] += 1
        bucket = self.buckets[key]
        if len(bucket) < self.cap:
            bucket.append(sequence)
        else:
            j = random.randint(0, self.seen_counts[key] - 1)
            if j < self.cap:
                bucket[j] = sequence

    def is_full(self, route: str) -> bool:
        allowed = ROUTE_LABEL_SETS.get(route, [])
        return all(len(self.buckets.get((route, label), [])) >= self.cap for label in allowed)


def ingest(collector: Collector, records, forced_route: str | None = None,
           max_scan: int = MAX_SCAN_PER_SOURCE, watch_routes: tuple[str, ...] = ROUTES) -> int:
    scanned = 0
    added = 0
    for rec in records:
        scanned += 1
        if scanned > max_scan:
            break
        if scanned % 50_000 == 0 and all(collector.is_full(r) for r in watch_routes):
            print(f"    ...watched routes full at {scanned:,} scanned, stopping this source early")
            break
        route = forced_route or lineage_to_route(rec.lineage)
        for chunk in chunk_long_sequence(rec.sequence):
            label = assign_label(route, chunk, rec.organism_name, rec.lineage)
            if label is None:
                continue
            collector.add(route, label, chunk)
            added += 1
        if scanned % 200_000 == 0:
            print(f"    ...scanned {scanned:,}, added {added:,}")
    return added


def inject_contamination(collector: Collector, fraction: float = 0.08) -> None:
    """possible_contamination is cross-route by nature (route X sample
    containing route Y's organism) — pull real human/domestic sequences
    already collected and inject them into routes whose label set includes
    possible_contamination but wouldn't otherwise see any."""
    human_pool = collector.buckets.get(("human_domestic_contamination", SequenceResultClass.known_species), [])
    if not human_pool:
        return
    targets = ["plant", "bacteria_pathogen"]
    for route in targets:
        if SequenceResultClass.possible_contamination not in ROUTE_LABEL_SETS.get(route, []):
            continue
        n = min(int(collector.cap * fraction), len(human_pool))
        sample = random.sample(human_pool, n)
        for seq in sample:
            collector.add(route, SequenceResultClass.possible_contamination, seq)


def write_splits(collector: Collector, out_dir: Path, target_routes: tuple[str, ...] = ROUTES,
                  dev_frac: float = 0.1, test_frac: float = 0.1) -> dict:
    stats = {}
    for route in target_routes:
        route_dir = out_dir / route
        route_dir.mkdir(parents=True, exist_ok=True)
        # Deduplicate by sequence BEFORE splitting. The reference databases
        # legitimately contain the same sequence many times (same marker gene
        # deposited under multiple accessions, overlapping DB coverage), and
        # shuffling raw rows scattered those copies across train/dev/test --
        # measured at 13.1% duplicate rows and ~11% of the test set also
        # present in train, which inflated reported test accuracy by ~2.5
        # points (84.88% headline vs 82.41% on the truly-unseen portion).
        # A sequence must appear in exactly one split, exactly once.
        seq_to_labels: dict[str, set[str]] = {}
        for label in ROUTE_LABEL_SETS.get(route, []):
            for seq in collector.buckets.get((route, label), []):
                seq_to_labels.setdefault(seq, set()).add(label)

        # A handful of sequences (~0.03%) carry conflicting labels across
        # sources; they are genuinely ambiguous supervision, so drop them
        # rather than arbitrarily picking one side.
        rows: list[tuple[str, str]] = [
            (seq, next(iter(lbls))) for seq, lbls in seq_to_labels.items() if len(lbls) == 1
        ]
        dropped_conflicts = sum(1 for lbls in seq_to_labels.values() if len(lbls) > 1)
        if dropped_conflicts:
            print(f"  {route}: dropped {dropped_conflicts} sequence(s) with conflicting labels")
        random.shuffle(rows)

        n = len(rows)
        n_dev = int(n * dev_frac)
        n_test = int(n * test_frac)
        splits = {
            "test": rows[:n_test],
            "dev": rows[n_test:n_test + n_dev],
            "train": rows[n_test + n_dev:],
        }
        for split_name, split_rows in splits.items():
            with open(route_dir / f"{split_name}.csv", "w", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh)
                writer.writerow(["sequence", "label"])
                writer.writerows(split_rows)

        label_counts = Counter(label for _, label in rows)
        stats[route] = {"total": n, "by_label": dict(label_counts)}
    return stats


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default=os.environ.get("TRAINING_DATA_DIR", "E:/synthveda-data"))
    parser.add_argument("--cap", type=int, default=MAX_PER_LABEL)
    parser.add_argument("--skip-blastdb", action="store_true", help="Skip the slow multi-GB BLAST DB sources")
    parser.add_argument("--only-routes", default=None,
                         help="Comma-separated route names to rebuild (e.g. bacteria_pathogen). "
                              "Other routes are still scanned-through as needed for cross-route "
                              "contamination injection, but their CSVs on disk are left untouched.")
    args = parser.parse_args()

    random.seed(1337)
    root = Path(args.data_dir)
    raw = root / "raw"
    taxonomy = TaxonomyResolver(root / "tools" / "taxdump")
    collector = Collector(cap=args.cap)

    target_routes = tuple(args.only_routes.split(",")) if args.only_routes else ROUTES
    # human_domestic_contamination must still be collected (not necessarily
    # written) whenever bacteria_pathogen or plant are targets, since their
    # possible_contamination class is injected from its known_species pool.
    watch_routes = target_routes
    if any(r in target_routes for r in ("bacteria_pathogen", "plant")) and "human_domestic_contamination" not in watch_routes:
        watch_routes = watch_routes + ("human_domestic_contamination",)
    print(f"target routes: {target_routes}  (watching: {watch_routes})")

    print("== BOLD ==")
    ingest(collector, sources.iter_bold(raw / "bold" / "BOLD_Public.31-Jul-2026.parquet"), watch_routes=watch_routes)

    print("== MIDORI2 ==")
    for f in (raw / "midori2").glob("*.fasta.zip"):
        print(f"  {f.name}")
        ingest(collector, sources.iter_midori2(f, taxonomy), watch_routes=watch_routes)

    print("== SILVA ==")
    for f in (raw / "silva").glob("*.fasta.gz"):
        print(f"  {f.name}")
        ingest(collector, sources.iter_silva(f), watch_routes=watch_routes)

    print("== UNITE ==")
    unite_candidates = [f for f in (raw / "unite").glob("**/*general_release*.fasta") if "_dev" not in f.name]
    if unite_candidates and "misc_unknown" in watch_routes:
        ingest(collector, sources.iter_unite(unite_candidates[0]), watch_routes=watch_routes)

    if "human_domestic_contamination" in watch_routes:
        print("== GRCh38 ==")
        ingest(collector, sources.iter_grch38(raw / "grch38" / "GRCh38_no_alt_analysis_set.fna.gz"),
               forced_route="human_domestic_contamination", watch_routes=watch_routes)

        print("== UniVec ==")
        for name in ("UniVec_Core", "UniVec"):
            f = raw / "univec" / name
            if f.exists():
                ingest(collector, sources.iter_univec(f), forced_route="human_domestic_contamination", watch_routes=watch_routes)

    if not args.skip_blastdb:
        blastdbcmd = root / "tools" / "ncbi-blast-2.17.0+" / "bin" / "blastdbcmd.exe"
        extracted = raw / "ncbi_blastdb" / "extracted"
        print("== NCBI BLAST DBs ==")
        for db_dir in sorted(extracted.iterdir()) if extracted.exists() else []:
            # DB base name = directory name; blastdbcmd wants the path w/o extension
            db_path = db_dir / db_dir.name
            if not any(db_dir.glob("*.nin")) and not any(db_dir.glob("*.??.nin")):
                continue
            print(f"  {db_dir.name}")
            ingest(collector, sources.iter_blastdb(blastdbcmd, db_path, taxonomy), max_scan=300_000, watch_routes=watch_routes)
            if all(collector.is_full(r) for r in watch_routes):
                print("  watched routes full, stopping early")
                break

    print("== injecting cross-route contamination ==")
    inject_contamination(collector)

    print("== writing splits ==")
    stats = write_splits(collector, root / "processed", target_routes=target_routes)

    print("\n=== Final dataset ===")
    grand_total = 0
    for route, info in stats.items():
        print(f"{route}: {info['total']} total  {info['by_label']}")
        grand_total += info["total"]
    print(f"\nTOTAL: {grand_total} records across {len(target_routes)} route(s)")


if __name__ == "__main__":
    main()
