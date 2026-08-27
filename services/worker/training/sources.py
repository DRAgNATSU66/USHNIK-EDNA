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

def iter_bold(parquet_path: Path, batch_size: int = 50_000) -> Iterator[Record]:
    import pyarrow.parquet as pq

    cols = ["kingdom", "phylum", "class", "order", "family", "genus", "species", "nuc"]
    pf = pq.ParquetFile(parquet_path)
    for batch in pf.iter_batches(columns=cols, batch_size=batch_size):
        d = batch.to_pydict()
        n = len(d["nuc"])
        for i in range(n):
            raw_seq = d["nuc"][i]
            seq = _clean_sequence(raw_seq) if raw_seq else None
            if not seq:
                continue
            lineage: dict[str, str] = {}
            for rank in ("kingdom", "phylum", "class", "order", "family", "genus", "species"):
                v = d[rank][i]
                if v:
                    lineage[rank] = v
            organism_name = d["species"][i] or d["genus"][i] or ""
            yield Record(sequence=seq, organism_name=organism_name, lineage=lineage, source="bold")


# ---------------------------------------------------------------------------
# MIDORI2 (.fasta packed in .zip; header carries a taxid on its last token)
# ---------------------------------------------------------------------------

def iter_midori2(zip_path: Path, taxonomy: TaxonomyResolver) -> Iterator[Record]:
    with zipfile.ZipFile(zip_path) as zf:
        inner_name = next(n for n in zf.namelist() if n.lower().endswith((".fasta", ".fa")))
        with zf.open(inner_name) as fh:
            text = io.TextIOWrapper(fh, encoding="utf-8", errors="replace")
            for header, raw_seq in _iter_fasta(text):
                seq = _clean_sequence(raw_seq)
                if not seq:
                    continue
                # "MG559732.1.<1.>690###root_1;Eukaryota_2759;...;Clydonella_sawyeri_2201168"
                _, sep, taxo = header.partition("###")
                if not sep:
                    continue
                tokens = taxo.split(";")
                if not tokens:
                    continue
                last = tokens[-1]
                name_part, _, tail = last.rpartition("_")
                if tail.isdigit():
                    taxid = int(tail)
                    organism_name = name_part.replace("_", " ")
                    lineage = taxonomy.lineage(taxid)
                else:
                    organism_name = last.replace("_", " ")
                    lineage = {}
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
    with open(univec_path, encoding="utf-8", errors="replace") as fh:
        for header, raw_seq in _iter_fasta(fh):
            seq = _clean_sequence(raw_seq)
            if not seq:
                continue
            yield Record(
                sequence=seq, organism_name=f"vector/adapter: {header[:60]}",
                lineage={}, source="univec",
            )
