"""
Per-source record extraction. Every source yields Record(sequence,
organism_name, lineage) — a common shape build_dataset.py can route and
label uniformly, regardless of how wildly the underlying formats differ.
"""
from __future__ import annotations

import gzip
import io
import re
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from .taxonomy import TaxonomyResolver

_VALID_BASES = re.compile(r"^[ACGTN]+$")
# IUPAC ambiguity codes (R,Y,S,W,K,M,B,D,H,V) are legitimate in real
# reference sequences (uncertain base call / heterozygous position) —
# fold them into N rather than rejecting the whole sequence, which is
# both their literal biological meaning and what downstream N-ratio
# quality thresholds already expect to see.
_IUPAC_AMBIGUITY = str.maketrans("RYSWKMBDHVryswkmbdhv", "N" * 20)


@dataclass
class Record:
    sequence: str
    organism_name: str
    lineage: dict[str, str]
    source: str
    # Set only for records whose route/label comes from provenance rather than
    # taxonomy (lab vectors, sequencing controls). None = build_dataset routes
    # via lineage_to_route and labels via assign_label as usual.
    route: str | None = None
    label: str | None = None


def _clean_sequence(seq: str) -> str | None:
    seq = seq.strip().upper().replace("U", "T")
    seq = seq.translate(_IUPAC_AMBIGUITY)
    if not seq or not _VALID_BASES.match(seq):
        return None
    return seq


def _iter_fasta(lines: Iterator[str]) -> Iterator[tuple[str, str]]:
    """Yields (header_without_gt, sequence) from an iterable of text lines."""
    header = None
    chunks: list[str] = []
    for raw in lines:
        line = raw.rstrip("\n")
        if line.startswith(">"):
            if header is not None:
                yield header, "".join(chunks)
            header = line[1:]
            chunks = []
        else:
            chunks.append(line.strip())
    if header is not None:
        yield header, "".join(chunks)


# ---------------------------------------------------------------------------
# BOLD (Parquet, already-structured taxonomy columns)
# ---------------------------------------------------------------------------

# BOLD kingdom -> (superkingdom, NCBI-style kingdom). routing.lineage_to_route
# only knows NCBI names, so raw "Animalia" sent every non-chordate animal to
# misc_unknown. "Mixture" (mixed-sample records) and anything unlisted are
# dropped: there is no single organism to label.
_BOLD_KINGDOMS: dict[str, tuple[str, str | None]] = {
    "Animalia": ("Eukaryota", "Metazoa"),
    "Plantae": ("Eukaryota", "Viridiplantae"),
    "Fungi": ("Eukaryota", "Fungi"),
    "Protista": ("Eukaryota", None),
    "Bacteria": ("Bacteria", None),
    "Viruses": ("Viruses", None),
}
# BOLD fish classes -> the NCBI class names routing.FISH_CLASSES knows.
# Without this, 446,683 Teleostei rows routed to animal_general.
_BOLD_FISH_CLASSES = {
    "Teleostei": "Actinopteri", "Chondrostei": "Actinopteri", "Holostei": "Actinopteri",
    "Cladistii": "Actinopteri", "Elasmobranchii": "Chondrichthyes", "Holocephali": "Chondrichthyes",
    "Petromyzonti": "Hyperoartia", "Coelacanthi": "Coelacanthimorpha", "Dipneusti": "Sarcopterygii",
}
_BOLD_SPECIES_RANKS = {"species", "subspecies"}
# BOLD names are accepted by shape rather than by spotting provisional forms:
# interim names come in too many shapes ("Eupselia sp. ANICMK59", "Ichneutes
# sp. BOLD:ADI5313", "Brevicornu JKJ-spB", "Megaselia pulicaria complex",
# "Simulium exiguum s.l.", hybrids "A b x A c"). A genus is one capitalised
# Latin word ("EntomobryidaeGEN", "Galumnidae_incertae_sedis" are family-level
# placeholders); a species is that genus plus one or two lowercase epithets.
_BOLD_GENUS = re.compile(r"^[A-Z][a-z]+(-[a-z]+)?$")
_BOLD_EPITHET = re.compile(r"^[a-z][a-z\-]+$")
_BOLD_NOT_EPITHETS = {"sp", "spp", "cf", "aff", "nr", "complex", "group", "grp", "agg", "sl"}
BOLD_RANKS = ("kingdom", "phylum", "class", "order", "family", "genus", "species")


