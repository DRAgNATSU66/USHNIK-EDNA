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
    """Genus keys (genus_key) and species names (lower case) that a set of
    source copies carried: from each copy's lineage (NCBI-unified, after
    _drop_vague_species), its SILVA path, and the first capitalised word of
    its organism name (plus the next word when it is a lower-case epithet).
    'uncultured Bacteroides sp.' carries genus 'bacteroides', no species."""
    genera: set[str] = set()
    species: set[str] = set()
    for c in copies:
        for lin in (c.get("lineage") or {}, c.get("path_lineage") or {}):
            nl = norm_lineage(lin)
            if (g := genus_key(nl.get("genus"))):
                genera.add(g)
            sp = nl.get("species")
            if sp and not _UNRESOLVED.search(sp) and not re.search(r"\bsp\.?(\s|$)|\bcf\.\s", sp):
                species.add(sp)
        words = [w for w in re.split(r"[\s_]+", (c.get("organism") or "").strip()) if w]
        for i, w in enumerate(words):
            if w.lower() in _NAME_STOP or not (w[:1].isupper() and w.isalpha()):
                continue
            if (g := genus_key(w)):
                genera.add(g)
                nxt = words[i + 1] if i + 1 < len(words) else ""
                if nxt.isalpha() and nxt.islower() and nxt not in ("sp", "bacterium", "environmental", "cf", "aff"):
                    species.add(f"{w} {nxt}".lower())
            break
    return {"genus": genera, "species": species}


_NAME_STOP = {"uncultured", "unidentified", "unclassified", "environmental", "sample", "bacterium", "organism",
              "eukaryote", "fungus", "metazoan", "marine", "soil", "candidatus", "metagenome", "prokaryote",
              "archaeon", "clone", "vector/adapter:", "unknown"}


def genus_key(name: str | None) -> str | None:
    """Comparable genus: lower-case first word, 'Candidatus' dropped, so
    SILVA's 'Clostridium sensu stricto 1' and NCBI's 'Clostridium' agree.
    None for placeholders ('uncultured', 'unidentified', ...)."""
    if not name:
        return None
    words = [w for w in name.lower().replace("_", " ").split() if w != "candidatus"]
    if not words or _UNRESOLVED.search(words[0]) or words[0] in ("incertae", "unknown", "environmental"):
        return None
    return words[0].strip("[]'\"")


def classify_relabel(row_names: dict[str, set[str]], hit_lineage: dict[str, str], name_cats: set[str],
                     same_specimen: str, named_copy_names: dict[str, set[str]] | None = None) -> tuple[str, str]:
    """(verdict, reason) for one possible_novelty row the orchestrator
    relabelled known_species / likely_taxonomic_group.

      label_noise        the hit is the same source record in another
                         database (shared accession); or the source records
                         name the hit's species; or they name the hit's
                         genus and no conflicting species: the sequence
                         belongs to a taxon its own record names, and only
                         the 'uncultured / environmental' wording made the
                         label
      real_disagreement  the source records name a different genus, or the
                         same genus but a different species
      undetermined       the source carries no genus or species to compare
                         ('uncultured bacterium'), or the hit resolves only
                         above genus, and no shared accession
    row_names: names_in(all copies); named_copy_names: names_in(copies with
    a usable organism name), only used to word the reason."""
    hl = norm_lineage(hit_lineage)
    hs, hg = hl.get("species"), genus_key(hl.get("genus"))

    def via(key: str, value: str) -> str:
        if named_copy_names and value in named_copy_names.get(key, set()):
            return "a named copy of the identical sequence"
        return "the source record"

    if same_specimen == "same_accession":
        return "label_noise", "hit is the same source record (shared accession) in another database"
    if hs and hs in row_names["species"]:
        return "label_noise", f"{via('species', hs)} names the hit's species"
    if hg and hg in row_names["genus"]:
        if hs and any(genus_key(s) == hg for s in row_names["species"]):
            return "real_disagreement", "same genus, but the source names a different species"
        return "label_noise", f"{via('genus', hg)} names the hit's genus"
    if row_names["genus"] and hg:
        return "real_disagreement", "the source names a different genus"
    if row_names["genus"]:
        return "undetermined", "the hit resolves only above genus"
    return "undetermined", f"the source carries no genus or species name ({', '.join(sorted(name_cats)) or 'none'})"


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


# ---------------------------------------------------------------------------
# trace: every source copy of every row
# ---------------------------------------------------------------------------

# build_dataset read these BLAST DBs only up to its max_scan (300,000; the
# 300,001st record stops it). They are not in the reference plan: their
# records are mostly "uncultured"/"environmental" and name nothing.
DATASET_ONLY_BLASTDB = {"env_nt": 300_001, "nt_others": 300_001}
DATASET_EXCLUDED_BLASTDB = {"nt_viruses", "ref_prok_rep_genomes", "taxdb"}   # build_report args


