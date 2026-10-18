"""
Builds the versioned per-route reference databases the reference-lookup
evidence provider searches (roadmap B4): for each of the 6 routes,

    <data>/reference/<version>/<route>/ref.fasta     SINTAX-style headers
    <data>/reference/<version>/<route>/ref.udb       vsearch index
    <data>/reference/<version>/<route>/blast/ref.*   BLAST+ v5 DB with taxids
    <data>/reference/<version>/manifest.json         counts, sha256, licences

plus a BLAST-only GRCh38 nuclear index under human_domestic_contamination/.

The route heads say *what kind* of result a sequence is; this database says
*which taxon* it is. It is a lookup reference, not training data, so the
choices differ from build_dataset.py:

  * Every curated record is kept (no per-label cap); exact duplicate
    sequences within a route are merged into one record whose taxonomy is
    the lowest common ancestor of the copies (identical barcodes deposited
    under two species resolve to the genus/family they share, rather than
    whichever copy was read first).
  * Records with no usable taxon ("uncultured bacterium", "environmental
    sample", "synthetic construct", ...) are dropped: a hit on them names
    nothing. nt_others is skipped wholesale for that reason (measured: its
    top taxids are uncultured organism 275,100, synthetic construct 260,137,
    uncultured prokaryote 175,383, unidentified 124,164 of 993,693).
  * Sequences that are in processed/*/{dev,test}.csv are left out, so the
    Day 10 taxon evaluation on held-out splits measures lookup of unseen
    sequences instead of each query finding itself at 100% identity. Long
    records are checked through the same chunking build_dataset applied.
  * Size: a route that fits in --max-route-bases (default 400 Mb) keeps
    every unique sequence. A larger one is capped per (lowest taxon, marker),
    longest first, stepping down CAP_LADDER (50, 20, 10, 5, 3, 2, 1) until it
    fits. vsearch loads the whole UDB into RAM per call (measured on a 776 Mb
    route: 3.45 GB UDB, 4.1 GB RSS per query), so the budget is set for it;
    a route that cannot fit even at 1 per group is kept at 1 and marked
    over_budget in the manifest - query it through BLAST, which memory-maps.

Header format (one token, no whitespace, so vsearch keeps it whole):

  >FSH0000001;tax=d:Eukaryota,k:Metazoa,p:Chordata,c:Actinopteri,o:Perciformes,f:Percidae,g:Perca,s:Perca_fluviatilis;src=midori2;marker=CO1;acc=MG559732.1;taxid=8168;n=3;

`tax=` is the vsearch --sintax format; src/marker/acc/taxid/n are extra
attributes vsearch ignores. parse_header() reads it back.

Run from services/worker/:
    python -m training.build_reference_db --version v1
"""
from __future__ import annotations

import argparse
import csv
import datetime as _dt
import gzip
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Iterator

from training import sources
from training.labeling import is_higher_rank_only, is_unresolved
from training.routing import ROUTES, lineage_to_route
from training.taxonomy import TaxonomyResolver

# ---------------------------------------------------------------------------
# Header format
# ---------------------------------------------------------------------------

RANKS = ("superkingdom", "kingdom", "phylum", "class", "order", "family", "genus", "species")
SINTAX_CODE = {
    "superkingdom": "d", "kingdom": "k", "phylum": "p", "class": "c",
    "order": "o", "family": "f", "genus": "g", "species": "s",
}
CODE_TO_RANK = {v: k for k, v in SINTAX_CODE.items()}

ROUTE_PREFIX = {
    "fish": "FSH",
    "plant": "PLT",
    "animal_general": "ANM",
    "bacteria_pathogen": "BAC",
    "human_domestic_contamination": "HDC",
    "misc_unknown": "MSC",
}

MIN_LEN = 50            # shorter records are primers/fragments, not references
MIN_LEN_VECTOR = 15     # UniVec adapters/primers are short by nature
MAX_LEN = 50_000        # vsearch's default --maxseqlength; longer = genome/chromosome
MAX_N_FRACTION = 0.05
CHUNK_SOURCE_LEN = 2000  # build_dataset.MAX_SEQ_LEN: longer records were chunked

DEFAULT_MAX_PER_TAXON = 0            # 0 = no hard ceiling; the base budget decides
DEFAULT_MAX_ROUTE_BASES = 400_000_000
# Per (taxon, marker) caps tried in order until the route fits; None = uncapped.
CAP_LADDER = (None, 50, 20, 10, 5, 3, 2, 1)


def _sanitize(name: str) -> str:
    """Rank values go inside `tax=` where ',' ';' ':' are separators and
    whitespace would end the vsearch label."""
    out = []
    for ch in name.strip():
        if ch in ",;:=" or ch.isspace():
            out.append("_")
        else:
            out.append(ch)
    s = "".join(out)
    while "__" in s:
        s = s.replace("__", "_")
    return s.strip("_")


def format_tax(lineage: dict[str, str]) -> str:
    parts = []
    for rank in RANKS:
        value = lineage.get(rank)
        if value:
            v = _sanitize(value)
            if v:
                parts.append(f"{SINTAX_CODE[rank]}:{v}")
    return ",".join(parts)


def format_header(seq_id: str, lineage: dict[str, str], src: str, marker: str,
                  acc: str, taxid: int | None, n: int) -> str:
    attrs = [seq_id, f"tax={format_tax(lineage)}", f"src={_sanitize(src)}",
             f"marker={_sanitize(marker)}", f"acc={_sanitize(acc) or 'NA'}"]
    if taxid:
        attrs.append(f"taxid={taxid}")
    attrs.append(f"n={n}")
    return ";".join(attrs) + ";"


