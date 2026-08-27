# SynthVeda — Mother Prompt (Mockup → Final Production UI)

Paste this into Claude Code alongside the uploaded mockup HTML files (`.dc.html`) and the 
project's real tech stack. This is the master instruction governing how ALL pages get 
rebuilt — read this in full before touching any single page.

---

## What you're looking at

Each `.dc.html` file (Analysis Report, Upload Analysis, Novelty DNA, Species Correction, 
Field Log, Partner Legislative, Partner Industrial, Partner Academia, Auth Login) is a 
**rough mockup-quality estimate** — static inline-styled HTML built in a design tool, not 
production code. It exists purely to lock down content, layout, and rough visual direction. 
It is NOT the target code quality, framework, or architecture. Do not port these files 
as-is, do not keep inline styles, do not treat them as anything beyond a visual/content 
reference.

The real build uses [your actual stack — React/Vite/Tailwind/etc., specify components, 
state management, backend integration]. Every page must be rebuilt properly in that stack, 
using shared, reusable components — not copy-pasted markup per page.

## Extracted design tokens (already present across the mockups — treat as the locked palette)

```
Background base:      #020409  (near-black navy)
Panel/card surface:   #0C1526, #101D33, #17253D  (layered dark navy, lighter = higher elevation)
Border/divider:       #14233C, #1C2E4C, #3D4A61
Primary text:         #F5F5F3
Secondary/muted text: #B8BECB, #7A8699
Accent (primary):     #3B9EFF (links, active states, primary actions)
Accent (light):       #6FBAFF, #7FD4FF, #DFF0FF
Accent (deep):        #146EFF, #1A71F0, #0D57D1
Success/positive:     #5FD9A9
Warning/caution:      #E0A85C, #E0C25C
Danger/critical:      #FF7B7B
Purple accent (rare): #8B7BE0

Font: 'Instrument Sans' (Google Fonts), fallback system-ui/sans-serif
Radial gradient glows: subtle blue-tinted radial gradients at 5-10% opacity behind hero 
  sections (e.g. radial-gradient(70% 40% at 50% 0%, rgba(20,110,255,0.10) 0%, transparent 60%))
Pills/badges: fully rounded (border-radius: 999px), 1px border, low-opacity tinted 
  background matching the badge's semantic color, small letter-spaced uppercase-ish text
```

**Do not invent a new palette.** Every page must draw from these exact tokens. If a new 
color is genuinely needed (e.g. a distinct severity tier), derive it as a tint/shade of an 
existing token family, don't introduce an unrelated hue.

## The core mandate: eliminate "AI slop" aesthetics

The mockups are functional but visually generic in places — flat cards, default spacing 
rhythm, no real visual hierarchy beyond font-size, and componentry that looks like "a chart 
was dropped in a box." The rebuild must read as a **premium, purpose-built scientific 
enterprise product** — closer to how Linear, Vercel, or a serious fintech dashboard treats 
density and hierarchy — not a generic admin-dashboard template. Concretely:

- **No default browser/framework component chrome.** Every input, button, table, badge, 
  slider, and card must be custom-styled to the token system above — no unstyled `<select>` 
  dropdowns, no default checkbox styling, no library-default chart colors.
- **Real visual hierarchy, not just font-size steps.** Use elevation (subtle shadow/border 
  layering between `#0C1526` → `#101D33` → `#17253D`), spacing rhythm, and restrained 
  color accents to guide the eye — not walls of equally-weighted cards.
- **Micro-interactions matter.** Hover states, focus rings, smooth transitions on sliders/
  toggles/tab switches, subtle loading skeletons — these are what separate "prototype" from 
  "shipped product." Build them in, don't leave default states.
- **Data density without clutter.** These are scientific/compliance dashboards with real 
  information density (tables, multi-metric cards, charts). Resist the urge to over-
  simplify for aesthetics — but equally resist cramming without breathing room. Reference 
  the existing mockup spacing as a floor, refine upward.
- **Charts must look intentional, not library-default.** If using a charting library, 
  restyle axes, gridlines, tooltips, and series colors to match the token palette exactly — 
  do not ship default Chart.js/Recharts blue-and-orange styling.
- **Iconography must be consistent in weight and style** across every page — pick one icon 
  set/style (stroke width, corner radius) and use it everywhere, don't mix icon libraries 
  page to page.

## Consistency requirements across ALL pages

1. **Shared component library first.** Before building individual pages, establish shared 
   components: the sidebar nav, the top header bar pattern, KPI card, provenance footer, 
   eDNA disclaimer banner, severity badge/pill, data table, modal/drawer shell, empty state. 
   Every page consumes these — no page invents its own one-off version of a component 
   another page already uses.
2. **Sidebar and navigation state** (as shown in the uploaded mockups: Upload Analysis / 
   Researcher Mode → Novelty DNA, Species Correction, Field Log / Partner Report → 
   Academia, Legislative, Industrial) must be identical in structure, spacing, and behavior 
   across every page — active/inactive states, expand/collapse for Researcher Mode and 
   Partner Report groups, user profile block at the bottom.
3. **The eDNA disclaimer banner and provenance footer are shared components**, not 
   per-page reimplementations. Build once, import everywhere they're required (see the 
   content spec files for which pages require which variant).
4. **Audience-appropriate density is intentional, not inconsistent.** Researcher Mode and 
   Academia are dense/technical by design; Legislative and Industrial are executive-
   simplified by design. This is a correct content distinction, not a visual inconsistency 
   to fix — but the underlying component styling (cards, buttons, colors, spacing units) 
   must still come from the same shared system across both.
5. **Responsive behavior** should degrade gracefully — these are dashboard-dense pages, 
   prioritize usable desktop/laptop layouts first, but don't hard-break on smaller screens.

## Content and data accuracy — do not silently "fix" content while restyling

The mockups may contain outdated or since-corrected labels, metrics, or copy from earlier 
iteration rounds (for example: earlier Industrial drafts used generic ESG metrics that were 
later corrected to eDNA-specific ones; earlier Legislative drafts used precise map pins 
that were corrected to diffused heat zones). 

**When rebuilding each page, cross-reference it against the corresponding detailed content 
prompt/spec already provided for that page** (Upload Analysis, Novelty DNA, Species 
Correction, Field Log, Partner Legislative, Partner Industrial, Partner Academia each have 
their own detailed content specification already written). Where the mockup's content 
conflicts with the spec, **the spec wins** — the mockup is a visual/layout reference only, 
not a content source of truth. Flag any conflict you find rather than silently picking one.

## Process

1. Build the shared component library first (Section: "Consistency requirements," item 1).
2. Rebuild each page one at a time, in this order: Upload Analysis → Analysis Report 
   (overview) → Novelty DNA → Species Correction → Field Log → Partner Legislative → 
   Partner Industrial → Partner Academia → Auth Login.
3. For each page: reference (a) this mother prompt for visual/system rules, (b) the 
   page's own detailed content spec for what must be included, and (c) the mockup HTML 
   for rough layout/content reference only.
4. After each page is rebuilt, do a pass checking it against the shared component library 
   — confirm it isn't reinventing anything that already exists as a shared component.
5. Do a final cross-page consistency pass once all pages are built: spacing units, color 
   usage, badge styles, button styles, and typography scale should be identical across 
   every page when compared side by side.

## What "done" looks like

A reviewer flipping between any two pages in this product should not be able to tell they 
were built at different times or by different passes — same spacing system, same component 
behavior, same visual weight logic, same restraint in color usage. The product should feel 
like it was designed once, holistically, by a senior product designer — not assembled from 
several separately-styled dashboards.
