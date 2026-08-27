# SynthVeda — Build Specification (Agentic Dev Reference)

**Purpose:** Page-by-page, section-by-section build doc. Feed one section at a time to the coding agent. Each section lists: what it contains, required fields/data, and open decisions that must be locked before that section is built.

**Build order recommendation:** Shared Components → Upload Analysis → Researcher Mode (Overview → Novelty DNA → Species Correction → Comments) → Partner Report (Legislative → Industrial → Academia).

---

## 0. SHARED COMPONENTS (Build First — Reused Everywhere)

These exist once, get imported into every page below. Do not rebuild per-page.

### 0.1 eDNA Limitations Disclaimer
- Persistent banner/footer component, two variants:
  - **Technical variant** (Researcher Mode, Academia): full 4-point caveat list — Live vs Dead, Population Count, Spatial Ambiguity, Temporal Decay
  - **Plain-language variant** (Upload Analysis, Legislative, Industrial): same 4 points, simplified wording
- Must appear on: Upload Analysis overview, Researcher Mode all sub-tabs, all four Partner Report tabs (Legislative, Industrial, Academia, and — build one for — the eventual generic export)

### 0.2 Provenance Tag
- Small component: `Reference DB: [name] v[version] · Pipeline: v[X] · Matched [date]`
- Attach to: any species/taxonomic call, anywhere it's displayed (table row, card, tooltip)
- **Open decision:** which reference DB(s) will actually be used (NCBI / SILVA / BOLD / custom)? Must be answered before this component is wired to real data.

### 0.3 Detection Window Badge
- Component: `Detected — genetic trace consistent with presence ~[X]–[Y] days prior to sample collection`
- Computed from: sample timestamp + generic eDNA degradation window (needs a default range, e.g. 1–14 days, adjustable per water temp/environment if backend supports it)
- Attach to: Upload Analysis binary Detection Dashboard, Legislative Threat/Alert Panel, Researcher Mode Species Correction (per confident call)

