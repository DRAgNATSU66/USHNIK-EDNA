"""
Supplementary sequence fetcher for thin classes (Q1, sprint Day 6, tracker t-1019-1).

Gathers extra reference sequences through official APIs only (NCBI E-utilities,
ENA Portal/Browser API; no HTML scraping) for the (route, label) classes that the
existing sources barely cover, and writes them with full provenance to
TRAINING_DATA_DIR/raw/supplementary/<source>/:

    <query_id>.fasta          sequences, header = ">ACCESSION query_id"
    <query_id>.manifest.csv   one row per sequence: accession, taxid, marker,
                              source, retrieved_at, licence, route, label, ...
    <query_id>.run.json       the exact query, hit count, sample size,
                              rejection counts, bytes downloaded

`sources.iter_supplementary` reads these back as Records, so build_dataset.py
ingests them on the next rebuild (Day 7). Nothing here touches processed/.

How a fetched sequence earns its label (see README.md in this directory):

  * label_basis="taxonomy" -- the record's NCBI taxid is resolved with the same
    local taxdump (TaxonomyResolver), routed with the same lineage_to_route,
    and labelled with the same assign_label that every other source goes
    through. A record is kept only if that pipeline independently produces the
    query's target (route, label); e.g. animal_general/possible_novelty needs a
    Metazoa (non-fish, non-domestic) lineage AND an organism name such as
    "uncultured Calanoida" / "Nematoda environmental sample". The query only
    pre-filters; it never assigns the label.
  * label_basis="provenance" -- lab/technical sequences whose contamination
    status comes from what they are, not from their taxonomy: cloning vectors
    (NCBI taxon 29278 "vectors") and the PhiX174 Illumina spike-in control.
    They are labelled possible_contamination in the human_domestic_contamination
    route, matching the "lab_reagent" contamination type in
    app/novelty/contamination.py. UniVec, the existing vector source, is
    labelled the same way (sources.iter_univec) so the two never disagree.

Run from services/worker/:
    python -m training.fetch_supplementary --list
    python -m training.fetch_supplementary                     # all queries
    python -m training.fetch_supplementary --only ncbi_phix174
    python -m training.fetch_supplementary --check-overlap     # vs processed/ splits
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Protocol

from app.inference.models import SequenceResultClass
from training.labeling import assign_label
from training.routing import lineage_to_route
from training.sources import _clean_sequence, _iter_fasta

NCBI_EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
ENA_PORTAL_SEARCH = "https://www.ebi.ac.uk/ena/portal/api/search"
ENA_BROWSER_FASTA = "https://www.ebi.ac.uk/ena/browser/api/fasta/"

# NCBI asks every E-utilities caller to identify itself with `tool` (and
# optionally `email`). We deliberately send only tool=synthveda: no personal
# email address goes into any request.
NCBI_TOOL = "synthveda"
USER_AGENT = "synthveda-supplementary-fetcher/1.0"
# NCBI limit is 3 requests/s without an API key, 10/s with one. Stay under it.
NCBI_MIN_INTERVAL_S = 0.40
NCBI_MIN_INTERVAL_WITH_KEY_S = 0.12
# ENA publishes no hard number; 2 requests/s is polite.
ENA_MIN_INTERVAL_S = 0.50

NCBI_BATCH = 200       # UIDs per esummary/efetch POST
ENA_FASTA_BATCH = 100  # accessions per ENA browser FASTA call
OVERSAMPLE = 1.3       # sample extra candidates; some fail routing/labelling
SAMPLE_SEED = 20261019

LICENCES = {
    "ncbi": (
        "INSDC/GenBank record retrieved via NCBI E-utilities. NCBI places no restrictions on "
        "the use or distribution of GenBank data; submitters may claim patent, copyright or "
        "other IP in their own records (https://www.ncbi.nlm.nih.gov/home/about/policies/). "
        "Access under the E-utilities usage guidelines "
        "(https://www.ncbi.nlm.nih.gov/books/NBK25497/)."
    ),
    "ena": (
        "INSDC record retrieved via the ENA Portal/Browser API. INSDC data is free and "
        "unrestricted (https://www.insdc.org/policy/); EMBL-EBI Terms of Use apply "
        "(https://www.ebi.ac.uk/about/terms-of-use)."
    ),
}


# ---------------------------------------------------------------------------
# Query definitions (the reproducible part: taxa, markers, length bounds)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SupplementaryQuery:
    query_id: str
    source: str          # "ncbi" | "ena"
    target_route: str
    target_label: str
    label_basis: str     # "taxonomy" | "provenance"
    taxon: str           # human-readable taxon scope
    marker: str
    base_query: str      # Entrez term / ENA query, WITHOUT the length clause
    min_len: int
    max_len: int
    max_records: int
    rationale: str

    def search_term(self) -> str:
        if self.source == "ncbi":
            return f"({self.base_query}) AND {self.min_len}:{self.max_len}[SLEN]"
        if self.source == "ena":
            return f"{self.base_query} AND base_count>={self.min_len} AND base_count<={self.max_len}"
        raise ValueError(f"unknown source {self.source!r}")


_ENV = '"environmental samples"[Organism]'   # NCBI's lineage node for uncultured/eDNA taxa
_METAZOA = "txid33208[Organism:exp]"
_ACTINOPTERYGII = "txid7898[Organism:exp]"     # excluded from animal queries: routes to fish
_COI = ('(COI[Gene] OR COX1[Gene] OR "cytochrome c oxidase subunit I"[Title] '
        'OR "cytochrome oxidase subunit 1"[Title])')
# Upper bound matches build_dataset.MAX_SEQ_LEN, so a taxonomy-labelled record
# is labelled here on exactly the sequence build_dataset will label (no chunking).
_AMPLICON_MAX = 2000

QUERIES: tuple[SupplementaryQuery, ...] = (
    SupplementaryQuery(
        query_id="ncbi_animal_env_coi", source="ncbi",
        target_route="animal_general", target_label=SequenceResultClass.possible_novelty,
        label_basis="taxonomy", taxon="Metazoa environmental samples, excluding Actinopterygii",
        marker="COI",
        base_query=f"({_METAZOA} AND {_ENV} AND {_COI}) NOT {_ACTINOPTERYGII}",
        min_len=150, max_len=_AMPLICON_MAX, max_records=2000,
        rationale="COI is the standard animal eDNA barcode; uncultured metazoan COI is the "
                  "closest real analogue of an unmatched animal read.",
    ),
    SupplementaryQuery(
        query_id="ncbi_animal_env_18s", source="ncbi",
        target_route="animal_general", target_label=SequenceResultClass.possible_novelty,
        label_basis="taxonomy", taxon="Metazoa environmental samples, excluding Actinopterygii",
        marker="18S rRNA",
        base_query=f'({_METAZOA} AND {_ENV} AND "18S ribosomal RNA"[Title]) NOT {_ACTINOPTERYGII}',
        min_len=150, max_len=_AMPLICON_MAX, max_records=1500,
        rationale="18S V4/V9 is the common eukaryote metabarcoding marker (meiofauna, plankton).",
    ),
    SupplementaryQuery(
        query_id="ncbi_animal_env_16s", source="ncbi",
        target_route="animal_general", target_label=SequenceResultClass.possible_novelty,
        label_basis="taxonomy", taxon="Metazoa environmental samples, excluding Actinopterygii",
        marker="mitochondrial 16S rRNA",
        base_query=f'({_METAZOA} AND {_ENV} AND "16S ribosomal RNA"[Title]) NOT {_ACTINOPTERYGII}',
        min_len=150, max_len=_AMPLICON_MAX, max_records=500,
        rationale="Mito 16S is used for invertebrate/vertebrate eDNA; small pool, take all.",
    ),
    SupplementaryQuery(
        query_id="ena_animal_env_any", source="ena",
        target_route="animal_general", target_label=SequenceResultClass.possible_novelty,
        label_basis="taxonomy", taxon="Metazoa with environmental_sample=true, excluding Actinopterygii",
        marker="any (marker not restricted)",
        base_query="tax_tree(33208) AND environmental_sample=true AND NOT tax_tree(7898)",
        min_len=150, max_len=_AMPLICON_MAX, max_records=1500,
        rationale="ENA's structured environmental_sample flag, marker-unrestricted, for marker "
                  "diversity beyond COI/18S/16S. Accessions already gathered from NCBI are excluded.",
    ),
    SupplementaryQuery(
        query_id="ncbi_fish_env", source="ncbi",
        target_route="fish", target_label=SequenceResultClass.possible_novelty,
        label_basis="taxonomy", taxon="Actinopterygii environmental samples",
        marker="any (marker not restricted)",
        base_query=f"{_ACTINOPTERYGII} AND {_ENV}",
        # 3500 * OVERSAMPLE exceeds the 3453 hits (2026-10-18), so every hit is
        # fetched: ~74% of them are "Actinopterygii environmental sample", whose
        # lineage has no class rank and so routes to animal_general and is rejected.
        min_len=150, max_len=_AMPLICON_MAX, max_records=3500,
        rationale="fish/possible_novelty has 0 rows in processed/ although the fish head "
                  "allows the label; same mechanism as the animal queries.",
    ),
    SupplementaryQuery(
        query_id="ena_fish_env", source="ena",
        target_route="fish", target_label=SequenceResultClass.possible_novelty,
        label_basis="taxonomy", taxon="Actinopterygii with environmental_sample=true",
        marker="any (marker not restricted)",
        base_query="tax_tree(7898) AND environmental_sample=true",
        min_len=150, max_len=_AMPLICON_MAX, max_records=2000,
        rationale="ENA's environmental_sample flag also covers fish eDNA records whose organism "
                  "is not under NCBI's 'environmental samples' node. Accessions already "
                  "gathered by ncbi_fish_env are excluded.",
    ),
    # Human DNA as a contaminant. Taxonomy-labelled: Homo sapiens routes to
    # human_domestic_contamination and assign_label gives known_species, the same
    # path the GRCh38 windows and the mito BLAST DB records take. processed/
    # holds ~35% 400 bp nuclear windows (chr1 only: iter_grch38 hits its 20k
    # window cap inside chr1) and the rest gene-length mito records; neither covers
    # the mtDNA control region, the most-sequenced human locus, nor nuclear rRNA,
    # which universal eukaryote 18S primers amplify from human handlers.
    # [Organism:noexp] keeps out archaic Homo subspecies.
    SupplementaryQuery(
        query_id="ncbi_human_mito_control_region", source="ncbi",
        target_route="human_domestic_contamination", target_label=SequenceResultClass.known_species,
        label_basis="taxonomy", taxon="Homo sapiens (txid9606, not expanded)",
        marker="mtDNA control region (D-loop / HVR)",
        base_query='txid9606[Organism:noexp] AND ("D-loop"[Title] OR "control region"[Title] '
                   'OR "hypervariable region"[Title]) AND mitochondrion[Filter]',
        min_len=150, max_len=_AMPLICON_MAX, max_records=800,
        rationale="Control-region amplicons are the classic human contaminant in eDNA/aDNA work "
                  "and are absent from the current human route pool.",
    ),
    SupplementaryQuery(
        query_id="ncbi_human_mito_rrna", source="ncbi",
        target_route="human_domestic_contamination", target_label=SequenceResultClass.known_species,
        label_basis="taxonomy", taxon="Homo sapiens (txid9606, not expanded)",
        marker="mitochondrial 12S/16S rRNA",
        base_query='txid9606[Organism:noexp] AND ("12S ribosomal RNA"[Title] OR '
                   '"16S ribosomal RNA"[Title]) AND mitochondrion[Filter]',
        min_len=150, max_len=_AMPLICON_MAX, max_records=400,
        rationale="Vertebrate 12S/16S metabarcoding primers (MiFish, Riaz 12S, 16Smam) co-amplify "
                  "human mtDNA; this is the human read a fish/animal eDNA run actually sees.",
    ),
    SupplementaryQuery(
        query_id="ncbi_human_nuclear_rrna", source="ncbi",
        target_route="human_domestic_contamination", target_label=SequenceResultClass.known_species,
        label_basis="taxonomy", taxon="Homo sapiens (txid9606, not expanded)",
        marker="nuclear rRNA (18S/28S/5.8S/45S)",
        base_query='txid9606[Organism:noexp] AND ("18S ribosomal RNA"[Title] OR "28S ribosomal RNA"[Title] '
                   'OR "5.8S ribosomal RNA"[Title] OR "45S"[Title] OR "ribosomal DNA"[Title]) '
                   # PDB-derived chains (cryo-EM ribosomes) are not INSDC records and
                   # carry no taxid in esummary; 78 of 436 hits on 2026-10-18.
                   'NOT srcdb_pdb[PROP]',
        min_len=150, max_len=_AMPLICON_MAX, max_records=500,
        rationale="Universal eukaryote 18S primers amplify handler DNA; small pool, take all.",
    ),
    SupplementaryQuery(
        query_id="ncbi_cloning_vectors", source="ncbi",
        target_route="human_domestic_contamination",
        target_label=SequenceResultClass.possible_contamination,
        label_basis="provenance", taxon="NCBI taxon 29278 'vectors' (artificial sequences)",
        marker="complete vector sequence",
        base_query='txid29278[Organism:exp] AND "complete sequence"[Title]',
        min_len=1000, max_len=20000, max_records=1500,
        rationale="Cloning/expression vectors are the lab_reagent contamination type. "
                  "build_dataset chunks each into <=5 x 400 bp windows.",
    ),
    SupplementaryQuery(
        query_id="ncbi_phix174", source="ncbi",
        target_route="human_domestic_contamination",
        target_label=SequenceResultClass.possible_contamination,
        label_basis="provenance", taxon="Escherichia phage phiX174 (Illumina spike-in control)",
        marker="complete genome",
        base_query='txid10847[Organism:exp] AND "complete genome"[Title]',
        min_len=4000, max_len=6000, max_records=200,
        rationale="PhiX174 is spiked into Illumina runs and is the most common sequencing-"
                  "control contaminant in public reads.",
    ),
)

QUERIES_BY_ID = {q.query_id: q for q in QUERIES}


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

@dataclass
class ManifestRow:
    accession: str          # versioned when the source gives a version
    accession_base: str     # version stripped, for cross-source dedup
    source: str
    query_id: str
    taxon_query: str
    marker: str
    taxid: str
    organism_name: str
    title: str
    length: int
    route: str
    label: str
    label_basis: str
    retrieved_at: str
    licence: str
    sha256: str
    lineage: str            # JSON {rank: name}; empty for provenance-labelled rows


MANIFEST_FIELDS = [f.name for f in fields(ManifestRow)]


def versionless(accession: str) -> str:
    return accession.split(".", 1)[0]


def write_manifest(path: Path, rows: Iterable[ManifestRow]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def read_manifest(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def write_fasta(path: Path, records: Iterable[tuple[str, str]], width: int = 80) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        for header, seq in records:
            fh.write(f">{header}\n")
            for i in range(0, len(seq), width):
                fh.write(seq[i:i + width] + "\n")


# ---------------------------------------------------------------------------
# Parsing (pure; unit-tested without network)
# ---------------------------------------------------------------------------

def parse_ncbi_fasta(text: str) -> dict[str, str]:
    """NCBI efetch FASTA -> {accession.version: raw sequence}."""
    out = {}
    for header, seq in _iter_fasta(iter(text.splitlines())):
        if header:
            out[header.split()[0]] = seq
    return out


def parse_ena_fasta(text: str) -> dict[str, str]:
    """ENA browser FASTA (">ENA|AB219791|AB219791.1 desc") -> {versionless accession: seq}."""
    out = {}
    for header, seq in _iter_fasta(iter(text.splitlines())):
        parts = header.split("|")
        acc = parts[1] if len(parts) >= 3 and parts[0] == "ENA" else header.split()[0]
        out[versionless(acc)] = seq
    return out


def parse_esummary(payload: dict) -> dict[str, dict]:
    """esummary JSON -> {accession.version: {taxid, title, organism, slen}}; skips error entries."""
    result = payload.get("result", {})
    out = {}
    for uid in result.get("uids", []):
        doc = result.get(uid) or {}
        accver = doc.get("accessionversion")
        if not accver or doc.get("error"):
            continue
        out[accver] = {
            "taxid": str(doc.get("taxid") or ""),
            "title": doc.get("title", ""),
            "organism": doc.get("organism", ""),
            "slen": doc.get("slen"),
        }
    return out


def parse_ena_tsv(text: str) -> list[dict]:
    lines = [l for l in text.splitlines() if l.strip()]
    if not lines:
        return []
    return list(csv.DictReader(lines, delimiter="\t"))


def sample_candidates(ids: Iterable[str], k: int, query_id: str, seed: int = SAMPLE_SEED) -> list[str]:
    """Deterministic sample: sort first so result depends only on the ID set,
    the query and the seed (not on the server's return order)."""
    pool = sorted(set(ids))
    if k >= len(pool):
        rng = random.Random(f"{seed}:{query_id}")
        rng.shuffle(pool)
        return pool
    return random.Random(f"{seed}:{query_id}").sample(pool, k)


# ---------------------------------------------------------------------------
# Labelling
# ---------------------------------------------------------------------------

class Taxonomy(Protocol):
    def lineage(self, taxid: int) -> dict[str, str]: ...
    def scientific_name(self, taxid: int) -> str | None: ...


def label_candidate(q: SupplementaryQuery, raw_seq: str, taxid: str, organism: str,
                    taxonomy: Taxonomy | None) -> tuple[dict | None, str]:
    """Returns ({sequence, route, label, organism_name, lineage}, "ok") or (None, reason).
    Taxonomy-basis records must independently reach the query's target through the
    same routing/labelling code as every other source; otherwise they're rejected."""
    seq = _clean_sequence(raw_seq or "")
    if not seq:
        return None, "invalid_sequence"
    if not (q.min_len <= len(seq) <= q.max_len):
        return None, "length_out_of_bounds"

    if q.label_basis == "provenance":
        return {"sequence": seq, "route": q.target_route, "label": q.target_label,
                "organism_name": organism, "lineage": {}}, "ok"

    if taxonomy is None or not taxid or not str(taxid).isdigit():
        return None, "no_taxid"
    lineage = taxonomy.lineage(int(taxid))
    if not lineage:
        return None, "taxid_not_in_local_taxdump"
    name = taxonomy.scientific_name(int(taxid)) or organism
    route = lineage_to_route(lineage)
    if route != q.target_route:
        return None, f"routed_to:{route}"
    label = assign_label(route, seq, name, lineage)
    if label != q.target_label:
        return None, f"labelled:{label}"
    return {"sequence": seq, "route": route, "label": label,
            "organism_name": name, "lineage": lineage}, "ok"


# ---------------------------------------------------------------------------
# HTTP with rate limiting
# ---------------------------------------------------------------------------

class RateLimiter:
    def __init__(self, min_interval: float, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep):
        self.min_interval = min_interval
        self._clock = clock
        self._sleep = sleep
        self._last: float | None = None

    def wait(self) -> None:
        now = self._clock()
        if self._last is not None:
            gap = self.min_interval - (now - self._last)
            if gap > 0:
                self._sleep(gap)
                now = self._clock()
        self._last = now


class Http:
    RETRY_STATUS = {429, 500, 502, 503, 504}

    def __init__(self, limiter: RateLimiter, max_attempts: int = 5):
        self.limiter = limiter
        self.max_attempts = max_attempts
        self.bytes_downloaded = 0
        self.requests = 0

    def request(self, url: str, params: dict | None = None, post: bool = False) -> bytes:
        data = None
        if params:
            encoded = urllib.parse.urlencode(params)
            if post:
                data = encoded.encode()
            else:
                url = f"{url}?{encoded}"
        for attempt in range(1, self.max_attempts + 1):
            self.limiter.wait()
            self.requests += 1
            req = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT})
            try:
                with urllib.request.urlopen(req, timeout=300) as resp:
                    body = resp.read()
                self.bytes_downloaded += len(body)
                return body
            except urllib.error.HTTPError as exc:
                if exc.code not in self.RETRY_STATUS or attempt == self.max_attempts:
                    raise
            except (urllib.error.URLError, TimeoutError):
                if attempt == self.max_attempts:
                    raise
            time.sleep(2 ** attempt)
        raise RuntimeError("unreachable")


