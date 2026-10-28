# SynthVeda — Missing Features & Gaps Checklist

Companion to `SYNTHVEDA_BUILD_SPEC.md`. This is a flat, checkable gap list — use it to track what's still missing as you build. Grouped by page. Cross-cutting items apply everywhere and should be built once as shared components.

---

## Cross-Cutting (build once, use everywhere)

- [ ] eDNA limitations disclaimer component (technical + plain-language variants) — currently absent from every page
- [ ] Provenance tag component (reference DB name + version + pipeline version) — currently absent from every page except planned for Academia's citation generator
- [ ] Detection Window / temporal decay badge — decided for Legislative only, not yet confirmed present anywhere
- [ ] Single source of truth for metadata capture — currently duplicated between Upload Analysis and Researcher Mode → Comments
- [ ] Confidence/Source Citation chip for any predictive or financial number

---

## Upload Analysis

- [ ] Decide: metadata mandatory vs. optional (current mockup says "Optional," conflicts with chain-of-custody requirement)
- [ ] Negative control included? toggle at upload
- [ ] Handler/collector/sequencer/uploader identity fields (chain-of-custody)
- [ ] Detection Window badge next to binary Detected/Not Detected status
- [ ] Provenance footer
- [ ] Decide: live-streaming render during parsing vs. render-only-at-completion
- [ ] File size / estimated processing time indicator, with cancel/retry option
- [ ] One-line pointer to full Pipeline Attrition breakdown (full version lives in Researcher Mode)
- [ ] Fix label: "Route Richness," not "Species Richness," if computed on triage buckets not true taxa
- [ ] Fix label: rename Shannon H to "Route Diversity" if computed on route-buckets, not species

## Researcher Mode — Overview Hub

- [ ] Provenance tag/DB version shown
- [ ] Source/date citation for "regional baselines" used in health-signature spline comparison
- [ ] Quick Insights auto-summary text should link back to underlying filtered data
- [ ] Pipeline Attrition Sankey diagram (full read-tracking flow: raw → dropped low quality → chimeras flagged → passed QC → matched → unmatched/novel)
- [ ] Negative Control Comparison view (diff against blank sample, auto-flag overlapping contamination signatures)

## Researcher Mode — Novelty DNA

- [ ] Inline taxonomic proximity metrics per row (not click-required)
- [ ] Reference DB(s) checked against, shown explicitly before something is labeled "novel"
- [ ] Batch/multi-select action for triaging multiple candidates
- [ ] Compute-cost/credit indicator before triggering Cloud Confirm

## Researcher Mode — Species Correction

- [ ] Provenance tag per row (DB/version for that specific match)
- [ ] Detection Window badge on confident calls
- [ ] Clarify whether corrections feed model retraining or are audit-only — reflect honestly in submit UI copy
- [ ] Conflict-resolution view for competing corrections on the same sequence (show both, don't silently overwrite)

## Researcher Mode — Comments / Field Log

- [ ] Resolve duplication with Upload Analysis metadata (pick one source of truth)
- [ ] Rename tab from "Comments" to something reflecting its actual scope (e.g. "Field Log")
- [ ] Edit/version history on field notes
- [ ] Stated file type/size limits on attachment hub

## Partner Report — Legislative

- [ ] Fix: remove or reframe "Coastal Erosion" (not eDNA-detectable as currently labeled)
- [ ] Fix: remove or reframe "Pollution Spike" similarly
- [ ] Disclaimer banner (currently missing)
- [ ] Detection Window badge on alerts
- [ ] Map rendering: replace precise target-reticle circles with diffused heat zones / probability radii
- [ ] Add "Generate Alert PDF" button inside alert modal
- [ ] Unify severity color/label system between map and alert panel
- [ ] Add Cryptographic Chain of Custody widget (uploader identity, timestamp, file hash verification)
- [ ] Add Trans-Boundary Drift indicator (framed as spatial uncertainty, not jurisdictional claim)
- [ ] Rename "Habitat Loss" → "Habitat-Associated Taxa Decline"
- [ ] Clarify "live sample" label — real-time streaming claim or placeholder tag?
- [ ] Reframe ROI/NPV metrics → "Economic Risk & Compliance Exposure"
- [ ] Confidence/Source chip on every economic risk number

## Partner Report — Industrial

- [ ] Rebuild mockup metrics: replace "Efficiency Gain" / "Emission Reduction" with "Mitigation Success" / "Biofouling-Invasive Load"
- [ ] Rebuild radar chart axes: remove "Market Volatility," add Regulatory Fines / Permit Delays / Biodiversity Loss / Biofouling Risk / Supply Disruption
- [ ] Add traceability to "Compliance Incidents" count (link each number back to its source detection event)
- [ ] Disclaimer banner (currently missing)
- [ ] Provenance/pipeline citation (lower priority here, still absent)
- [ ] Add Predictive Threshold / Time-to-Failure metric, with Confidence chip
- [ ] Add Remediation ROI (Cost Delta) metric, with external data source citation

## Partner Report — Academia

- [ ] Fix: relabel co-occurrence edges "Symbiosis"/"Competition" → "Positive/Negative statistical co-occurrence"
- [ ] Fix: soften Multi-Omics Overlay purpose language from "proves...crashed exactly when" → "correlates with"
- [ ] Add Algorithm Parameters card (E-value threshold, min sequence length, other pipeline params)
- [ ] Add native R²/p-values directly in chart tooltips
- [ ] Auto-Citation Generator must include reference DB name + exact version, not just software version
- [ ] Define interaction/filtering pattern for co-occurrence network at scale (thousands of nodes) before build
- [ ] Disclaimer banner (lower priority, still recommended for consistency)

---

## Open Decisions (Blocking — Resolve Before Building Related Sections)

- [ ] Which reference database(s): NCBI / SILVA / BOLD / custom
- [ ] Metadata mandatory vs. optional at upload
- [ ] Live-streaming vs. render-at-completion for Upload Analysis
- [ ] Species Correction: retraining feedback loop or audit-only
- [ ] Industrial predictive/financial figures: real trend-model backing or single-point extrapolation needing softer framing
- [ ] Negative control: required per run, or optional-but-flagged
- [ ] Co-occurrence network scale-handling: filtering, clustering, or another mechanism
