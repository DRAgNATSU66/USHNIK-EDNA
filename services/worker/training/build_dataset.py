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
import json
import os
import random
import time
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

from app.inference.models import ROUTE_LABEL_SETS, SequenceResultClass
from training import near_dup, sources
from training.labeling import assign_label, is_low_quality
from training.routing import ROUTES, lineage_to_route
from training.taxonomy import TaxonomyResolver

MAX_SEQ_LEN = 2000     # sequences longer than this get chunked into windows
CHUNK_LEN = 400
CHUNK_STRIDE = 800
MAX_PER_LABEL = 5000    # cap per (route, label) combination
MAX_SCAN_PER_SOURCE = 2_000_000  # safety valve so one huge DB can't run forever
# BOLD_Public is sorted by processid (project code), so a 2M cap would sample
# only the first few projects alphabetically. The whole 24.5M-row file
# streams in about 3 min, so scan all of it.
BOLD_MAX_SCAN = 50_000_000
SPLITS = ("train", "dev", "test")


def chunk_long_sequence(seq: str) -> list[str]:
    if len(seq) <= MAX_SEQ_LEN:
        return [seq]
    return [seq[i:i + CHUNK_LEN] for i in range(0, len(seq) - CHUNK_LEN, CHUNK_STRIDE)][:5]


class Collector:
    """Accumulates records per (route, label), capped, with reservoir-style
    replacement so late-arriving sources still get a fair shot once early
    ones fill a bucket."""

    def __init__(self, cap: int, route_caps: dict[str, int] | None = None):
        self.cap = cap
        # Per-route overrides; the August build used 20000 for bacteria_pathogen
        # and 5000 elsewhere (row counts in processed_v0/).
        self.route_caps = dict(route_caps or {})
        self.buckets: dict[tuple[str, str], list[str]] = defaultdict(list)
        self.seen_counts: Counter = Counter()

    def cap_for(self, route: str) -> int:
        return self.route_caps.get(route, self.cap)

    def add(self, route: str, label: str, sequence: str) -> None:
        key = (route, label)
        cap = self.cap_for(route)
        self.seen_counts[key] += 1
        bucket = self.buckets[key]
        if len(bucket) < cap:
            bucket.append(sequence)
        else:
            j = random.randint(0, self.seen_counts[key] - 1)
            if j < cap:
                bucket[j] = sequence

    def is_full(self, route: str) -> bool:
        allowed = ROUTE_LABEL_SETS.get(route, [])
        cap = self.cap_for(route)
        return all(len(self.buckets.get((route, label), [])) >= cap for label in allowed)


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
        route = forced_route or rec.route or lineage_to_route(rec.lineage)
        for chunk in chunk_long_sequence(rec.sequence):
            if rec.label is not None:
                # Provenance-labelled record (vector, sequencing control).
                # Still drop low-quality windows rather than mislabel them.
                if is_low_quality(chunk) or rec.label not in ROUTE_LABEL_SETS.get(route, []):
                    continue
                label = rec.label
            else:
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
    # Both human-route pools: organismal human/domestic DNA (known_species)
    # and lab/technical sequences (possible_contamination: UniVec, vectors,
    # PhiX). UniVec sat in known_species before 2026-10-19, so drawing from
    # both keeps it in the injected contamination as before.
    human_pool = (
        collector.buckets.get(("human_domestic_contamination", SequenceResultClass.known_species), [])
        + collector.buckets.get(("human_domestic_contamination", SequenceResultClass.possible_contamination), [])
    )
    if not human_pool:
        return
    targets = ["plant", "bacteria_pathogen"]
    for route in targets:
        if SequenceResultClass.possible_contamination not in ROUTE_LABEL_SETS.get(route, []):
            continue
        n = min(int(collector.cap_for(route) * fraction), len(human_pool))
        sample = random.sample(human_pool, n)
        for seq in sample:
            collector.add(route, SequenceResultClass.possible_contamination, seq)


def find_bold_parquet(bold_dir: Path) -> Path | None:
    """Newest raw/bold/BOLD_Public*.parquet, or None. BOLD needs an owner
    login to download, so the builder must run without it; the data package
    is dated in its name (BOLD_Public.<dd-Mon-yyyy>.parquet), which does not
    sort by date, so the newest file by mtime wins."""
    if not bold_dir.is_dir():
        return None
    found = sorted(bold_dir.glob("BOLD_Public*.parquet"), key=lambda p: (p.stat().st_mtime, p.name))
    return found[-1] if found else None