def _bold_species_ok(species: str, genus: str) -> bool:
    words = species.split()
    return (words[0] == genus and len(words) in (2, 3)
            and all(_BOLD_EPITHET.match(w) and w not in _BOLD_NOT_EPITHETS for w in words[1:]))


def bold_lineage(row: dict) -> tuple[dict[str, str], str] | None:
    """(lineage, organism_name) for one BOLD_Public row, or None to drop it.
    Shared by iter_bold (training set) and build_reference_db (reference DB)
    so both read BOLD the same way. Genus-level identifications come back as
    "Genus sp." with no species in the lineage, so assign_label gives them
    likely_taxonomic_group; rows without a real genus are dropped."""
    mapped = _BOLD_KINGDOMS.get(row.get("kingdom") or "")
    if mapped is None:
        return None
    genus = row.get("genus")
    if not genus or not _BOLD_GENUS.match(genus):
        return None
    superkingdom, kingdom = mapped
    lineage = {"superkingdom": superkingdom}
    if kingdom:
        lineage["kingdom"] = kingdom
    for rank in BOLD_RANKS[1:6]:
        if row.get(rank):
            lineage[rank] = row[rank]
    if lineage.get("class") in _BOLD_FISH_CLASSES:
        lineage["class"] = _BOLD_FISH_CLASSES[lineage["class"]]
    species = row.get("species")
    id_rank = row.get("identification_rank")
    if species and (id_rank is None or id_rank in _BOLD_SPECIES_RANKS) and _bold_species_ok(species, genus):
        lineage["species"] = species
        return lineage, species
    return lineage, f"{genus} sp."


def bold_sequence(nuc: str | None) -> str | None:
    """BOLD `nuc` is alignment-padded ("---ACGT-ACGT---"); drop the gaps
    before the usual cleaning, else 3,836,703 rows are rejected whole."""
    if not nuc:
        return None
    return _clean_sequence(nuc.replace("-", ""))


def iter_bold(parquet_path: Path, batch_size: int = 50_000) -> Iterator[Record]:
    import pyarrow.parquet as pq

    pf = pq.ParquetFile(parquet_path)
    wanted = [*BOLD_RANKS, "identification_rank", "nuc"]
    cols = [c for c in wanted if c in pf.schema_arrow.names]
    for batch in pf.iter_batches(columns=cols, batch_size=batch_size):
        d = batch.to_pydict()
        n = len(d["nuc"])
        for i in range(n):
            seq = bold_sequence(d["nuc"][i])
            if not seq:
                continue
            parsed = bold_lineage({c: d[c][i] for c in cols})
            if parsed is None:
                continue
            lineage, organism_name = parsed
            yield Record(sequence=seq, organism_name=organism_name, lineage=lineage, source="bold")


# ---------------------------------------------------------------------------
# MIDORI2 (one .zip holding per-gene .fasta(.gz) members; the header carries
# the full lineage with a taxid on every token)
# ---------------------------------------------------------------------------
#
# GB273 ships as a single MIDORI2_GB273_RAW.zip with 15 genes x 3 selections
# (RAW/total/, RAW/uniq/, RAW/longest/), e.g.
#   RAW/uniq/MIDORI2_UNIQ_NUC_GB273_CO1_RAW.fasta.gz
# Older releases were one zip per gene holding one plain .fasta. The member
# name tokens are not in a fixed order across archives (the _sp variants put
# SP first), so the selection and gene are found by token, not by position.

MIDORI2_SELECTIONS = ("UNIQ", "LONGEST", "TOTAL")
_MIDORI2_FASTA_SUFFIXES = (".fasta", ".fa", ".fas", ".fasta.gz", ".fa.gz", ".fas.gz")
# MIDORI2 lineage tokens after "root_1" are positional: superkingdom,
# phylum, class, order, family, genus, species (no kingdom).
_MIDORI2_POSITIONAL_RANKS = ("superkingdom", "phylum", "class", "order", "family", "genus", "species")


@dataclass(frozen=True)
class Midori2Member:
    name: str
    selection: str | None   # UNIQ / LONGEST / TOTAL, None for pre-GB273 single-file zips
    gene: str | None        # CO1, srRNA, ... None if the name carries no GB token


