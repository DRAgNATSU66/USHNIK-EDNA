# Taxon evaluation on held-out rows: orchestrator-1.2.0, reference v2 (t-1023-3)

Results file: `taxon_eval_2026-10-20.json`. Per-row relabel audit for the test split:
`taxon_eval_2026-10-20_relabel_audit_test.jsonl.gz`. Script: `services/worker/training/eval_taxon.py`
(phases `run` → `trace` → `leak` → `report`). Raw per-row output and logs (not in git):
`synthveda-data/logs/taxon_eval/`.

What is graded: `decision.predicted_taxon` / `decision.taxon_rank`, the taxon the orchestrator reports
after route selection and the plant genus cap. The predicted lineage is the final route's reference
assignment, cut at the reported rank.

## Test split

All 8,675 rows of `processed/<route>/test.csv` ran through the job's own stages (parser → QC → router
→ `Orchestrator.run`) in 9 seeded chunks (seed 1023). 7 rows were dropped by the parser (shorter than
10 bp), leaving **8,668 evaluated rows**. Orchestrator time was 3,062 s (353 ms per sequence). Of that,
bacteria BLAST took 2,579 s. Peak GPU allocation was 2,290 MB and peak Python RSS 1,608 MB.

Ground truth comes from tracing each row (or the record it was chunked from) back to its source
records. 4,936 rows have the QNA-020 tracer's named lineage (`reference_named`). The other rows fall
back to:
- 160: LCA of named copies from sources outside the reference plan.
- 3,085: LCA over all copies (`unresolved_name_only`: a lineage taken from records named like
  "uncultured X sp.").
- 487 (481 of them misc_unknown): traced, but no lineage at any rank, so they cannot be graded.

The QNA-020 tracer and the all-copies tracer agree on 4,857 rows and differ on 50 of the rows that
both name.

| Route | n | with truth lineage | sp / gen / fam / coarser / none (%) | Species P / R | Genus P / R | Family P / R | Species P uncapped | Leaky | Species P / Genus P, leaky excl. |
|---|---|---|---|---|---|---|---|---|---|
| fish | 591 | 591 | 65.3 / 18.6 / 10.0 / 1.9 / 4.2 | 95.5 / 64.5 | 99.1 / 87.0 | 99.8 / 94.3 | 95.5 | 0 | 95.5 / 99.1 |
| plant | 595 | 595 | 3.4 / 45.9 / 22.7 / 16.3 / 11.8 | 90.0 / 3.9 | 93.3 / 46.7 | 98.2 / 74.1 | 58.3 | 8 | 90.0 / 93.2 |
| animal_general | 992 | 992 | 40.1 / 18.4 / 18.6 / 4.2 / 18.5 | 91.3 / 48.8 | 96.9 / 65.7 | 98.3 / 79.0 | 91.3 | 0 | 91.3 / 96.9 |
| bacteria_pathogen | 4219 | 4213 | 19.0 / 28.2 / 18.1 / 22.9 / 11.9 | 86.3 / 32.1 | 93.4 / 54.4 | 95.4 / 72.5 | 85.6 | 308 | 83.7 / 92.4 |
| human_domestic_contamination | 914 | 914 | 49.7 / 1.9 / 0.7 / 0.6 / 47.2 | 89.1 / 45.2 | 98.6 / 56.1 | 99.8 / 96.3 | 89.1 | 112 | 89.9 / 98.6 |
| misc_unknown | 1357 | 876 | 11.6 / 7.7 / 4.2 / 6.3 / 70.3 | 78.4 / 13.4 | 91.7 / 54.2 | 97.3 / 68.6 | 78.4 | 16 | 76.9 / 91.6 |
| **all** | 8668 | 8181 | 25.6 / 21.6 / 13.9 / 13.9 / 25.0 | 89.1 / 34.0 | 95.2 / 58.4 | 97.2 / 77.8 | 87.1 | 444 | 88.8 / 95.0 |

How to read the table:
- **Rows:** the route is the row's *true* route. Every row is counted, including possible_novelty,
  possible_contamination and low_quality_unusable rows.
- **Precision:** correct calls ÷ calls at that rank, among rows whose truth has that rank. The metrics
  are rank-aware: a species call is also a genus call and a family call.
- **Recall:** correct calls ÷ rows whose truth has that rank.
- **Known-class rows only** (label = known_species, or unknown_needs_online_confirmation for misc), as
  species / genus / family P/R in %:
  - fish: 95.5/65.4, 99.1/88.0, 99.8/95.0
  - plant: no species calls, 92.6/45.8, 98.1/73.3
  - animal: 91.3/48.8, 97.1/73.6, 99.1/87.6
  - bacteria: 86.6/31.4, 95.1/64.8, 97.4/82.8
  - human: 98.4/74.6, 99.5/75.3, 99.7/96.9
  - misc: 78.4/24.5, 92.5/55.8, 97.2/70.1
  - all: 91.6/40.2, 96.3/67.2, 98.3/84.1

### Weak results, as measured

- **Recall is low.** Overall species recall is 34.0% and genus recall 58.4%. Most misses are "no
  call on the right route": at species, 2,118 rows had no call on the right route, 159 had a wrong
  call on the right route, 630 had no call on a wrong route (366 of them at the low-quality gate) and
  26 had a wrong call on a wrong route. Wrong route selection is a small share of the *wrong* calls.
  In 16 species-graded rows the true route was planned but lost. In 2 of those, the true route's
  reference would have been right.