@contextlib.contextmanager
def _usable_name_lifted():
    """build_reference_db's iterators drop records without a usable organism
    name before yielding them; the possible_novelty rows came from exactly
    those records. Lift that filter for the duration of the trace only."""
    from training import build_reference_db as brd
    orig = brd._usable_name
    brd._usable_name = lambda name: bool(name and name.strip())
    try:
        yield orig
    finally:
        brd._usable_name = orig


def _iter_blastdb_all(blastdbcmd: Path, db_path: Path, taxonomy, marker: str, limit: int | None):
    """Like build_reference_db.iter_blastdb_ref without the name and length
    filters (sources.iter_blastdb has neither), with accessions."""
    from training import build_reference_db as brd
    from training import sources

    proc = subprocess.Popen([str(blastdbcmd), "-db", str(db_path), "-entry", "all", "-outfmt", "%a|%T|%s"],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                            encoding="utf-8", errors="replace", bufsize=1 << 20)
    n = 0
    try:
        for line in proc.stdout:
            acc, taxid_s, raw_seq = (line.rstrip("\n").split("|", 2) + ["", ""])[:3]
            if not taxid_s.isdigit():
                continue
            seq = sources._clean_sequence(raw_seq)
            if not seq:
                continue
            n += 1
            if limit and n > limit:
                break
            taxid = int(taxid_s)
            yield brd.RefRecord(seq, dict(taxonomy.lineage(taxid)), taxid, acc, db_path.name, marker,
                                taxonomy.scientific_name(taxid) or "")
    finally:
        proc.stdout.close()
        proc.kill()
        proc.wait()


def _iter_grch38_windows(path: Path):
    from training import build_reference_db as brd
    from training import sources
    for i, rec in enumerate(sources.iter_grch38(path)):
        yield brd.RefRecord(rec.sequence, {"superkingdom": "Eukaryota", "kingdom": "Metazoa", "genus": "Homo",
                                           "species": "Homo sapiens"}, 9606, f"GRCh38_window_{i}", "grch38",
                            "genome", "Homo sapiens", forced_route="human_domestic_contamination")


def full_source_plan(root: Path, taxonomy, names, blastdbcmd: Path | None) -> list[tuple[str, callable]]:
    """Every source build_dataset read, as RefRecords with accessions. Call
    inside _usable_name_lifted()."""
    from training import build_reference_db as brd

    raw = root / "raw"
    plan: list = []
    for key, make_iter, _files in brd._source_plan(raw, taxonomy, names, None, {"midori2", "silva", "unite", "bold"}):
        plan.append((key, make_iter))
    supp = raw / "supplementary"
    if supp.exists():
        pairs = [(m, m.with_name(m.name[: -len(".manifest.csv")] + ".fasta"))
                 for m in sorted(supp.glob("*/*.manifest.csv"))]
        pairs = [(m, f) for m, f in pairs if f.exists()]
        plan.append(("supplementary", lambda q=pairs: brd.iter_supplementary_ref(supp, taxonomy, q)))
    for name in ("UniVec", "UniVec_Core"):
        f = raw / "univec" / name
        if f.exists():
            plan.append((f"univec:{name}", lambda f=f: brd.iter_univec_ref(f)))
    grch = raw / "grch38" / "GRCh38_no_alt_analysis_set.fna.gz"
    if grch.exists():
        plan.append(("grch38_windows", lambda: _iter_grch38_windows(grch)))
    extracted = raw / "ncbi_blastdb" / "extracted"
    markers = dict(brd.BLAST_SOURCES)
    if blastdbcmd is not None and extracted.exists():
        for d in sorted(extracted.iterdir()):
            if d.name in DATASET_EXCLUDED_BLASTDB or not d.is_dir():
                continue
            if not (any(d.glob("*.nin")) or any(d.glob("*.nal")) or any(d.glob("*.??.nin"))):
                continue
            plan.append((f"ncbi_blastdb:{d.name}",
                         lambda d=d: _iter_blastdb_all(blastdbcmd, d / d.name, taxonomy, markers.get(d.name, "nt"),
                                                       DATASET_ONLY_BLASTDB.get(d.name))))
    return plan


