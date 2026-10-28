use std::io::{BufRead, BufReader, Read};

use anyhow::{bail, Result};

/// A single parsed sequence record from a FASTA or FASTQ file.
#[derive(Debug, Clone, PartialEq)]
pub struct RawRecord {
    pub id: String,
    pub description: String,
    pub sequence: String,
}

/// Auto-detect file format from the first non-empty, non-comment line.
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum Format {
    Fasta,
    Fastq,
}

/// Parse either FASTA or FASTQ from any `Read` source.
///
/// Format is detected automatically from the first character:
///   `>` → FASTA
///   `@` → FASTQ
///
/// Returns all records in a `Vec`. For very large files (> a few GB) consider
/// using the lower-level `parse_fasta` / `parse_fastq` iterators directly.
pub fn parse_fastx<R: Read>(reader: R, source_file: &str) -> Result<Vec<RawRecord>> {
    let mut buf = BufReader::new(reader);
    let mut first_line = String::new();

    // Peek at the first non-empty line to detect format.
    loop {
        first_line.clear();
        let n = buf.read_line(&mut first_line)?;
        if n == 0 {
            return Ok(vec![]);
        }
        let trimmed = first_line.trim();
        if trimmed.is_empty() {
            continue;
        }
        if trimmed.starts_with(';') {
            // FASTA comment line — skip and keep peeking
            continue;
        }
        break;
    }

    let trimmed = first_line.trim();
    let format = if trimmed.starts_with('>') {
        Format::Fasta
    } else if trimmed.starts_with('@') {
        Format::Fastq
    } else {
        bail!(
            "Cannot detect format for '{}': first line is neither '>' (FASTA) nor '@' (FASTQ): {:?}",
            source_file,
            trimmed
        );
    };

    match format {
        Format::Fasta => parse_fasta_with_first_line(buf, first_line),
        Format::Fastq => parse_fastq_with_first_line(buf, first_line),
    }
}

// ---------------------------------------------------------------------------
// FASTA parser
// ---------------------------------------------------------------------------

fn parse_fasta_with_first_line<R: BufRead>(reader: R, first_line: String) -> Result<Vec<RawRecord>> {
    let mut records: Vec<RawRecord> = Vec::new();
    let mut current_id = String::new();
    let mut current_desc = String::new();
    let mut current_seq = String::new();
    let mut in_record = false;

    // Process the already-read first line, then continue with the reader.
    let first = std::iter::once(Ok(first_line));
    let rest = reader.lines();
    let lines = first.chain(rest);

    for line_result in lines {
        let line = line_result?;
        let line = line.trim();

        if line.is_empty() || line.starts_with(';') {
            continue;
        }

        if let Some(header) = line.strip_prefix('>') {
            // Flush previous record.
            if in_record {
                records.push(RawRecord {
                    id: current_id.clone(),
                    description: current_desc.clone(),
                    sequence: current_seq.clone(),
                });
                current_seq.clear();
            }
            let mut parts = header.splitn(2, ' ');
            current_id = parts.next().unwrap_or("").to_owned();
            current_desc = parts.next().unwrap_or("").to_owned();
            in_record = true;
        } else if in_record {
            // Sequence continuation — uppercase for consistency.
            for ch in line.chars() {
                if !ch.is_whitespace() {
                    current_seq.push(ch.to_ascii_uppercase());
                }
            }
        }
    }

    if in_record && !current_seq.is_empty() {
        records.push(RawRecord {
            id: current_id,
            description: current_desc,
            sequence: current_seq,
        });
    }

    Ok(records)
}

// ---------------------------------------------------------------------------
// FASTQ parser
// ---------------------------------------------------------------------------