### 0.4 Confidence/Source Citation Chip (for predictive & financial numbers)
- Any forecasted or financial figure (Industrial's Time-to-Failure, Remediation ROI) must carry a visible chip: `Modeled estimate — based on [N samples / external cost DB] · Confidence: [range or "low sample size"]`
- Prevents any number from appearing as unqualified fact

### 0.5 Negative Control Flag
- Component: shows on Upload Analysis and Researcher Mode header: `Negative control: [Included / Not included]`
- If not included: visible warning that contamination cross-check is unavailable for this run

---

## 1. UPLOAD ANALYSIS

### 1.1 Pre-Upload / New Analysis Screen
*(matches your current mockup — DNA helix visual, FASTA-JSON / mRNA-tRNA / Sugar phosphate / Peptide bonds decorative cards, drag-drop zone)*

**Required fields — LOCK THIS DECISION FIRST:**
> Current mockup labels Environmental Metadata section "**Optional** — improves classification accuracy." This conflicts with the chain-of-custody requirement (Section 2 concept, carried through every downstream Partner Report). **Decide now:** either (a) make metadata mandatory before a run can be exported/used in a Partner Report, with a soft "skip for now, required before export" pattern, or (b) formally downgrade chain-of-custody to best-effort. Recommendation: (a) — legal defensibility for Legislative/Industrial tabs depends on this data existing.

**Fields on this form:**
- Location Label
- Date / Time
- Latitude, Longitude
- Depth (m)
- Source Type
- Habitat
- Salinity (PPT)
- Temperature (°C)
- **Add (missing from current mockup):** Negative control included? (Y/N toggle)
- **Add:** Handler/collector identity, sequencer identity, uploader identity — for chain-of-custody
- Analysis Mode selector (ties to Methodology Toggle — see 1.2)
- Processing Model selector
- File upload: FASTA/FASTQ, max size shown (currently "up to 500MB" in mockup — confirm real limit against Rust backend capacity)

### 1.2 Post-Processing Overview (Executive Summary)

**Global info bar:**
- SynthVeda logo, page title
- Run file name + Run ID
- Methodology Toggle (Targeted qPCR / Metabarcoding) — set at upload, read-only here, not re-editable
- Export JSON / Export CSV
- User profile block

**Disclaimer banner** (component 0.1, plain-language variant)

**Negative Control Flag** (component 0.5)

**Top KPI row:**
- Total Sequences
- Passed QC %
- Route/Triage Richness (label explicitly as "Route," not "Species," per earlier decision)
- Contamination % (+ dominant route shown small, not headline-sized)
- eDNA Target Status: Detected/Not Detected (+ Detection Window badge, component 0.3)
- Novelty % with adjustable similarity-threshold slider (40%–97%)

**QC Summary block:**
- Total Sequences, Passed QC, Low Quality, Mean Length (bp), Mean GC Ratio
- **Add:** Pipeline Attrition summary (simplified, non-Sankey version) — e.g. "9.2M of 10M reads filtered — see Researcher Mode for full breakdown" with a link out. Full Sankey lives in Researcher Mode; this page gets a one-line pointer so non-technical users at least know attrition happened.

**Route/Triage Distribution:** bar/chart breakdown, labeled "Triage Category Distribution"

**Possible Novelty preview:** summary cards (ID, novelty %, route, recommendation, reason codes, alignment score/E-value) — full detail deferred to Novelty DNA tab

**Provenance tag** (component 0.2) — footer placement

**Loading state — LOCK THIS DECISION:**
> Does this page stream live via WebSocket as parsing completes, or only render at 100%? Pick one before building loading states. If streaming: show pipeline stage progression (QC filtering → trimming → clustering → taxonomic matching). If batch: skeleton loader + estimated time remaining.

---

## 2. RESEARCHER MODE

### 2.1 Overview Hub (Landing view)

- Top KPI cards: Active Samples, Total Novel Candidates, Average Match Confidence
- Taxa filters (Microbial, Vertebrate, etc.)
- Biodiversity Profile Chart: bar + spline combo, Y-axis normalized percentile rank (0–100), metrics = Shannon H′, Pielou's J′, Sequence Coverage, Novelty Index, Genetic Variance
  - **Fix required:** "regional baselines" referenced by the spline overlay must show its own source/date — where does baseline data come from? Display as a small citation under the chart.
- Quick Insights panel: auto-generated text summary + Export CSV
  - **Add:** make summary text clickable/linked back to the underlying filtered data (e.g. "dominant taxa: X" → jumps to Species Correction filtered on X)
- **Add — Pipeline Attrition Sankey diagram** (Three.js or equivalent): full read-tracking flow — raw reads in → dropped for low quality → flagged as chimeras → passed QC → matched to species → unmatched/novel. This is the most important addition from the gap review; build it here as the canonical full version (Upload Analysis gets only the one-line pointer).
- **Add — Negative Control Comparison view:** side-by-side or diff view of active sample vs. blank/negative control sample, auto-flagging any overlapping DNA signatures (e.g. human, dog) as contamination risk. Only renders if a negative control was marked included at upload (component 0.5).
- Provenance tag (component 0.2)

### 2.2 Novelty DNA

- Novelty Candidate List (table): Candidate ID, Sampling Site, Collection Depth
- Taxonomic Proximity Metrics **shown inline per-row**, not requiring a click: Closest Match Genus/Family, Alignment Identity %, E-value, Query Coverage
- Deep Alignment Viewer: click-through sub-panel, raw FASTA string alignment vs. closest hit
- Compute Trigger: `Cloud Confirm` button per row → deeper BLAST search
  - **Add:** compute-cost/credit indicator shown before triggering (if this is a premium-tier feature)
  - **Add:** batch/multi-select action for triaging multiple candidates at once
- Provenance tag: which DB(s) were checked before "novel" was assigned — must be explicit, not implied

### 2.3 Species Correction

- ASV/OTU Match Table: Sequence Hash/ID, Automated Taxonomic Assignment (italicized binomial), Confidence Score
- Quality flags: Green/Amber/Red (Amber/Red = <80% confidence or contaminant flag)
- Manual Override Form (per flagged row): Proposed Species Name, Submitter ID, Justification text box (supports DOI/literature links)
- Data Integrity Preview: raw JSON diff of the change, shown before Submit Correction
- Provenance tag **per row** — which DB/version this specific match came from
- Detection Window badge on confident calls
- **Add:** clarify in UI copy whether submitting a correction feeds a retraining pipeline or is audit-only — decide this on the backend first, then reflect it honestly in the submit button's confirmation text
- **Add:** conflict view — if two submitters propose different corrections for the same sequence, surface both with submitter/timestamp, don't silently overwrite

### 2.4 Comments (rename recommendation: "Field Log" or "Sample Context")

> **Resolve metadata duplication before building:** this tab currently re-captures chain-of-custody fields (name, affiliation, geospatial, methodology) that also live in Upload Analysis. Decide: Upload Analysis is the single mandatory input point, and this tab becomes read-only display + net-new qualitative fields only. Do not build two independent input forms for the same data.

**Net-new content unique to this tab (build these regardless of the above decision):**
- Field Notes & Anomalies: rich-text area (e.g. "algal bloom present," "contaminated by runoff")
- Attachment Hub: drag-drop for PDFs, field photos, literature — **add stated file type/size limits**
- **Add:** edit/version history on field notes (consistent with Species Correction's audit-trail standard — if a note is edited later, preserve the original)
- Threaded comments per sample/species call (multi-researcher collaboration)

---

## 3. PARTNER REPORT — LEGISLATIVE

**Top nav:** Partner Report > Legislative indicator

**Disclaimer banner** (component 0.1, plain-language variant) — mandatory, currently missing from all mockups

### 3.1 Biodiversity Hotspot Map
- Default region: client's operational area (e.g. Bay of Bengal)
- **Rendering fix required:** replace precise target-reticle circles with diffused heat zones / probability radii — current mockup still shows exact rings, must be redrawn
- Severity key: Red (Critical) / Yellow (High) / Green (Medium) / Blue (Low)
  - **Fix required:** "Coastal Erosion" and "Pollution Spike" are not eDNA-detectable as currently labeled. Either remove them from the alert taxonomy entirely, or reframe as inference-based (e.g. "Coastal Stabilization Risk — inferred from mangrove/seagrass indicator taxa decline") with the inference chain stated
  - **Add — Trans-boundary drift flag:** if a hotspot sits near a maritime border/EEZ, show a note: "detected near maritime boundary — origin uncertain due to current drift." Frame as spatial uncertainty, not a jurisdictional claim.
- Actions: Open Map (fullscreen), Export Region CSV
- **Fix:** severity color/label system must visually match the Alert Panel below (currently map uses colors, alert panel uses text badges only — unify)

### 3.2 Threat & Active Alert Panel
- Alert feed, sorted by severity: Invasive Species, Protected/IUCN species detections
- Detection Window badge (component 0.3) on each alert
- Modal on click: Action Directive (e.g. "Suggested action: field survey and sample removal")
  - **Add:** `Generate Alert PDF` button inside modal — recommended addition, not yet built
- **Add — Cryptographic Chain of Custody widget:** shows uploader identity, upload timestamp, file hash verification (unaltered since upload) — required for any alert that could lead to legal/regulatory action

### 3.3 Ecological Trend Graphs
- Indicator Species line graph (e.g. "+8% YTD")
- **Rename required:** "Habitat Loss" bar chart → "Habitat-Associated Taxa Decline" — plots decline of indicator-species DNA (coral, seagrass, mangrove, kelp), not physical acreage loss
- Clarify "live sample" label — confirm whether this means real-time streaming or is a placeholder tag; resolve before shipping as UI copy

### 3.4 Economic Risk & Feasibility Engine
- **Rename required:** frame as "Economic Risk & Compliance Exposure," not raw ROI/NPV — eDNA data feeds a risk multiplier, it doesn't calculate financial return directly
- Metrics: Estimated financial risk exposure (project delay costs, compliance fine risk)
- Confidence/Source Citation Chip (component 0.4) mandatory on every number here
- Actions: Run Feasibility, Export Report

---

## 4. PARTNER REPORT — INDUSTRIAL

**Disclaimer banner** — mandatory, currently missing

### 4.1 Top-Level Compliance KPIs
- Active Incidents, Avg Impact Score, Pending Audits
- **Fix required:** "Compliance Incidents" count needs traceability — each number must link back to the specific detection event(s) that triggered it, not just a bare "View" link. This is meant to function as legal-defense documentation; unauditable numbers defeat the purpose.

### 4.2 Environmental Risk Radar
- **Fix required — current mockup still shows old axes.** Rebuild with: Regulatory Fines, Permit Delays, Biodiversity Loss, Biofouling Risk, Supply Disruption. Remove "Market Volatility" (not eDNA-derivable, same category error as Emission Reduction).
- Overall Risk Indicator: plain-text readout (e.g. "Medium Overall Risk")

### 4.3 Biological Impact Metrics
- **Fix required — current mockup still shows Efficiency Gain / Emission Reduction.** Rebuild as:
  - Mitigation Success (%) — return of native species DNA post-restoration
  - Biofouling / Invasive Load (%) — DNA linked to infrastructure-damaging invasive organisms
  - Indicator Species Stability — baseline biodiversity stability metric
- Visual: donut/pie chart, matching current layout style, just with corrected metrics

### 4.4 Operational & Audit Summary
- Audit Trail: last audit status + Schedule Audit button
- Remediation Action Plan: Action / Owner / Deadline, `Open remediation plan` link
- Document Hub: direct PDF download links
- Quick Notes: checklist tied to chain-of-custody batch IDs (consistent with the single-source-of-truth metadata decision from Section 2.4)
- **Add — Predictive Threshold (Time-to-Failure):** e.g. "Current trajectory indicates biofouling will exceed regulatory limits in 45 days." **Must carry Confidence/Source Citation Chip (component 0.4)** — state whether this is a real trend model with N samples, or flag as directional-only if data is thin.
- **Add — Remediation ROI (Cost Delta):** e.g. "Estimated Mitigation Cost: $12,000 vs. Projected Regulatory Fine: $85,000." **Must cite external data source** (fine schedule reference, cost estimate basis) — do not present as a number eDNA data alone produced.

---

## 5. PARTNER REPORT — ACADEMIA

**Disclaimer banner** — lower priority than other tabs (academic audience already eDNA-literate) but include for consistency and citation defensibility

### 5.1 Statistical Validation Hub (Hero section)
- Alpha & Beta Diversity Delta: statistical divergence between sites/timeframes with p-values (e.g. "Site A: 42% higher Chao1 richness than Site B, p < 0.05")
- Rarefaction Curve chart — must visually plateau to demonstrate adequate sequencing depth
- Good's Coverage Estimator KPI card (e.g. "99.2%")
- **Add — Algorithm Parameters card** (collapsible): BLAST E-value threshold, minimum sequence length, and other pipeline parameters used — required for reproducibility, distinct from just citing the DB version

### 5.2 Species Co-occurrence Network
- Nodes = species/ASVs, radius = relative abundance
- Edges = statistical correlation (Pearson/Spearman)
  - **Fix required:** relabel edges from "Symbiosis" / "Competition" to "Positive statistical co-occurrence" / "Negative statistical co-occurrence" — correlation ≠ confirmed biological interaction, current labels overclaim causation
- Modularity KPI
- **Add — interaction/filtering pattern for scale:** with "thousands of data points," define now whether this uses abundance-threshold filtering, zoom-to-reveal clustering, or another mechanism. Do not defer this decision past initial build — an unfiltered graph at that scale is unusable.
- Render via WebGL (Three.js) for performance

### 5.3 Multi-Omics & Environmental Overlay
- Dual-axis chart: Left Y = target species DNA read count (area chart), Right Y = environmental variables (temp, pH, salinity — spline lines)
- X-axis: time or depth
- **Fix required:** soften purpose framing from "proves population crashed exactly when..." to "allows visual correlation between [X] and [Y]" — avoid causal language
- **Add:** native R² and p-values shown directly in chart tooltips, not just implied by the visual

### 5.4 Phylogenetic Diversity (PD) Tree
- Circular dendrogram, color-coded by taxonomic kingdom
- Faith's PD Index KPI card

### 5.5 Publish-Ready Export Engine
- Generate Supplementary Data Archive (ZIP: raw FASTA + curated JSON ASV tables + environmental metadata) — FAIR-compliant
- Vector export (SVG/EPS) on every chart
- Auto-Citation Generator
  - **Fix required:** must include reference DB name + exact version in the generated citation, not just SynthVeda's own software version (e.g. "...matched against SILVA v138.1, accessed [date]") — this is the actual reproducibility requirement, software version alone is insufficient

---

## 6. OPEN DECISIONS — LOCK BEFORE BUILDING (Master List)

1. Reference database(s) for species matching: NCBI / SILVA / BOLD / custom — affects components 0.2, 2.2, 2.3, 5.5
2. Upload metadata: mandatory vs. optional — current mockup says optional, conflicts with legal-defensibility requirements downstream
3. Upload Analysis: live-streaming render vs. render-at-100% — affects loading state design
4. Species Correction submissions: feed retraining pipeline, or audit-only — affects backend + submit-button UI copy
5. Predictive/financial modeling (Industrial 4.4): is there real multi-sample trend data backing Time-to-Failure and ROI figures, or are these single-point extrapolations that need softer framing?
6. Negative control: is it required for every run, or optional-but-flagged? (Spec assumes optional-but-flagged — confirm.)
7. Co-occurrence network scale-handling pattern (5.2): filtering mechanism must be chosen before build, not discovered after.

---

## 7. STAKEHOLDER REVIEW LENS (Apply to every new section going forward)

- **Customer:** does this help them decide or act, without fighting the interface?
- **Investor:** does this justify premium pricing / generate the compliance-grade outputs Partner Report promises?
- **Reviewer:** is it reproducible (DB version, pipeline params, audit trail)? Exportable in standard formats? Consistent design language as data density increases?