def parse_tax(tax: str) -> dict[str, str]:
    lineage: dict[str, str] = {}
    for part in tax.split(","):
        code, sep, value = part.partition(":")
        rank = CODE_TO_RANK.get(code)
        if sep and rank and value:
            lineage[rank] = value.replace("_", " ")
    return lineage


def parse_header(header: str) -> dict:
    """Inverse of format_header. Accepts the label with or without '>' and
    with BLAST's 'id rest' split. Returns id, lineage, src, marker, acc,
    taxid (int or None), n (int)."""
    h = header.strip()
    if h.startswith(">"):
        h = h[1:]
    h = h.replace(" ", ";", 1)  # BLAST defline: "<id> <rest>"
    fields = [f for f in h.split(";") if f]
    out: dict = {"id": fields[0] if fields else "", "lineage": {}, "src": None, "marker": None,
                 "acc": None, "taxid": None, "n": 1}
    for f in fields[1:]:
        key, sep, value = f.partition("=")
        if not sep:
            continue
        if key == "tax":
            out["lineage"] = parse_tax(value)
        elif key in ("taxid", "n"):
            out[key] = int(value) if value.isdigit() else None
        elif key in ("src", "marker", "acc"):
            out[key] = value
    if out["id"].startswith("lcl|"):
        out["id"] = out["id"][4:]
    return out


def lineage_tuple(lineage: dict[str, str]) -> tuple[tuple[str, str], ...]:
    return tuple((r, lineage[r]) for r in RANKS if lineage.get(r))


def lca_lineage(a: tuple[tuple[str, str], ...], b: tuple[tuple[str, str], ...]) -> tuple[tuple[str, str], ...]:
    """Rank-by-rank agreement from the top down. A rank only one side has is
    kept (sources differ in how many ranks they fill); the first rank where
    both have a value and disagree ends the lineage."""
    da, db = dict(a), dict(b)
    out = []
    for rank in RANKS:
        va, vb = da.get(rank), db.get(rank)
        if va and vb:
            if va != vb:
                break
            out.append((rank, va))
        elif va or vb:
            out.append((rank, va or vb))
    return tuple(out)


def lowest_taxon(lin: tuple[tuple[str, str], ...]) -> str:
    return f"{lin[-1][0]}:{lin[-1][1]}" if lin else "none"


# ---------------------------------------------------------------------------
# Reference records from each source
# ---------------------------------------------------------------------------

@dataclass
class RefRecord:
    sequence: str
    lineage: dict[str, str]
    taxid: int | None
    acc: str
    src: str
    marker: str
    organism: str
    forced_route: str | None = None


def _usable_name(name: str) -> bool:
    if not name:
        return False
    low = name.lower()
    return not (is_unresolved(name) or "synthetic construct" in low or low.startswith("unknown"))


def _drop_vague_species(lineage: dict[str, str]) -> dict[str, str]:
    """'Bacillus sp. XYZ' is a genus-level identification: keep the genus,
    not a species value that would be reported as one."""
    sp = lineage.get("species")
    if sp and (is_higher_rank_only(sp, lineage) or " sp. " in f" {sp} " or is_unresolved(sp)):
        lineage = dict(lineage)
        del lineage["species"]
    return lineage


def iter_midori2_ref(zip_path: Path, taxonomy: TaxonomyResolver, selection: str = "UNIQ") -> Iterator[RefRecord]:
    with zipfile.ZipFile(zip_path) as zf:
        members = sources.midori2_members(zf)
        has_selection = any(m.selection for m in members)
        for m in members:
            if has_selection and m.selection != selection:
                continue
            for header, raw_seq in sources.iter_midori2_member(zf, m.name):
                seq = sources._clean_sequence(raw_seq)
                if not seq:
                    continue
                parsed = sources.parse_midori2_header(header, taxonomy)
                if parsed is None:
                    continue
                acc, organism, lineage, taxid = parsed
                yield RefRecord(seq, lineage, taxid, acc, "midori2", m.gene or "mito", organism)


_SILVA_HINTS = (
    ("Metazoa", "Metazoa"),
    ("Chloroplastida", "Viridiplantae"),
    ("Streptophyta", "Viridiplantae"),
    ("Fungi", "Fungi"),
)


class NameResolver:
    """Organism name -> NCBI taxid, disambiguating homonyms by domain."""

    def __init__(self, taxonomy: TaxonomyResolver):
        self.tax = taxonomy

    def resolve(self, name: str, domain: str | None) -> int | None:
        words = name.replace("[", "").replace("]", "").split()
        candidates: list[str] = []
        if len(words) >= 2:
            candidates.append(" ".join(words[:2]))
        if len(words) >= 3:
            candidates.insert(0, " ".join(words[:3]))
        if words:
            candidates.append(words[0])
        for cand in candidates:
            ids = self.tax.taxids_for_name(cand)
            if domain:
                ids = [t for t in ids if self.tax.lineage(t).get("superkingdom") == domain]
            if len(ids) == 1:
                return ids[0]
        return None