def _silva_paths(raw: Path, want: dict[bytes, list[str]]) -> dict[str, list[dict]]:
    """SILVA's own path for every matched record (the NCBI-unified lineage
    of 'uncultured bacterium' is just Bacteria; the path keeps the genus)."""
    from training import build_reference_db as brd
    from training import sources

    out: dict[str, list[dict]] = defaultdict(list)
    for p in sorted((raw / "silva").glob("*.fasta.gz")):
        with gzip.open(p, "rt", encoding="utf-8", errors="replace") as fh:
            for header, raw_seq in sources._iter_fasta(fh):
                seq = sources._clean_sequence(raw_seq)
                if not seq:
                    continue
                digs = [brd._digest(seq)]
                if len(seq) > brd.CHUNK_SOURCE_LEN:
                    digs += [brd._digest(c) for c in brd.build_dataset_chunks(seq)]
                hits = [rid for d in digs for rid in want.get(d, ())]
                if not hits:
                    continue
                acc, _, path = header.partition(" ")
                tokens = path.split(";")
                pl: dict[str, str] = {}
                if tokens and tokens[0] in ("Bacteria", "Archaea") and len(tokens) == 7:
                    pl = dict(zip(("superkingdom", "phylum", "class", "order", "family", "genus"), tokens[:6]))
                for rid in hits:
                    out[rid].append({"acc": acc, "path": path, "path_lineage": pl, "organism": tokens[-1] if tokens else "",
                                     "src": "silva", "marker": "LSU" if "LSU" in p.name else "SSU",
                                     "seq_digest": brd._digest(seq).hex()})
    return out


MAX_COPIES_KEPT = 40


def trace_all_copies(root: Path, rows: list[dict]) -> dict[str, dict]:
    from training import build_reference_db as brd
    from training.taxonomy import TaxonomyResolver

    want: dict[bytes, list[str]] = defaultdict(list)
    for r in rows:
        want[brd._digest(r["sequence"])].append(r["id"])
    taxonomy = TaxonomyResolver(root / "tools" / "taxdump")
    names = brd.NameResolver(taxonomy)
    blastdbcmd = brd.find_tool("blastdbcmd", root)
    found: dict[str, dict] = {}
    t0 = time.time()
    with _usable_name_lifted() as usable:
        for key, make_iter in full_source_plan(root, taxonomy, names, blastdbcmd):
            n = 0
            for rec in make_iter():
                n += 1
                digs = [brd._digest(rec.sequence)]
                if len(rec.sequence) > brd.CHUNK_SOURCE_LEN:
                    digs += [brd._digest(c) for c in brd.build_dataset_chunks(rec.sequence)]
                hits = [rid for d in digs for rid in want.get(d, ())]
                if not hits:
                    continue
                copy = {"src": rec.src, "marker": rec.marker, "acc": rec.acc, "organism": rec.organism,
                        "usable_name": bool(usable(rec.organism)) or rec.forced_route is not None,
                        "lineage": brd._drop_vague_species(rec.lineage), "taxid": rec.taxid,
                        "chunked": len(rec.sequence) > brd.CHUNK_SOURCE_LEN, "seq_digest": digs[0].hex()}
                for rid in hits:
                    cur = found.setdefault(rid, {"copies": [], "n_copies": 0, "accessions": set()})
                    cur["n_copies"] += 1
                    if (b := acc_base(rec.acc)):
                        cur["accessions"].add(b)
                    if len(cur["copies"]) < MAX_COPIES_KEPT:
                        cur["copies"].append(copy)
            print(f"  {key}: {n:,} records, traced so far {len(found):,} ({time.time() - t0:.0f}s)", flush=True)
    for rid, extra in _silva_paths(root / "raw", want).items():
        cur = found.setdefault(rid, {"copies": [], "n_copies": 0, "accessions": set()})
        for e in extra:
            if (b := acc_base(e["acc"])):
                cur["accessions"].add(b)
            match = next((c for c in cur["copies"] if c["src"] == "silva" and c["acc"] == e["acc"]), None)
            if match is not None:
                match["path"], match["path_lineage"] = e["path"], e["path_lineage"]
            elif len(cur["copies"]) < MAX_COPIES_KEPT:   # organelle rRNA brd could not place
                cur["n_copies"] += 1
                cur["copies"].append({**e, "usable_name": bool(usable(e["organism"])), "lineage": {},
                                      "taxid": None, "chunked": False})
    print(f"  silva paths done ({time.time() - t0:.0f}s)", flush=True)
    for v in found.values():
        v["accessions"] = sorted(v["accessions"])
        named = [norm_lineage(c["lineage"]) for c in v["copies"] if c["usable_name"] and c["lineage"]]
        anyl = [norm_lineage(c["lineage"]) for c in v["copies"] if c["lineage"]]
        v["lca_named"] = lca(named) if named else None
        v["lca_any"] = lca(anyl) if anyl else None
    return found


def cmd_trace(args: argparse.Namespace) -> None:
    from training import eval_reference_lookup as erl

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    root = _data_root()
    rows = _split_rows(args.split)
    t0 = time.time()
    print("== (a) eval_reference_lookup.trace_ground_truth (QNA-020 ground truth, unchanged)", flush=True)
    samples: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        samples[r["true_route"]].append({"id": r["id"], "sequence": r["sequence"]})
    named = erl.trace_ground_truth(root, dict(samples))
    ta = time.time() - t0
    print(f"== (b) every source copy, names kept ({ta:.0f}s so far)", flush=True)
    copies = trace_all_copies(root, rows)
    truth = {}
    for r in rows:
        a = named.get(r["id"])
        b = copies.get(r["id"])
        truth[r["id"]] = {
            "reference_truth": {"lineage": a["lineage"], "sources": a["sources"], "accessions": a["accessions"],
                                "copies": a["copies"]} if a else None,
            **(b or {"copies": [], "n_copies": 0, "accessions": [], "lca_named": None, "lca_any": None}),
        }
    meta = {"split": args.split, "rows": len(rows), "traced_reference_view": len(named),
            "traced_any_copy": len(copies), "seconds_reference_view": round(ta, 1),
            "seconds_total": round(time.time() - t0, 1)}
    (out / f"truth_{args.split}.json").write_text(json.dumps({"meta": meta, "rows": truth}, default=str))
    print(json.dumps(meta), flush=True)


