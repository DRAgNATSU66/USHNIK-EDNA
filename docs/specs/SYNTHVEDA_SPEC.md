# SynthVeda — Product & UI Specification (Master Reference)

**Status:** Build reference doc. Consolidates all product decisions from brainstorm sessions.
**Last updated:** derived from conversation, pre-implementation.

---

## 0. What SynthVeda Is

A high-performance eDNA (environmental DNA) parsing and analysis platform. Converts raw FASTA/FASTQ sequencing files into actionable biological insight for four audiences: marine researchers, academia, government/legislative bodies, and industrial partners (offshore wind, fisheries, shipping).

**Core moat:** backend microservices (Rust) built for concurrent processing of multi-terabyte sequencing datasets — enables near-real-time executive reports from heavy bioinformatics pipelines that legacy Python pipelines can't match on speed/cost.

**Design philosophy:** move the user from raw data → validated research → monetizable decision-ready report. Overview first, drill-down second.

---

## 1. Scientific Integrity Constraints (Non-Negotiable, Baked Into UI)

eDNA has hard biological limitations. If the UI misrepresents these, the platform loses scientific and legal credibility. These must appear as persistent UI elements, not buried in docs.

| Constraint | What it means | Where it must show |
|---|---|---|
| **Live vs. Dead** | Cannot confirm a living organism is present vs. DNA from a carcass, waste, or shed material from an animal that moved on | Tooltip/info icon next to every abundance metric |
| **Population Count** | Read count = relative DNA abundance, NOT exact population, age, size, gender, or health | Tooltip on all read-count displays |
| **Spatial Ambiguity** | eDNA drifts via currents/wind/runoff — indicates presence in the water/soil body, not exact meter-level coordinates | Map views use probability radius / heat zone, never a precise pin |
| **Temporal Decay** | Detection = recent activity (days to ~2 weeks pre-sample, degradation-dependent) | "Detection Window" badge computed from sample timestamp |

**Legal/trust angle:** these disclaimers are a liability shield. If a government halts a project based on a SynthVeda detection and it's challenged, the explicit "Live vs. Dead" caveat protects platform credibility. Transparency here is a selling point to institutional buyers, not just a compliance checkbox.

**Standing UI requirement:** every report (Researcher and Partner) must carry a "What this result does NOT show" panel — consistent placement, same four points as above, audience-appropriately worded (technical for Researcher Mode, plain-language for Partner Reports).

---

## 2. Upload Analysis (Input Gateway + Generalized Overview)

Two jobs live here: (a) capturing a scientifically valid upload, and (b) rendering the general triage dashboard once processing completes. Niche/deep-dive views live elsewhere (Researcher Mode, Partner Report) — this page is the 10,000-ft summary.

### 2.1 Pre-Upload Capture

- **Methodology Toggle (mandatory, first decision point):**
  - *Targeted qPCR* — searching for one specific declared species
  - *Metabarcoding* — broad community/biodiversity sweep
  - UI must visibly change downstream based on this choice (targeted mode leans into Detected/Not Detected; metabarcoding leans into taxa breakdown)
- **Metadata & Chain-of-Custody (required fields, not optional):**
  - Geospatial coordinates
  - Sampling depth
  - Timestamp
  - Water temperature (and salinity if available)
  - Handler/collector identity, sequencer identity, uploader identity — for audit trail integrity in compliance use cases

### 2.2 Post-Processing Overview Screen

**Top-level KPI row** (non-technical, immediately validates run health):
- Total Sequences
- Passed QC / Low Quality / Invalid Chars
- Mean Length, Mean GC Ratio
- Contamination %
- Novelty % (must carry a one-line explainer: "sequences without a confident reference match" — do not let this read as "% broken")
- Route/Taxa Richness

**Naming fix (Reviewer note):** avoid "Route Richness" / "Route Distribution" as primary ecological labels — traditional biologists expect "Taxonomic Richness," "OTU/ASV Count," "Taxa Distribution." If "Route" is intentionally a coarse pre-taxonomic triage bucket (contamination / pathogen / novel / plant / animal_general), keep it but label it explicitly as a triage layer, e.g. "Triage Category," not as a stand-in for species diversity.

**Diversity metric labeling:** if Shannon H (or similar) is computed on coarse route-buckets rather than actual species/OTUs, label it "Route Diversity," not "Shannon H" unqualified — true Shannon H belongs in the species-level deep dive (Researcher Mode), computed on actual taxa, not 5 broad categories.