def iter_silva_ref(gz_path: Path, names: NameResolver, marker: str) -> Iterator[RefRecord]:
    """SILVA paths are rank-aligned only for Bacteria/Archaea (domain;phylum;
    class;order;family;genus + organism). The organism name is looked up in
    NCBI taxonomy first so SILVA, MIDORI2 and the BLAST DBs share one
    taxonomy, and so chloroplast/mitochondrial rRNA (filed under Bacteria in
    SILVA) gets the plant/animal it was sequenced from."""
    tax = names.tax
    with gzip.open(gz_path, "rt", encoding="utf-8", errors="replace") as fh:
        for header, raw_seq in sources._iter_fasta(fh):
            acc, sep, path = header.partition(" ")
            if not sep:
                continue
            tokens = path.split(";")
            organism = tokens[-1].strip()
            if not _usable_name(organism):
                continue
            seq = sources._clean_sequence(raw_seq)
            if not seq:
                continue
            domain = tokens[0]
            organelle = any(t in ("Chloroplast", "Mitochondria") for t in tokens)
            ncbi_domain = None if organelle else domain
            taxid = names.resolve(organism, ncbi_domain)
            lineage: dict[str, str] = {}
            if taxid is not None:
                lineage = dict(tax.lineage(taxid))
                if "species" not in lineage and len(organism.split()) >= 2 and taxid and \
                        (tax.scientific_name(taxid) or "").count(" ") >= 1:
                    lineage["species"] = tax.scientific_name(taxid) or ""
            elif domain in ("Bacteria", "Archaea") and len(tokens) == 7 and not organelle:
                for rank, tok in zip(("superkingdom", "phylum", "class", "order", "family", "genus"), tokens[:6]):
                    lineage[rank] = tok
                lineage["species"] = organism
            elif domain == "Eukaryota" and not organelle:
                lineage["superkingdom"] = "Eukaryota"
                for hint, kingdom in _SILVA_HINTS:
                    if hint in path:
                        lineage["kingdom"] = kingdom
                        break
                lineage["genus"] = organism.split()[0]
                lineage["species"] = organism
            else:
                continue  # organelle rRNA whose host we cannot name
            yield RefRecord(seq, lineage, taxid, acc, "silva", marker, organism)


def iter_unite_ref(fasta_path: Path, names: NameResolver) -> Iterator[RefRecord]:
    with open(fasta_path, encoding="utf-8", errors="replace") as fh:
        for header, raw_seq in sources._iter_fasta(fh):
            fields = header.split("|")
            if len(fields) < 5:
                continue
            seq = sources._clean_sequence(raw_seq)
            if not seq:
                continue
            lineage: dict[str, str] = {"superkingdom": "Eukaryota"}
            for token in fields[-1].split(";"):
                prefix, sep, value = token.partition("__")
                rank = {"k": "kingdom", "p": "phylum", "c": "class", "o": "order",
                        "f": "family", "g": "genus", "s": "species"}.get(prefix)
                if sep and rank and value and "Incertae_sedis" not in value and not value.endswith("_sp"):
                    lineage[rank] = value.replace("_", " ")
            organism = lineage.get("species") or fields[0].replace("_", " ")
            taxid = names.resolve(lineage["species"], "Eukaryota") if lineage.get("species") else None
            yield RefRecord(seq, lineage, taxid, fields[1], "unite", "ITS", organism)