def midori2_members(zf: zipfile.ZipFile) -> list[Midori2Member]:
    """Every nucleotide FASTA member of a MIDORI2 zip with its selection and
    gene. Amino-acid members are left out: _clean_sequence folds IUPAC
    letters into N, so protein text would otherwise pass as N-rich DNA."""
    out: list[Midori2Member] = []
    for name in zf.namelist():
        if not name.lower().endswith(_MIDORI2_FASTA_SUFFIXES):
            continue
        base = name.rsplit("/", 1)[-1]
        tokens = re.split(r"[_.]", base)
        if "AA" in tokens:
            continue
        selection = next((t for t in tokens if t in MIDORI2_SELECTIONS), None)
        gene = None
        for i, tok in enumerate(tokens[:-1]):
            if re.fullmatch(r"GB\d+", tok):
                gene = tokens[i + 1]
                break
        out.append(Midori2Member(name=name, selection=selection, gene=gene))
    return out


_MIDORI2_RANK_LABELS = {
    "domain": "superkingdom", "superkingdom": "superkingdom", "kingdom": "kingdom", "phylum": "phylum",
    "class": "class", "order": "order", "family": "family", "genus": "genus", "species": "species",
}


def parse_midori2_header(header: str, taxonomy: TaxonomyResolver | None) -> tuple[str, str, dict[str, str], int | None] | None:
    """(accession, organism_name, lineage, taxid) for one MIDORI2 header, or
    None if it carries no taxonomy. Two layouts exist:

      GB273 (rank-labelled, tab-separated, MIDORI2's own frozen taxdump):
        "MG559732.1.<1.>690\troot_1;cellularroot_cellular_organisms_131567;
         domain_Eukaryota_2759;...;genus_Clydonella_218657;species_Clydonella sawyeri_2201168"
      pre-GB273 (positional, "###"):
        "MG559732.1.<1.>690###root_1;Eukaryota_2759;...;Clydonella_sawyeri_2201168"

    Rank-labelled headers are read as-is. Positional ones lack kingdom (which
    routing needs), so their lineage comes from the local taxdump via the
    species taxid, falling back to the positional ranks when that taxid is
    newer than the snapshot."""
    if "###" in header:
        acc_part, _, taxo = header.partition("###")
        labelled = False
    else:
        parts = header.split(None, 1)
        if len(parts) != 2:
            return None
        acc_part, taxo = parts
        labelled = True
    tokens = [t for t in taxo.strip().split(";") if t]
    if tokens and tokens[0].startswith("root"):
        tokens = tokens[1:]
    if not tokens:
        return None
    # accession is "MG559732.1" out of "MG559732.1.<1.>690"
    acc_bits = acc_part.strip().split(".")
    accession = ".".join(acc_bits[:2]) if len(acc_bits) >= 2 and acc_bits[1].isdigit() else acc_part.strip()

    def split_token(tok: str) -> tuple[str, int | None]:
        name_part, _, tail = tok.rpartition("_")
        if tail.isdigit() and name_part:
            return name_part.replace("_", " "), int(tail)
        return tok.replace("_", " "), None

    if labelled:
        lineage: dict[str, str] = {}
        organism_name, taxid = "", None
        for tok in tokens:
            label, _, rest = tok.partition("_")
            name, tok_taxid = split_token(rest)
            rank = _MIDORI2_RANK_LABELS.get(label)
            if rank and name and rank not in lineage:
                lineage[rank] = name
            organism_name, taxid = name, tok_taxid
        if "species" in lineage:
            organism_name = lineage["species"]
        return accession, organism_name, lineage, taxid

    organism_name, taxid = split_token(tokens[-1])
    lineage = dict(taxonomy.lineage(taxid)) if (taxonomy is not None and taxid is not None) else {}
    if not lineage:
        for rank, tok in zip(_MIDORI2_POSITIONAL_RANKS, tokens):
            name, _ = split_token(tok)
            if name:
                lineage[rank] = name
    return accession, organism_name, lineage, taxid


def iter_midori2_member(zf: zipfile.ZipFile, member: str) -> Iterator[tuple[str, str]]:
    """(header, raw_sequence) for one member, gunzipping .gz members."""
    with zf.open(member) as fh:
        raw = gzip.open(fh) if member.lower().endswith(".gz") else fh
        text = io.TextIOWrapper(raw, encoding="utf-8", errors="replace")
        yield from _iter_fasta(text)


