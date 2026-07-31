use crate::output::BatchRecord;
use crate::parser::RawRecord;
use crate::qc::compute_qc;

/// How to group parsed sequences into batches.
#[derive(Debug, Clone, Copy)]
pub enum BatchMode {
    /// Exactly `n` sequences per batch (last batch may be smaller).
    ByCount(usize),
    /// At most `n` total bases per batch (a single sequence that exceeds `n`
    /// bases still forms its own batch rather than being split).
    ByBases(usize),
    /// All sequences go into one batch (use for small files / offline mode).
    All,
}

impl Default for BatchMode {
    fn default() -> Self {
        BatchMode::ByCount(1_000)
    }
}

/// Batching filters — sequences that fail a filter are dropped with a reason.
#[derive(Debug, Clone)]
pub struct BatchFilter {
    /// Drop sequences shorter than this (0 = keep all).
    pub min_length: usize,
    /// Drop sequences whose N ratio exceeds this (None = keep all).
    pub max_n_ratio: Option<f64>,
    /// Drop sequences with non-IUPAC characters.
    pub reject_invalid: bool,
}

impl Default for BatchFilter {
    fn default() -> Self {
        BatchFilter {
            min_length: 0,
            max_n_ratio: None,
            reject_invalid: false,
        }
    }
}

/// Summary statistics produced after batching.
#[derive(Debug, Default)]
pub struct BatchStats {
    pub total_sequences: usize,
    pub accepted_sequences: usize,
    pub rejected_too_short: usize,
    pub rejected_high_n: usize,
    pub rejected_invalid_chars: usize,
    pub total_batches: usize,
    pub total_bases: usize,
}

/// Convert `RawRecord` items into `BatchRecord` batches according to `mode`
/// and `filter`.
///
/// Batches are returned as a `Vec<Vec<BatchRecord>>`.  Each inner `Vec` is one
/// batch.  The batch_id is formatted as `bat_{batch_index:06}` (zero-padded to
/// 6 digits).
pub fn batch_records(
    records: Vec<RawRecord>,
    source_file: &str,
    mode: BatchMode,
    filter: &BatchFilter,
) -> (Vec<Vec<BatchRecord>>, BatchStats) {
    let mut stats = BatchStats {
        total_sequences: records.len(),
        ..Default::default()
    };

    let mut accepted: Vec<BatchRecord> = Vec::with_capacity(records.len());

    for record in records {
        let qc = compute_qc(&record.sequence);

        // Apply filters.
        if qc.length < filter.min_length {
            stats.rejected_too_short += 1;
            continue;
        }
        if let Some(max_n) = filter.max_n_ratio {
            if qc.n_ratio > max_n {
                stats.rejected_high_n += 1;
                continue;
            }
        }
        if filter.reject_invalid && qc.has_invalid_chars {
            stats.rejected_invalid_chars += 1;
            continue;
        }

        stats.accepted_sequences += 1;
        stats.total_bases += qc.length;

        accepted.push(BatchRecord {
            batch_id: String::new(), // filled in after grouping
            sequence_id: record.id,
            description: record.description,
            sequence: record.sequence,
            length: qc.length,
            gc_ratio: round_f64(qc.gc_ratio, 4),
            n_ratio: round_f64(qc.n_ratio, 4),
            has_invalid_chars: qc.has_invalid_chars,
            sha256: qc.sha256,
            source_file: source_file.to_owned(),
        });
    }

    let batches = group_into_batches(accepted, mode);
    stats.total_batches = batches.len();

    (batches, stats)
}

fn group_into_batches(records: Vec<BatchRecord>, mode: BatchMode) -> Vec<Vec<BatchRecord>> {
    if records.is_empty() {
        return vec![];
    }

    let mut batches: Vec<Vec<BatchRecord>> = vec![];
    let mut current: Vec<BatchRecord> = vec![];
    let mut current_bases: usize = 0;

    for mut record in records {
        let should_flush = match mode {
            BatchMode::ByCount(n) => !current.is_empty() && current.len() >= n,
            BatchMode::ByBases(n) => !current.is_empty() && current_bases + record.length > n,
            BatchMode::All => false,
        };

        if should_flush {
            let batch_id = format!("bat_{:06}", batches.len());
            for r in &mut current {
                r.batch_id = batch_id.clone();
            }
            batches.push(current);
            current = vec![];
            current_bases = 0;
        }

        current_bases += record.length;
        current.push(record);
    }

    if !current.is_empty() {
        let batch_id = format!("bat_{:06}", batches.len());
        for r in &mut current {
            r.batch_id = batch_id.clone();
        }
        batches.push(current);
    }

    batches
}