def iter_blastdb_ref(blastdbcmd: Path, db_path: Path, taxonomy: TaxonomyResolver, marker: str) -> Iterator[RefRecord]:
    proc = subprocess.Popen(
        [str(blastdbcmd), "-db", str(db_path), "-entry", "all", "-outfmt", "%a|%T|%l|%s"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
        encoding="utf-8", errors="replace", bufsize=1 << 20,
    )
    assert proc.stdout is not None
    try:
        for line in proc.stdout:
            acc, taxid_s, length_s, raw_seq = (line.rstrip("\n").split("|", 3) + ["", "", ""])[:4]
            if not taxid_s.isdigit() or not length_s.isdigit():
                continue
            if int(length_s) > MAX_LEN:
                continue
            taxid = int(taxid_s)
            organism = taxonomy.scientific_name(taxid) or ""
            if not _usable_name(organism):
                continue
            seq = sources._clean_sequence(raw_seq)
            if not seq:
                continue
            yield RefRecord(seq, dict(taxonomy.lineage(taxid)), taxid, acc, db_path.name, marker, organism)
    finally:
        proc.stdout.close()
        proc.wait()


def supplementary_queries(supp_dir: Path) -> list[tuple[Path, Path]]:
    """(manifest, fasta) for every *finished* supplementary query: listed in
    index.json and with its .fasta, .manifest.csv and .run.json all present.
    The fetcher writes into this directory while it runs, so a manifest
    without its FASTA (or not yet indexed) is a query still in progress."""
    try:
        done = set(json.loads((supp_dir / "index.json").read_text(encoding="utf-8")))
    except (OSError, ValueError):
        done = set()
    out = []
    for manifest in sorted(supp_dir.glob("*/*.manifest.csv")):
        query_id = manifest.name[: -len(".manifest.csv")]
        fasta = manifest.with_name(query_id + ".fasta")
        run = manifest.with_name(query_id + ".run.json")
        if query_id in done and fasta.exists() and run.exists():
            out.append((manifest, fasta))
    return out


def iter_supplementary_ref(supp_dir: Path, taxonomy: TaxonomyResolver,
                           queries: list[tuple[Path, Path]] | None = None) -> Iterator[RefRecord]:
    """raw/supplementary/<source>/<query>.fasta + .manifest.csv (one row per
    accession with taxid, route, licence). The manifest's route is honoured
    (vectors/phiX are filed under human_domestic_contamination on purpose);
    environmental-sample queries drop out at the usable-name check."""
    for manifest, fasta in (supplementary_queries(supp_dir) if queries is None else queries):
        rows: dict[str, dict] = {}
        with open(manifest, encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                rows[row["accession"]] = row
        query_id = fasta.stem
        with open(fasta, encoding="utf-8", errors="replace") as fh:
            for header, raw_seq in sources._iter_fasta(fh):
                acc = header.split()[0]
                row = rows.get(acc)
                if row is None:
                    continue
                organism = row.get("organism_name", "")
                if not _usable_name(organism):
                    continue
                seq = sources._clean_sequence(raw_seq)
                if not seq:
                    continue
                taxid = int(row["taxid"]) if (row.get("taxid") or "").isdigit() else None
                lineage = dict(taxonomy.lineage(taxid)) if taxid else {}
                if not lineage and row.get("lineage"):
                    try:
                        lineage = json.loads(row["lineage"])
                    except ValueError:
                        lineage = {}
                if not lineage:
                    lineage = {"species": organism}
                route = row.get("route") or None
                yield RefRecord(seq, lineage, taxid, acc, f"supplementary:{query_id}",
                                _sanitize(row.get("marker") or "any"), organism,
                                forced_route=route if route in ROUTES else None)


def iter_univec_ref(univec_path: Path) -> Iterator[RefRecord]:
    with open(univec_path, encoding="utf-8", errors="replace") as fh:
        for header, raw_seq in sources._iter_fasta(fh):
            seq = sources._clean_sequence(raw_seq)
            if not seq:
                continue
            ident, _, desc = header.partition(" ")
            acc = ident.split("|")[-1]
            lineage = {"superkingdom": "Artificial sequences", "genus": "UniVec",
                       "species": f"UniVec {desc[:60]}" if desc else f"UniVec {acc}"}
            yield RefRecord(seq, lineage, None, acc, "univec", "vector", desc or acc,
                            forced_route="human_domestic_contamination")


def bold_rows_to_records(rows: Iterable[dict]) -> Iterator[RefRecord]:
    """BOLD hook. BOLD is not downloaded yet (owner login); when
    raw/bold/*.parquet appears it is read through this. Rows are dicts with
    the BOLD_Public column names (kingdom..species, nuc, processid,
    marker_code)."""
    for row in rows:
        seq = sources._clean_sequence(row.get("nuc") or "")
        if not seq:
            continue
        lineage = {r: row[r] for r in ("kingdom", "phylum", "class", "order", "family", "genus", "species") if row.get(r)}
        if lineage.get("kingdom") in ("Animalia",):
            lineage["kingdom"] = "Metazoa"
        if lineage.get("kingdom") == "Plantae":
            lineage["kingdom"] = "Viridiplantae"
        if lineage:
            lineage.setdefault("superkingdom", "Eukaryota")
        organism = row.get("species") or row.get("genus") or ""
        if not organism:
            continue
        yield RefRecord(seq, lineage, None, row.get("processid") or "NA", "bold",
                        row.get("marker_code") or "barcode", organism)


def iter_bold_ref(parquet_path: Path, batch_size: int = 50_000) -> Iterator[RefRecord]:
    import pyarrow.parquet as pq  # only needed once BOLD exists

    pf = pq.ParquetFile(parquet_path)
    wanted = ["kingdom", "phylum", "class", "order", "family", "genus", "species", "nuc", "processid", "marker_code"]
    cols = [c for c in wanted if c in pf.schema_arrow.names]
    for batch in pf.iter_batches(columns=cols, batch_size=batch_size):
        d = batch.to_pydict()
        n = len(d["nuc"])
        yield from bold_rows_to_records({c: d[c][i] for c in cols} for i in range(n))


# ---------------------------------------------------------------------------
# Held-out exclusion
# ---------------------------------------------------------------------------

def _digest(seq: str) -> bytes:
    return hashlib.blake2b(seq.encode("ascii"), digest_size=16).digest()


def build_dataset_chunks(seq: str) -> list[str]:
    """Must mirror build_dataset.chunk_long_sequence exactly: the processed
    splits hold these windows, not the full record."""
    from training.build_dataset import chunk_long_sequence
    return chunk_long_sequence(seq)


def load_heldout(processed_dir: Path, splits: tuple[str, ...] = ("dev", "test")) -> tuple[set[bytes], dict]:
    held: set[bytes] = set()
    info: dict = {}
    if not processed_dir.exists():
        return held, info
    csv.field_size_limit(sys.maxsize)
    for route_dir in sorted(p for p in processed_dir.iterdir() if p.is_dir()):
        for split in splits:
            f = route_dir / f"{split}.csv"
            if not f.exists():
                continue
            n = 0
            with open(f, encoding="utf-8", newline="") as fh:
                for row in csv.DictReader(fh):
                    seq = (row.get("sequence") or "").strip().upper()
                    if seq:
                        held.add(_digest(seq))
                        n += 1
            info[f"{route_dir.name}/{split}.csv"] = {"rows": n, "sha256": sha256_file(f)}
    return held, info


def is_heldout(seq: str, held: set[bytes]) -> bool:
    if not held:
        return False
    if _digest(seq) in held:
        return True
    if len(seq) > CHUNK_SOURCE_LEN:
        return any(_digest(c) in held for c in build_dataset_chunks(seq))
    return False


# ---------------------------------------------------------------------------
# Per-route accumulation
# ---------------------------------------------------------------------------

class _Entry:
    __slots__ = ("lineage", "taxid", "acc", "src", "marker", "n", "length", "group")

    def __init__(self, lineage, taxid, acc, src, marker, length):
        self.lineage = lineage
        self.taxid = taxid
        self.acc = acc
        self.src = src
        self.marker = marker
        self.n = 1
        self.length = length
        self.group = None


@dataclass
class RouteStats:
    candidates: int = 0
    duplicates_merged: int = 0
    lca_coarsened: int = 0
    heldout_excluded: int = 0
    by_source: Counter = field(default_factory=Counter)


class RouteAccumulator:
    """Unique sequences of one route. Sequences go to a temp file in arrival
    order; only metadata stays in memory."""

    def __init__(self, route: str, tmp_dir: Path, taxonomy: TaxonomyResolver | None):
        self.route = route
        self.entries: dict[bytes, _Entry] = {}
        self.tmp_path = tmp_dir / f"{route}.seqs"
        self._fh = open(self.tmp_path, "w", encoding="ascii")
        self.stats = RouteStats()
        self.tax = taxonomy
        self._interned: dict = {}

    def _intern(self, lin):
        return self._interned.setdefault(lin, lin)

    def add(self, rec: RefRecord) -> None:
        self.stats.candidates += 1
        self.stats.by_source[rec.src] += 1
        d = _digest(rec.sequence)
        lin = self._intern(lineage_tuple(rec.lineage))
        e = self.entries.get(d)
        if e is None:
            self.entries[d] = _Entry(lin, rec.taxid, rec.acc, rec.src, rec.marker, len(rec.sequence))
            self._fh.write(d.hex())
            self._fh.write("\t")
            self._fh.write(rec.sequence)
            self._fh.write("\n")
            return
        self.stats.duplicates_merged += 1
        e.n += 1
        if lin != e.lineage:
            merged = self._intern(lca_lineage(e.lineage, lin))
            if len(merged) < len(e.lineage):
                self.stats.lca_coarsened += 1
            e.lineage = merged
        if e.taxid != rec.taxid:
            if e.taxid and rec.taxid and self.tax is not None:
                e.taxid = self.tax.lowest_common_ancestor(e.taxid, rec.taxid)
            else:
                e.taxid = None

    def close(self) -> None:
        self._fh.close()

    def select(self, max_per_taxon: int, max_bases: int) -> tuple[set[bytes], int | None, dict]:
        """Longest-first per (lowest taxon, marker). A route that fits in
        max_bases keeps every unique sequence; otherwise the per-group cap
        steps down CAP_LADDER until it fits (or reaches 1, recorded as
        over_budget). max_per_taxon > 0 is a hard ceiling on top."""
        groups: dict[tuple, list[tuple[int, bytes]]] = defaultdict(list)
        for d, e in self.entries.items():
            groups[(lowest_taxon(e.lineage), e.marker)].append((e.length, d))
        for g in groups.values():
            g.sort(key=lambda t: (-t[0], t[1]))
        ladder = [k for k in CAP_LADDER if max_per_taxon <= 0 or (k is not None and k <= max_per_taxon)]
        if max_per_taxon > 0 and max_per_taxon not in ladder:
            ladder.insert(0, max_per_taxon)
        chosen_k = ladder[-1]
        total = 0
        for k in ladder:
            total = sum(sum(length for length, _ in g[:k]) for g in groups.values())
            chosen_k = k
            if total <= max_bases:
                break
        keep = {d for g in groups.values() for _, d in g[:chosen_k]}
        info = {"max_per_taxon_marker": chosen_k, "groups": len(groups),
                "unique_before_cap": len(self.entries), "kept": len(keep),
                "removed_by_cap": len(self.entries) - len(keep),
                "bases_after_cap": total, "over_budget": total > max_bases}
        return keep, chosen_k, info

    def write(self, out_fasta: Path, keep: set[bytes], width: int = 0) -> dict:
        prefix = ROUTE_PREFIX[self.route]
        n = 0
        bases = 0
        by_src: Counter = Counter()
        by_marker: Counter = Counter()
        rank_depth: Counter = Counter()
        taxid_map: list[tuple[str, int]] = []
        with open(self.tmp_path, encoding="ascii") as src, open(out_fasta, "w", encoding="utf-8") as out:
            for line in src:
                hexd, _, seq = line.rstrip("\n").partition("\t")
                d = bytes.fromhex(hexd)
                if d not in keep:
                    continue
                e = self.entries[d]
                n += 1
                seq_id = f"{prefix}{n:07d}"
                out.write(">" + format_header(seq_id, dict(e.lineage), e.src, e.marker, e.acc, e.taxid, e.n) + "\n")
                out.write(seq + "\n")
                bases += len(seq)
                by_src[e.src] += 1
                by_marker[e.marker] += 1
                rank_depth[e.lineage[-1][0] if e.lineage else "none"] += 1
                if e.taxid:
                    taxid_map.append((seq_id, e.taxid))
        return {"sequences": n, "bases": bases, "by_source": dict(by_src.most_common()),
                "by_marker": dict(by_marker.most_common()), "lowest_rank": dict(rank_depth.most_common()),
                "taxid_map": taxid_map}


# ---------------------------------------------------------------------------
# Tools / indexes
# ---------------------------------------------------------------------------

def default_data_root() -> Path:
    """TRAINING_DATA_DIR, else the registry's resolution (SYNTHVEDA_DATA_ROOT,
    else the first synthveda-data/ walking up from here, else /data)."""
    env = os.environ.get("TRAINING_DATA_DIR")
    if env:
        return Path(env)
    from app.inference.registry import _resolve_data_root
    return _resolve_data_root()


def find_tool(name: str, data_root: Path) -> Path | None:
    on_path = shutil.which(name)
    if on_path:
        return Path(on_path)
    for cand in (data_root / "tools" / "blast" / "bin" / name,
                 data_root / "tools" / "vsearch" / "bin" / name):
        if cand.exists() and os.access(cand, os.X_OK):
            return cand
    return None


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def build_udb(vsearch: Path, fasta: Path, out: Path, threads: int) -> dict:
    t0 = time.time()
    proc = subprocess.run([str(vsearch), "--makeudb_usearch", str(fasta), "--output", str(out),
                           "--threads", str(threads)], capture_output=True, text=True)
    return {"ok": proc.returncode == 0 and out.exists(), "seconds": round(time.time() - t0, 1),
            "log_tail": proc.stderr.strip().splitlines()[-3:]}


def build_blastdb(makeblastdb: Path, fasta: Path, out_prefix: Path, title: str, taxid_map: Path) -> dict:
    """makeblastdb wants '<id> <title>' deflines and IDs under 50 chars, so
    the vsearch header is split at its first ';' on the fly."""
    t0 = time.time()
    out_prefix.parent.mkdir(parents=True, exist_ok=True)
    cmd = [str(makeblastdb), "-in", "-", "-dbtype", "nucl", "-parse_seqids", "-blastdb_version", "5",
           "-title", title, "-out", str(out_prefix), "-taxid_map", str(taxid_map)]
    with tempfile.TemporaryFile("w+") as log:
        # stdout/stderr to a file, not a pipe: a pipe nobody drains while we
        # stream stdin can fill up and deadlock both processes.
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT, text=True)
        assert proc.stdin is not None
        with open(fasta, encoding="utf-8") as fh:
            for line in fh:
                if line.startswith(">"):
                    seq_id, _, rest = line[1:].rstrip("\n").partition(";")
                    proc.stdin.write(f">lcl|{seq_id} {rest}\n")
                else:
                    proc.stdin.write(line)
        proc.stdin.close()
        rc = proc.wait()
        log.seek(0)
        tail = log.read().strip().splitlines()[-3:]
    return {"ok": rc == 0, "seconds": round(time.time() - t0, 1), "log_tail": tail}


def build_grch38_blastdb(makeblastdb: Path, fna_gz: Path, out_prefix: Path) -> dict:
    """Nuclear human genome, BLAST only: a 3.1 Gb genome is not a vsearch
    target (chromosomes exceed --maxseqlength and the index would not fit
    in RAM). Held-out GRCh38 windows cannot be excluded from a genome; see
    the manifest note."""
    t0 = time.time()
    out_prefix.parent.mkdir(parents=True, exist_ok=True)
    cmd = [str(makeblastdb), "-in", "-", "-dbtype", "nucl", "-parse_seqids", "-blastdb_version", "5",
           "-title", "GRCh38_no_alt_analysis_set (nuclear+chrM)", "-out", str(out_prefix), "-taxid", "9606",
           "-max_file_sz", "4GB"]
    with tempfile.TemporaryFile("w+") as log:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT)
        assert proc.stdin is not None
        with gzip.open(fna_gz, "rb") as fh:
            for line in fh:
                if line.startswith(b">"):
                    ident = line[1:].split()[0].decode()
                    proc.stdin.write(f">lcl|{ident} Homo sapiens GRCh38 {ident}\n".encode())
                else:
                    proc.stdin.write(line)
        proc.stdin.close()
        rc = proc.wait()
        log.seek(0)
        tail = log.read().strip().splitlines()[-3:]
    return {"ok": rc == 0, "seconds": round(time.time() - t0, 1), "log_tail": tail}


