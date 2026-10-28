# Synth Veda — Design System

Canonical source for color/type/material tokens actually in use. The single locked
palette is `web_frontend/src/pages/uploadStyles.js` (`uploadColors`) plus
`web_frontend/src/components/shared/tokens.js` (`tokens`, semantic additions) — read
this file for a quick reference, but change color values in those two files, not here.
Deeper original rationale: `docs/specs/SYNTHVEDA_MASTER_FRONTEND.md` §2 ("the locked
palette").

## Typography

- **Font:** Instrument Sans (Google Fonts, weights 400–700, italic 400), loaded in
  `web_frontend/src/index.css`.
- No separate display/mono face currently defined — if one gets added, record why here.

## Color palette

Dark theme. Base:

| Token | Value | Use |
|---|---|---|
| `pageBg` | `#020409` | page background |
| `textPrimary` | `#F5F5F3` | primary text |
| `wordmark` | `#C7D3E6` | logo/wordmark |
| `headerMuted` / `headerName` | `#7A8699` / `#DCE6F5` | header text |
| `accentBlue` | `#3B9EFF` | primary accent (also `tokens.accent`) |
| `accentCyan` | `#7FD4FF` | secondary accent |
| `sectionBorder` / `badgeBorder` | `#15243C` / `#1C3357` | hairline borders |
| `cardBorderActive` | `#2E67B8` | active/selected card border |

Semantic (`tokens.js`, each with a matching `*Bg`/`*Border` at ~10%/28% opacity):

| Token | Value | Meaning |
|---|---|---|
| `success` | `#5FD9A9` | positive/confirmed states |
| `warning` | `#E0A85C` (alt `#E0C25C`) | caution states |
| `danger` | `#FF7B7B` | error/negative states |
| `purple` | `#8B7BE0` | (in-repo use varies — check call sites before assuming meaning) |
| `pending` | `#5A6C86` | default/neutral/unset state |

Scrollbar theming uses `#2A3B58` (thumb) / `#3B4F73` (hover) — see `index.css`, not part
of the semantic token set but should match it if the palette changes.

## Material: "Liquid Glass"

Shared visual language for every raised interactive element (buttons, pills, cards) —
defined in `web_frontend/src/styles/liquidGlass.js`:

- `liquidGlass({ top, bottom, border, highlight, innerShadow, outerShadow, blur })` —
  raised/frosted surface: gradient fill, bright top-edge specular highlight, soft inner
  bottom shadow, diffuse tinted drop shadow, `backdrop-filter: blur(...) saturate(160%)`.
- `liquidGlassRecessed({ top, bottom, border, innerHighlight, innerShadow, blur })` —
  same material, sunk-in variant for inputs/dropzones (content sits inside, not on top).
- Rule: tint per element, keep the same layering everywhere — new UI should read as part
  of the same system, not one-off styling. Elements needing `:focus`/`:hover`/
  `:-webkit-autofill` overrides must use a CSS class (e.g. `.sv-auth-input`), not inline
  styles, since inline styles beat any class selector.

## Shared components

- **Pills/badges** — `pillStyle(tone, { solid })` in `tokens.js`: fully rounded, 1px
  border, low-opacity tinted background matching the badge's semantic tone, small
  letter-spaced text. One implementation, reused everywhere — don't reimplement a pill
  inline.
- **Section accent tick** — `gradientTickStyle` (3px, `linear-gradient(#5AA9FF, #1F6FE0)`)
  used on section headers and active nav items.

## Motion

- Panel/chart entrance: fade + rise (`sv-panel-reveal` keyframes in `index.css`,
  `styles/reveal.js`). Deliberately **not** gated behind `prefers-reduced-motion` — an
  explicit product call (user wants charts to visibly "appear" on load regardless of OS
  reduced-motion setting). Don't silently add a reduced-motion guard here without
  checking that's still wanted.
- Micro-interactions otherwise follow the "premium product, not prototype" bar noted in
  `docs/specs/SYNTHVEDA_TECH_STACK.md` (originally scoped to Framer Motion; verify
  current implementation before assuming that library is what's actually wired in).
