import { uploadColors } from "../../pages/uploadStyles";

// Semantic tokens from the locked palette (SYNTHVEDA_MASTER_FRONTEND.md
// Section 2) that don't exist in uploadColors yet -- success/warning/danger
// weren't needed until cross-cutting components (disclaimer banner,
// confidence chip, negative-control flag) required them. Spreads
// uploadColors first so every existing hex (accentBlue, pageBg, etc.) stays
// the single source of truth -- this module only adds what's missing.
export const tokens = {
  ...uploadColors,

  accent: uploadColors.accentBlue,
  accentBg: "rgba(59,158,255,0.10)",
  accentBorder: "rgba(59,158,255,0.28)",

  success: "#5FD9A9",
  successBg: "rgba(95,217,169,0.10)",
  successBorder: "rgba(95,217,169,0.28)",

  warning: "#E0A85C",
  warningAlt: "#E0C25C",
  warningBg: "rgba(224,168,92,0.10)",
  warningBorder: "rgba(224,168,92,0.28)",

  danger: "#FF7B7B",
  dangerBg: "rgba(255,123,123,0.10)",
  dangerBorder: "rgba(255,123,123,0.28)",

  purple: "#8B7BE0",
  purpleBg: "rgba(139,123,224,0.10)",
  purpleBorder: "rgba(139,123,224,0.28)",

  pending: "#5A6C86",
  pendingBg: "rgba(90,108,134,0.10)",
  pendingBorder: "rgba(90,108,134,0.28)",
};

// Shared pill/badge shell (SynthVeda mother prompt: "fully rounded, 1px
// border, low-opacity tinted background matching the badge's semantic
// color, small letter-spaced uppercase-ish text"). tone picks the color
// triplet; every cross-cutting badge/chip component builds on this so a
// reviewer sees one consistent pill language everywhere, not five
// near-identical reimplementations.
export function pillStyle(tone = "pending", { solid = false } = {}) {
  const color = tokens[tone] ?? tokens.pending;
  const bg = tokens[`${tone}Bg`] ?? tokens.pendingBg;
  const border = tokens[`${tone}Border`] ?? tokens.pendingBorder;
  return {
    display: "inline-flex",
    alignItems: "center",
    gap: 6,
    padding: "4px 11px",
    borderRadius: 999,
    border: `1px solid ${border}`,
    background: solid ? color : bg,
    color: solid ? "#04070D" : color,
    fontSize: 11.5,
    fontWeight: 600,
    letterSpacing: "0.04em",
    lineHeight: 1.5,
    whiteSpace: "nowrap",
  };
}

// The 3px gradient tick used on section headers (uploadSlabTickStyle) and
// active nav items (navItemTickStyle) -- centralized here so new shared
// components reuse the exact same accent-line signature instead of each
// re-deriving the gradient stops.
export const gradientTickStyle = {
  width: 3,
  height: 16,
  borderRadius: 2,
  background: "linear-gradient(#5AA9FF, #1F6FE0)",
  flexShrink: 0,
};