# ---------------------------------------------------------------------------
# Main build
# ---------------------------------------------------------------------------

LICENCES = {
    "midori2": "CC BY 4.0 (MIDORI2 GB273, doi:10.5281/zenodo.22685701; Leray et al. 2022 Environmental DNA 4:894). Underlying GenBank records: NCBI policy.",
    "silva": "CC BY 4.0 (SILVA 138.2; Quast et al. 2013 NAR 41:D590).",
    "unite": "CC BY-SA 4.0 (UNITE general FASTA release 04.04.2024, doi:10.15156/BIO/2959332).",
    "ncbi_blastdb": "NCBI preformatted BLAST DBs: no NCBI restrictions; submitters may claim IP in records (https://www.ncbi.nlm.nih.gov/home/about/policies/).",
    "univec": "NCBI UniVec: public, NCBI policy.",
    "grch38": "GRCh38 (GCA_000001405.15): Genome Reference Consortium, public.",
    "supplementary": "Per-record licence in raw/supplementary/*/*.manifest.csv (INSDC/GenBank, ENA terms).",
    "bold": "CC BY-SA 4.0 (BOLD Public data package) - not present in this build.",
}

# (directory name, marker label); nt_others and partial nt_viruses are left out.
BLAST_SOURCES = (
    ("16S_ribosomal_RNA", "16S"),
    ("LSU_prokaryote_rRNA", "LSU"),
    ("SSU_eukaryote_rRNA", "SSU"),
    ("LSU_eukaryote_rRNA", "LSU"),
    ("18S_fungal_sequences", "18S"),
    ("ITS_RefSeq_Fungi", "ITS"),
    ("ITS_eukaryote_sequences", "ITS"),
    ("mito", "mitogenome"),
    ("ref_viruses_rep_genomes", "viral_genome"),
)


