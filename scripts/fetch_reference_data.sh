#!/usr/bin/env bash
# Re-download the raw reference data described in synthveda-data/README.md.
#
# Resumable (wget -c) and safe to re-run: finished files are skipped, NCBI BLAST
# DB archives are md5-checked before extraction. Sources that need a login or a
# browser click (BOLD) are NOT fetched here -- see the note printed at the end.
#
#   scripts/fetch_reference_data.sh            # tier 1: ~3.5 GB, what build_dataset needs
#   scripts/fetch_reference_data.sh --all      # + tier 2: nt_viruses (14 GB), ref_prok_rep_genomes (24 GB)
#
# Data root: $SYNTHVEDA_DATA_ROOT, default <repo>/synthveda-data.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
ROOT="${SYNTHVEDA_DATA_ROOT:-$REPO/synthveda-data}"
RAW="$ROOT/raw"
TOOLS="$ROOT/tools"
NCBI_DB="https://ftp.ncbi.nlm.nih.gov/blast/db"
SILVA="https://www.arb-silva.de/fileadmin/silva_databases/release_138.2/Exports"
TIER2=0
[[ "${1:-}" == "--all" ]] && TIER2=1

mkdir -p "$RAW"/{silva,univec,grch38,ncbi_blastdb/extracted,bold,unite,midori2} "$TOOLS"

fetch() { # url dest
  echo "-> $(basename "$2")"
  wget -q --show-progress -c -O "$2" "$1"
}