fn round_f64(v: f64, decimals: u32) -> f64 {
    let factor = 10_f64.powi(decimals as i32);
    (v * factor).round() / factor
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    fn make_records(seqs: &[&str]) -> Vec<RawRecord> {
        seqs.iter()
            .enumerate()
            .map(|(i, s)| crate::parser::RawRecord {
                id: format!("seq{}", i),
                description: String::new(),
                sequence: s.to_string(),
            })
            .collect()
    }

    #[test]
    fn test_batch_by_count() {
        let records = make_records(&["ATCG", "GCTA", "TTTT", "AAAA", "CCCC"]);
        let filter = BatchFilter::default();
        let (batches, stats) = batch_records(records, "test.fasta", BatchMode::ByCount(2), &filter);
        assert_eq!(batches.len(), 3);
        assert_eq!(batches[0].len(), 2);
        assert_eq!(batches[1].len(), 2);
        assert_eq!(batches[2].len(), 1);
        assert_eq!(stats.total_sequences, 5);
        assert_eq!(stats.accepted_sequences, 5);
        assert_eq!(stats.total_batches, 3);
    }

    #[test]
    fn test_batch_by_bases() {
        // Each sequence is 4 bases. limit = 8 bases → 2 per batch.
        let records = make_records(&["ATCG", "GCTA", "TTTT", "AAAA"]);
        let filter = BatchFilter::default();
        let (batches, _) = batch_records(records, "test.fasta", BatchMode::ByBases(8), &filter);
        assert_eq!(batches.len(), 2);
        assert_eq!(batches[0].len(), 2);
        assert_eq!(batches[1].len(), 2);
    }

    #[test]
    fn test_batch_all() {
        let records = make_records(&["ATCG", "GCTA", "TTTT"]);
        let filter = BatchFilter::default();
        let (batches, _) = batch_records(records, "test.fasta", BatchMode::All, &filter);
        assert_eq!(batches.len(), 1);
        assert_eq!(batches[0].len(), 3);
    }

    #[test]
    fn test_filter_min_length() {
        let records = make_records(&["AT", "ATCGATCG", "GC"]);
        let filter = BatchFilter { min_length: 4, ..Default::default() };
        let (batches, stats) = batch_records(records, "t.fasta", BatchMode::All, &filter);
        assert_eq!(stats.accepted_sequences, 1);
        assert_eq!(stats.rejected_too_short, 2);
        assert_eq!(batches[0].len(), 1);
    }

    #[test]
    fn test_filter_max_n_ratio() {
        let records = make_records(&["NNNN", "ATCG", "NNAT"]);
        // max_n_ratio = 0.3 → NNNN (1.0) and NNAT (0.5) are rejected
        let filter = BatchFilter {
            max_n_ratio: Some(0.3),
            ..Default::default()
        };
        let (_, stats) = batch_records(records, "t.fasta", BatchMode::All, &filter);
        assert_eq!(stats.accepted_sequences, 1);
        assert_eq!(stats.rejected_high_n, 2);
    }

    #[test]
    fn test_batch_ids_are_assigned() {
        let records = make_records(&["ATCG", "GCTA", "TTTT"]);
        let filter = BatchFilter::default();
        let (batches, _) = batch_records(records, "test.fasta", BatchMode::ByCount(2), &filter);
        assert_eq!(batches[0][0].batch_id, "bat_000000");
        assert_eq!(batches[0][1].batch_id, "bat_000000");
        assert_eq!(batches[1][0].batch_id, "bat_000001");
    }

    #[test]
    fn test_empty_input() {
        let filter = BatchFilter::default();
        let (batches, stats) = batch_records(vec![], "t.fasta", BatchMode::All, &filter);
        assert!(batches.is_empty());
        assert_eq!(stats.total_sequences, 0);
    }
}
