# services/worker/training

Builds the per-route training data and fine-tunes the route heads.

| File | Role |
|------|------|
| `sources.py` | One iterator per reference source, all yielding `Record(sequence, organism_name, lineage, source, route?, label?)` |
| `routing.py` / `labeling.py` | Lineage → route, and (route, sequence, name, lineage) → label. Every source goes through these. |
| `build_dataset.py` | Walks `raw/`, routes, labels, caps, dedups, writes `processed/<route>/{train,dev,test}.csv` |
| `fetch_supplementary.py` | Fetches extra sequences for thin classes from official APIs into `raw/supplementary/` |
| `finetune.py`, `evaluate_checkpoint.py` | Training and evaluation |

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
| `ncbi_cloning_vectors` | NCBI E-utilities | taxon 29278 "vectors", complete sequences | vector | 1000–20000 | human_domestic_contamination / possible_contamination |
| `ncbi_phix174` | NCBI E-utilities | Escherichia phage phiX174, complete genomes | genome | 4000–6000 | same |

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
- *Not gathered:* reagent "kitome" bacteria (Ralstonia, Bradyrhizobium, ...), because those
  genera are also real environmental organisms and nothing in a single record shows it is a
  contaminant. Also MGnify contigs and OTUs, whose taxonomy is MGnify's own pipeline prediction,
  not a curated identification.

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