fn parse_fastq_with_first_line<R: BufRead>(reader: R, first_line: String) -> Result<Vec<RawRecord>> {
    let mut records: Vec<RawRecord> = Vec::new();

    let first = std::iter::once(Ok(first_line));
    let mut lines = first.chain(reader.lines());

    loop {
        // Line 1: @header
        let header_line = match lines.next() {
            None => break,
            Some(l) => l?,
        };
        let header_line = header_line.trim().to_owned();
        if header_line.is_empty() {
            continue;
        }

        let header = header_line
            .strip_prefix('@')
            .ok_or_else(|| anyhow::anyhow!("FASTQ header must start with '@', got: {:?}", header_line))?;

        let mut parts = header.splitn(2, ' ');
        let id = parts.next().unwrap_or("").to_owned();
        let desc = parts.next().unwrap_or("").to_owned();

        // Line 2: sequence
        let seq_line = lines
            .next()
            .ok_or_else(|| anyhow::anyhow!("Truncated FASTQ: missing sequence line for '{}'", id))??;
        let sequence = seq_line.trim().to_ascii_uppercase();

        // Line 3: + separator
        let plus_line = lines
            .next()
            .ok_or_else(|| anyhow::anyhow!("Truncated FASTQ: missing '+' line for '{}'", id))??;
        if !plus_line.trim().starts_with('+') {
            bail!("FASTQ '+' line missing for '{}', got: {:?}", id, plus_line.trim());
        }

        // Line 4: quality scores (consumed but not stored)
        let _quality = lines
            .next()
            .ok_or_else(|| anyhow::anyhow!("Truncated FASTQ: missing quality line for '{}'", id))??;

        if !sequence.is_empty() {
            records.push(RawRecord { id, description: desc, sequence });
        }
    }

    Ok(records)
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Cursor;

    #[test]
    fn test_fasta_single_record() {
        let data = b">seq1 a test\nATCGATCG\n";
        let records = parse_fastx(Cursor::new(data), "test.fasta").unwrap();
        assert_eq!(records.len(), 1);
        assert_eq!(records[0].id, "seq1");
        assert_eq!(records[0].description, "a test");
        assert_eq!(records[0].sequence, "ATCGATCG");
    }

    #[test]
    fn test_fasta_multi_record() {
        let data = b">seq1\nATCG\n>seq2\nGCTA\n";
        let records = parse_fastx(Cursor::new(data), "test.fasta").unwrap();
        assert_eq!(records.len(), 2);
        assert_eq!(records[0].sequence, "ATCG");
        assert_eq!(records[1].id, "seq2");
    }

    #[test]
    fn test_fasta_multiline_sequence() {
        let data = b">seq1\nATCG\nGGCC\nTTAA\n";
        let records = parse_fastx(Cursor::new(data), "test.fasta").unwrap();
        assert_eq!(records[0].sequence, "ATCGGGCCTTAA");
    }

    #[test]
    fn test_fasta_lowercase_uppercased() {
        let data = b">seq1\natcgatcg\n";
        let records = parse_fastx(Cursor::new(data), "test.fasta").unwrap();
        assert_eq!(records[0].sequence, "ATCGATCG");
    }

    #[test]
    fn test_fasta_comment_lines_skipped() {
        let data = b"; comment\n>seq1\nATCG\n";
        let records = parse_fastx(Cursor::new(data), "test.fasta").unwrap();
        assert_eq!(records.len(), 1);
        assert_eq!(records[0].sequence, "ATCG");
    }

    #[test]
    fn test_fasta_empty_input() {
        let data: &[u8] = b"";
        let records = parse_fastx(Cursor::new(data), "empty.fasta").unwrap();
        assert!(records.is_empty());
    }

    #[test]
    fn test_fastq_basic() {
        let data = b"@read1 desc\nATCGATCG\n+\nIIIIIIII\n@read2\nGGCC\n+\nHHHH\n";
        let records = parse_fastx(Cursor::new(data), "test.fastq").unwrap();
        assert_eq!(records.len(), 2);
        assert_eq!(records[0].id, "read1");
        assert_eq!(records[0].description, "desc");
        assert_eq!(records[0].sequence, "ATCGATCG");
        assert_eq!(records[1].id, "read2");
        assert_eq!(records[1].sequence, "GGCC");
    }

    #[test]
    fn test_fastq_lowercase_uppercased() {
        let data = b"@r1\natcg\n+\nIIII\n";
        let records = parse_fastx(Cursor::new(data), "test.fastq").unwrap();
        assert_eq!(records[0].sequence, "ATCG");
    }

    #[test]
    fn test_unknown_format_error() {
        let data = b"not a fasta or fastq\n";
        let result = parse_fastx(Cursor::new(data), "bad.txt");
        assert!(result.is_err());
    }
}