def ncbi_params(**kw) -> dict:
    p = {"tool": NCBI_TOOL, **kw}
    key = os.environ.get("NCBI_API_KEY")
    if key:
        p["api_key"] = key
    return p


# ---------------------------------------------------------------------------
# Source backends -> list of candidate dicts {accession, taxid, organism, title, raw_seq}
# ---------------------------------------------------------------------------

def ncbi_all_uids(http: Http, term: str) -> list[str]:
    head = json.loads(http.request(NCBI_EUTILS + "esearch.fcgi", ncbi_params(
        db="nuccore", term=term, usehistory="y", retmax=0, retmode="json")))["esearchresult"]
    count = int(head["count"])
    uids: list[str] = []
    for start in range(0, count, 10_000):
        text = http.request(NCBI_EUTILS + "efetch.fcgi", ncbi_params(
            db="nuccore", WebEnv=head["webenv"], query_key=head["querykey"],
            rettype="uilist", retmode="text", retstart=start, retmax=10_000), post=True).decode()
        uids.extend(l.strip() for l in text.splitlines() if l.strip().isdigit())
    return uids


def ncbi_fetch(http: Http, uids: list[str]) -> list[dict]:
    out = []
    for i in range(0, len(uids), NCBI_BATCH):
        batch = ",".join(uids[i:i + NCBI_BATCH])
        summ = parse_esummary(json.loads(http.request(
            NCBI_EUTILS + "esummary.fcgi", ncbi_params(db="nuccore", id=batch, retmode="json"), post=True)))
        seqs = parse_ncbi_fasta(http.request(
            NCBI_EUTILS + "efetch.fcgi", ncbi_params(db="nuccore", id=batch, rettype="fasta", retmode="text"),
            post=True).decode("utf-8", errors="replace"))
        for accver, raw in seqs.items():
            meta = summ.get(accver, {})
            out.append({"accession": accver, "taxid": meta.get("taxid", ""),
                        "organism": meta.get("organism", ""), "title": meta.get("title", ""), "raw_seq": raw})
        print(f"    fetched {min(i + NCBI_BATCH, len(uids))}/{len(uids)}")
    return out


