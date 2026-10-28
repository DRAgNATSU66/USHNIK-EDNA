use sha2::{Digest, Sha256};

/// Per-sequence quality control metrics computed in O(n) over the sequence.
#[derive(Debug, Clone, PartialEq)]
pub struct QcMetrics {
    /// Total number of characters in the sequence.
    pub length: usize,
    /// (G + C) / (A + T + G + C), ignoring N and ambiguity codes.
    pub gc_ratio: f64,
    /// N count / length. High values indicate poor sequencing quality.
    pub n_ratio: f64,
    /// True if non-IUPAC characters are present (digits, spaces, etc.).
    pub has_invalid_chars: bool,
    /// SHA-256 hex digest of the uppercase sequence — used for deduplication.
    pub sha256: String,
}

/// Compute QC metrics for a single sequence string.
///
/// The sequence should already be uppercased (the parser guarantees this), but
/// this function uppercases defensively so it is safe to call independently.
pub fn compute_qc(sequence: &str) -> QcMetrics {
    if sequence.is_empty() {
        return QcMetrics {
            length: 0,
            gc_ratio: 0.0,
            n_ratio: 0.0,
            has_invalid_chars: false,
            sha256: hex::encode(Sha256::digest(b"")),
        };
    }

    let mut g_count: usize = 0;
    let mut c_count: usize = 0;
    let mut n_count: usize = 0;
    let mut gc_base_count: usize = 0; // denominator: A + T + G + C only
    let mut has_invalid = false;

    // Upper-case as we iterate — avoids a heap allocation for the whole string.
    let mut upper_bytes: Vec<u8> = Vec::with_capacity(sequence.len());

    for byte in sequence.bytes() {
        let b = byte.to_ascii_uppercase();
        upper_bytes.push(b);

        match b {
            b'A' | b'T' => {
                gc_base_count += 1;
            }
            b'G' => {
                g_count += 1;
                gc_base_count += 1;
            }
            b'C' => {
                c_count += 1;
                gc_base_count += 1;
            }
            b'N' => {
                n_count += 1;
            }
            // IUPAC ambiguity codes — valid, but not counted in GC denominator.
            b'R' | b'Y' | b'S' | b'W' | b'K' | b'M'
            | b'B' | b'D' | b'H' | b'V' | b'U' => {}
            _ => {
                has_invalid = true;
            }
        }
    }

    let length = upper_bytes.len();

    let gc_ratio = if gc_base_count > 0 {
        (g_count + c_count) as f64 / gc_base_count as f64
    } else {
        0.0
    };

    let n_ratio = n_count as f64 / length as f64;

    let sha256 = hex::encode(Sha256::digest(&upper_bytes));

    QcMetrics {
        length,
        gc_ratio,
        n_ratio,
        has_invalid_chars: has_invalid,
        sha256,
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_empty_sequence() {
        let m = compute_qc("");
        assert_eq!(m.length, 0);
        assert_eq!(m.gc_ratio, 0.0);
        assert_eq!(m.n_ratio, 0.0);
        assert!(!m.has_invalid_chars);
    }

    #[test]
    fn test_pure_gc() {
        let m = compute_qc("GCGCGCGC");
        assert_eq!(m.length, 8);
        assert!((m.gc_ratio - 1.0).abs() < 1e-9);
        assert_eq!(m.n_ratio, 0.0);
        assert!(!m.has_invalid_chars);
    }

    #[test]
    fn test_pure_at() {
        let m = compute_qc("ATATAT");
        assert_eq!(m.gc_ratio, 0.0);
    }

    #[test]
    fn test_half_gc() {
        // ATGC → A(1) T(1) G(1) C(1) → gc = 2/4 = 0.5
        let m = compute_qc("ATGC");
        assert!((m.gc_ratio - 0.5).abs() < 1e-9);
    }

    #[test]
    fn test_n_ratio() {
        // NNNN out of 8 chars → 0.5
        let m = compute_qc("ATCGNNNN");
        assert!((m.n_ratio - 0.5).abs() < 1e-9);
    }

    #[test]
    fn test_invalid_chars() {
        let m = compute_qc("ATCG1234");
        assert!(m.has_invalid_chars);
    }

    #[test]
    fn test_iupac_ambiguity_not_invalid() {
        let m = compute_qc("RYSWKMBDHVN");
        assert!(!m.has_invalid_chars);
    }

    #[test]
    fn test_lowercase_handled() {
        // Parser uppercases, but compute_qc should be safe anyway.
        let lower = compute_qc("atcg");
        let upper = compute_qc("ATCG");
        assert_eq!(lower.gc_ratio, upper.gc_ratio);
        assert_eq!(lower.sha256, upper.sha256);
    }

    #[test]
    fn test_sha256_deterministic() {
        let a = compute_qc("ATCGATCG");
        let b = compute_qc("ATCGATCG");
        assert_eq!(a.sha256, b.sha256);
    }

    #[test]
    fn test_sha256_differs_for_different_sequences() {
        let a = compute_qc("ATCGATCG");
        let b = compute_qc("GCTAGCTA");
        assert_ne!(a.sha256, b.sha256);
    }
}