def _source_plan(raw: Path, taxonomy: TaxonomyResolver, names: NameResolver, blastdbcmd: Path | None,
                 only: set[str] | None) -> list[tuple[str, Callable[[], Iterator[RefRecord]], list[Path]]]:
    plan: list = []

    def want(key: str) -> bool:
        return only is None or key in only

    midori = set((raw / "midori2").glob("MIDORI2_*_RAW.zip")) | set((raw / "midori2").glob("*.fasta.zip"))
    for z in sorted(midori):
        if want("midori2"):
            plan.append(("midori2", lambda z=z: iter_midori2_ref(z, taxonomy), [z]))
    for p in sorted((raw / "bold").glob("*.parquet")) if (raw / "bold").exists() else []:
        if want("bold"):
            plan.append(("bold", lambda p=p: iter_bold_ref(p), [p]))
    for p in sorted((raw / "silva").glob("*.fasta.gz")):
        marker = "LSU" if "LSU" in p.name else "SSU"
        if want("silva"):
            plan.append(("silva", lambda p=p, m=marker: iter_silva_ref(p, names, m), [p]))
    unite = [f for f in sorted((raw / "unite").glob("*general_release*.fasta")) if "_dev" not in f.name]
    if unite and want("unite"):
        plan.append(("unite", lambda f=unite[0]: iter_unite_ref(f, names), [unite[0]]))
    extracted = raw / "ncbi_blastdb" / "extracted"
    if blastdbcmd is not None and want("ncbi_blastdb"):
        for name, marker in BLAST_SOURCES:
            db_dir = extracted / name
            if not (db_dir.exists() and (any(db_dir.glob("*.nin")) or any(db_dir.glob("*.nal")))):
                continue
            plan.append(("ncbi_blastdb", lambda d=db_dir, m=marker: iter_blastdb_ref(blastdbcmd, d / d.name, taxonomy, m),
                         sorted(db_dir.glob(f"{name}*.n*"))))
    supp = raw / "supplementary"
    if supp.exists() and want("supplementary"):
        queries = supplementary_queries(supp)
        plan.append(("supplementary", lambda q=queries: iter_supplementary_ref(supp, taxonomy, q),
                     [f for m, fa in queries for f in (fa, m)]))
    univec = raw / "univec" / "UniVec"
    if univec.exists() and want("univec"):
        plan.append(("univec", lambda: iter_univec_ref(univec), [univec]))
    return plan