def ena_search(http: Http, query: str) -> list[dict]:
    text = http.request(ENA_PORTAL_SEARCH, {
        "result": "sequence", "query": query, "limit": 0, "format": "tsv",
        "fields": "accession,tax_id,scientific_name,description,base_count"}).decode()
    return parse_ena_tsv(text)


def ena_fetch(http: Http, rows: list[dict]) -> list[dict]:
    out = []
    for i in range(0, len(rows), ENA_FASTA_BATCH):
        batch = rows[i:i + ENA_FASTA_BATCH]
        accs = ",".join(r["accession"] for r in batch)
        seqs = parse_ena_fasta(http.request(ENA_BROWSER_FASTA + accs, {"download": "false"})
                               .decode("utf-8", errors="replace"))
        for r in batch:
            raw = seqs.get(versionless(r["accession"]))
            if raw is None:
                continue
            out.append({"accession": r["accession"], "taxid": r.get("tax_id", ""),
                        "organism": r.get("scientific_name", ""), "title": r.get("description", ""),
                        "raw_seq": raw})
        print(f"    fetched {min(i + ENA_FASTA_BATCH, len(rows))}/{len(rows)}")
    return out


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def already_gathered(out_root: Path, q: SupplementaryQuery) -> set[str]:
    """Versionless accessions other queries already hold for the same target class,
    so NCBI and ENA (both INSDC mirrors) never contribute the same record twice."""
    seen: set[str] = set()
    for manifest in out_root.glob("*/*.manifest.csv"):
        if manifest.name == f"{q.query_id}.manifest.csv":
            continue
        for row in read_manifest(manifest):
            if row["route"] == q.target_route and row["label"] == q.target_label:
                seen.add(row["accession_base"])
    return seen


