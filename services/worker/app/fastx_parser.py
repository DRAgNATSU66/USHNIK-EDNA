"""
Pure-Python FASTA/FASTQ streaming parser.

This is the fallback used when the Rust `synthveda-parse` binary is not
available.  It produces the same BatchRecord schema as the Rust parser and
is called by job_runner._stage_parse().

Performance note: this parser is intentionally simple and correct.
For large files (> 100 MB) the Rust binary is ~20-50x faster.  Build it
with: cd packages/fastx_parser && cargo build --release
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Generator, Iterator


# ---------------------------------------------------------------------------
# Data model (mirrors Rust BatchRecord)
# ---------------------------------------------------------------------------

@dataclass
class BatchRecord:
    batch_id: str
    sequence_id: str
    description: str
    sequence: str
    length: int
    gc_ratio: float
    n_ratio: float
    has_invalid_chars: bool
    sha256: str
    source_file: str

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# QC helpers
# ---------------------------------------------------------------------------

_IUPAC = frozenset("ACGTURYSWKMBDHVN")
_GC_BASES = frozenset("GC")
_AT_BASES = frozenset("AT")


def compute_qc(sequence: str) -> tuple[float, float, bool, str]:
    """Return (gc_ratio, n_ratio, has_invalid_chars, sha256_hex)."""
    upper = sequence.upper()
    length = len(upper)
    if length == 0:
        return 0.0, 0.0, False, hashlib.sha256(b"").hexdigest()

    gc = sum(1 for c in upper if c in _GC_BASES)
    at = sum(1 for c in upper if c in _AT_BASES)
    n_count = upper.count("N")
    has_invalid = any(c not in _IUPAC for c in upper)

    gc_denom = gc + at
    gc_ratio = round(gc / gc_denom, 4) if gc_denom > 0 else 0.0
    n_ratio = round(n_count / length, 4)
    sha256 = hashlib.sha256(upper.encode()).hexdigest()

    return gc_ratio, n_ratio, has_invalid, sha256


# ---------------------------------------------------------------------------
# Format detection
# ---------------------------------------------------------------------------

class Format(Enum):
    FASTA = "fasta"
    FASTQ = "fastq"
    JSON = "json"


def detect_format(path: str | Path) -> Format:
    # Extension is authoritative for JSON/JSONL — content sniffing below
    # (">" / "@") only applies to FASTA/FASTQ text files.
    suffix = Path(path).suffix.lower()
    if suffix in (".json", ".jsonl"):
        return Format.JSON

    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            stripped = line.strip()
            if not stripped or stripped.startswith(";"):
                continue
            if stripped.startswith(">"):
                return Format.FASTA
            if stripped.startswith("@"):
                return Format.FASTQ
            raise ValueError(
                f"Cannot detect format for {path!r}: "
                f"first content line is neither '>' nor '@': {stripped!r}"
            )
    raise ValueError(f"Empty file: {path!r}")


# ---------------------------------------------------------------------------
# FASTA iterator
# ---------------------------------------------------------------------------

def _iter_fasta(path: str | Path) -> Generator[tuple[str, str, str], None, None]:
    """Yield (id, description, sequence) tuples from a FASTA file."""
    current_id: str | None = None
    current_desc = ""
    seq_parts: list[str] = []

    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith(";"):
                continue
            if line.startswith(">"):
                if current_id is not None:
                    yield current_id, current_desc, "".join(seq_parts).upper()
                    seq_parts = []
                header = line[1:]
                parts = header.split(" ", 1)
                current_id = parts[0]
                current_desc = parts[1] if len(parts) > 1 else ""
            elif current_id is not None:
                seq_parts.append(line)

    if current_id is not None and seq_parts:
        yield current_id, current_desc, "".join(seq_parts).upper()


# ---------------------------------------------------------------------------
# FASTQ iterator
# ---------------------------------------------------------------------------

def _iter_fastq(path: str | Path) -> Generator[tuple[str, str, str], None, None]:
    """Yield (id, description, sequence) tuples from a FASTQ file."""
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        while True:
            header = fh.readline()
            if not header:
                break
            header = header.strip()
            if not header:
                continue

            if not header.startswith("@"):
                raise ValueError(
                    f"FASTQ header must start with '@', got: {header!r}"
                )

            sequence = fh.readline().strip().upper()
            plus = fh.readline().strip()
            _quality = fh.readline().strip()

            if not plus.startswith("+"):
                raise ValueError(f"Expected '+' line, got: {plus!r}")

            header_content = header[1:]
            parts = header_content.split(" ", 1)
            seq_id = parts[0]
            desc = parts[1] if len(parts) > 1 else ""

            if sequence:
                yield seq_id, desc, sequence


# ---------------------------------------------------------------------------
# JSON / JSONL iterator
# ---------------------------------------------------------------------------

def _iter_json(path: str | Path) -> Generator[tuple[str, str, str], None, None]:
    """
    Yield (id, description, sequence) tuples from a JSON or JSONL file.

    Accepts either:
      - JSONL: one {"sequence_id": ..., "sequence": ..., "description": ...} object per line
      - JSON: a top-level array of the same object shape
    Each record must have "sequence_id" and "sequence"; "description" is optional.
    """
    text = Path(path).read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        raise ValueError(f"Empty file: {path!r}")

    if text.lstrip().startswith("["):
        records = json.loads(text)
        if not isinstance(records, list):
            raise ValueError(f"{path!r}: top-level JSON must be an array of sequence records")
    else:
        records = []
        for line_no, line in enumerate(text.splitlines(), start=1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path!r}: invalid JSON on line {line_no}: {exc}") from exc

    for i, record in enumerate(records):
        if not isinstance(record, dict):
            raise ValueError(f"{path!r}: record {i} is not a JSON object")
        if "sequence_id" not in record or "sequence" not in record:
            raise ValueError(
                f"{path!r}: record {i} missing required 'sequence_id' or 'sequence' field"
            )
        seq_id = str(record["sequence_id"])
        desc = str(record.get("description", ""))
        sequence = str(record["sequence"]).upper()
        yield seq_id, desc, sequence


# ---------------------------------------------------------------------------
# Batcher
# ---------------------------------------------------------------------------

def parse_and_batch(
    path: str | Path,
    *,
    batch_size: int = 1000,
    batch_bases: int | None = None,
    all_in_one: bool = False,
    min_length: int = 0,
    max_n_ratio: float | None = None,
    reject_invalid: bool = False,
) -> list[list[BatchRecord]]:
    """
    Parse a FASTA/FASTQ file and return grouped BatchRecord batches.

    Parameters mirror the Rust CLI flags so callers can switch implementations
    without changing arguments.
    """
    path = Path(path)
    source_file = path.name
    fmt = detect_format(path)
    if fmt == Format.FASTA:
        iterator = _iter_fasta(path)
    elif fmt == Format.FASTQ:
        iterator = _iter_fastq(path)
    else:
        iterator = _iter_json(path)

    accepted: list[BatchRecord] = []
    for seq_id, desc, sequence in iterator:
        gc_ratio, n_ratio, has_invalid, sha256 = compute_qc(sequence)
        length = len(sequence)

        if length < min_length:
            continue
        if max_n_ratio is not None and n_ratio > max_n_ratio:
            continue
        if reject_invalid and has_invalid:
            continue

        accepted.append(
            BatchRecord(
                batch_id="",  # filled in after grouping
                sequence_id=seq_id,
                description=desc,
                sequence=sequence,
                length=length,
                gc_ratio=gc_ratio,
                n_ratio=n_ratio,
                has_invalid_chars=has_invalid,
                sha256=sha256,
                source_file=source_file,
            )
        )

    return _group_into_batches(accepted, batch_size, batch_bases, all_in_one)


def _group_into_batches(
    records: list[BatchRecord],
    batch_size: int,
    batch_bases: int | None,
    all_in_one: bool,
) -> list[list[BatchRecord]]:
    if not records:
        return []

    batches: list[list[BatchRecord]] = []
    current: list[BatchRecord] = []
    current_bases = 0

    for record in records:
        if all_in_one:
            current.append(record)
            continue

        should_flush = False
        if batch_bases is not None:
            should_flush = bool(current) and (current_bases + record.length > batch_bases)
        else:
            should_flush = bool(current) and len(current) >= batch_size

        if should_flush:
            bid = f"bat_{len(batches):06d}"
            for r in current:
                r.batch_id = bid
            batches.append(current)
            current = []
            current_bases = 0

        current_bases += record.length
        current.append(record)

    if current:
        bid = f"bat_{len(batches):06d}"
        for r in current:
            r.batch_id = bid
        batches.append(current)

    return batches


# ---------------------------------------------------------------------------
# Rust binary integration
# ---------------------------------------------------------------------------

def _rust_binary_path() -> str | None:
    """Return path to the compiled Rust binary, or None if not found."""
    candidates = [
        Path(__file__).parents[4] / "packages" / "fastx_parser" / "target" / "release" / "synthveda-parse",
        Path(__file__).parents[4] / "packages" / "fastx_parser" / "target" / "release" / "synthveda-parse.exe",
        Path("packages/fastx_parser/target/release/synthveda-parse"),
        Path("packages/fastx_parser/target/release/synthveda-parse.exe"),
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    return None


def parse_and_batch_auto(
    path: str | Path,
    *,
    batch_size: int = 1000,
    batch_bases: int | None = None,
    all_in_one: bool = False,
    min_length: int = 0,
    max_n_ratio: float | None = None,
    reject_invalid: bool = False,
) -> tuple[list[list[BatchRecord]], bool]:
    """
    Parse using the Rust binary if available, otherwise fall back to Python.

    Returns (batches, used_rust: bool).
    """
    rust_bin = _rust_binary_path()
    if rust_bin:
        return _parse_via_rust(
            rust_bin, path,
            batch_size=batch_size,
            batch_bases=batch_bases,
            all_in_one=all_in_one,
            min_length=min_length,
            max_n_ratio=max_n_ratio,
            reject_invalid=reject_invalid,
        ), True

    return parse_and_batch(
        path,
        batch_size=batch_size,
        batch_bases=batch_bases,
        all_in_one=all_in_one,
        min_length=min_length,
        max_n_ratio=max_n_ratio,
        reject_invalid=reject_invalid,
    ), False


def _parse_via_rust(
    rust_bin: str,
    path: str | Path,
    *,
    batch_size: int,
    batch_bases: int | None,
    all_in_one: bool,
    min_length: int,
    max_n_ratio: float | None,
    reject_invalid: bool,
) -> list[list[BatchRecord]]:
    import subprocess
    import tempfile

    cmd = [rust_bin, str(path)]

    if all_in_one:
        cmd.append("--all-in-one")
    elif batch_bases is not None:
        cmd += ["--batch-bases", str(batch_bases)]
    else:
        cmd += ["--batch-size", str(batch_size)]

    if min_length > 0:
        cmd += ["--min-length", str(min_length)]
    if max_n_ratio is not None:
        cmd += ["--max-n-ratio", str(max_n_ratio)]
    if reject_invalid:
        cmd.append("--reject-invalid")

    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        cmd += ["--out", tmp_path]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            raise RuntimeError(
                f"synthveda-parse failed (exit {result.returncode}): {result.stderr}"
            )
        return _read_jsonl_batches(tmp_path)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _read_jsonl_batches(jsonl_path: str) -> list[list[BatchRecord]]:
    """Read a JSONL file produced by the Rust binary into BatchRecord batches."""
    batches: dict[str, list[BatchRecord]] = {}
    with open(jsonl_path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            record = BatchRecord(
                batch_id=d["batch_id"],
                sequence_id=d["sequence_id"],
                description=d.get("description", ""),
                sequence=d["sequence"],
                length=d["length"],
                gc_ratio=d["gc_ratio"],
                n_ratio=d["n_ratio"],
                has_invalid_chars=d["has_invalid_chars"],
                sha256=d["sha256"],
                source_file=d["source_file"],
            )
            batches.setdefault(record.batch_id, []).append(record)

    # Return batches in insertion order (Python 3.7+).
    return list(batches.values())
