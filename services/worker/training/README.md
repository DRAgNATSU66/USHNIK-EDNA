# services/worker/training

Builds the per-route training data and fine-tunes the route heads.

| File | Role |
|------|------|
| `sources.py` | One iterator per reference source, all yielding `Record(sequence, organism_name, lineage, source, route?, label?)` |
| `routing.py` / `labeling.py` | Lineage → route, and (route, sequence, name, lineage) → label. Every source goes through these. |
| `build_dataset.py` | Walks `raw/`, routes, labels, caps, dedups, writes `processed/<route>/{train,dev,test}.csv` |
| `near_dup.py` | MinHash/LSH near-duplicate groups (16-mer Jaccard ≥ 0.8) used to split without near-duplicate leakage |
| `check_leakage.py` | Exact cross-split check (THEORY_README §3, exit 1 if non-zero) plus near-duplicate and cross-route counts |
| `fetch_supplementary.py` | Fetches extra sequences for thin classes from official APIs into `raw/supplementary/` |
| `finetune.py`, `evaluate_checkpoint.py` | Training and evaluation |
| `eval_orchestrator.py` | Day 9 orchestrator: planner sweep on dev, held-out smoke run (`docs/ml/results/orchestrator_*`) |

## Rebuilding `processed/` (`build_dataset.py`)

```bash
cd services/worker
python -m training.build_dataset --data-dir <root> --route-cap bacteria_pathogen=20000 \
    --exclude-blastdb nt_viruses,ref_prok_rep_genomes      # tier-2 DBs while they download
python -m training.check_leakage --processed <root>/processed --json <root>/processed/leakage_report.json
```

- **BOLD** is read from the newest `raw/bold/BOLD_Public*.parquet`. With none present the build logs
  `WARNING: skipping BOLD` and carries on. Reading it needs `pyarrow`, which no requirements file
  installs yet.
- **MIDORI2** is ingested one gene at a time (UNIQ selection), so the per-source scan cap applies per gene.
- **Splits.** Rows are exact-deduplicated per route as before. Then, by default (`--split-mode group`),
  near-duplicate groups (`near_dup.py`) are kept inside a single split. Groups are placed largest first, so the
  largest clusters go to train. `--split-mode random` restores the old shuffle-and-slice.
- `processed/build_report.json` records sources scanned or skipped, caps, candidates seen per class,
  per-split counts and wall time.

## Supplementary data (`fetch_supplementary.py`)

**Why.** Measured in `processed/` on 2026-10-15, some classes a head is allowed to predict have
almost no examples: `animal_general/possible_novelty` 17/1/4 (train/dev/test),
`fish/possible_novelty` 0/0/0, and `human_domestic_contamination/possible_contamination` 0/0/0.
A head cannot learn a class it never sees. Decision Q1 (2026-10-14, `docs/decisions.md`) says to
gather more through official APIs, keeping an accession for every sequence.

**What it fetches.** The queries live in `QUERIES` in the script (`--list` prints them with the
exact search terms). In summary:

| query_id | API | Taxa | Marker | Length | Target |
|----------|-----|------|--------|--------|--------|
| `ncbi_animal_env_coi` | NCBI E-utilities | Metazoa "environmental samples", not Actinopterygii | COI | 150–2000 | animal_general / possible_novelty |
| `ncbi_animal_env_18s` | NCBI E-utilities | same | 18S rRNA | 150–2000 | same |
| `ncbi_animal_env_16s` | NCBI E-utilities | same | mito 16S rRNA | 150–2000 | same |
| `ena_animal_env_any` | ENA Portal API | Metazoa, `environmental_sample=true`, not Actinopterygii | any | 150–2000 | same |
| `ncbi_fish_env` | NCBI E-utilities | Actinopterygii "environmental samples" | any | 150–2000 | fish / possible_novelty |
| `ena_fish_env` | ENA Portal API | Actinopterygii, `environmental_sample=true` | any | 150–2000 | same |
| `ncbi_human_mito_control_region` | NCBI E-utilities | Homo sapiens (not expanded), mitochondrion | D-loop / control region / HVR | 150–2000 | human_domestic_contamination / known_species |
| `ncbi_human_nuclear_rrna` | NCBI E-utilities | Homo sapiens (not expanded), PDB chains excluded | 18S/28S/5.8S/45S rRNA | 150–2000 | same |
| `ncbi_cloning_vectors` | NCBI E-utilities | taxon 29278 "vectors", complete sequences | vector | 1000–20000 | human_domestic_contamination / possible_contamination |
| `ncbi_phix174` | NCBI E-utilities | Escherichia phage phiX174, complete genomes | genome | 4000–6000 | same |

Kept per query on the 2026-10-15 and 2026-10-18 runs, as records then unique sequences:

| Query | Records | Unique |
|-------|--------:|-------:|
| animal COI | 2000 | 1945 |
| animal 18S | 1500 | 1291 |
| animal 16S | 225 | 146 |
| ENA animal | 1500 | 1492 |
| NCBI fish | 872 | 836 |
| ENA fish | 4 | 4 |
| human control region | 800 | 779 |
| human nuclear rRNA | 358 | 138 |
| vectors | 1500 | 1500 |
| PhiX174 | 157 | 145 |

