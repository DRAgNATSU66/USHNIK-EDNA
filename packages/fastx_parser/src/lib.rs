pub mod batcher;
pub mod output;
pub mod parser;
pub mod qc;

// Re-export the most commonly used types for convenience.
pub use batcher::{batch_records, BatchFilter, BatchMode, BatchStats};
pub use output::BatchRecord;
pub use parser::{parse_fastx, Format, RawRecord};
pub use qc::{compute_qc, QcMetrics};