# ---------------------------------------------------------------------------
# leak: reference v2 vs the evaluated rows
# ---------------------------------------------------------------------------

def _ref_dir(root: Path) -> tuple[Path, str]:
    ref = root / "reference"
    version = (ref / "CURRENT").read_text().strip() if (ref / "CURRENT").exists() else "v2"
    return ref / version, version


def _read_ref_digests(ref_dir: Path, want_ids: set[str]) -> tuple[set[bytes], dict[str, bytes], dict[str, int]]:
    """Digest of every ref.fasta sequence (all routes), and id -> digest for
    want_ids (the hit target ids)."""
    from training import build_reference_db as brd
    from training import sources

    all_d: set[bytes] = set()
    by_id: dict[str, bytes] = {}
    counts: dict[str, int] = {}
    for route in ROUTES:
        f = ref_dir / route / "ref.fasta"
        if not f.exists():
            continue
        n = 0
        with open(f, encoding="utf-8", errors="replace") as fh:
            for header, seq in sources._iter_fasta(fh):
                d = brd._digest(seq.strip().upper())
                all_d.add(d)
                sid = header.split(";", 1)[0]
                if sid in want_ids:
                    by_id[sid] = d
                n += 1
        counts[route] = n
    return all_d, by_id, counts


def same_record_hits(hits: list[dict], row_accs: set[str], ref_accs: dict[str, set[str]],
                     min_identity: float = NEAR_DUP_IDENTITY) -> list[dict]:
    """Hits at >= min_identity whose reference record came (in any of its
    merged copies) from a source record sharing an accession with the row's
    own source records."""
    out = []
    for h in hits or []:
        if (h.get("identity") or 0) < min_identity:
            continue
        accs = set(ref_accs.get(h.get("target_id") or "", set()))
        if (b := acc_base(h.get("accession"))):
            accs.add(b)
        shared = accs & row_accs
        if shared:
            out.append({"target_id": h.get("target_id"), "accession": h.get("accession"),
                        "identity": h.get("identity"), "shared_accessions": sorted(shared)})
    return out


