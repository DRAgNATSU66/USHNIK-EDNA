"""
Held-out evaluation of the taxon the orchestrator finally reports (roadmap
Day 10, tracker t-1023-3). QNA-020 measured the reference lookup alone on
~300 rows per route; this measures decision.predicted_taxon / taxon_rank
(after route selection and the plant genus cap) on every row of a split,
per true route, and tests the label-noise explanation of QNA-030.

Run from services/worker/ with SYNTHVEDA_DATA_ROOT set. Four phases, each
writing into --out <dir>:

  python -m training.eval_taxon run --split test --out <dir>
      Every row of processed/<route>/<split>.csv through the job's own
      stages (eval_orchestrator._pipeline_dicts: FASTA -> parser -> QC ->
      router) and Orchestrator.run, in seeded-shuffle chunks of --chunk rows
      (resumable: finished chunks are skipped). The reference provider is
      wrapped so the full hit list of every lookup (target id, accession,
      identity, lineage; the trace keeps only 3 hits without target ids) is
      kept for the leakage check. Writes rows_<split>.jsonl.

  python -m training.eval_taxon trace --split test --out <dir>
      Ground truth. (a) eval_reference_lookup.trace_ground_truth, unchanged:
      the lineage of the reference-builder source records each row (or the
      record it was chunked from) came from, LCA-merged across copies -- the
      QNA-020 ground truth; it skips records without a usable name. (b) the
      same streaming over the sources build_dataset read (reference plan +
      env_nt / nt_others first 300,001 records + UniVec_Core + GRCh38
      windows + every supplementary manifest), with the usable-name filter
      lifted, keeping every copy's organism name, accession, source and the
      SILVA path. (b) is what the possible_novelty labels were made from.
      Writes truth_<split>.json.

  python -m training.eval_taxon leak --split test --out <dir>
      Reference v2 leakage for the evaluated rows: exact (row or its source
      record in a ref.fasta) and same-source-record (a reference sequence
      whose contributing records share an accession with the row's source
      records, among the row's hits at >= 99% identity). Writes
      leak_<split>.json.

  python -m training.eval_taxon report --split test --out <dir> --json <results.json>
      Per true route and overall: assigned share by rank; rank-aware
      precision/recall at species/genus/family; wrong-route vs wrong-taxon
      errors; the genus cap's effect (uncapped species read from the trace);
      the same with leaky rows excluded; and the possible_novelty ->
      known_species / likely_taxonomic_group relabel audit (QNA-030).

Truth lineages are names, compared after the reference header's own
sanitising (build_reference_db._sanitize, '_' -> ' '), so "Homo sapiens"
in a source record and "Homo_sapiens" in a SINTAX header compare equal.
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import gzip
import json
import random
import re
import resource
import subprocess
import sys
import time
from collections import Counter, defaultdict
from itertools import islice
from pathlib import Path
from typing import Iterator

from training.eval_orchestrator import ROUTES, _data_root, _gpu_peak_mb, _pipeline_dicts, _read

EVAL_RANKS = ("species", "genus", "family")
RANK_ORDER = ("species", "genus", "family", "order", "class", "phylum", "kingdom", "superkingdom")
LINEAGE_RANKS = ("superkingdom", "kingdom", "phylum", "class", "order", "family", "genus", "species")
NEAR_DUP_IDENTITY = 99.0
RELABELLED_CLASSES = ("known_species", "likely_taxonomic_group")


# ---------------------------------------------------------------------------
# pure helpers (tested in tests/test_eval_taxon.py)
# ---------------------------------------------------------------------------

def norm_name(name: str | None) -> str | None:
    """A taxon name as the reference header stores it, back with spaces:
    build_reference_db._sanitize then '_' -> ' ', lower-cased."""
    if not name:
        return None
    out = []
    for ch in name.strip():
        out.append("_" if (ch in ",;:=" or ch.isspace()) else ch)
    s = "".join(out)
    while "__" in s:
        s = s.replace("__", "_")
    s = s.strip("_").replace("_", " ").lower()
    return s or None


def norm_lineage(lineage: dict | None) -> dict[str, str]:
    return {r: n for r in LINEAGE_RANKS if (n := norm_name((lineage or {}).get(r)))}


def acc_base(acc: str | None) -> str | None:
    """'MG559732.1' -> 'MG559732'; SILVA 'AB000106.1.1343' -> 'AB000106';
    'gb|X|' style ids -> the accession field. None for placeholders."""
    if not acc:
        return None
    a = acc.strip()
    if "|" in a:
        parts = [p for p in a.split("|") if p]
        a = parts[1] if len(parts) > 1 and parts[0] in ("gb", "emb", "dbj", "ref", "lcl") else parts[-1]
    a = a.split(".")[0].upper()
    return a if a and a not in ("NA", "NONE") else None


def predicted_lineage(row: dict) -> tuple[dict[str, str], dict[str, str]]:
    """(effective, uncapped) predicted lineage of one evaluated row.

    effective: the lineage behind decision.predicted_taxon -- the final
    route's reference assignment, cut at decision.taxon_rank (so the genus
    cap's dropped species is gone). uncapped: the same assignment before
    the genus cap (the trace keeps the reference payload as searched).
    Both empty when the decision names no taxon."""
    d = row.get("decision") or {}
    trace = row.get("decision_trace") or {}
    final = d.get("final_route")
    payload = None
    for e in trace.get("evidence") or []:
        if e.get("provider") == "reference_lookup" and e.get("route") == final and e.get("status") == "ok":
            payload = e.get("payload") or {}
            break
    if not d.get("predicted_taxon") or not payload or payload.get("status") != "assigned":
        return {}, {}
    full = norm_lineage(payload.get("lineage"))
    uncapped = dict(full)
    rank = d.get("taxon_rank")
    if rank in LINEAGE_RANKS:
        keep = LINEAGE_RANKS[: LINEAGE_RANKS.index(rank) + 1]
        eff = {r: v for r, v in full.items() if r in keep}
    else:
        eff = {}
    return eff, uncapped


def genus_capped(row: dict) -> bool:
    for c in (row.get("decision_trace") or {}).get("combine") or []:
        if c.get("step") == "taxon" and c.get("rule") == "genus_cap":
            return True
    return False


def rank_metrics(pairs: list[tuple[dict, dict]], ranks: tuple[str, ...] = EVAL_RANKS) -> dict:
    """Rank-aware precision/recall over (predicted lineage, true lineage) pairs.

    At rank R only rows whose truth has a value at R are gradable. A row is
    called at R when its predicted lineage has a value at R (a species call
    is also a genus and a family call); it is correct when that value equals
    the truth's. precision = correct / called, recall = correct / gradable.
    Rows with truth but no call count against recall only."""
    out = {}
    for r in ranks:
        gradable = called = correct = 0
        called_ungradable = 0
        for pred, truth in pairs:
            if r in pred and r not in truth:
                called_ungradable += 1
            if r not in truth:
                continue
            gradable += 1
            if r in pred:
                called += 1
                correct += pred[r] == truth[r]
        out[r] = {"gradable": gradable, "called": called, "correct": correct, "wrong": called - correct,
                  "precision_pct": _pct(correct, called), "recall_pct": _pct(correct, gradable),
                  "called_without_truth_at_rank": called_ungradable}
    return out


def _pct(a: int, b: int) -> float | None:
    return round(100.0 * a / b, 1) if b else None


def lca(lineages: list[dict[str, str]]) -> dict[str, str]:
    """build_reference_db.lca_lineage over normalised dicts: rank-by-rank
    from the top; a rank only one side fills is kept; the first rank where
    both have a value and differ ends the lineage."""
    if not lineages:
        return {}
    cur = dict(lineages[0])
    for other in lineages[1:]:
        out = {}
        for r in LINEAGE_RANKS:
            a, b = cur.get(r), other.get(r)
            if a and b:
                if a != b:
                    break
                out[r] = a
            elif a or b:
                out[r] = a or b
        cur = out
    return cur


_UNRESOLVED = re.compile(r"uncultured|environmental sample|unidentified|unclassified|metagenome", re.IGNORECASE)


def name_category(name: str | None) -> str:
    """Which part of labeling._UNRESOLVED_PATTERNS a source name matched,
    or 'named' when none (the row's label then came from another copy)."""
    n = (name or "").lower()
    for key in ("uncultured", "environmental sample", "unidentified", "unclassified", "metagenome"):
        if key in n:
            return key
    return "named" if n else "empty"


def names_in(copies: list[dict]) -> dict[str, set[str]]:
    """Genus and species names a set of source copies carried, from the
    organism name words and from every lineage (NCBI-unified and SILVA
    path). 'uncultured Bacteroides sp.' carries genus 'bacteroides'."""
    genera: set[str] = set()
    species: set[str] = set()
    stop = {"uncultured", "unidentified", "unclassified", "environmental", "sample", "bacterium", "organism",
            "eukaryote", "fungus", "metazoan", "marine", "soil", "candidatus", "sp", "sp.", "cf.", "aff.",
            "metagenome", "prokaryote", "archaeon", "clone"}
    for c in copies:
        for lin in (c.get("lineage") or {}, c.get("path_lineage") or {}):
            nl = norm_lineage(lin)
            if nl.get("genus"):
                genera.add(nl["genus"])
            if nl.get("species") and not _UNRESOLVED.search(nl["species"]) and " sp." not in nl["species"] + ".":
                species.add(nl["species"])
        words = [w for w in re.split(r"[\s_]+", (c.get("organism") or "").strip()) if w]
        words_l = [w.lower() for w in words]
        cands = [w for w, wl in zip(words, words_l) if wl not in stop and w[:1].isupper() and w.isalpha()]
        if cands:
            genera.add(cands[0].lower())
            i = words.index(cands[0])
            if i + 1 < len(words) and words[i + 1].islower() and words[i + 1].isalpha() and \
                    words[i + 1] not in ("sp", "bacterium", "environmental"):
                species.add(f"{cands[0]} {words[i + 1]}".lower())
    return {"genus": genera, "species": species}


def classify_relabel(row_names: dict[str, set[str]], hit_lineage: dict[str, str], name_cats: set[str],
                     same_specimen: str) -> tuple[str, str]:
    """(verdict, reason) for one possible_novelty row the orchestrator
    relabelled. verdict:
      label_noise        the source record itself names the taxon the hit
                         names (same species, or same genus for a genus-or-
                         coarser call), or the hit is the same specimen in
                         another database: the sequence is known, only its
                         submitter's name was 'uncultured/environmental'
      real_disagreement  the source names a genus and the hit names a
                         different genus: the reference and the record
                         disagree about what the organism is
      undetermined       the source carries no genus/species name to
                         compare (e.g. 'uncultured bacterium'), and no
                         same-specimen evidence
    """
    hl = norm_lineage(hit_lineage)
    if same_specimen == "same_accession":
        return "label_noise", "hit is the same source record (shared accession) in another database"
    hs, hg = hl.get("species"), hl.get("genus")
    if hs and hs in row_names["species"]:
        return "label_noise", "source record names the hit's species"
    if hg and hg in row_names["genus"]:
        return "label_noise", "source record names the hit's genus"
    if row_names["genus"] and hg:
        return "real_disagreement", "source record names a different genus"
    if row_names["genus"] and not hg:
        # the hit only resolves above genus: compare the family if the row has one
        return "undetermined", "hit resolves above genus; source names a genus"
    return "undetermined", f"source carries no genus name ({', '.join(sorted(name_cats)) or 'none'})"


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------

class _FullHitRecorder:
    """Wraps ReferenceLookupProvider: keeps every lookup's full hit list
    (with target ids) and each batch's run info."""

    def __init__(self, inner):
        self.inner = inner
        self.hits: dict[tuple[str, str], list[dict]] = {}
        self.runs: list[dict] = []

    def lookup(self, items, route):
        ev = self.inner.lookup(items, route)
        for (sid, _), e in zip(items, ev):
            self.hits[(str(sid), route)] = [
                {k: h.get(k) for k in ("target_id", "accession", "source", "marker", "identity",
                                       "query_coverage", "alignment_length", "lineage", "merged_copies")}
                for h in (e.to_dict().get("hits") or [])]
        if ev:
            self.runs.append({"route": route, "n": len(items), "available": ev[0].available,
                              "reason": ev[0].reason, **(ev[0].run or {})})
        return ev


def _split_rows(split: str) -> list[dict]:
    rows = []
    for route in ROUTES:
        for i, seq, label in _read(route, split):
            rows.append({"id": f"{route}:{split}:{i}", "sequence": seq, "label": label, "true_route": route})
    return rows


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except ValueError:   # a torn last line from a killed run
                    pass
    return out


def cmd_run(args: argparse.Namespace) -> None:
    from app.config import get_worker_settings
    from app.evidence.providers import ReferenceEvidenceProvider
    from app.evidence.reference_lookup import ReferenceLookupProvider
    from app.orchestrator import ORCHESTRATOR_VERSION, Orchestrator

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    settings = get_worker_settings()
    rows = _split_rows(args.split)
    if args.limit:
        rows = random.Random(args.seed).sample(rows, min(args.limit, len(rows)))
    random.Random(args.seed).shuffle(rows)
    chunks = [rows[i:i + args.chunk] for i in range(0, len(rows), args.chunk)]
    rows_path = out / f"rows_{args.split}.jsonl"
    done = {r["id"] for r in _load_jsonl(rows_path)}
    meta_path = out / f"run_{args.split}.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {
        "orchestrator_version": ORCHESTRATOR_VERSION, "split": args.split, "seed": args.seed,
        "chunk": args.chunk, "input_rows": len(rows), "chunks": []}
    recorder = _FullHitRecorder(ReferenceLookupProvider(settings))
    orch = Orchestrator(settings, reference=ReferenceEvidenceProvider(recorder, settings=settings))
    by_id = {r["id"]: r for r in rows}
    for ci, chunk in enumerate(chunks):
        todo = [r for r in chunk if r["id"] not in done]
        if not todo:
            continue
        recorder.hits.clear()
        recorder.runs.clear()
        t0 = time.perf_counter()
        seqs = _pipeline_dicts(todo)
        t1 = time.perf_counter()
        stats = orch.run(seqs)
        t2 = time.perf_counter()
        with open(rows_path, "a", encoding="utf-8") as fh:
            for s in seqs:
                t = by_id[s["sequence_id"]]
                planned = (s.get("decision_trace") or {}).get("plan", {}).get("routes") or []
                fh.write(json.dumps({
                    "id": s["sequence_id"], "label": t["label"], "true_route": t["true_route"],
                    "router_route": s.get("router_route"),
                    "decision": s["decision"], "decision_trace": s["decision_trace"],
                    "ref_hits": {r: recorder.hits.get((s["sequence_id"], r)) for r in planned
                                 if (s["sequence_id"], r) in recorder.hits},
                }, default=str) + "\n")
            parsed = {s["sequence_id"] for s in seqs}
            for r in todo:
                if r["id"] not in parsed:   # the parser's min_length=10 drop
                    fh.write(json.dumps({"id": r["id"], "label": r["label"], "true_route": r["true_route"],
                                         "dropped_by_parser": True}) + "\n")
        meta["chunks"].append({"chunk": ci, "rows": len(todo), "after_parse": len(seqs),
                               "routing_seconds": round(t1 - t0, 2), "orchestrator_seconds": round(t2 - t1, 2),
                               "reference_batches": list(recorder.runs), "stats": stats,
                               "peak_gpu_allocated_mb": _gpu_peak_mb(),
                               "peak_rss_mb_python": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)})
        meta_path.write_text(json.dumps(meta, indent=1, default=str))
        done.update(r["id"] for r in todo)
        print(f"chunk {ci + 1}/{len(chunks)}: {len(seqs)} rows, route {t1 - t0:.1f}s, orchestrator {t2 - t1:.1f}s, "
              f"{len(done)}/{len(rows)} done", flush=True)
    print("run complete", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--split", default="test", choices=("dev", "test"))
    r.add_argument("--out", required=True)
    r.add_argument("--chunk", type=int, default=1000)
    r.add_argument("--seed", type=int, default=1023)
    r.add_argument("--limit", type=int, default=0, help="seeded sample of this many rows (0 = every row)")
    args = ap.parse_args()
    {"run": cmd_run}[args.cmd](args)


if __name__ == "__main__":
    main()
