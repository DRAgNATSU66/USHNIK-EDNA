# SynthVeda — Master Frontend Implementation Document

This is the single reference document to hand to Claude Code (or any coding agent) to begin 
building the production frontend. It consolidates: the locked design token system, the new 
marine bioluminescent visual language, the shared-component mandate, the build order, and 
where to find the detailed content spec for each individual page.

Read this in full before writing any code. This document governs *how everything looks and 
is structured*; the previously-provided per-page prompts (Upload Analysis, Analysis Report, 
Novelty DNA, Species Correction, Field Log, Partner Legislative/Industrial/Academia) govern 
*what content and functionality each page contains*. Use both together — this doc first for 
system-level rules, the per-page prompt when building that specific page.

---

## 1. What already exists (context, not instructions to copy)

A set of `.dc.html` mockup files exist for every page. They are **rough visual/content 
references only** — built in a design tool, not production code. Do not port their markup, 
inline styles, or structure directly. Extract layout intent and content only. Where mockup 
content conflicts with a page's detailed content spec (already provided separately), the 
spec wins.

---

## 2. Locked Design Token System

Extracted directly from the existing mockups — this is the actual palette in use, treat it 
as fixed. Do not introduce new colors outside this system; derive variants as tints/shades 
of these tokens if something new is genuinely needed.

```
Background base:       #020409
Panel surface (L1):    #0C1526
Panel surface (L2):    #101D33
Panel surface (L3):    #17253D
Border/divider:        #14233C, #1C2E4C, #3D4A61

Primary text:          #F5F5F3
Secondary/muted text:  #B8BECB, #7A8699

Accent primary:        #3B9EFF
Accent light:          #6FBAFF, #7FD4FF, #DFF0FF
Accent deep:           #146EFF, #1A71F0, #0D57D1

Success/positive:      #5FD9A9
Warning/caution:       #E0A85C, #E0C25C
Danger/critical:       #FF7B7B
Purple accent (rare):  #8B7BE0

Typeface: 'Instrument Sans' (Google Fonts) — fallback system-ui, sans-serif
```

---

## 3. Visual Language Layer — "Bioluminescent Marine" Motif

This is a new, formalized addition on top of the existing dark-navy token system above — 
NOT a replacement for it. The goal: make SynthVeda feel unmistakably like a *marine* 
science product, not a generic dark-mode SaaS dashboard, while staying fully within the 
locked color palette in Section 2.

**Where this comes from:** deep-sea bioluminescent creature aesthetics (jellyfish, glowing 
organisms against black water) — soft internal glow, translucent layered forms, light that 
seems to emanate from within rather than sit on top of a flat surface. This is a strong 
thematic fit for a marine eDNA product and should be used deliberately, not everywhere.

### 3.1 Where to apply it (deliberately limited — this is an accent motif, not the whole UI)

- **Auth / Login screen:** the strongest candidate for a literal bioluminescent hero visual 
  — an abstract, softly-glowing organic form (jellyfish-inspired, translucent, using the 
  accent-blue token family from Section 2) as a background or side-panel visual. This is 
  the one place a more illustrative, atmospheric treatment is appropriate.
- **Upload Analysis hero moment:** the existing DNA helix visual on the upload screen can 
  carry a soft internal glow / translucent rendering treatment rather than a flat line-art 
  helix — reinforcing "living organism data" rather than "abstract science diagram."
- **Loading/processing states:** while a file is parsing, consider a subtle ambient glow 
  pulse (using the radial gradient technique already present in the mockups — see Section 
  2's existing `radial-gradient(70% 40% at 50% 0%, rgba(20,110,255,0.10)...)` pattern) — 
  this reads as "something alive is being analyzed," reinforcing the theme without adding 
  new colors.
- **Background ambient gradients** across dashboard pages generally: keep the existing 
  subtle radial glow treatment already established in the mockups — this is already 
  aligned with the bioluminescent direction, just keep it restrained (5–10% opacity, 
  corner/edge placement, never competing with data legibility).

### 3.2 Where NOT to apply it

- Data tables, KPI cards, and dense scientific views (Species Correction, Academia stats, 
  Legislative/Industrial compliance panels) should stay functional and high-legibility — 
  no glow effects competing with numbers, confidence scores, or fine print. The 
  bioluminescent motif is for atmosphere/hero moments, not for surfaces where a researcher 
  needs to read precise data quickly.
- Do not apply organic/translucent shapes to functional UI chrome (buttons, inputs, nav) — 
  those stay crisp and geometric per the existing token system.

### 3.3 Chart & data visualization style (separate from the glow motif — this is about chart 
rendering quality)