def cmd_leak(args: argparse.Namespace) -> None:
    from training import build_reference_db as brd
    from training.taxonomy import TaxonomyResolver

    out = Path(args.out)
    root = _data_root()
    rows = [r for r in _load_jsonl(out / f"rows_{args.split}.jsonl") if not r.get("dropped_by_parser")]
    truth = json.loads((out / f"truth_{args.split}.json").read_text())["rows"]
    seqs = {r["id"]: r["sequence"] for r in _split_rows(args.split)}
    hit_ids = {h["target_id"] for r in rows for hs in (r.get("ref_hits") or {}).values() for h in (hs or [])
               if h.get("target_id")}
    ref_dir, version = _ref_dir(root)
    t0 = time.time()
    ref_all, id_digest, ref_counts = _read_ref_digests(ref_dir, hit_ids)
    print(f"reference {version}: {sum(ref_counts.values()):,} sequences, {len(id_digest):,}/{len(hit_ids):,} hit ids "
          f"resolved ({time.time() - t0:.0f}s)", flush=True)
    # accessions behind every hit's reference record (all merged copies)
    digest_ids: dict[bytes, list[str]] = defaultdict(list)
    for sid, d in id_digest.items():
        digest_ids[d].append(sid)
    row_accs_all = {a for t in truth.values() for a in t.get("accessions") or []}
    ref_accs: dict[str, set[str]] = defaultdict(set)
    acc_in_ref: dict[str, set[str]] = defaultdict(set)   # row accession -> ref digests (hex) from that accession
    taxonomy = TaxonomyResolver(root / "tools" / "taxdump")
    names = brd.NameResolver(taxonomy)
    blastdbcmd = brd.find_tool("blastdbcmd", root)
    with _usable_name_lifted():
        for key, make_iter in full_source_plan(root, taxonomy, names, blastdbcmd):
            n = 0
            for rec in make_iter():
                n += 1
                b = acc_base(rec.acc)
                d = brd._digest(rec.sequence)
                if d in digest_ids and b:
                    for sid in digest_ids[d]:
                        ref_accs[sid].add(b)
                if b in row_accs_all and d in ref_all:
                    acc_in_ref[b].add(d.hex())
            print(f"  {key}: {n:,} records ({time.time() - t0:.0f}s)", flush=True)
    per_row = {}
    for r in rows:
        t = truth.get(r["id"]) or {}
        accs = set(t.get("accessions") or [])
        seq = seqs.get(r["id"], "")
        exact_row = brd._digest(seq) in ref_all
        exact_source = any(bytes.fromhex(c["seq_digest"]) in ref_all for c in t.get("copies") or []
                           if c.get("seq_digest"))
        all_hits = [h for hs in (r.get("ref_hits") or {}).values() for h in (hs or [])]
        final = (r.get("decision") or {}).get("final_route")
        same = same_record_hits(all_hits, accs, ref_accs)
        same_final = same_record_hits((r.get("ref_hits") or {}).get(final) or [], accs, ref_accs)
        per_row[r["id"]] = {
            "exact_row_in_ref": exact_row, "exact_source_record_in_ref": exact_source,
            "same_accession_sequence_in_ref": sorted(a for a in accs if acc_in_ref.get(a)),
            "same_record_hits_ge99": same, "same_record_hits_ge99_final_route": same_final,
            "leaky": bool(exact_row or exact_source or same),
        }
    summary = {
        "reference_version": version, "reference_sequences": ref_counts, "rows": len(per_row),
        "rows_with_accessions": sum(1 for r in rows if (truth.get(r["id"]) or {}).get("accessions")),
        "exact_row_in_ref": sum(v["exact_row_in_ref"] for v in per_row.values()),
        "exact_source_record_in_ref": sum(v["exact_source_record_in_ref"] for v in per_row.values()),
        "same_accession_sequence_in_ref_any_identity": sum(bool(v["same_accession_sequence_in_ref"]) for v in per_row.values()),
        "same_record_hit_ge99_any_planned_route": sum(bool(v["same_record_hits_ge99"]) for v in per_row.values()),
        "same_record_hit_ge99_final_route": sum(bool(v["same_record_hits_ge99_final_route"]) for v in per_row.values()),
        "leaky": sum(v["leaky"] for v in per_row.values()),
        "seconds": round(time.time() - t0, 1),
    }
    (out / f"leak_{args.split}.json").write_text(json.dumps({"summary": summary, "rows": per_row}))
    print(json.dumps(summary, indent=1), flush=True)


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------

KNOWN_CLASS = {r: "known_species" for r in ROUTES} | {"misc_unknown": "unknown_needs_online_confirmation"}


def grading_truth(t: dict | None) -> tuple[dict[str, str] | None, str]:
    """(normalised truth lineage, basis). The QNA-020 tracer's lineage
    (eval_reference_lookup.trace_ground_truth: named reference-builder
    records, LCA over copies) wins; a row it could not trace falls back to
    the LCA over named copies from the dataset-only sources, then over all
    copies (names like 'uncultured Salmo sp.' keep their genus)."""
    if not t:
        return None, "untraced"
    if t.get("reference_truth"):
        return norm_lineage(t["reference_truth"]["lineage"]), "reference_named"
    if t.get("lca_named"):
        return dict(t["lca_named"]), "named_copy_outside_reference_plan"
    if t.get("lca_any"):
        return dict(t["lca_any"]), "unresolved_name_only"
    return None, "untraced"


def _ref_payload(row: dict, route: str | None) -> dict | None:
    for e in (row.get("decision_trace") or {}).get("evidence") or []:
        if e.get("provider") == "reference_lookup" and e.get("route") == route and e.get("status") == "ok":
            return e.get("payload") or {}
    return None


def _ref_pred(payload: dict | None, cap: bool) -> dict[str, str]:
    if not payload or payload.get("status") != "assigned":
        return {}
    lin = norm_lineage(payload.get("lineage"))
    # combiner.combine caps on ORCHESTRATOR_GENUS_CAP_ROUTES or a Viridiplantae lineage
    if (cap or lin.get("kingdom") in ("viridiplantae", "plantae")) and "species" in lin:
        lin.pop("species")
    return lin