def assign_groups_to_splits(labels: list[str], groups, dev_frac: float = 0.1, test_frac: float = 0.1,
                            rng: random.Random | None = None) -> list[str]:
    """Split name per row such that every row of one group lands in the same
    split, with each label's rows close to the dev/test/train fractions.

    Groups are placed largest first (seeded shuffle among equal sizes), each
    into the split whose per-label quota it fills best: score(s) = sum over the
    group's labels of count * remaining_quota(s, label) / quota(s, label).
    Ties go to train, so the largest near-duplicate clusters train the model
    and dev/test hold the less redundant sequences."""
    rng = rng or random.Random(0)
    fracs = {"train": 1.0 - dev_frac - test_frac, "dev": dev_frac, "test": test_frac}
    label_totals = Counter(labels)
    quota = {s: {lab: fracs[s] * n for lab, n in label_totals.items()} for s in SPLITS}
    filled = {s: Counter() for s in SPLITS}
    members: dict = defaultdict(list)
    for i, g in enumerate(groups):
        members[g].append(i)
    order = list(members)
    rng.shuffle(order)
    order.sort(key=lambda g: len(members[g]), reverse=True)
    out = [""] * len(labels)
    for g in order:
        counts = Counter(labels[i] for i in members[g])
        best, best_score = None, None
        for s in SPLITS:
            score = sum(c * (quota[s][lab] - filled[s][lab]) / max(quota[s][lab], 1e-9)
                        for lab, c in counts.items())
            if best_score is None or score > best_score:
                best, best_score = s, score
        filled[best].update(counts)
        for i in members[g]:
            out[i] = best
    return out


def write_splits(collector: Collector, out_dir: Path, target_routes: tuple[str, ...] = ROUTES,
                  dev_frac: float = 0.1, test_frac: float = 0.1, split_mode: str = "group",
                  near_dup_threshold: float = near_dup.DEFAULT_THRESHOLD) -> dict:
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
        group_info: dict = {}
        if split_mode == "group":
            # Exact dedup alone still lets near-identical copies (one SNP, a
            # sibling haplotype, a shifted window) straddle train/test:
            # measured on the August processed/ at 16-mer Jaccard >= 0.8,
            # 211/500 human, 348/1002 animal and 1023/4107 bacteria test rows
            # had a near-duplicate in another split. Keep each near-duplicate
            # group (training/near_dup.py) inside a single split.
            t0 = time.time()
            groups = near_dup.near_duplicate_groups([seq for seq, _ in rows], threshold=near_dup_threshold)
            assigned = assign_groups_to_splits([lab for _, lab in rows], groups, dev_frac, test_frac,
                                               rng=random.Random(f"split:{route}"))
            splits = {s: [row for row, a in zip(rows, assigned) if a == s] for s in ("test", "dev", "train")}
            sizes = Counter(Counter(groups.tolist()).values())
            group_info = {
                "near_dup_threshold": near_dup_threshold,
                "groups": int(sum(sizes.values())),
                "rows_in_multi_member_groups": int(sum(k * v for k, v in sizes.items() if k > 1)),
                "largest_group": int(max(sizes) if sizes else 0),
                "seconds": round(time.time() - t0, 1),
            }
        else:
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
        stats[route] = {
            "total": n, "by_label": dict(label_counts), "dropped_label_conflicts": dropped_conflicts,
            "by_split": {s: dict(Counter(lab for _, lab in r)) for s, r in splits.items()},
            "split_mode": split_mode, **({"near_dup": group_info} if group_info else {}),
        }
    return stats


def _counted(records, box: list[int]):
    for rec in records:
        box[0] += 1
        yield rec