- **Plant species recall is 3.9%.** This is by design: the genus cap. Without the cap, plant species
  precision would be **58.3%** (103 calls), and the species dropped by the cap were right in 42 of 83
  cases (50.6%). The cap is justified on held-out data. Across all routes, the cap fired on 106 rows;
  species precision is 89.1% with the cap (1,694 calls) and 87.1% without it (1,786 calls).
- **The human route gives no taxon for 47.2% of its rows**:
  - **107 GRCh38 genome windows:** the GRCh38 screen hits them (`human_genome.hit`), flagging
    contamination, but it sets no taxon.
  - **309 vector/adapter rows** (UniVec, cloning vectors): their held-out sequences are excluded
    from the reference, so they get no hit or no consensus.
  - **15 other rows.**

  In total, 431 of the 914 human-route rows have no taxon.

  Known-class human species recall is 74.6%. With leaky rows excluded it is 95.1%, because the GRCh38
  windows are leaky by construction.
- **misc_unknown.** 70.3% of its rows get no taxon. 357 rows stop at the low-quality gate (360 are
  labelled low_quality_unusable). 481 rows have no truth lineage at all.

### Reference v2 leakage (evaluated rows)

| Check | Rows |
|---|---|
| exact row sequence in a ref.fasta | 0 |
| exact source-record sequence in a ref.fasta | 0 |
| a ≥ 99% identity hit (any planned route) to a reference record from the same source accession | 325 (all on the final route; 200 of them at ≥ 99.9%) |
| GRCh38 window rows (the GRCh38 BLAST index is the whole genome) | 119 |
| **leaky (any of the above)** | **444** |
| upper bound: another sequence with the row's source accession is in the reference, at any identity | 1,936 |

How the leakage check was done:
- **Accession match:** accessions are compared without the version. SILVA accessions are also
  compared without their start.end coordinates, so another rRNA operon copy of the same genome
  assembly counts as the same record. This is why bacteria hold 308 of the 325 same-record rows.
- **Coverage:** all 26,184 hit reference records were found in ref.fasta and traced back to their
  source accessions.
- **Effect of excluding leaky rows:** species precision falls from 89.1 to 88.8 overall, and for
  bacteria from 86.3 to 83.7. The bacteria numbers above are inflated by about 2.6 points by
  same-genome operon copies.

## possible_novelty → known_species / likely_taxonomic_group relabels (QNA-030 test)

1,262 test rows labelled possible_novelty are reported as known_species (440) or
likely_taxonomic_group (822).

**Only 739 come from the reference rules:**
- 325 `novelty_suppressed_by_reference`
- 414 `novelty_downgraded_by_reference`

The other **523 come from the route head itself** (`head_class`): the classifier did not call them
novel in the first place.

Every one of the 1,262 source names is unresolved: 912 "uncultured", 283 "environmental sample",
61 "metagenome", 6 "unidentified". None has a named copy.

| Verdict | All | head_class | suppressed_by_reference | downgraded_by_reference |
|---|---|---|---|---|
| label_noise | 624 | 244 | 188 | 192 |
| real_disagreement | 92 | 50 | 15 | 27 |
| undetermined | 546 | 229 | 122 | 195 |
| *without SILVA taxonomy paths:* label_noise / real / undetermined | 246 / 31 / 985 | 81 / 22 / 420 | 87 / 6 / 232 | 78 / 3 / 333 |

### What the verdicts mean

- **label_noise:** the names the source carried agree with the hit. The names come from three places:
  the organism name, the NCBI lineage, and SILVA's own taxonomy path. They agreed at these ranks:
  - genus: 427
  - family: 196
  - species: 1
  - same accession: 0
- **real_disagreement:** the source names a different genus, a different family, or the same genus
  but a different species.
- **undetermined:** either the source names nothing comparable (343 rows: "uncultured bacterium",
  "Arthropoda environmental sample", "marine metagenome"), or the hit resolves only above the genus the
  source names (203 rows).

### Same specimen

- **No relabelled row has a ≥ 99% hit that shares an accession with its source record.**
- 293 rows have an assignment at ≥ 99% identity. For these, a copy of the same specimen in another
  database (with a different accession) cannot be excluded.
- 969 rows are below 99%.

### What this supports and what it does not

- **About half the relabels (624/1,262) are consistent with label noise from wording.** In these, the
  source record's own taxonomy places the sequence in the taxon the hit reports. Only the
  "uncultured / environmental" wording made the possible_novelty label.
- **Most of that agreement comes from SILVA's taxonomy path.** Without the path, only 246 rows remain
  label_noise. SILVA assigns that path to "uncultured bacterium" records by its own sequence-based
  classification, so it is **not independent** of a sequence-similarity hit.
- **Many label_noise rows are reported finer than the agreement rank.** In 246 of them, the reported
  taxon is finer than the rank at which the names agree, for example a species call on
  "uncultured Bacteroides sp.". All 188 label_noise rows under `novelty_suppressed_by_reference` are
  species calls whose species the source never named.
- **Some real_disagreement rows are taxonomy-system mismatches.** Of the 92 real disagreements, only
  31 remain when SILVA paths are left out. Examples of the mismatch: SILVA Ruminococcaceae vs NCBI
  Oscillospiraceae, and SILVA Rhizobiaceae vs NCBI Phyllobacteriaceae for *Nitratireductor*.
- **The explanation is not shown for most rows.** 546 rows are undetermined. 55 of them are species
  calls at ≥ 99% identity on sources that name nothing ("Arthropoda environmental sample" → a named
  *Hydropsyche* species).
- **Conclusion:** label noise explains at most about half of the relabelled rows. It explains at least
  about a fifth (246) on evidence independent of SILVA's classifier. The rest are either unresolvable
  from the source names or real disagreements.
