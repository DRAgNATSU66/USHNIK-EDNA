use std::fs::File;
use std::io::{self, BufWriter, Write};
use std::path::Path;
use std::time::Instant;

use anyhow::{Context, Result};
use clap::Parser;

use fastx_parser::{batch_records, parse_fastx, BatchFilter, BatchMode};

// ---------------------------------------------------------------------------
// CLI definition
// ---------------------------------------------------------------------------

#[derive(Parser, Debug)]
#[command(
    name = "synthveda-parse",
    version,
    about = "Synth Veda FASTA/FASTQ parser and batching engine.\n\
             Reads FASTA or FASTQ input and writes a JSONL batch file."
)]
struct Args {
    /// Input FASTA or FASTQ file path.
    /// Use '-' to read from stdin.
    input: String,

    /// Output JSONL file path.
    /// Use '-' to write to stdout.
    #[arg(long, default_value = "-")]
    out: String,

    /// Batch size in number of sequences (default: 1000).
    /// Ignored if --batch-bases is set.
    #[arg(long, default_value_t = 1_000)]
    batch_size: usize,

    /// Batch size in total bases.
    /// When set, overrides --batch-size.
    /// Useful for variable-length reads where a fixed count per batch is uneven.
    #[arg(long)]
    batch_bases: Option<usize>,

    /// Put all sequences in a single batch.
    /// Best for small files and offline Abyss Mode processing.
    #[arg(long)]
    all_in_one: bool,

    /// Minimum sequence length filter (sequences shorter than this are dropped).
    #[arg(long, default_value_t = 0)]
    min_length: usize,

    /// Maximum N ratio filter (0.0–1.0).
    /// Sequences with a higher N ratio are dropped.
    #[arg(long)]
    max_n_ratio: Option<f64>,

    /// Drop sequences that contain non-IUPAC characters.
    #[arg(long)]
    reject_invalid: bool,

    /// Print summary statistics to stderr after processing.
    #[arg(long)]
    stats: bool,
}

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------

fn main() -> Result<()> {
    let args = Args::parse();
    let t0 = Instant::now();

    // --- Determine batch mode ---
    let mode = if args.all_in_one {
        BatchMode::All
    } else if let Some(bases) = args.batch_bases {
        BatchMode::ByBases(bases)
    } else {
        BatchMode::ByCount(args.batch_size)
    };

    // --- Determine source file name for traceability ---
    let source_file = if args.input == "-" {
        "stdin".to_owned()
    } else {
        Path::new(&args.input)
            .file_name()
            .and_then(|n| n.to_str())
            .unwrap_or(&args.input)
            .to_owned()
    };

    // --- Parse ---
    let records = if args.input == "-" {
        parse_fastx(io::stdin(), &source_file)
            .context("Failed to parse FASTA/FASTQ from stdin")?
    } else {
        let f = File::open(&args.input)
            .with_context(|| format!("Cannot open input file: {}", args.input))?;
        parse_fastx(f, &source_file)
            .with_context(|| format!("Failed to parse FASTA/FASTQ from: {}", args.input))?
    };

    // --- Build filter ---
    let filter = BatchFilter {
        min_length: args.min_length,
        max_n_ratio: args.max_n_ratio,
        reject_invalid: args.reject_invalid,
    };

    // --- Batch ---
    let (batches, batch_stats) = batch_records(records, &source_file, mode, &filter);

    // --- Write JSONL output ---
    let mut writer: Box<dyn Write> = if args.out == "-" {
        Box::new(BufWriter::new(io::stdout()))
    } else {
        let f = File::create(&args.out)
            .with_context(|| format!("Cannot create output file: {}", args.out))?;
        Box::new(BufWriter::new(f))
    };

    let mut records_written: usize = 0;
    for batch in &batches {
        for record in batch {
            let line = record.to_jsonl_line()?;
            writer.write_all(line.as_bytes())?;
            writer.write_all(b"\n")?;
            records_written += 1;
        }
    }
    writer.flush()?;

    // --- Optional stats ---
    if args.stats {
        let elapsed = t0.elapsed();
        eprintln!("=== synthveda-parse stats ===");
        eprintln!("  source file    : {}", source_file);
        eprintln!("  total sequences: {}", batch_stats.total_sequences);
        eprintln!("  accepted       : {}", batch_stats.accepted_sequences);
        eprintln!("  rejected (short): {}", batch_stats.rejected_too_short);
        eprintln!("  rejected (N%)  : {}", batch_stats.rejected_high_n);
        eprintln!("  rejected (inv) : {}", batch_stats.rejected_invalid_chars);
        eprintln!("  total bases    : {}", batch_stats.total_bases);
        eprintln!("  total batches  : {}", batch_stats.total_batches);
        eprintln!("  records written: {}", records_written);
        eprintln!("  elapsed        : {:.3}s", elapsed.as_secs_f64());
        if elapsed.as_secs_f64() > 0.0 {
            let mbps = batch_stats.total_bases as f64 / 1_000_000.0 / elapsed.as_secs_f64();
            eprintln!("  throughput     : {:.1} Mbp/s", mbps);
        }
    }

    Ok(())
}