def summarise_taxon(rows: list[dict], truth: dict, leak: dict | None, genus_cap_routes: set[str]) -> dict:
    n = len(rows)
    rank_share = Counter((r.get("decision") or {}).get("taxon_rank") or "none" for r in rows)
    graded = []
    for r in rows:
        tl, basis = grading_truth(truth.get(r["id"]))
        eff, unc = predicted_lineage(r)
        graded.append((r, tl, basis, eff, unc))
    traced = [g for g in graded if g[1] is not None]
    basis = Counter(g[2] for g in graded)

    def metrics(sub):
        return rank_metrics([(eff, tl) for _, tl, _, eff, _ in sub])

    known = [g for g in traced if g[0]["label"] == KNOWN_CLASS[g[0]["true_route"]]]
    novelty = [g for g in traced if g[0]["label"] == "possible_novelty"]
    named_basis = [g for g in traced if g[2] == "reference_named"]
    # genus cap: the same rows, species read from the uncapped assignment
    capped = [g for g in traced if genus_capped(g[0])]
    cap_species_truth = [g for g in capped if "species" in g[1]]
    cap_effect = {
        "rows_capped": sum(genus_capped(r) for r in rows),
        "rows_capped_traced": len(capped),
        "capped_with_species_truth": len(cap_species_truth),
        "dropped_species_correct": sum(g[4].get("species") == g[1]["species"] for g in cap_species_truth),
        "species_with_cap": rank_metrics([(eff, tl) for _, tl, _, eff, _ in traced], ("species",))["species"],
        "species_without_cap": rank_metrics([(unc, tl) for _, tl, _, _, unc in traced], ("species",))["species"],
    }
    d = cap_effect
    d["dropped_species_precision_pct"] = _pct(d["dropped_species_correct"], d["capped_with_species_truth"])
    # errors: wrong final route vs wrong taxon in the right route
    errors = {}
    for rank in EVAL_RANKS:
        e = Counter()
        for r, tl, _, eff, _ in traced:
            if rank not in tl:
                continue
            right_route = (r.get("decision") or {}).get("final_route") == r["true_route"]
            where = "right_route" if right_route else "wrong_route"
            if rank in eff:
                if eff[rank] != tl[rank]:
                    e[f"wrong_call_{where}"] += 1
                    if not right_route:
                        planned = (r.get("decision_trace") or {}).get("plan", {}).get("routes") or []
                        if r["true_route"] in planned:
                            alt = _ref_pred(_ref_payload(r, r["true_route"]),
                                            r["true_route"] in genus_cap_routes)
                            e["wrong_route_true_route_planned"] += 1
                            e["wrong_route_true_route_reference_correct"] += alt.get(rank) == tl[rank]
            else:
                e[f"no_call_{where}"] += 1
                if not right_route and (r.get("decision") or {}).get("final_route") == "low_quality":
                    e["no_call_low_quality_gate"] += 1
        errors[rank] = dict(e)
    out = {
        "n": n,
        "labels": dict(Counter(r["label"] for r in rows)),
        "final_route_correct": sum((r.get("decision") or {}).get("final_route") == r["true_route"] for r in rows),
        "truth_basis": dict(basis),
        "assigned_share_by_rank_pct": {k: _pct(v, n) for k, v in sorted(rank_share.items(),
                                                                         key=lambda kv: (RANK_ORDER + ("none",)).index(kv[0])
                                                                         if kv[0] in RANK_ORDER + ("none",) else 99)},
        "assigned_by_rank": dict(rank_share),
        "rank_metrics_all_traced": metrics(traced),
        "rank_metrics_known_class": metrics(known),
        "rank_metrics_possible_novelty": metrics(novelty),
        "rank_metrics_reference_named_truth_only": metrics(named_basis),
        "genus_cap": cap_effect,
        "errors_by_rank": errors,
    }
    if leak:
        clean = [g for g in traced if not (leak.get(g[0]["id"]) or {}).get("leaky")]
        out["leaky_rows"] = sum(1 for r in rows if (leak.get(r["id"]) or {}).get("leaky"))
        out["rank_metrics_all_traced_leaky_excluded"] = metrics(clean)
        out["rank_metrics_known_class_leaky_excluded"] = metrics(
            [g for g in clean if g[0]["label"] == KNOWN_CLASS[g[0]["true_route"]]])
    return out


def audit_relabels(rows: list[dict], truth: dict, leak: dict | None) -> list[dict]:
    """Every possible_novelty row whose final class is known_species or
    likely_taxonomic_group: what its source said, what the hit said, and a
    classify_relabel verdict."""
    out = []
    for r in rows:
        d = r.get("decision") or {}
        if r["label"] != "possible_novelty" or d.get("result_class") not in RELABELLED_CLASSES:
            continue
        t = truth.get(r["id"]) or {}
        copies = t.get("copies") or []
        payload = _ref_payload(r, d.get("final_route")) or {}
        full_hits = (r.get("ref_hits") or {}).get(d.get("final_route")) or []
        top = full_hits[0] if full_hits else ((payload.get("hits") or [{}])[0])
        lk = (leak or {}).get(r["id"]) or {}
        ident = payload.get("identity") or 0
        if lk.get("same_record_hits_ge99_final_route"):
            same = "same_accession"
        elif ident >= NEAR_DUP_IDENTITY:
            same = "possible_not_confirmable"
        else:
            same = "no_identity_below_99"
        cats = {name_category(c.get("organism")) for c in copies}
        if not copies:
            verdict, reason = "undetermined", "row not traced to a source record"
        else:
            verdict, reason = classify_relabel(names_in(copies), payload.get("lineage") or {}, cats, same,
                                               names_in([c for c in copies if c.get("usable_name")]))
        out.append({
            "id": r["id"], "true_route": r["true_route"], "final_route": d.get("final_route"),
            "result_class": d.get("result_class"), "rule": d.get("rule"),
            "source": {"names": sorted({c.get("organism") or "" for c in copies})[:8],
                       "name_categories": sorted(cats), "named_copy": any(c.get("usable_name") for c in copies),
                       "sources": sorted({c.get("src") or "" for c in copies}),
                       "accessions": (t.get("accessions") or [])[:8], "n_copies": t.get("n_copies", 0),
                       "silva_paths": sorted({c["path"] for c in copies if c.get("path")})[:3]},
            "hit": {"taxon": payload.get("taxon"), "rank": payload.get("rank"), "identity": payload.get("identity"),
                    "query_coverage": payload.get("query_coverage"), "lineage": payload.get("lineage"),
                    "reported_taxon": d.get("predicted_taxon"), "reported_rank": d.get("taxon_rank"),
                    "top_accession": top.get("accession"), "top_source_db": top.get("source"),
                    "top_marker": top.get("marker"), "reference_db": payload.get("reference_db")},
            "same_specimen": same, "same_record_hits": lk.get("same_record_hits_ge99_final_route") or [],
            "verdict": verdict, "reason": reason,
        })
    return out