def build_rows(q: SupplementaryQuery, candidates: list[dict], taxonomy: Taxonomy | None,
               retrieved_at: str, exclude: set[str]) -> tuple[list[ManifestRow], list[tuple[str, str]], Counter]:
    rows: list[ManifestRow] = []
    fasta: list[tuple[str, str]] = []
    reasons: Counter = Counter()
    seen_acc: set[str] = set()
    for c in candidates:
        if len(rows) >= q.max_records:
            reasons["over_cap"] += 1
            continue
        base = versionless(c["accession"])
        if base in exclude or base in seen_acc:
            reasons["duplicate_accession"] += 1
            continue
        labelled, reason = label_candidate(q, c["raw_seq"], c["taxid"], c["organism"], taxonomy)
        reasons[reason] += 1
        if labelled is None:
            continue
        seen_acc.add(base)
        seq = labelled["sequence"]
        rows.append(ManifestRow(
            accession=c["accession"], accession_base=base, source=q.source, query_id=q.query_id,
            taxon_query=q.taxon, marker=q.marker, taxid=str(c["taxid"] or ""),
            organism_name=labelled["organism_name"], title=c["title"], length=len(seq),
            route=labelled["route"], label=labelled["label"], label_basis=q.label_basis,
            retrieved_at=retrieved_at, licence=LICENCES[q.source],
            sha256=hashlib.sha256(seq.encode()).hexdigest(),
            lineage=json.dumps(labelled["lineage"], sort_keys=True) if labelled["lineage"] else "",
        ))
        fasta.append((f"{c['accession']} {q.query_id}", seq))
    return rows, fasta, reasons