def iter_midori2(zip_path: Path, taxonomy: TaxonomyResolver, selection: str | None = "UNIQ",
                 genes: tuple[str, ...] | list[str] | None = None) -> Iterator[Record]:
    """Records from every gene FASTA in the zip (not just the first member).

    selection: UNIQ (every unique haplotype per species, the default),
    LONGEST, TOTAL, or None for all members. Zips whose members carry no
    selection token (pre-GB273, one gene per zip) are read whole whatever
    `selection` says. genes: restrict to these gene tokens (e.g. ("CO1",
    "srRNA")); None = all 15."""
    with zipfile.ZipFile(zip_path) as zf:
        members = midori2_members(zf)
        has_selection = any(m.selection for m in members)
        for m in members:
            if has_selection and selection is not None and m.selection != selection:
                continue
            if genes is not None and m.gene not in genes:
                continue
            for header, raw_seq in iter_midori2_member(zf, m.name):
                seq = _clean_sequence(raw_seq)
                if not seq:
                    continue
                parsed = parse_midori2_header(header, taxonomy)
                if parsed is None:
                    continue
                _, organism_name, lineage, _ = parsed
                yield Record(sequence=seq, organism_name=organism_name, lineage=lineage, source="midori2")


# ---------------------------------------------------------------------------
# SILVA (.fasta.gz; positional lineage, domain-reliable, deeper ranks best-effort)
# ---------------------------------------------------------------------------

_SILVA_PLANT_HINTS = ("Chloroplastida", "Streptophyta", "Chlorophyta", "Viridiplantae")


def iter_silva(gz_path: Path) -> Iterator[Record]:
    with gzip.open(gz_path, "rt", encoding="utf-8", errors="replace") as fh:
        for header, raw_seq in _iter_fasta(fh):
            seq = _clean_sequence(raw_seq)
            if not seq:
                continue
            _, sep, taxo = header.partition(" ")
            if not sep:
                continue
            tokens = taxo.split(";")
            if not tokens:
                continue
            domain = tokens[0]
            organism_name = tokens[-1]
            lineage: dict[str, str] = {}
            if domain in ("Bacteria", "Archaea"):
                lineage["superkingdom"] = domain
            elif domain == "Eukaryota":
                lineage["superkingdom"] = "Eukaryota"
                if any(hint in taxo for hint in _SILVA_PLANT_HINTS):
                    lineage["kingdom"] = "Viridiplantae"
            lineage["species"] = organism_name
            yield Record(sequence=seq, organism_name=organism_name, lineage=lineage, source="silva")


# ---------------------------------------------------------------------------
# UNITE (.fasta, always Fungi -> misc_unknown, k__/p__/.../s__ prefixed lineage)
# ---------------------------------------------------------------------------

_UNITE_RANK_PREFIX = {"k": "kingdom", "p": "phylum", "c": "class", "o": "order", "f": "family", "g": "genus", "s": "species"}


def iter_unite(fasta_path: Path) -> Iterator[Record]:
    with open(fasta_path, encoding="utf-8", errors="replace") as fh:
        for header, raw_seq in _iter_fasta(fh):
            seq = _clean_sequence(raw_seq)
            if not seq:
                continue
            fields = header.split("|")
            if len(fields) < 5:
                continue
            taxo = fields[-1]
            lineage: dict[str, str] = {}
            for token in taxo.split(";"):
                prefix, sep, value = token.partition("__")
                rank = _UNITE_RANK_PREFIX.get(prefix)
                if sep and rank and value and not value.endswith("_sp"):
                    lineage[rank] = value.replace("_", " ")
            organism_name = fields[0].replace("_", " ")
            yield Record(sequence=seq, organism_name=organism_name, lineage=lineage, source="unite")


# ---------------------------------------------------------------------------
# NCBI preformatted BLAST DBs (streamed via blastdbcmd, not loaded to disk as FASTA)
# ---------------------------------------------------------------------------