def relabel_counts(audit: list[dict]) -> dict:
    def block(items):
        return {"n": len(items), "verdict": dict(Counter(a["verdict"] for a in items)),
                "reason": dict(Counter(a["reason"] for a in items).most_common()),
                "same_specimen": dict(Counter(a["same_specimen"] for a in items)),
                "source_name_categories": dict(Counter(c for a in items for c in a["source"]["name_categories"])),
                "named_copy_exists": sum(a["source"]["named_copy"] for a in items),
                "hit_identity_ge99": sum((a["hit"]["identity"] or 0) >= 99 for a in items)}
    return {"all": block(audit),
            "by_result_class": {c: block([a for a in audit if a["result_class"] == c]) for c in RELABELLED_CLASSES},
            "by_rule": {k: block([a for a in audit if a["rule"] == k]) for k in sorted({a["rule"] for a in audit})},
            "by_true_route": {k: block([a for a in audit if a["true_route"] == k]) for k in ROUTES
                              if any(a["true_route"] == k for a in audit)}}


def cmd_report(args: argparse.Namespace) -> None:
    from app.config import get_worker_settings

    out = Path(args.out)
    settings = get_worker_settings()
    cap_routes = set(settings.orchestrator_genus_cap_routes or [])
    report: dict = {"task": "t-1023-3", "date": time.strftime("%Y-%m-%d"),
                    "script": "services/worker/training/eval_taxon.py", "splits": {}}
    for split in args.splits.split(","):
        all_rows = _load_jsonl(out / f"rows_{split}.jsonl")
        if not all_rows:
            continue
        dropped = [r for r in all_rows if r.get("dropped_by_parser")]
        rows = [r for r in all_rows if not r.get("dropped_by_parser")]
        tpath, lpath = out / f"truth_{split}.json", out / f"leak_{split}.json"
        truth_doc = json.loads(tpath.read_text()) if tpath.exists() else {"meta": None, "rows": {}}
        truth = truth_doc["rows"]
        leak_doc = json.loads(lpath.read_text()) if lpath.exists() else None
        leak = leak_doc["rows"] if leak_doc else None
        run_meta = json.loads((out / f"run_{split}.json").read_text())
        chunks = run_meta["chunks"]
        # (a) vs (b) agreement on rows both traced with a named lineage
        agree = disagree = 0
        for t in truth.values():
            if t.get("reference_truth") and t.get("lca_named"):
                a = norm_lineage(t["reference_truth"]["lineage"])
                if a == t["lca_named"]:
                    agree += 1
                else:
                    disagree += 1
        audit = audit_relabels(rows, truth, leak)
        per_route = {route: summarise_taxon([r for r in rows if r["true_route"] == route], truth, leak, cap_routes)
                     for route in ROUTES}
        orch_s = sum(c["orchestrator_seconds"] for c in chunks)
        report["splits"][split] = {
            "orchestrator_version": run_meta["orchestrator_version"],
            "reference_db_version": next((p.get("reference_db_version") for r in rows
                                          if (p := _ref_payload(r, (r.get("decision") or {}).get("final_route")))),
                                         None),
            "rows": {"input": run_meta["input_rows"], "evaluated": len(rows), "dropped_by_parser": len(dropped),
                     "seed": run_meta["seed"], "chunk": run_meta["chunk"]},
            "timing": {"orchestrator_seconds": round(orch_s, 1),
                       "orchestrator_ms_per_sequence": round(1000 * orch_s / max(1, len(rows)), 1),
                       "reference_search_seconds_by_route": {
                           rt: round(sum(b.get("elapsed_seconds") or 0 for c in chunks for b in c["reference_batches"]
                                         if b["route"] == rt), 1) for rt in ROUTES},
                       "peak_gpu_allocated_mb": max((c.get("peak_gpu_allocated_mb") or 0) for c in chunks),
                       "peak_rss_mb_python": max(c["peak_rss_mb_python"] for c in chunks)},
            "truth": {"meta": truth_doc["meta"], "reference_view_vs_all_copies_named_lca": {
                "agree": agree, "differ": disagree}},
            "leakage": leak_doc["summary"] if leak_doc else None,
            "overall": summarise_taxon(rows, truth, leak, cap_routes),
            "per_route": per_route,
            "novelty_relabel_audit": relabel_counts(audit),
        }
        if args.audit_out:
            p = Path(args.audit_out.replace("{split}", split))
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "w", encoding="utf-8") as fh:
                for a in audit:
                    fh.write(json.dumps(a, default=str) + "\n")
    report["definitions"] = {
        "truth": grading_truth.__doc__.strip(),
        "rank_metrics": rank_metrics.__doc__.strip(),
        "predicted": predicted_lineage.__doc__.strip(),
        "relabel_verdict": classify_relabel.__doc__.strip(),
        "same_specimen": ("same_accession: a final-route hit at >= 99% identity whose reference record (any "
                          "merged copy) shares an accession with the row's source records; "
                          "possible_not_confirmable: assignment identity >= 99% but no shared accession (RefSeq "
                          "and INSDC copies of one specimen carry different accessions, so this cannot be "
                          "excluded); no_identity_below_99."),
        "leaky": "exact row or source record in a ref.fasta, or any planned-route hit >= 99% from the same source "
                 "record (shared accession)",
    }
    Path(args.json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.json).write_text(json.dumps(report, indent=1, default=str))
    print(markdown_tables(report), flush=True)


