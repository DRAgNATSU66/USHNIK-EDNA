"""
Held-out evaluation of the reference-lookup evidence provider (roadmap B4,
tracker t-1021-2). Day 10 does the formal taxon evaluation; this is the
Day 8 smoke-scale run that the provider's "done when" rests on.

Two phases, run from services/worker/:

  python -m training.eval_reference_lookup sample --out <dir>
      Samples up to --known rows of the class whose sequences carry a species
      name (known_species; misc_unknown has none, so its
      unknown_needs_online_confirmation rows stand in) and up to --novelty
      possible_novelty rows per route from processed/<route>/test.csv.
      With --ground-truth (default) it then streams the same sources the
      reference builder reads (build_reference_db._source_plan) and records
      the lineage of every source record whose sequence, or one of whose
      build_dataset chunks, is a sampled test row. The processed CSVs carry
      only sequence,label, so this exact-sequence provenance is the only
      ground truth available; rows it cannot trace are reported as such.
      Lineages from several source copies are merged with the builder's LCA,
      exactly as the reference DB merges duplicates.

  python -m training.eval_reference_lookup run --out <dir> [--routes a,b]
      Runs app.evidence.reference_lookup on each route's sample (one batched
      search per route, routes one after another) and writes per-row
      evidence plus a summary: assignment rate per rank, identity
      distribution, wall time, peak RSS of the search process, and
      species/genus accuracy against the traced ground truth.

The sampled rows are excluded from reference v2 (QNA-016 Q5: 0 of 17,251
held-out sequences in any ref.fasta), so a query never finds itself.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROUTES = ("fish", "plant", "animal_general", "bacteria_pathogen", "human_domestic_contamination", "misc_unknown")
KNOWN_CLASS = {r: "known_species" for r in ROUTES} | {"misc_unknown": "unknown_needs_online_confirmation"}


# ---------------------------------------------------------------------------
# sample + ground truth
# ---------------------------------------------------------------------------

def sample_rows(processed: Path, known: int, novelty: int, seed: int) -> dict[str, list[dict]]:
    csv.field_size_limit(sys.maxsize)
    rng = random.Random(seed)
    out: dict[str, list[dict]] = {}
    for route in ROUTES:
        f = processed / route / "test.csv"
        if not f.exists():
            continue
        with open(f, encoding="utf-8", newline="") as fh:
            rows = [(i, r["sequence"].strip().upper(), r["label"]) for i, r in enumerate(csv.DictReader(fh))]
        picked: list[dict] = []
        for label, n in ((KNOWN_CLASS[route], known), ("possible_novelty", novelty)):
            pool = [r for r in rows if r[2] == label]
            for i, seq, lab in sorted(rng.sample(pool, min(n, len(pool)))):
                picked.append({"id": f"{route}:test:{i}", "row": i, "label": lab, "sequence": seq})
        out[route] = picked
    return out


def trace_ground_truth(data_root: Path, samples: dict[str, list[dict]]) -> dict:
    from training import build_reference_db as brd
    from training.taxonomy import TaxonomyResolver

    want: dict[bytes, list[str]] = defaultdict(list)
    for rows in samples.values():
        for r in rows:
            want[brd._digest(r["sequence"])].append(r["id"])
    taxonomy = TaxonomyResolver(data_root / "tools" / "taxdump")
    names = brd.NameResolver(taxonomy)
    blastdbcmd = brd.find_tool("blastdbcmd", data_root)
    found: dict[str, dict] = {}
    t0 = time.time()
    for key, make_iter, _files in brd._source_plan(data_root / "raw", taxonomy, names, blastdbcmd, None):
        n = 0
        for rec in make_iter():
            n += 1
            digs = [brd._digest(rec.sequence)]
            if len(rec.sequence) > brd.CHUNK_SOURCE_LEN:
                digs += [brd._digest(c) for c in brd.build_dataset_chunks(rec.sequence)]
            hits = [rid for d in digs for rid in want.get(d, ())]
            if not hits:
                continue
            lineage = brd._drop_vague_species(rec.lineage)
            lin = brd.lineage_tuple(lineage)
            for rid in hits:
                cur = found.get(rid)
                if cur is None:
                    found[rid] = {"lineage": lin, "sources": {rec.src}, "accessions": [rec.acc], "copies": 1}
                else:
                    cur["lineage"] = brd.lca_lineage(cur["lineage"], lin)
                    cur["sources"].add(rec.src)
                    if len(cur["accessions"]) < 5:
                        cur["accessions"].append(rec.acc)
                    cur["copies"] += 1
        print(f"  {key}: {n:,} records, traced so far {len(found):,} ({time.time() - t0:.0f}s)", flush=True)
    return {rid: {"lineage": dict(v["lineage"]), "sources": sorted(v["sources"]),
                  "accessions": v["accessions"], "copies": v["copies"]} for rid, v in found.items()}


# ---------------------------------------------------------------------------
# run + summary
# ---------------------------------------------------------------------------

RANK_ORDER = ("species", "genus", "family", "order", "class", "phylum", "kingdom", "superkingdom")


def _pct(a: int, b: int) -> float | None:
    return round(100.0 * a / b, 1) if b else None


def summarise(route: str, rows: list[dict], evidence: list[dict], truth: dict) -> dict:
    by_class: dict[str, dict] = {}
    for label in sorted({r["label"] for r in rows}):
        idx = [i for i, r in enumerate(rows) if r["label"] == label]
        evs = [evidence[i] for i in idx]
        n = len(evs)
        status = Counter(e["status"] for e in evs)
        ranks = Counter(e["assignment"]["rank"] for e in evs if e["status"] == "assigned")
        top_ids = [e["hits"][0]["identity"] for e in evs if e["hits"]]
        qcovs = [e["hits"][0]["query_coverage"] for e in evs if e["hits"]]
        entry = {
            "n": n,
            "status": dict(status),
            "assigned_pct": _pct(status.get("assigned", 0), n),
            "rank_pct": {k: _pct(ranks.get(k, 0), n) for k in RANK_ORDER if ranks.get(k)},
            "with_hit_pct": _pct(len(top_ids), n),
            "top_identity_median": round(statistics.median(top_ids), 2) if top_ids else None,
            "top_identity_quartiles": [round(q, 2) for q in statistics.quantiles(top_ids, n=4)] if len(top_ids) > 1 else None,
            "top_identity_bins": {
                ">=99": sum(x >= 99 for x in top_ids), "97-99": sum(97 <= x < 99 for x in top_ids),
                "95-97": sum(95 <= x < 97 for x in top_ids), "90-95": sum(90 <= x < 95 for x in top_ids),
                "<90": sum(x < 90 for x in top_ids)},
            "top_qcov_median": round(statistics.median(qcovs), 1) if qcovs else None,
            "lca_tied": sum(1 for e in evs if e["assignment"].get("tied_taxa", 0) > 1),
        }
        # accuracy vs traced provenance
        sp_n = sp_ok = sp_assigned = sp_wrong = 0
        g_n = g_ok = g_assigned = g_wrong = 0
        traced = 0
        for i in idx:
            t = truth.get(rows[i]["id"])
            if not t:
                continue
            traced += 1
            tl = t["lineage"]
            a = evidence[i]["assignment"]
            al = a.get("lineage") or {}
            assigned = evidence[i]["status"] == "assigned"
            if tl.get("species"):
                sp_n += 1
                if assigned and a["rank"] == "species":
                    sp_assigned += 1
                    if al.get("species") == tl["species"]:
                        sp_ok += 1
                    else:
                        sp_wrong += 1
            if tl.get("genus"):
                g_n += 1
                if assigned and al.get("genus"):
                    g_assigned += 1
                    if al["genus"] == tl["genus"]:
                        g_ok += 1
                    else:
                        g_wrong += 1
        entry["ground_truth"] = {
            "traced": traced, "traced_pct": _pct(traced, n),
            "species": {"n": sp_n, "assigned_at_species": sp_assigned, "correct": sp_ok, "wrong": sp_wrong,
                        "recall_pct": _pct(sp_ok, sp_n), "precision_pct": _pct(sp_ok, sp_assigned)},
            "genus": {"n": g_n, "assigned_with_genus": g_assigned, "correct": g_ok, "wrong": g_wrong,
                      "recall_pct": _pct(g_ok, g_n), "precision_pct": _pct(g_ok, g_assigned)},
        }
        by_class[label] = entry
    e0 = evidence[0] if evidence else {}
    return {"route": route, "method": e0.get("method"), "reference_db": e0.get("reference_db"),
            "reference_db_version": e0.get("reference_db_version"), "by_class": by_class}


def run(out: Path, routes: list[str], method: str = "auto") -> None:
    from app.config import get_worker_settings
    from app.evidence.reference_lookup import ReferenceLookupProvider

    samples = json.loads((out / "sample.json").read_text())
    truth_path = out / "ground_truth.json"
    truth = json.loads(truth_path.read_text()) if truth_path.exists() else {}
    settings = get_worker_settings().model_copy(update={"reference_method": method})
    provider = ReferenceLookupProvider(settings)
    summary_path = out / f"summary_{method}.json"
    summary = json.loads(summary_path.read_text()) if summary_path.exists() else {}
    for route in routes:
        rows = samples.get(route) or []
        if not rows:
            continue
        print(f"== {route}: {len(rows)} queries", flush=True)
        t0 = time.time()
        evs = provider.lookup([(r["id"], r["sequence"]) for r in rows], route)
        wall = round(time.time() - t0, 1)
        evd = [e.to_dict() for e in evs]
        (out / f"evidence_{route}_{method}.json").write_text(json.dumps(evd, indent=1))
        s = summarise(route, rows, evd, truth)
        run_info = evd[0]["run"] if evd else {}
        s["wall_seconds"] = wall
        s["search"] = run_info
        summary[route] = s
        summary_path.write_text(json.dumps(summary, indent=1))
        print(json.dumps(s, indent=1), flush=True)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    ps = sub.add_parser("sample")
    ps.add_argument("--out", required=True)
    ps.add_argument("--data-dir", default=None)
    ps.add_argument("--known", type=int, default=300)
    ps.add_argument("--novelty", type=int, default=100)
    ps.add_argument("--seed", type=int, default=1021)
    ps.add_argument("--no-ground-truth", action="store_true")
    pr = sub.add_parser("run")
    pr.add_argument("--out", required=True)
    pr.add_argument("--routes", default=",".join(ROUTES))
    pr.add_argument("--method", choices=("auto", "vsearch", "blast"), default="auto",
                    help="auto = the provider's choice (vsearch within the UDB budget, else BLAST)")
    args = p.parse_args(argv)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if args.cmd == "sample":
        from training.build_reference_db import default_data_root
        root = Path(args.data_dir) if args.data_dir else default_data_root()
        samples = sample_rows(root / "processed", args.known, args.novelty, args.seed)
        (out / "sample.json").write_text(json.dumps(samples))
        print({r: Counter(x["label"] for x in v) for r, v in samples.items()}, flush=True)
        if not args.no_ground_truth:
            truth = trace_ground_truth(root, samples)
            (out / "ground_truth.json").write_text(json.dumps(truth, indent=1))
            for route, rows in samples.items():
                c = Counter((r["label"], r["id"] in truth) for r in rows)
                print(route, dict(c), flush=True)
    else:
        run(out, [r for r in args.routes.split(",") if r], args.method)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
