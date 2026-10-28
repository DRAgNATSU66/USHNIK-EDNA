# fastx_parser

Synth Veda fast FASTA/FASTQ streaming parser and batching engine.

## Features

- Auto-detects FASTA (`>`) and FASTQ (`@`) format
- Streams line-by-line — constant memory for any file size
- Per-sequence QC metrics: length, GC ratio, N ratio, invalid chars, SHA-256
- Flexible batch modes: by count, by total bases, or all-in-one
- Pre-filter: min length, max N ratio, reject non-IUPAC chars
- JSONL output — one `BatchRecord` per line, directly consumed by the worker
- Criterion benchmarks (HTML reports via `cargo bench`)
- Library target for future PyO3/maturin Python bindings

## Prerequisites

Install Rust (once):
```
# Windows PowerShell (run as user, not admin):
winget install Rustlang.Rustup
# Then open a new terminal — cargo should be on PATH.
```

## Build

```bash
# Debug build (development):
cd packages/fastx_parser
cargo build

# Release build (production — use this for benchmarks):
cargo build --release
# Binary at: target/release/synthveda-parse  (or .exe on Windows)
```

## Usage

```bash
# Parse FASTA → JSONL batches of 1000 sequences each:
synthveda-parse input.fasta --out batches.jsonl

# Custom batch size:
synthveda-parse input.fasta --out batches.jsonl --batch-size 500

# Batch by total bases (useful for variable-length reads):
synthveda-parse input.fasta --out batches.jsonl --batch-bases 500000

# Single batch (offline Abyss Mode):
synthveda-parse input.fasta --out batches.jsonl --all-in-one

# Filter: drop sequences shorter than 50 bp or with > 20% N:
synthveda-parse input.fasta --out batches.jsonl --min-length 50 --max-n-ratio 0.2

# Print throughput stats:
synthveda-parse input.fasta --out batches.jsonl --stats

# Read from stdin, write to stdout:
cat input.fasta | synthveda-parse - --out - | head -5
```

## Output format (JSONL)

Each line is one sequence record:

```json
{
  "batch_id": "bat_000000",
  "sequence_id": "seq001",
  "description": "Hypothetical fish 12S rRNA fragment",
  "sequence": "ATCGATCG...",
  "length": 420,
  "gc_ratio": 0.4702,
  "n_ratio": 0.0119,
  "has_invalid_chars": false,
  "sha256": "a3f2b1...",
  "source_file": "sample.fasta"
}
```

## Tests

```bash
cargo test              # unit tests (inline) + integration tests
cargo test -- --nocapture   # verbose
```

## Benchmarks

```bash
cargo bench             # runs Criterion benchmarks, opens HTML report
# Report at: target/criterion/report/index.html
```

## Python integration

The worker automatically uses the Rust binary when built. The Python fallback
(`services/worker/app/fastx_parser.py`) produces identical output so you can
develop without building Rust.

Priority order in the worker:
1. `packages/fastx_parser/target/release/synthveda-parse` (fast)
2. Pure-Python fallback in `services/worker/app/fastx_parser.py` (always works)

## Future: PyO3 bindings

Add `--features pyo3-binding` to enable the PyO3 extension module target.
Build with `maturin develop` or `maturin build --release` from this directory.
The Python API will mirror `parse_and_batch_auto()` for zero-copy integration.
