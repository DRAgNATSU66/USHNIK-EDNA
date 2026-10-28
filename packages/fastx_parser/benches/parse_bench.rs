use criterion::{black_box, criterion_group, criterion_main, BenchmarkId, Criterion, Throughput};
use fastx_parser::{batch_records, parse_fastx, BatchFilter, BatchMode};
use std::io::Cursor;

// ---------------------------------------------------------------------------
// Synthetic data generators
// ---------------------------------------------------------------------------

fn make_fasta(n_seqs: usize, seq_len: usize) -> Vec<u8> {
    let mut buf = Vec::with_capacity(n_seqs * (seq_len + 30));
    // Pre-build a single sequence line of the right length.
    let seq: String = "ATCG".chars().cycle().take(seq_len).collect();
    for i in 0..n_seqs {
        buf.extend_from_slice(format!(">seq_{}\n", i).as_bytes());
        buf.extend_from_slice(seq.as_bytes());
        buf.push(b'\n');
    }
    buf
}

fn make_fastq(n_seqs: usize, seq_len: usize) -> Vec<u8> {
    let mut buf = Vec::with_capacity(n_seqs * (seq_len * 2 + 40));
    let seq: String = "ATCG".chars().cycle().take(seq_len).collect();
    let qual: String = "I".repeat(seq_len);
    for i in 0..n_seqs {
        buf.extend_from_slice(format!("@read_{}\n", i).as_bytes());
        buf.extend_from_slice(seq.as_bytes());
        buf.extend_from_slice(b"\n+\n");
        buf.extend_from_slice(qual.as_bytes());
        buf.push(b'\n');
    }
    buf
}

// ---------------------------------------------------------------------------
// Benchmarks
// ---------------------------------------------------------------------------

fn bench_fasta_parse(c: &mut Criterion) {
    let mut group = c.benchmark_group("fasta_parse");

    for &(n_seqs, seq_len) in &[(1_000, 500), (10_000, 500), (1_000, 2_000)] {
        let data = make_fasta(n_seqs, seq_len);
        let total_bases = n_seqs * seq_len;
        let label = format!("{}seqs_{}bp", n_seqs, seq_len);

        group.throughput(Throughput::Bytes(data.len() as u64));
        group.bench_with_input(
            BenchmarkId::new("parse_only", &label),
            &data,
            |b, data| {
                b.iter(|| {
                    let cursor = Cursor::new(black_box(data.as_slice()));
                    parse_fastx(cursor, "bench.fasta").unwrap()
                });
            },
        );

        let records = parse_fastx(Cursor::new(&data), "bench.fasta").unwrap();
        group.throughput(Throughput::Elements(total_bases as u64));
        group.bench_with_input(
            BenchmarkId::new("parse_and_batch", &label),
            &records,
            |b, records| {
                b.iter(|| {
                    batch_records(
                        black_box(records.clone()),
                        "bench.fasta",
                        BatchMode::ByCount(1_000),
                        &BatchFilter::default(),
                    )
                });
            },
        );
    }

    group.finish();
}

fn bench_fastq_parse(c: &mut Criterion) {
    let mut group = c.benchmark_group("fastq_parse");

    for &(n_seqs, seq_len) in &[(1_000, 150), (10_000, 150)] {
        let data = make_fastq(n_seqs, seq_len);
        let label = format!("{}reads_{}bp", n_seqs, seq_len);

        group.throughput(Throughput::Bytes(data.len() as u64));
        group.bench_with_input(
            BenchmarkId::new("parse_only", &label),
            &data,
            |b, data| {
                b.iter(|| {
                    let cursor = Cursor::new(black_box(data.as_slice()));
                    parse_fastx(cursor, "bench.fastq").unwrap()
                });
            },
        );
    }

    group.finish();
}

fn bench_qc(c: &mut Criterion) {
    let mut group = c.benchmark_group("qc");

    for &seq_len in &[150, 500, 2_000, 10_000] {
        let seq: String = "ATCGNNRY".chars().cycle().take(seq_len).collect();
        group.throughput(Throughput::Elements(seq_len as u64));
        group.bench_with_input(
            BenchmarkId::new("compute_qc", seq_len),
            &seq,
            |b, seq| {
                b.iter(|| fastx_parser::compute_qc(black_box(seq)));
            },
        );
    }

    group.finish();
}

criterion_group!(benches, bench_fasta_parse, bench_fastq_parse, bench_qc);
criterion_main!(benches);