def markdown_tables(report: dict) -> str:
    lines = []
    for split, s in report["splits"].items():
        lines.append(f"### {split} ({s['rows']['evaluated']} rows, {s['orchestrator_version']}, reference "
                     f"{s['reference_db_version']})\n")
        lines.append("| Route | n | traced | sp / gen / fam / coarser / none (%) | Species P / R | Genus P / R | "
                     "Family P / R | Species P uncapped | Leaky | Species P / Genus P, leaky excl. |")
        lines.append("|---|---|---|---|---|---|---|---|---|---|")
        for name, m in list(s["per_route"].items()) + [("**all**", s["overall"])]:
            sh = m["assigned_share_by_rank_pct"]
            coarser = round(sum(v for k, v in sh.items() if k not in ("species", "genus", "family", "none")), 1)
            rm = m["rank_metrics_all_traced"]
            lx = m.get("rank_metrics_all_traced_leaky_excluded") or {}
            traced = m["n"] - m["truth_basis"].get("untraced", 0)
            pr = lambda x: f"{x['precision_pct']} / {x['recall_pct']}"
            lines.append(
                f"| {name} | {m['n']} | {traced} | {sh.get('species', 0)} / {sh.get('genus', 0)} / "
                f"{sh.get('family', 0)} / {coarser} / {sh.get('none', 0)} | {pr(rm['species'])} | {pr(rm['genus'])} | "
                f"{pr(rm['family'])} | {m['genus_cap']['species_without_cap']['precision_pct']} | "
                f"{m.get('leaky_rows', '-')} | "
                f"{(lx.get('species') or {}).get('precision_pct')} / {(lx.get('genus') or {}).get('precision_pct')} |")
        a = s["novelty_relabel_audit"]["all"]
        lines.append(f"\nRelabelled possible_novelty rows: {a['n']}; verdicts {a['verdict']}; "
                     f"same specimen {a['same_specimen']}.\n")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--split", default="test", choices=("dev", "test"))
    r.add_argument("--out", required=True)
    r.add_argument("--chunk", type=int, default=1000)
    r.add_argument("--seed", type=int, default=1023)
    r.add_argument("--limit", type=int, default=0, help="seeded sample of this many rows (0 = every row)")
    t = sub.add_parser("trace")
    t.add_argument("--split", default="test", choices=("dev", "test"))
    t.add_argument("--out", required=True)
    lk = sub.add_parser("leak")
    lk.add_argument("--split", default="test", choices=("dev", "test"))
    lk.add_argument("--out", required=True)
    rp = sub.add_parser("report")
    rp.add_argument("--out", required=True)
    rp.add_argument("--splits", default="test,dev")
    rp.add_argument("--json", required=True, help="results file, e.g. docs/ml/results/taxon_eval_2026-10-19.json")
    rp.add_argument("--audit-out", default=None, help="per-row relabel audit JSONL; {split} is substituted")
    args = ap.parse_args()
    {"run": cmd_run, "trace": cmd_trace, "leak": cmd_leak, "report": cmd_report}[args.cmd](args)


if __name__ == "__main__":
    main()