Each query's `run.json` gives its rejection reasons.

The human queries do not fill an empty class. `human_domestic_contamination/known_species` is
already at the 5000 cap, and the queries add loci that class lacks. Measured on `processed/` on
2026-10-18, 1732 of its 5000 rows are 400 bp windows. The rest are gene-length mito records
(cytb, COI, 12S, 16S). The overlap check counts fetched records that share at least one 32-mer
with an existing row: 1 of 358 for nuclear rRNA and 110 of 800 for the control region.
`chunk_long_sequence` keeps only the first 3.6 kb of a mitogenome, so HVR1 never arrives from long
records. A human mito 12S/16S query was also run (400 records). It was dropped because 390 of
those 400 already shared a 32-mer with existing rows, so it added near-duplicates and no new
coverage. These records are labelled through taxonomy (Homo sapiens gives this route, and
`assign_label` gives known_species), the same path GRCh38 takes.

Fish yield is low by construction. 2581 of the 3453 NCBI fish hits are "Actinopterygii
environmental sample". In the NCBI taxonomy, Actinopterygii is a superclass, so that lineage has
no class rank, `lineage_to_route` sends it to animal_general, and it is rejected. The ENA query
adds only 4 records after accession dedup. Mapping superclass Actinopterygii to fish would be a
change to `routing.py` and is out of scope here.

Candidates are sampled with a fixed seed from the full hit list, so a rerun on the same database
state picks the same records. ENA and NCBI mirror the same INSDC data, so accessions already
gathered by another query for the same class are excluded.

**How a sequence earns its label.**

- *Taxonomy-labelled* (animal and fish novelty): the record's taxid is resolved with the local
  NCBI taxdump, then routed by `lineage_to_route` and labelled by `assign_label`, which is the
  same path the BLAST DB records take. A record is kept only if that path independently lands on
  the query's target. For example, `possible_novelty` needs an organism name like
  "uncultured Calanoida" or "Nematoda environmental sample" (the `_UNRESOLVED_PATTERNS` rule), and
  `animal_general` needs a Metazoa lineage that is not fish and not a domestic species. The query
  only narrows the search; it never assigns the label. `build_dataset.py` re-derives route and
  label from the stored lineage on rebuild.
- *Provenance-labelled* (vectors, PhiX174): these are contaminants because of what they are, a
  lab reagent or a sequencing control, not because of their taxonomy. They are labelled
  `possible_contamination` in the `human_domestic_contamination` route, which matches the
  `lab_reagent` type in `app/novelty/contamination.py`. UniVec, which is also vectors and
  adapters, used to fall through to `known_species`. It is now labelled the same way, so the
  head is not told the same kind of sequence is two different things.
- *Not gathered:*
  - Reagent "kitome" bacteria (Ralstonia, Bradyrhizobium, ...). These genera are also real
    environmental organisms, and nothing in a single record shows that it is a contaminant.
  - Lambda phage, the Nanopore DNA CS control. There are only 7 complete genomes, each 48.5 kb.
    `chunk_long_sequence` keeps the first five 400 bp windows of each, so they would add a few
    near-identical windows.
  - MGnify. The API (`/metagenomics/api/v1/`, checked 2026-10-18) exposes studies, runs,
    analyses, assemblies and prokaryotic MAG catalogues. It has no endpoint that returns
    individual sequences with a curated organism identification. Its taxonomy for OTUs and
    contigs is its own pipeline's prediction from SILVA/PR2 matches, so labelling with it would
    train the heads on another classifier's output. The underlying reads are in ENA, and the ENA
    queries above already reach the curated INSDC records.

**Output.** Written to `synthveda-data/raw/supplementary/<source>/` (gitignored):
`<query_id>.fasta`, `<query_id>.manifest.csv` (accession, taxid, organism, marker, source,
retrieved_at, licence, route, label, label_basis, sha256, lineage), and `<query_id>.run.json`
(term, hit count, sample size, rejection reasons, bytes downloaded). `index.json` summarises all
runs. `--check-overlap` writes `overlap_report.json`, the exact-duplicate overlap of the fetched
data (after `build_dataset` chunking) with the current `processed/` splits.

**Licences.** NCBI GenBank: NCBI places no restrictions on use or redistribution; submitters may
claim IP in individual records. ENA/INSDC: free and unrestricted access under the EMBL-EBI Terms
of Use. The full text is stored per row in the manifests.

**Rate limits and identity.** NCBI requests are spaced at least 0.4 s apart (3 req/s is NCBI's
limit without a key; set `NCBI_API_KEY` to use 0.12 s). ENA requests are spaced 0.5 s apart.
Requests carry `tool=synthveda` and no email address.

```bash
cd services/worker
python -m training.fetch_supplementary --list
python -m training.fetch_supplementary                 # all queries
python -m training.fetch_supplementary --check-overlap
python -m training.build_dataset                       # picks up raw/supplementary/ (Day 7)
```
