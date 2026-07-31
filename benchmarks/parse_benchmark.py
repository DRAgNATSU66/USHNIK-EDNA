#!/usr/bin/env python3
"""
Synth Veda parser benchmark.

Compares:
  1. Python fallback parser (services/worker/app/fastx_parser.py)
  2. Bio.SeqIO (if biopython is installed)
  3. Rust synthveda-parse binary (if built)

Usage:
    # Use a real file:
    python benchmarks/parse_benchmark.py --fasta path/to/large.fasta

    # Generate a synthetic file first:
    python benchmarks/parse_benchmark.py --generate 50000 --seq-len 500

    # Run the Rust binary on the same data:
    python benchmarks/parse_benchmark.py --generate 50000 --all

Options:
    --fasta PATH        Path to FASTA file (must exist)
    --fastq PATH        Path to FASTQ file (must exist)
    --generate N        Generate a synthetic FASTA with N sequences
    --seq-len N         Sequence length for generated data (default: 500)
    --all               Run all benchmarks including Rust
    --rust-bin PATH     Path to synthveda-parse binary (auto-detected otherwise)
    --repetitions N     Number of benchmark repetitions (default: 3)
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
from pathlib import Path

# Allow running from project root without installing packages.
sys.path.insert(0, str(Path(__file__).parents[1]))

from services.worker.app.fastx_parser import (
    _rust_binary_path,
    parse_and_batch,
)


# ---------------------------------------------------------------------------
# Synthetic data
# ---------------------------------------------------------------------------

def generate_fasta(n_seqs: int, seq_len: int, path: str) -> None:
    chunk = "ATCG" * (seq_len // 4 + 1)
    seq = chunk[:seq_len]
    with open(path, "w") as fh:
        for i in range(n_seqs):
            fh.write(f">seq_{i:07d} synthetic\n{seq}\n")
    print(f"Generated {n_seqs} sequences ({seq_len} bp each) → {path}")


# ---------------------------------------------------------------------------
# Benchmark runners
# ---------------------------------------------------------------------------

def bench_python_fallback(fasta_path: str, repetitions: int) -> list[float]:
    times = []
    for _ in range(repetitions):
        t0 = time.perf_counter()
        batches = parse_and_batch(fasta_path, batch_size=1000)
        elapsed = time.perf_counter() - t0
        times.append(elapsed)
        total = sum(len(b) for b in batches)
    return times, total  # type: ignore[return-value]


def bench_biopython(fasta_path: str, repetitions: int) -> tuple[list[float], int] | None:
    try:
        from Bio import SeqIO  # type: ignore
    except ImportError:
        return None

    times = []
    total = 0
    for _ in range(repetitions):
        t0 = time.perf_counter()
        records = list(SeqIO.parse(fasta_path, "fasta"))
        elapsed = time.perf_counter() - t0
        times.append(elapsed)
        total = len(records)
    return times, total


def bench_rust(fasta_path: str, repetitions: int, rust_bin: str | None) -> tuple[list[float], int] | None:
    import subprocess

    if rust_bin is None:
        rust_bin = _rust_binary_path()
    if rust_bin is None:
        return None

    times = []
    total = 0
    for _ in range(repetitions):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            t0 = time.perf_counter()
            result = subprocess.run(
                [rust_bin, fasta_path, "--out", tmp_path, "--batch-size", "1000"],
                capture_output=True,
                text=True,
                timeout=600,
            )
            elapsed = time.perf_counter() - t0
            if result.returncode != 0:
                print(f"  [rust] ERROR: {result.stderr}", file=sys.stderr)
                return None
            times.append(elapsed)
            # Count records in output.
            with open(tmp_path) as fh:
                total = sum(1 for line in fh if line.strip())
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    return times, total


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def stats(times: list[float]) -> str:
    import statistics
    mean = statistics.mean(times)
    if len(times) > 1:
        stdev = statistics.stdev(times)
        return f"{mean:.3f}s ± {stdev:.3f}s"
    return f"{mean:.3f}s"


def report(
    label: str,
    times: list[float],
    total_seqs: int,
    total_bases: int,
) -> None:
    mean = sum(times) / len(times)
    mbps = total_bases / 1_000_000 / mean if mean > 0 else 0.0
    print(f"  {label:<30s}  {stats(times)}   {total_seqs:>8,} seqs   {mbps:>8.1f} Mbp/s")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Synth Veda parser benchmark")
    parser.add_argument("--fasta", help="Path to FASTA file")
    parser.add_argument("--generate", type=int, metavar="N", help="Generate N synthetic sequences")
    parser.add_argument("--seq-len", type=int, default=500, metavar="N")
    parser.add_argument("--all", action="store_true", help="Run all benchmarks including Rust")
    parser.add_argument("--rust-bin", help="Path to synthveda-parse binary")
    parser.add_argument("--repetitions", type=int, default=3)
    args = parser.parse_args()

    fasta_path: str | None = args.fasta
    tmp_fasta: tempfile.NamedTemporaryFile | None = None

    if args.generate:
        tmp_fasta = tempfile.NamedTemporaryFile(suffix=".fasta", delete=False, mode="w")
        fasta_path = tmp_fasta.name
        tmp_fasta.close()
        generate_fasta(args.generate, args.seq_len, fasta_path)

    if fasta_path is None:
        # Default to sample file in repo.
        default = Path(__file__).parent.parent / "packages" / "fastx_parser" / "data" / "sample.fasta"
        if default.exists():
            fasta_path = str(default)
            print(f"No input specified — using {fasta_path}")
        else:
            print("No input file. Use --fasta <path> or --generate <n>")
            sys.exit(1)

    n_seqs = args.generate or 0
    total_bases = n_seqs * args.seq_len if n_seqs else 0

    # Count sequences if not generated.
    if not n_seqs:
        with open(fasta_path) as fh:
            n_seqs = sum(1 for line in fh if line.startswith(">"))
        total_bases = n_seqs * args.seq_len  # rough estimate

    print(f"\n=== Synth Veda Parser Benchmark ===")
    print(f"  file        : {fasta_path}")
    print(f"  sequences   : {n_seqs:,}")
    print(f"  repetitions : {args.repetitions}")
    print()

    # --- Python fallback ---
    print("Running Python fallback parser ...")
    py_times, py_total = bench_python_fallback(fasta_path, args.repetitions)
    report("Python (fallback)", py_times, py_total, total_bases)

    # --- Bio.SeqIO ---
    print("Running Bio.SeqIO parser ...")
    bio_result = bench_biopython(fasta_path, args.repetitions)
    if bio_result is None:
        print("  Bio.SeqIO                         [not installed — pip install biopython]")
    else:
        bio_times, bio_total = bio_result
        report("Bio.SeqIO", bio_times, bio_total, total_bases)

    # --- Rust binary ---
    if args.all or args.rust_bin:
        print("Running Rust binary parser ...")
        rust_result = bench_rust(fasta_path, args.repetitions, args.rust_bin)
        if rust_result is None:
            print(
                "  Rust (synthveda-parse)            "
                "[not built — run: cd packages/fastx_parser && cargo build --release]"
            )
        else:
            rust_times, rust_total = rust_result
            report("Rust (synthveda-parse)", rust_times, rust_total, total_bases)

            # Speedup vs Python.
            py_mean = sum(py_times) / len(py_times)
            rust_mean = sum(rust_times) / len(rust_times)
            if rust_mean > 0:
                speedup = py_mean / rust_mean
                print(f"\n  Speedup (Python / Rust): {speedup:.1f}x")

    print()

    # Cleanup temp file.
    if tmp_fasta is not None:
        try:
            os.unlink(fasta_path)
        except OSError:
            pass


if __name__ == "__main__":
    main()