Reference inspiration: smooth, layered spline/waveform charts with soft area-fill 
gradients (rather than flat default library styling), and radial/circular gauge components 
for single-percentage metrics (e.g. Good's Coverage, confidence scores, risk indicators).

- **Line/area charts** (DNA read count over time, trend graphs, multi-omics overlay): use 
  smooth spline interpolation, not sharp straight-line segments between points. Fill areas 
  under lines with a soft vertical gradient fading from the accent color at ~15-20% opacity 
  down to transparent — this is a genuinely nicer, more premium treatment than a flat-fill 
  or unfilled line, and fits the "waveform" reference aesthetic well.
- **Radial/circular gauges** for single-value percentage metrics (novelty %, coverage %, 
  confidence %, overall risk score): use a circular progress ring rather than a plain 
  number or linear bar wherever a metric is meant to be a quick visual read — this pattern 
  appears well-suited to KPI cards across Upload Analysis, Academia's Good's Coverage, and 
  Industrial's risk indicators.
- **All chart colors must come from the Section 2 token palette** — restyle any charting 
  library's default color scheme entirely; never ship default library blue/orange/green.
- Do not adopt the multi-hue purple/pink/teal palette seen in generic dashboard inspiration — 
  stay within the established blue/success-green/warning-amber/danger-red token family from 
  Section 2, even when applying the new spline/gradient/radial-gauge *techniques*.

### 3.4 Workflow note for attaching reference images to Claude Code

If attaching visual references directly in a Claude Code prompt, only attach the 
bioluminescent jellyfish dashboard examples specifically for the Auth screen / Upload hero 
visual — and state explicitly "extract the internal-glow, translucent-layering rendering 
technique only, do not adopt this reference's layout, spacing, or unrelated color palette." 
Do not attach the generic finance/weather/event-ticketing dashboard references — those have 
no thematic relevance and risk the agent copying irrelevant layout patterns. The chart/
gauge techniques described in 3.3 are sufficiently specified in text above and don't need 
an attached image.

---

## 4. Anti-"AI Slop" Mandate

The rebuild must read as a premium, purpose-built scientific/enterprise product — not a 
generic admin-dashboard template. Concretely:

- No default browser/framework component chrome — every input, button, table, badge, 
  slider, toggle, and chart must be custom-styled to the token system.
- Real visual hierarchy via elevation (L1→L2→L3 surface layering from Section 2), spacing 
  rhythm, and restrained color accents — not walls of equally-weighted flat cards.
- Micro-interactions: hover states, focus rings, smooth transitions on sliders/toggles/tab 
  switches, loading skeletons — built in deliberately, not left as defaults.
- Data density without clutter — these are real scientific/compliance dashboards, resist 
  over-simplifying for aesthetics, but keep breathing room.
- Consistent icon set (single stroke-weight, single corner-radius style) across every page.

---

## 5. Shared Component Library (build this before any individual page)

- Sidebar navigation (Upload Analysis / Researcher Mode group [Novelty DNA, Species 
  Correction, Field Log] / Partner Report group [Academia, Legislative, Industrial], user 
  profile block, expand/collapse states)
- Top header bar pattern (logo, page title, breadcrumb, action buttons, user block)
- KPI card (supports both plain-number and radial-gauge variants per Section 3.3)
- eDNA disclaimer banner (technical variant + plain-language variant)
- Provenance footer (reference DB + version + pipeline version)
- Detection Window badge
- Confidence/Source Citation chip (for predictive/financial figures)
- Severity badge/pill (Critical/High/Medium/Low — consistent color mapping used identically 
  on every map, alert list, and radar chart across the product)
- Data table shell (sortable, filterable, with quality-flag color coding)
- Modal/drawer shell (for row detail views, corrections, alerts)
- Empty state pattern
- Chart wrapper (enforces token-based colors, spline/gradient treatment per Section 3.3)

---

## 6. Build Order

1. Shared component library (Section 5)
2. Auth / Login (apply Section 3.1 bioluminescent hero treatment here)
3. Upload Analysis (pre-upload form + post-processing overview) — see dedicated content prompt
4. Analysis Report (executive overview) — see dedicated content prompt
5. Researcher Mode → Novelty DNA — see dedicated content prompt
6. Researcher Mode → Species Correction — see dedicated content prompt
7. Researcher Mode → Field Log (Comments) — see dedicated content prompt
8. Partner Report → Legislative — see dedicated content prompt
9. Partner Report → Industrial — see dedicated content prompt
10. Partner Report → Academia — see dedicated content prompt
11. Final cross-page consistency pass (Section 7)

---

## 7. Definition of Done

A reviewer flipping between any two pages should not be able to tell they were built at 
different times — identical spacing system, component behavior, visual weight logic, and 
restrained color usage throughout. Bioluminescent/glow treatment appears only where 
specified (Section 3.1) and never interferes with data legibility on dense scientific 
views. Every chart uses the token palette and spline/gradient/radial-gauge techniques from 
Section 3.3, not library defaults. Content on every page matches its dedicated content spec, 
not the rough mockup, wherever the two conflict.