blastdb() { # name -- single-archive or multi-part NCBI BLAST DB
  local name="$1" dir="$RAW/ncbi_blastdb"
  local parts
  if curl -sfI "$NCBI_DB/$name.tar.gz" >/dev/null; then
    parts=("$name.tar.gz")
  else
    mapfile -t parts < <(curl -s "$NCBI_DB/" | grep -oE "\"$name\.[0-9]+\.tar\.gz\"" | tr -d '"' | sort -u)
  fi
  [[ ${#parts[@]} -gt 0 ]] || { echo "!! $name: not found on NCBI FTP"; return 1; }
  mkdir -p "$dir/extracted/$name"
  for p in "${parts[@]}"; do
    local marker="$dir/extracted/$name/.done.$p"
    [[ -f "$marker" ]] && continue
    fetch "$NCBI_DB/$p" "$dir/$p"
    fetch "$NCBI_DB/$p.md5" "$dir/$p.md5"
    (cd "$dir" && md5sum -c --quiet "$p.md5") || { echo "!! md5 mismatch: $p (delete it and re-run)"; return 1; }
    tar -xzf "$dir/$p" -C "$dir/extracted/$name"
    rm -f "$dir/$p"          # keep only the extracted DB
    touch "$marker"
  done
}

echo "== tools =="
if [[ ! -x "$TOOLS/blast/bin/blastdbcmd" ]]; then
  tgz=$(curl -s https://ftp.ncbi.nlm.nih.gov/blast/executables/blast+/LATEST/ | grep -oE 'ncbi-blast-[0-9.]+\+-x64-linux\.tar\.gz' | head -1)
  fetch "https://ftp.ncbi.nlm.nih.gov/blast/executables/blast+/LATEST/$tgz" "$TOOLS/$tgz"
  mkdir -p "$TOOLS/blast" && tar -xzf "$TOOLS/$tgz" -C "$TOOLS/blast" --strip-components=1 && rm -f "$TOOLS/$tgz"
fi
if [[ ! -x "$TOOLS/vsearch/bin/vsearch" ]]; then
  url=$(curl -s https://api.github.com/repos/torognes/vsearch/releases/latest | grep -oE 'https://[^"]+linux-x86_64\.tar\.gz' | head -1)
  fetch "$url" "$TOOLS/vsearch.tar.gz"
  mkdir -p "$TOOLS/vsearch" && tar -xzf "$TOOLS/vsearch.tar.gz" -C "$TOOLS/vsearch" --strip-components=1 && rm -f "$TOOLS/vsearch.tar.gz"
fi
# Capture first, then trim: piping straight into `head` can SIGPIPE the
# producer, which pipefail turns into a script exit (seen as EXIT 141).
v=$("$TOOLS/blast/bin/blastdbcmd" -version); echo "${v%%$'\n'*}"
v=$("$TOOLS/vsearch/bin/vsearch" --version 2>&1); echo "${v%%$'\n'*}"

echo "== SILVA 138.2 =="
for f in SILVA_138.2_SSURef_NR99_tax_silva.fasta.gz SILVA_138.2_LSURef_NR99_tax_silva.fasta.gz; do
  fetch "$SILVA/$f" "$RAW/silva/$f"
done

echo "== UniVec =="
fetch https://ftp.ncbi.nlm.nih.gov/pub/UniVec/UniVec_Core "$RAW/univec/UniVec_Core"
fetch https://ftp.ncbi.nlm.nih.gov/pub/UniVec/UniVec "$RAW/univec/UniVec"

echo "== GRCh38 =="
fetch https://ftp.ncbi.nlm.nih.gov/genomes/all/GCA/000/001/405/GCA_000001405.15_GRCh38/seqs_for_alignment_pipelines.ucsc_ids/GCA_000001405.15_GRCh38_no_alt_analysis_set.fna.gz \
  "$RAW/grch38/GRCh38_no_alt_analysis_set.fna.gz"

echo "== UNITE v10.0 general release (CC BY 4.0, DOI 10.15156/BIO/2959332) =="
# Direct file behind the DOI, as returned by the public PlutoF API
# (api.plutof.ut.ee/v1/public/dois/?identifier=10.15156/BIO/2959332).
if ! ls "$RAW"/unite/*general_release*.fasta >/dev/null 2>&1; then
  fetch https://s3.hpc.ut.ee/plutof-public/original/d18aa648-3f4c-4f46-84d4-c8c5d48439ba.tgz "$RAW/unite/unite_general_release_v10.tgz"
  tar -xzf "$RAW/unite/unite_general_release_v10.tgz" -C "$RAW/unite"
fi

echo "== MIDORI2 GB273 RAW (CC BY 4.0, Zenodo record 22685701) =="
# MIDORI2 moved its downloads to Zenodo in 2026; RAW.zip holds plain FASTA with
# the "###" MIDORI headers for all 15 genes (UNIQ, LONGEST, TOTAL selections).
fetch https://zenodo.org/api/records/22685701/files/MIDORI2_GB273_RAW.zip/content "$RAW/midori2/MIDORI2_GB273_RAW.zip"
(cd "$RAW/midori2" && echo "6145c5f0844780b93b38deec04ea64b3  MIDORI2_GB273_RAW.zip" | md5sum -c --quiet) \
  || { echo "!! MIDORI2 md5 mismatch (delete it and re-run)"; exit 1; }

echo "== NCBI BLAST DBs (tier 1) =="
for db in taxdb 16S_ribosomal_RNA LSU_prokaryote_rRNA SSU_eukaryote_rRNA LSU_eukaryote_rRNA \
          ITS_RefSeq_Fungi ITS_eukaryote_sequences 18S_fungal_sequences env_nt mito \
          ref_viruses_rep_genomes nt_others; do
  blastdb "$db" || true
done

if [[ $TIER2 == 1 ]]; then
  echo "== NCBI BLAST DBs (tier 2) =="
  blastdb nt_viruses || true
  blastdb ref_prok_rep_genomes || true
fi

cat <<EOF

== Done with scriptable sources. One manual download still needed ==
  BOLD -> $RAW/bold/BOLD_Public.<date>.parquet
          boldsystems.org/data/data-packages/ requires a BOLD login and acceptance of the
          data terms (CC BY-SA 4.0). Log in, accept, and download the Parquet package.
EOF
