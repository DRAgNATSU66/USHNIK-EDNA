# Synth Veda — Product Requirements

Living PRD. Canonical going forward — supersedes `docs/specs/SYNTHVEDA_SPEC.md` and
`docs/specs/SYNTHVEDA_MISSING_FEATURES.md` for current product decisions; those stay as
historical/deep-dive reference. Update this file when product scope actually changes,
not on every code change (that's `flow.md`/`decisions.md`).

## What Synth Veda is

A high-performance eDNA (environmental DNA) parsing and analysis platform. Converts raw
FASTA/FASTQ sequencing files into biodiversity insight for four audiences: marine
researchers, academia, government/legislative bodies, and industrial partners (offshore
wind, fisheries, shipping).

Product promise: fast eDNA biodiversity triage in remote field conditions ("Synth Veda
Abyss Mode" — offline), followed by deeper online reanalysis when full compute and
connectivity are available. Abyss Mode is field triage, never final scientific
confirmation.

## Target users

- **Marine/field researchers** — upload sequencing runs, get triage results, correct
  model output, request full analysis.
- **Academia** — deeper researcher-mode drill-down, methodology transparency.
- **Government/legislative bodies** — compliance-grade reports, audit trail, hotspot
  maps for legislative/regulatory use.
- **Industrial partners** (offshore wind, fisheries, shipping) — plain-language partner
  reports for decision-making, not raw bioinformatics output.

## Core features (current scope)

1. **Upload / New Analysis** — methodology toggle (targeted qPCR vs. metabarcoding),
   mandatory chain-of-custody metadata (geo coordinates, depth, timestamp, temperature/
   salinity, handler/sequencer/uploader identity), FASTA/FASTQ ingestion.
2. **Routed classification pipeline** — heuristic router → 6 taxonomic routes → per-route
   fine-tuned DNABERT-2 classifier → novelty/contamination scoring. See `architecture.md`
   and `docs/ml/THEORY_README.md` for how this actually works.
3. **Review workflow** — expert/admin correction of model output; corrections feed
   monthly training batches.
4. **Reporting** — Researcher Mode (technical, full detail) and Partner Reports
   (plain-language, decision-ready).
5. **Field Log / Abyss Mode** — offline-capable field triage.

## Non-negotiable scientific integrity constraints (baked into UI, not just docs)

eDNA has hard biological limits that must be visible, not buried:

| Constraint | Meaning | Must show |
|---|---|---|
| Live vs. Dead | Can't confirm a living organism vs. DNA from a carcass/shed material | Tooltip on every abundance metric |
| Population Count | Read count = relative abundance, not exact population/age/size/health | Tooltip on read-count displays |
| Spatial Ambiguity | eDNA drifts via current/wind/runoff — indicates presence in a water/soil body, not a meter-level point | Probability radius / heat zone on maps, never a precise pin |
| Temporal Decay | Detection reflects recent activity (days to ~2 weeks pre-sample) | "Detection Window" badge from sample timestamp |

Every report must carry a "What this result does NOT show" panel using these four points,
audience-appropriately worded. This is a legal/trust requirement, not a nice-to-have —
see `docs/specs/SYNTHVEDA_SPEC.md` §1 for the full rationale.

## Known gaps (as of 2026-09-03)

- Species-level identification (`predicted_taxon`) is not implemented — output is a
  confidence *category*, not a species name. See `docs/ml/THEORY_README.md`.
- Full audit of remaining mocks/stubs/TODOs: `docs/AUDIT_MOCKS_STUBS_TODOS.md`.
- Roadmap to a polished/shippable tool: `docs/ROADMAP_TO_POLISHED_TOOL.md`.

## Source material

- `docs/specs/SYNTHVEDA_SPEC.md` — full original product/UI spec.
- `docs/specs/SYNTHVEDA_MASTER_FRONTEND.md`, `SYNTHVEDA_BUILD_SPEC.md` — frontend/build
  detail.
- `docs/specs/SYNTHVEDA_MISSING_FEATURES.md` — gap list at time of writing.
- `docs/specs/MOTHER_PROMPT.md` — original founding brief.