def run_query(q: SupplementaryQuery, out_root: Path, taxonomy: Taxonomy | None,
              max_records: int | None = None) -> dict:
    if max_records is not None:
        q = SupplementaryQuery(**{**asdict(q), "max_records": max_records})
    retrieved_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    out_dir = out_root / q.source
    out_dir.mkdir(parents=True, exist_ok=True)
    exclude = already_gathered(out_root, q)
    term = q.search_term()
    k = int(q.max_records * OVERSAMPLE) + 1
    print(f"== {q.query_id} [{q.source}] -> {q.target_route}/{q.target_label}\n   term: {term}")

    if q.source == "ncbi":
        http = Http(RateLimiter(NCBI_MIN_INTERVAL_WITH_KEY_S if os.environ.get("NCBI_API_KEY")
                                else NCBI_MIN_INTERVAL_S))
        uids = ncbi_all_uids(http, term)
        hits = len(uids)
        picked = sample_candidates(uids, k, q.query_id)
        candidates = ncbi_fetch(http, picked)
        # efetch returns records in server order; put them in a seeded order so
        # the max_records truncation in build_rows is reproducible, not server-driven.
        candidates = seeded_order(candidates, q.query_id)
    elif q.source == "ena":
        http = Http(RateLimiter(ENA_MIN_INTERVAL_S))
        rows = [r for r in ena_search(http, term) if versionless(r["accession"]) not in exclude]
        hits = len(rows)
        by_acc = {r["accession"]: r for r in rows}
        picked = sample_candidates(by_acc, k, q.query_id)
        candidates = ena_fetch(http, [by_acc[a] for a in picked])
    else:
        raise ValueError(q.source)

    rows, fasta, reasons = build_rows(q, candidates, taxonomy, retrieved_at, exclude)
    write_fasta(out_dir / f"{q.query_id}.fasta", fasta)
    write_manifest(out_dir / f"{q.query_id}.manifest.csv", rows)
    run = {
        "query": asdict(q), "search_term": term, "retrieved_at": retrieved_at,
        "hits": hits, "sampled": len(picked), "fetched": len(candidates), "kept": len(rows),
        "unique_sequences_kept": len({r.sha256 for r in rows}),
        "reasons": dict(reasons), "http_requests": http.requests,
        "bytes_downloaded": http.bytes_downloaded, "licence": LICENCES[q.source],
    }
    (out_dir / f"{q.query_id}.run.json").write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
    print(f"   hits={hits} sampled={len(picked)} fetched={len(candidates)} kept={len(rows)} "
          f"bytes={http.bytes_downloaded:,} reasons={dict(reasons)}")
    return run