def _passes_filters(rec: RefRecord) -> str | None:
    """None if the record is usable, else the reason it is dropped."""
    min_len = MIN_LEN_VECTOR if rec.marker == "vector" else MIN_LEN
    if len(rec.sequence) < min_len:
        return "too_short"
    if len(rec.sequence) > MAX_LEN:
        return "too_long"
    if rec.sequence.count("N") > MAX_N_FRACTION * len(rec.sequence):
        return "n_rich"
    if rec.forced_route is None and not _usable_name(rec.organism):
        return "no_usable_taxon"
    if not rec.lineage:
        return "no_lineage"
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--data-dir", default=str(default_data_root()))
    parser.add_argument("--version", default="v1")
    parser.add_argument("--max-per-taxon", type=int, default=DEFAULT_MAX_PER_TAXON)
    parser.add_argument("--max-route-bases", type=int, default=DEFAULT_MAX_ROUTE_BASES)
    parser.add_argument("--only-sources", default=None, help="comma list: midori2,silva,unite,ncbi_blastdb,supplementary,univec,bold")
    parser.add_argument("--no-heldout-exclusion", action="store_true")
    parser.add_argument("--skip-indexes", action="store_true")
    parser.add_argument("--skip-grch38", action="store_true")
    parser.add_argument("--threads", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    parser.add_argument("--force", action="store_true", help="overwrite an existing version directory")
    args = parser.parse_args(argv)

    t_start = time.time()
    root = Path(args.data_dir)
    raw = root / "raw"
    out_root = root / "reference" / args.version
    if out_root.exists():
        if not args.force:
            raise SystemExit(f"{out_root} exists; versions are immutable (use a new --version, or --force)")
        shutil.rmtree(out_root)
    out_root.mkdir(parents=True)

    taxonomy = TaxonomyResolver(root / "tools" / "taxdump")
    names = NameResolver(taxonomy)
    blastdbcmd = find_tool("blastdbcmd", root)
    makeblastdb = find_tool("makeblastdb", root)
    vsearch = find_tool("vsearch", root)
    print(f"tools: blastdbcmd={blastdbcmd} makeblastdb={makeblastdb} vsearch={vsearch}", flush=True)

    held: set[bytes] = set()
    held_info: dict = {}
    if not args.no_heldout_exclusion:
        held, held_info = load_heldout(root / "processed")
        print(f"held-out (dev+test) sequences to exclude: {len(held):,}", flush=True)

    only = set(args.only_sources.split(",")) if args.only_sources else None
    tmp = Path(tempfile.mkdtemp(prefix=".build-", dir=out_root))
    accs = {r: RouteAccumulator(r, tmp, taxonomy) for r in ROUTES}
    source_report: list[dict] = []
    dropped: Counter = Counter()

    for key, make_iter, files in _source_plan(raw, taxonomy, names, blastdbcmd, only):
        t0 = time.time()
        label = files[0].name if files else key
        print(f"== {key}: {label}", flush=True)
        seen = kept = 0
        per_route: Counter = Counter()
        sub_src = None
        for rec in make_iter():
            seen += 1
            sub_src = sub_src or rec.src
            reason = _passes_filters(rec)
            if reason is None:
                rec.lineage = _drop_vague_species(rec.lineage)
                route = rec.forced_route or lineage_to_route(rec.lineage)
                if held and is_heldout(rec.sequence, held):
                    accs[route].stats.heldout_excluded += 1
                    reason = "heldout_dev_test"
                else:
                    accs[route].add(rec)
                    per_route[route] += 1
                    kept += 1
            if reason:
                dropped[(key, reason)] += 1
            if seen % 500_000 == 0:
                print(f"    ...{seen:,} read, {kept:,} kept ({time.time() - t0:.0f}s)", flush=True)
        secs = round(time.time() - t0, 1)
        print(f"    {seen:,} read, {kept:,} kept in {secs}s  {dict(per_route)}", flush=True)
        source_report.append({
            "source": key, "name": label, "src_tag": sub_src, "records_read": seen, "records_kept": kept,
            "kept_by_route": dict(per_route), "seconds": secs,
            "files": [{"path": str(f.relative_to(root)), "bytes": f.stat().st_size,
                       "sha256": sha256_file(f) if f.stat().st_size < 4 * 1024**3 else None} for f in files],
            "licence": LICENCES.get(key, ""),
        })

    routes_report: dict = {}
    for route, acc in accs.items():
        acc.close()
        t0 = time.time()
        route_dir = out_root / route
        route_dir.mkdir(parents=True, exist_ok=True)
        keep, k, cap_info = acc.select(args.max_per_taxon, args.max_route_bases)
        fasta = route_dir / "ref.fasta"
        written = acc.write(fasta, keep)
        taxid_map = written.pop("taxid_map")
        map_path = route_dir / "taxid_map.txt"
        with open(map_path, "w", encoding="utf-8") as fh:
            for seq_id, taxid in taxid_map:
                fh.write(f"{seq_id}\t{taxid}\n")
        info = {
            "candidates": acc.stats.candidates, "duplicates_merged": acc.stats.duplicates_merged,
            "lca_coarsened": acc.stats.lca_coarsened, "heldout_excluded": acc.stats.heldout_excluded,
            "candidates_by_source": dict(acc.stats.by_source.most_common()),
            "cap": cap_info, **written, "with_taxid": len(taxid_map),
            "fasta": {"path": str(fasta.relative_to(root)), "bytes": fasta.stat().st_size, "sha256": sha256_file(fasta)},
            "write_seconds": round(time.time() - t0, 1),
        }
        print(f"[{route}] {written['sequences']:,} seqs, {written['bases']:,} bases, cap k={k}", flush=True)
        if not args.skip_indexes and written["sequences"]:
            if vsearch is not None:
                info["vsearch_udb"] = build_udb(vsearch, fasta, route_dir / "ref.udb", args.threads)
                if info["vsearch_udb"]["ok"]:
                    info["vsearch_udb"]["bytes"] = (route_dir / "ref.udb").stat().st_size
            else:
                info["vsearch_udb"] = {"ok": False, "reason": "vsearch not found"}
            if makeblastdb is not None:
                info["blastdb"] = build_blastdb(makeblastdb, fasta, route_dir / "blast" / "ref",
                                                f"SynthVeda reference {args.version} {route}", map_path)
                if info["blastdb"]["ok"]:
                    info["blastdb"]["bytes"] = sum(p.stat().st_size for p in (route_dir / "blast").iterdir())
            else:
                info["blastdb"] = {"ok": False, "reason": "makeblastdb not found"}
            print(f"    udb={info['vsearch_udb'].get('ok')} ({info['vsearch_udb'].get('seconds')}s)  "
                  f"blast={info['blastdb'].get('ok')} ({info['blastdb'].get('seconds')}s)", flush=True)
        routes_report[route] = info
    shutil.rmtree(tmp, ignore_errors=True)

    extra: dict = {}
    grch = raw / "grch38" / "GRCh38_no_alt_analysis_set.fna.gz"
    if not args.skip_grch38 and not args.skip_indexes and grch.exists() and makeblastdb is not None:
        print("== GRCh38 BLAST-only index", flush=True)
        prefix = out_root / "human_domestic_contamination" / "grch38_blast" / "grch38"
        res = build_grch38_blastdb(makeblastdb, grch, prefix)
        if res["ok"]:
            res["bytes"] = sum(p.stat().st_size for p in prefix.parent.iterdir())
        res["source"] = {"path": str(grch.relative_to(root)), "bytes": grch.stat().st_size}
        res["note"] = ("Held-out GRCh38 windows in processed/human_domestic_contamination cannot be excluded "
                       "from a whole genome: a human-route taxon score from this index is not a "
                       "generalisation measure.")
        extra["grch38_blast"] = res
        print(f"    ok={res['ok']} ({res['seconds']}s)", flush=True)

    manifest = {
        "version": args.version,
        "created": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "build_seconds": round(time.time() - t_start, 1),
        "builder": "services/worker/training/build_reference_db.py",
        "header_format": "<ID>;tax=d:..,k:..,p:..,c:..,o:..,f:..,g:..,s:..;src=..;marker=..;acc=..;[taxid=..;]n=..;",
        "id_prefixes": ROUTE_PREFIX,
        "taxonomy": {"taxdump": "tools/taxdump", "blast_taxdb": "raw/ncbi_blastdb/extracted/taxdb"},
        "parameters": {
            "min_len": MIN_LEN, "min_len_vector": MIN_LEN_VECTOR, "max_len": MAX_LEN,
            "max_n_fraction": MAX_N_FRACTION, "max_per_taxon_requested": args.max_per_taxon,
            "max_route_bases": args.max_route_bases, "midori2_selection": "UNIQ",
            "heldout_exclusion": not args.no_heldout_exclusion,
        },
        "heldout_exclusion": {
            "enabled": not args.no_heldout_exclusion,
            "unique_sequences": len(held),
            "files": held_info,
            "why": ("The reference is for taxon lookup. Day 10 evaluates taxon assignment on the held-out "
                    "splits; a query that is itself in the reference returns a 100% self-hit and measures "
                    "nothing. dev+test sequences (and long records whose build_dataset chunks are in them) "
                    "are excluded; train sequences stay. Rebuild when processed/ is rebuilt - the sha256 "
                    "values here show which splits this build excluded."),
        },
        "dropped": {f"{k}:{r}": n for (k, r), n in sorted(dropped.items())},
        "sources": source_report,
        "sources_absent": [s for s in ("bold",) if not any((raw / s).glob("*.parquet"))],
        "sources_skipped": {
            "nt_others": "99% uncultured/synthetic/unidentified (measured top taxids), no taxon to report",
            "env_nt": "0 of 479,996 records have a usable taxon (all '<habitat> metagenome' taxids, measured 2026-10-18)",
            "nt_viruses": "tier-2 download in progress; partial volumes not read",
            "ref_prok_rep_genomes": "tier-2 download in progress; whole genomes, BLAST-only candidate for v2",
        },
        "licences": LICENCES,
        "routes": routes_report,
        **extra,
    }
    with open(out_root / "manifest.json", "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)
    (root / "reference" / "CURRENT").write_text(args.version + "\n", encoding="utf-8")
    print(f"done in {manifest['build_seconds']}s -> {out_root}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