def iter_blastdb(blastdbcmd_exe: Path, db_path: Path, taxonomy: TaxonomyResolver) -> Iterator[Record]:
    proc = subprocess.Popen(
        [str(blastdbcmd_exe), "-db", str(db_path), "-entry", "all", "-outfmt", "%T|%s"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    assert proc.stdout is not None
    try:
        for line in proc.stdout:
            line = line.rstrip("\n")
            taxid_str, sep, raw_seq = line.partition("|")
            if not sep or not taxid_str.isdigit():
                continue
            seq = _clean_sequence(raw_seq)
            if not seq:
                continue
            taxid = int(taxid_str)
            lineage = taxonomy.lineage(taxid)
            organism_name = taxonomy.scientific_name(taxid) or ""
            yield Record(sequence=seq, organism_name=organism_name, lineage=lineage, source=db_path.name)
    finally:
        proc.stdout.close()
        proc.wait()


# ---------------------------------------------------------------------------
# GRCh38 / UniVec — direct injection, no per-record taxonomy needed
# ---------------------------------------------------------------------------

def iter_grch38(fna_gz_path: Path, window: int = 400, stride: int = 2000, max_windows: int = 20_000) -> Iterator[Record]:
    """Chunks the human genome into amplicon-sized windows. `stride` >> `window`
    so we sample spread-out positions rather than every overlapping window of
    a 3B-base genome; `max_windows` caps total output regardless."""
    yielded = 0
    with gzip.open(fna_gz_path, "rt", encoding="utf-8", errors="replace") as fh:
        chrom_seq = []
        current_header = None
        for line in fh:
            line = line.rstrip("\n")
            if line.startswith(">"):
                if current_header is not None:
                    seq = "".join(chrom_seq)
                    for i in range(0, len(seq) - window, stride):
                        if yielded >= max_windows:
                            return
                        chunk = _clean_sequence(seq[i:i + window])
                        if chunk:
                            yielded += 1
                            yield Record(
                                sequence=chunk, organism_name="Homo sapiens",
                                lineage={"species": "Homo sapiens"}, source="grch38",
                            )
                current_header = line[1:]
                chrom_seq = []
            else:
                chrom_seq.append(line)
        if current_header is not None and yielded < max_windows:
            seq = "".join(chrom_seq)
            for i in range(0, len(seq) - window, stride):
                if yielded >= max_windows:
                    return
                chunk = _clean_sequence(seq[i:i + window])
                if chunk:
                    yielded += 1
                    yield Record(
                        sequence=chunk, organism_name="Homo sapiens",
                        lineage={"species": "Homo sapiens"}, source="grch38",
                    )


def iter_univec(univec_path: Path) -> Iterator[Record]:
    # Vectors/adapters/primers are contamination by provenance (the
    # "lab_reagent" type in app/novelty/contamination.py), not a known
    # species. Before 2026-10-19 they fell through assign_label to
    # known_species; they are now labelled possible_contamination so they
    # agree with the vectors gathered by fetch_supplementary.py instead of
    # giving the human route head contradictory supervision.
    with open(univec_path, encoding="utf-8", errors="replace") as fh:
        for header, raw_seq in _iter_fasta(fh):
            seq = _clean_sequence(raw_seq)
            if not seq:
                continue
            yield Record(
                sequence=seq, organism_name=f"vector/adapter: {header[:60]}",
                lineage={}, source="univec",
                route="human_domestic_contamination", label="possible_contamination",
            )


# ---------------------------------------------------------------------------
# Supplementary API-fetched data (training/fetch_supplementary.py output)
# ---------------------------------------------------------------------------

def iter_supplementary(supp_dir: Path) -> Iterator[Record]:
    """Reads raw/supplementary/<source>/<query_id>.{manifest.csv,fasta}.
    Taxonomy-labelled rows carry their lineage, so build_dataset routes and
    labels them with the same code as every other source; provenance-labelled
    rows (vectors, PhiX) carry their fixed route/label."""
    import csv
    import json

    for manifest in sorted(supp_dir.glob("*/*.manifest.csv")):
        fasta = manifest.with_name(manifest.name.removesuffix(".manifest.csv") + ".fasta")
        if not fasta.exists():
            continue
        with open(fasta, encoding="utf-8", errors="replace") as fh:
            seqs = {header.split()[0]: seq for header, seq in _iter_fasta(fh) if header}
        with open(manifest, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                raw_seq = seqs.get(row["accession"])
                seq = _clean_sequence(raw_seq) if raw_seq else None
                if not seq:
                    continue
                provenance = row["label_basis"] == "provenance"
                yield Record(
                    sequence=seq, organism_name=row["organism_name"],
                    lineage=json.loads(row["lineage"]) if row["lineage"] else {},
                    source=f"supplementary:{row['source']}:{row['query_id']}",
                    route=row["route"] if provenance else None,
                    label=row["label"] if provenance else None,
                )