**Detection Dashboard (binary):** for high-priority/target species — a clear **Detected / Not Detected** state. Critical for qPCR mode and for non-technical stakeholders (port authority doesn't want Shannon H, wants yes/no).

**Route/Triage Distribution panel:** bar breakdown across categories (e.g. human_domestic_contamination, misc_unknown, bacteria_pathogen, plant, animal_general) with counts + %.

**Dominant Route/flag placement caution:** leading with an alarming category name (e.g. "human_domestic_contamination") as a headline stat is fine in Researcher Mode, risky if the same layout feeds Partner Report — legislative/industrial viewers may misread it without context. Partner Report needs its own framing layer.

**Possible Novelty preview section:** surfaced here as a summary card list (full detail lives in Researcher Mode → Novelty DNA). Each item needs, at minimum:
- Sequence ID
- Novelty % / confidence tier
- Route/category
- Recommendation (e.g. `preserve_sample`, `cloud confirm needed`)
- Reason codes (already strong — keep this, it's real explainability)
- **Add:** alignment score / E-value next to the recommendation so a researcher can judge *why* it's flagged novel at a glance, not just that it is

**Mandatory disclaimer banner:** results are preliminary; novelty/contamination flags require expert confirmation; not a taxonomic authority. (Already designed — keep as-is, it's correctly placed.)

**Export:** JSON export button — non-negotiable, keep visible top-of-page.

### 2.3 Loading / Processing States

For large files (multi-GB/TB), the dashboard cannot populate instantly.
- Show pipeline stage progression: QC filtering → trimming → OTU/ASV clustering → taxonomic matching
- Use skeleton loaders or stream metrics incrementally (WebSockets) as the parser completes stages, rather than a blank spinner
- Decide explicitly: does this page update live as parsing streams in, or only render once the pipeline hits 100%? (Open decision — pick one and design loading state accordingly.)

### 2.4 Accessibility Note (Reviewer flag)

Deep purple text/progress bars (e.g. `human_domestic_contamination` KPI, purple bars) on dark navy background risk failing contrast standards — a real problem for field laptops with screen glare. Audit contrast ratios before shipping.

---

## 3. Researcher Mode (Deep Dive — built for the Marine Ecologist)

Trades executive summary for granular, interactive bioinformatics data. This is where trust is won or lost with the scientific user.

### 3.1 Novelty DNA ("Dark Taxa")

- Isolates high-quality sequences that pass QC but have no confident match in reference databases (NCBI, SILVA, BOLD, etc.)
- Each entry shows: closest known relative + % identity (e.g. "97% match to nothing in DB, closest is Genus X at 78%")
- Confidence/alignment scoring: E-values or alignment percentages, not just a novelty % — researchers need to see *why*
- Tagging system: `cloud confirm needed`, `preserve_sample`, etc. — keep, it's a good pattern
- Action: flag/save as "candidate novel taxa" for later curation — a real research workflow (biologists build custom reference libraries this way)

### 3.2 Species Correction (Taxonomic Composition)

- **ASV/OTU Table:** grid of all identified species/taxa ranked by read abundance — this is the core taxonomic inventory deliverable, must exist and must be prominent
- **Per-entry fields:** taxonomic rank (species/genus/family), confidence %, sequence identity match %, read count → relative abundance
- **Expert validation / human-in-the-loop:**
  - Researcher can manually verify, override, or reject an auto-generated taxonomic call
  - Low-confidence or ambiguous matches flagged distinctly from confident calls
  - **Corrections must feed back into the model** — this is the platform's best training signal; if it's write-only and doesn't loop back into retraining/reference refinement, that's wasted value
  - Version history: who corrected what, when — required for scientific reproducibility and audit trail
- **Provenance requirement (Reviewer-critical):** every result must state which reference database + version was used (SILVA vX, NCBI snapshot date, etc.) and which pipeline/model version ran. Without this, results are not reproducible and won't survive peer review.

### 3.3 Comments / Quality Control

- Threaded comments per sample or per species call — multi-researcher collaboration layer
- QC transparency dashboard: exact % of data filtered out and why (low quality, known contamination — human/domestic pet/livestock DNA false positives specifically called out)
- Sequence filtering visualization (funnel: raw reads → passed QC → contamination-flagged → final usable set)

### 3.4 Cross-Study / Cross-Cruise Comparability (Reviewer requirement)

- Platform should normalize and compare data from multiple sampling events/cruises/methodologies
- Detect and surface analytical biases (e.g. differing sequencing platforms between batches) so cross-study comparisons remain statistically valid
- This is flagged as a "major technical hurdle" — treat as a real backlog item, not a v1 nice-to-have, but document the intent now

### 3.5 Missing From Current Nav (Add These)

- **Comparison/trend view** across samples, sites, or time — single-upload analysis alone won't bring users back; longitudinal tracking will
- **Map view** — eDNA is inherently spatial; GIS-taggable results should plug into existing marine monitoring systems, not sit in a silo. Use probability-radius/heat-zone rendering per the spatial ambiguity constraint (Section 1), never precise pins.

---

## 4. Partner Report (Output & Monetization Layer)

Translates Researcher Mode's complexity into automated, exportable, audience-specific deliverables. This is the highest-leverage commercial surface — each audience needs genuinely different framing, not the same data relabeled.

### 4.1 Academia

- **Diversity metrics, properly defined:**
  - Alpha diversity — species richness within a single sample
  - Beta diversity — variance in composition between different sites
  - Gamma diversity — total diversity across all sampling sites in a project
  - Phylogenetic/evolutionary diversity trees
- **Export-ready data:** one-click CSV/JSON/BIOM-style export so academics can run their own downstream stats in R/Python, or port into standard biodiversity platforms (e.g. OBIS)
- **Citability:** methods used, reference DB + version, stats — formatted so it can be referenced in a paper

### 4.2 Legislative (Government & Policy)

- **Executive framing, not data tables** — policymakers don't read ASV tables
- **Invasive Species Alerts:** automatic red-flag if invasive/pest DNA detected at a port or marine protected area
- **Thermal Risk Mapping:** cross-reference detected species' known thermal tolerance limits against current sea surface temperature to model climate-driven range shift risk
- **IUCN Red List tracking:** flag threatened/endangered species detections explicitly
- **Detection Window badge:** surface the temporal decay caveat (Section 1) directly — "organism present within 7–14 days prior to collection" style framing
- **Plain-language "what this does NOT show" panel** — mandatory here specifically, since this audience is most likely to over-interpret results

### 4.3 Industrial (Offshore Wind, Fisheries, Shipping)

- **Automated Environmental Impact Assessment (EIA):** standardized, export-ready PDF confirming baseline biodiversity and absence/presence of protected/IUCN Red List species prior to construction/dredging
- Framing: compliance-ready document a company can hand directly to a regulator

---

## 5. Data & Provenance Requirements (Cross-Cutting, Applies Everywhere)

Every taxonomic/species-level result, regardless of which section displays it, must carry:

- Reference database name + version used for matching (SILVA / NCBI / BOLD / custom)
- Pipeline/model version that produced the call
- Confidence %, sequence identity %, read count
- Clear separation of confident calls vs. "unknown, closest match X at Y% identity" — never force a bad classification, especially given patchy marine species coverage in public reference DBs
- Geospatial tag (for downstream GIS/map plugging)

**Open question to resolve before deep build:** which reference database(s) will Species Correction actually ping against (NCBI, SILVA, BOLD, custom-curated)? This affects schema, novelty-threshold defaults, and citation formatting across every downstream report.

---

## 6. Open Implementation Decisions (Not Yet Settled — Flag Before Building)

1. Does the Upload Analysis overview update live/streaming as a large file parses, or render only at 100% completion?
2. Is "Route" classification a permanent triage layer (contamination/pathogen/novel/plant/animal_general) sitting *alongside* full species ID, or a temporary placeholder for it? Confirm this doesn't get conflated in Partner Report exports.
3. Primary reference database(s) for Species Correction matching — decide before building schema.
4. Does correction feedback (Section 3.2) feed an active retraining loop, or is it stored as audit-only for now? Affects backend design significantly.
5. Cross-study normalization (Section 3.4) — v1 scope or backlog?

---

## 7. Stakeholder Lens Summary (For Ongoing Design Review)

Use these three lenses on every future screen/section before it's considered done:

- **Customer (Researcher/Ecologist/Policymaker):** Does this actually help them decide or act? Can they override false positives without fighting the UI? Do binary Detected/Not Detected views exist where the audience needs speed over depth?
- **Investor:** Does this module justify premium pricing? Does it generate the high-value compliance/EIA outputs that Partner Report promises? Does the backend (Rust microservices) actually support the real-time claims the UI is making?
- **Reviewer:** Is it reproducible (DB version, pipeline version, audit trail)? Is data exportable in standard formats? Is the design language consistent as data density increases from overview → deep dive? Does contrast/accessibility hold up?