def seeded_order(candidates: list[dict], query_id: str) -> list[dict]:
    """Sort by accession, then a seeded shuffle: depends only on the record set."""
    ordered = sorted(candidates, key=lambda c: c["accession"])
    random.Random(f"{SAMPLE_SEED}:order:{query_id}").shuffle(ordered)
    return ordered


# ---------------------------------------------------------------------------
# Exact-duplicate overlap with processed/ splits (leakage check input for Day 7)
# ---------------------------------------------------------------------------

def check_overlap(out_root: Path, processed: Path) -> dict:
    from training.build_dataset import chunk_long_sequence

    split_seqs: dict[tuple[str, str], set[str]] = {}
    for csv_path in sorted(processed.glob("*/*.csv")):
        if csv_path.stem not in ("train", "dev", "test"):
            continue  # skip *.leaky.csv archives
        with open(csv_path, newline="", encoding="utf-8") as fh:
            split_seqs[(csv_path.parent.name, csv_path.stem)] = {r["sequence"] for r in csv.DictReader(fh)}
    all_by_split: dict[str, set[str]] = {}
    for (route, split), seqs in split_seqs.items():
        all_by_split.setdefault(split, set()).update(seqs)

    report: dict = {"per_query": {}, "totals": {}}
    union_chunks: set[str] = set()
    for manifest in sorted(out_root.glob("*/*.manifest.csv")):
        qid = manifest.name.removesuffix(".manifest.csv")
        fasta = manifest.with_name(f"{qid}.fasta")
        with open(fasta, encoding="utf-8") as fh:
            seqs = [s for _, s in _iter_fasta(fh)]
        chunks = {c for s in seqs for c in chunk_long_sequence(s)}
        union_chunks |= chunks
        report["per_query"][qid] = {
            "sequences": len(seqs), "unique_chunks": len(chunks),
            **{f"in_{split}": len(chunks & all_by_split.get(split, set())) for split in ("train", "dev", "test")},
            "in_test_by_route": {route: len(chunks & s) for (route, split), s in split_seqs.items()
                                 if split == "test" and chunks & s},
        }
    report["totals"] = {
        "unique_chunks": len(union_chunks),
        **{f"in_{split}": len(union_chunks & all_by_split.get(split, set())) for split in ("train", "dev", "test")},
    }
    (out_root / "overlap_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    default_root = os.environ.get("TRAINING_DATA_DIR") or os.environ.get("SYNTHVEDA_DATA_ROOT") \
        or str(Path(__file__).resolve().parents[3] / "synthveda-data")
    parser.add_argument("--data-dir", default=default_root)
    parser.add_argument("--only", default=None, help="Comma-separated query_ids")
    parser.add_argument("--max-records", type=int, default=None, help="Override per-query cap (smoke runs)")
    parser.add_argument("--list", action="store_true", help="Print the query definitions and exit")
    parser.add_argument("--check-overlap", action="store_true",
                        help="Only compute exact-duplicate overlap of fetched data with processed/ splits")
    args = parser.parse_args()

    if args.list:
        for q in QUERIES:
            print(f"{q.query_id}: {q.source} -> {q.target_route}/{q.target_label} "
                  f"[{q.label_basis}] cap={q.max_records}\n    {q.search_term()}")
        return

    root = Path(args.data_dir)
    out_root = root / "raw" / "supplementary"
    if args.check_overlap:
        print(json.dumps(check_overlap(out_root, root / "processed"), indent=2))
        return

    from training.taxonomy import TaxonomyResolver
    taxonomy = TaxonomyResolver(root / "tools" / "taxdump")
    selected = [QUERIES_BY_ID[i] for i in args.only.split(",")] if args.only else list(QUERIES)
    runs = {q.query_id: run_query(q, out_root, taxonomy, args.max_records) for q in selected}
    index_path = out_root / "index.json"
    index = json.loads(index_path.read_text()) if index_path.exists() else {}
    index.update({qid: {k: r[k] for k in ("retrieved_at", "hits", "kept", "bytes_downloaded")}
                  for qid, r in runs.items()})
    index_path.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