def parse_route_caps(spec: str | None) -> dict[str, int]:
    """"bacteria_pathogen=20000,fish=8000" -> {route: cap}."""
    caps: dict[str, int] = {}
    for part in (spec or "").split(","):
        if not part.strip():
            continue
        route, _, value = part.partition("=")
        route = route.strip()
        if route not in ROUTES or not value.strip().isdigit():
            raise SystemExit(f"--route-cap: bad entry {part!r} (want <route>=<int>, route in {ROUTES})")
        caps[route] = int(value)
    return caps


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    default_root = os.environ.get("TRAINING_DATA_DIR") or os.environ.get("SYNTHVEDA_DATA_ROOT") \
        or str(Path(__file__).resolve().parents[3] / "synthveda-data")
    parser.add_argument("--data-dir", default=default_root)
    parser.add_argument("--cap", type=int, default=MAX_PER_LABEL)
    parser.add_argument("--route-cap", default=None,
                        help="Per-route cap overrides, e.g. bacteria_pathogen=20000 (the August build's value)")
    parser.add_argument("--skip-blastdb", action="store_true", help="Skip the slow multi-GB BLAST DB sources")
    parser.add_argument("--exclude-blastdb", default="",
                        help="Comma-separated BLAST DB names under raw/ncbi_blastdb/extracted/ to skip "
                             "(e.g. tier-2 DBs still downloading: nt_viruses,ref_prok_rep_genomes)")
    parser.add_argument("--skip-supplementary", action="store_true",
                        help="Ignore raw/supplementary/ (fetch_supplementary.py output)")
    parser.add_argument("--only-routes", default=None,
                         help="Comma-separated route names to rebuild (e.g. bacteria_pathogen). "
                              "Other routes are still scanned-through as needed for cross-route "
                              "contamination injection, but their CSVs on disk are left untouched.")
    parser.add_argument("--split-mode", choices=("group", "random"), default="group",
                        help="group (default): near-duplicate groups (training/near_dup.py) never straddle "
                             "splits. random: the pre-2026-10-20 shuffle-and-slice after exact dedup.")
    parser.add_argument("--near-dup-threshold", type=float, default=near_dup.DEFAULT_THRESHOLD,
                        help="Estimated 16-mer Jaccard at or above which two sequences share a group")
    args = parser.parse_args(argv)

    t_start = time.time()
    random.seed(1337)
    root = Path(args.data_dir)
    raw = root / "raw"
    taxonomy = TaxonomyResolver(root / "tools" / "taxdump")
    collector = Collector(cap=args.cap, route_caps=parse_route_caps(args.route_cap))
    excluded_dbs = {x.strip() for x in args.exclude_blastdb.split(",") if x.strip()}
    source_log: list[dict] = []
    skipped: dict[str, str] = {}

    target_routes = tuple(args.only_routes.split(",")) if args.only_routes else ROUTES
    # human_domestic_contamination must still be collected (not necessarily
    # written) whenever bacteria_pathogen or plant are targets, since their
    # possible_contamination class is injected from its known_species pool.
    watch_routes = target_routes
    if any(r in target_routes for r in ("bacteria_pathogen", "plant")) and "human_domestic_contamination" not in watch_routes:
        watch_routes = watch_routes + ("human_domestic_contamination",)
    print(f"target routes: {target_routes}  (watching: {watch_routes})")

    def run(name: str, records, **kw) -> None:
        box = [0]
        t0 = time.time()
        added = ingest(collector, _counted(records, box), watch_routes=watch_routes, **kw)
        source_log.append({"source": name, "scanned": box[0], "added_chunks": added,
                           "seconds": round(time.time() - t0, 1)})
        print(f"    {name}: scanned {box[0]:,}, added {added:,} ({time.time() - t0:.0f}s)", flush=True)

    print("== BOLD ==")
    bold = find_bold_parquet(raw / "bold")
    if bold is None:
        # BOLD needs an owner login (roadmap Day 1); build without it.
        skipped["bold"] = f"no BOLD_Public*.parquet in {raw / 'bold'}"
        print(f"  WARNING: skipping BOLD: {skipped['bold']}")
    else:
        print(f"  {bold.name}")
        run(f"bold:{bold.name}", sources.iter_bold(bold), max_scan=BOLD_MAX_SCAN)

    print("== MIDORI2 ==")
    # GB273 is one MIDORI2_GB273_RAW.zip (15 genes); older releases were
    # per-gene *.fasta.zip. Each gene is ingested on its own so the per-source
    # scan cap applies per gene rather than once across the whole zip.
    for f in sorted(set((raw / "midori2").glob("MIDORI2_*_RAW.zip")) | set((raw / "midori2").glob("*.fasta.zip"))):
        print(f"  {f.name}")
        with zipfile.ZipFile(f) as zf:
            members = sources.midori2_members(zf)
        genes = sorted({m.gene for m in members if m.gene and m.selection in (None, "UNIQ")})
        if any(m.selection for m in members) and genes:
            for gene in genes:
                run(f"midori2:{f.name}:{gene}", sources.iter_midori2(f, taxonomy, genes=(gene,)))
        else:
            run(f"midori2:{f.name}", sources.iter_midori2(f, taxonomy))

    print("== SILVA ==")
    for f in sorted((raw / "silva").glob("*.fasta.gz")):
        print(f"  {f.name}")
        run(f"silva:{f.name}", sources.iter_silva(f))

    print("== UNITE ==")
    unite_candidates = sorted(f for f in (raw / "unite").glob("**/*general_release*.fasta") if "_dev" not in f.name)
    if unite_candidates and "misc_unknown" in watch_routes:
        run(f"unite:{unite_candidates[0].name}", sources.iter_unite(unite_candidates[0]))

    if "human_domestic_contamination" in watch_routes:
        print("== GRCh38 ==")
        run("grch38", sources.iter_grch38(raw / "grch38" / "GRCh38_no_alt_analysis_set.fna.gz"),
            forced_route="human_domestic_contamination")

        print("== UniVec ==")
        for name in ("UniVec_Core", "UniVec"):
            f = raw / "univec" / name
            if f.exists():
                run(f"univec:{name}", sources.iter_univec(f), forced_route="human_domestic_contamination")

    supplementary = raw / "supplementary"
    if args.skip_supplementary:
        skipped["supplementary"] = "--skip-supplementary"
    elif supplementary.exists():
        # API-fetched sequences for thin classes; see training/README.md.
        print("== Supplementary (fetch_supplementary.py) ==")
        run("supplementary", sources.iter_supplementary(supplementary))

    if args.skip_blastdb:
        skipped["ncbi_blastdb"] = "--skip-blastdb"
    else:
        # tools/blast/ is the Linux build fetch_reference_data.sh installs;
        # tools/ncbi-blast-2.17.0+/ is the old Windows install.
        blastdbcmd = next((p for p in (root / "tools" / "blast" / "bin" / "blastdbcmd",
                                       root / "tools" / "ncbi-blast-2.17.0+" / "bin" / "blastdbcmd.exe")
                           if p.exists()), None)
        if blastdbcmd is None:
            raise SystemExit("blastdbcmd not found under tools/; run scripts/fetch_reference_data.sh")
        extracted = raw / "ncbi_blastdb" / "extracted"
        print("== NCBI BLAST DBs ==")
        for db_dir in sorted(extracted.iterdir()) if extracted.exists() else []:
            # DB base name = directory name; blastdbcmd wants the path w/o extension
            db_path = db_dir / db_dir.name
            if not any(db_dir.glob("*.nin")) and not any(db_dir.glob("*.??.nin")):
                continue
            if db_dir.name in excluded_dbs:
                skipped[f"ncbi_blastdb:{db_dir.name}"] = "--exclude-blastdb"
                print(f"  {db_dir.name}: excluded (--exclude-blastdb)")
                continue
            print(f"  {db_dir.name}")
            run(f"ncbi_blastdb:{db_dir.name}", sources.iter_blastdb(blastdbcmd, db_path, taxonomy), max_scan=300_000)
            if all(collector.is_full(r) for r in watch_routes):
                print("  watched routes full, stopping early")
                break

    print("== injecting cross-route contamination ==")
    inject_contamination(collector)

    print("== writing splits ==")
    stats = write_splits(collector, root / "processed", target_routes=target_routes,
                         split_mode=args.split_mode, near_dup_threshold=args.near_dup_threshold)

    print("\n=== Final dataset ===")
    grand_total = 0
    for route, info in stats.items():
        print(f"{route}: {info['total']} total  {info['by_label']}")
        for split, by_label in info["by_split"].items():
            print(f"    {split}: {sum(by_label.values())}  {dict(sorted(by_label.items()))}")
        grand_total += info["total"]
    print(f"\nTOTAL: {grand_total} records across {len(target_routes)} route(s)")

    report = {
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "wall_seconds": round(time.time() - t_start, 1),
        "args": vars(args),
        "caps": {r: collector.cap_for(r) for r in ROUTES},
        "sources": source_log,
        "skipped": skipped,
        "candidates_seen_per_route_label": {f"{r}/{lab}": n for (r, lab), n in sorted(collector.seen_counts.items())},
        "routes": stats,
    }
    out = root / "processed"
    out.mkdir(parents=True, exist_ok=True)
    (out / "build_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"wall time {report['wall_seconds']}s; report -> {out / 'build_report.json'}")


if __name__ == "__main__":
    main()
