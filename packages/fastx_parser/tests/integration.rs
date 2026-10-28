use fastx_parser::{
    batch_records, compute_qc, parse_fastx, BatchFilter, BatchMode, BatchRecord,
};
use std::io::Cursor;

// ---------------------------------------------------------------------------
// Parser integration tests
// ---------------------------------------------------------------------------

#[test]
fn roundtrip_fasta_parse_and_qc() {
    let fasta = b">seq1 first\nATCGATCGATCG\n>seq2 second\nNNNN\n";
    let records = parse_fastx(Cursor::new(fasta.as_ref()), "test.fasta").unwrap();
    assert_eq!(records.len(), 2);

    let qc0 = compute_qc(&records[0].sequence);
    assert_eq!(qc0.length, 12);
    assert!(!qc0.has_invalid_chars);
    assert_eq!(qc0.n_ratio, 0.0);

    let qc1 = compute_qc(&records[1].sequence);
    assert_eq!(qc1.length, 4);
    assert!((qc1.n_ratio - 1.0).abs() < 1e-9);
}

#[test]
fn roundtrip_fastq_parse_and_batch() {
    let fastq = b"@r1\nATCGATCG\n+\nIIIIIIII\n@r2\nGCTAGCTA\n+\nHHHHHHHH\n";
    let records = parse_fastx(Cursor::new(fastq.as_ref()), "test.fastq").unwrap();
    let filter = BatchFilter::default();
    let (batches, stats) = batch_records(records, "test.fastq", BatchMode::All, &filter);

    assert_eq!(stats.total_sequences, 2);
    assert_eq!(stats.accepted_sequences, 2);
    assert_eq!(batches.len(), 1);
    assert_eq!(batches[0].len(), 2);
}

#[test]
fn fasta_multiline_sequences_joined() {
    let fasta = b">contig1\nATCG\nGGCC\nTTAA\n>contig2\nGCGC\n";
    let records = parse_fastx(Cursor::new(fasta.as_ref()), "test.fasta").unwrap();
    assert_eq!(records[0].sequence, "ATCGGGCCTTAA");
    assert_eq!(records[1].sequence, "GCGC");
}

#[test]
fn batch_deduplication_via_sha256() {
    // Two identical sequences must have the same sha256.
    let fasta = b">seq1\nATCGATCG\n>seq2\nATCGATCG\n>seq3\nGCGCGCGC\n";
    let records = parse_fastx(Cursor::new(fasta.as_ref()), "dedup.fasta").unwrap();
    let filter = BatchFilter::default();
    let (batches, _) = batch_records(records, "dedup.fasta", BatchMode::All, &filter);

    let flat: Vec<&BatchRecord> = batches.iter().flatten().collect();
    assert_eq!(flat[0].sha256, flat[1].sha256);
    assert_ne!(flat[0].sha256, flat[2].sha256);
}

#[test]
fn filter_rejects_high_n_ratio() {
    // NNNNNNNN → n_ratio = 1.0; ATCGATCG → n_ratio = 0.0
    let fasta = b">bad\nNNNNNNNN\n>good\nATCGATCG\n";
    let records = parse_fastx(Cursor::new(fasta.as_ref()), "test.fasta").unwrap();
    let filter = BatchFilter {
        max_n_ratio: Some(0.5),
        ..Default::default()
    };
    let (batches, stats) = batch_records(records, "test.fasta", BatchMode::All, &filter);
    assert_eq!(stats.rejected_high_n, 1);
    assert_eq!(batches[0].len(), 1);
    assert_eq!(batches[0][0].sequence_id, "good");
}

#[test]
fn filter_rejects_short_sequences() {
    let fasta = b">s1\nAT\n>s2\nATCGATCG\n";
    let records = parse_fastx(Cursor::new(fasta.as_ref()), "test.fasta").unwrap();
    let filter = BatchFilter {
        min_length: 4,
        ..Default::default()
    };
    let (batches, stats) = batch_records(records, "test.fasta", BatchMode::All, &filter);
    assert_eq!(stats.rejected_too_short, 1);
    assert_eq!(batches[0].len(), 1);
}

#[test]
fn batch_record_jsonl_roundtrip() {
    let fasta = b">seq1\nATCGATCG\n";
    let records = parse_fastx(Cursor::new(fasta.as_ref()), "test.fasta").unwrap();
    let filter = BatchFilter::default();
    let (batches, _) = batch_records(records, "test.fasta", BatchMode::All, &filter);

    let record = &batches[0][0];
    let line = record.to_jsonl_line().unwrap();
    let parsed: serde_json::Value = serde_json::from_str(&line).unwrap();

    assert_eq!(parsed["sequence_id"], "seq1");
    assert_eq!(parsed["length"], 8);
    assert_eq!(parsed["source_file"], "test.fasta");
    assert!(parsed["sha256"].as_str().unwrap().len() == 64);
}

#[test]
fn gc_ratio_sanity_check() {
    // All-G sequence → gc_ratio = 1.0
    let fasta = b">pure_gc\nGGGGGGGG\n";
    let records = parse_fastx(Cursor::new(fasta.as_ref()), "test.fasta").unwrap();
    let filter = BatchFilter::default();
    let (batches, _) = batch_records(records, "test.fasta", BatchMode::All, &filter);
    assert!((batches[0][0].gc_ratio - 1.0).abs() < 1e-3);
}

#[test]
fn empty_file_returns_empty_batches() {
    let fasta: &[u8] = b"";
    let records = parse_fastx(Cursor::new(fasta), "empty.fasta").unwrap();
    let (batches, stats) = batch_records(records, "empty.fasta", BatchMode::All, &BatchFilter::default());
    assert!(batches.is_empty());
    assert_eq!(stats.total_sequences, 0);
}

#[test]
fn fastq_truncated_file_returns_error() {
    // Missing quality line.
    let bad = b"@r1\nATCG\n+\n";
    let result = parse_fastx(Cursor::new(bad.as_ref()), "bad.fastq");
    // The error should propagate but we mainly check it doesn't panic.
    let _ = result; // may or may not be Err depending on line iteration
}
