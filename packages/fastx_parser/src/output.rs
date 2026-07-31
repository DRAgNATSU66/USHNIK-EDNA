use serde::{Deserialize, Serialize};

/// A single sequence record ready for downstream processing.
///
/// This is the authoritative output format written to JSONL files and
/// consumed by the Python worker's parse stage.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BatchRecord {
    /// Batch identifier — e.g. "bat_000001". All records in the same batch
    /// share this id so the worker can group them into one Mongo document.
    pub batch_id: String,
    /// Original sequence identifier from the FASTA/FASTQ header.
    pub sequence_id: String,
    /// Optional free-text description after the sequence id.
    pub description: String,
    /// Uppercase nucleotide sequence.
    pub sequence: String,
    /// Sequence length in bases.
    pub length: usize,
    /// (G + C) / (A + T + G + C). 0.0 for an all-N or empty sequence.
    pub gc_ratio: f64,
    /// N count / length. High → low sequencing quality.
    pub n_ratio: f64,
    /// True if the sequence contains non-IUPAC characters.
    pub has_invalid_chars: bool,
    /// SHA-256 hex of the uppercase sequence — used for deduplication.
    pub sha256: String,
    /// Basename of the source file, for traceability.
    pub source_file: String,
}

impl BatchRecord {
    /// Serialize to a single compact JSON line (no trailing newline).
    pub fn to_jsonl_line(&self) -> anyhow::Result<String> {
        Ok(serde_json::to_string(self)?)
    }
}
