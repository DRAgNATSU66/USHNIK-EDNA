import { useState } from "react";
import { tokens } from "./tokens";
import { WarningTriangleIcon, ChevronIcon } from "./icons";

// The four non-negotiable eDNA scientific-integrity constraints
// (SYNTHVEDA_SPEC.md Section 1), combined into one flowing paragraph --
// wording matches the "Interpretation notice" banner from the reference
// mockup (frontend_zips_claude_design/_extracted_fasta_output/
// Analysis Report.dc.html), collapsed by default per direct design
// feedback (always-expanded read as too heavy on the page). "technical"
// is a more precise phrasing for Researcher Mode / Academia; "plain" is
// the mockup's exact wording.
const COPY = {
  plain:
    "Results are preliminary and require expert confirmation. Read counts show relative abundance — not exact population, age, size, or live/dead status. Detections indicate recent presence (roughly 1–14 days before collection) and are subject to DNA degradation. Spatial results reflect the water body sampled, not exact organism coordinates — eDNA drifts with currents.",
  technical:
    "Results are preliminary and require expert confirmation before use in publication. Read count reflects relative DNA abundance, not exact population size, age, size, gender, health, or live/dead status. Detection reflects recent activity only — typically 1–14 days pre-sample, degradation-dependent. Spatial results indicate presence within the sampled water/soil body, not exact coordinates — eDNA disperses via currents, wind, and runoff.",
};

function wrapStyle(open) {
  return {
    borderRadius: 6,
    border: `1px solid ${open ? tokens.warningAlt : tokens.warningBorder}`,
    background: `linear-gradient(180deg, ${tokens.warningBg}, rgba(224,168,92,0.03))`,
    overflow: "hidden",
    transition: "border-color .15s ease",
  };
}

const headRowStyle = {
  display: "flex",
  alignItems: "center",
  gap: 10,
  padding: "12px 18px",
  cursor: "pointer",
  userSelect: "none",
};

const textStyle = {
  margin: "0 18px 14px 42px",
  fontSize: 12.5,
  lineHeight: 1.65,
  color: "#C8B79A",
};

/**
 * eDNA limitations disclaimer -- shared component 0.1. Collapsed by
 * default: icon + lead-in only, click to expand the full caveat text.
 * @param {"technical"|"plain"} variant -- ignored when `children` is passed
 * @param {boolean} defaultOpen
 * @param {string} title -- lead-in text next to the warning icon
 * @param {import("react").ReactNode} [children] -- custom body content,
 *   for callers whose caveat text doesn't fit the two built-in variants
 *   (Partner Report pages each have their own domain-specific wording).
 *   Falls back to COPY[variant] when omitted, so every existing call site
 *   keeps working unchanged.
 */
export default function DisclaimerBanner({ variant = "plain", defaultOpen = false, title = "Interpretation notice", children }) {
  const [open, setOpen] = useState(defaultOpen);
  const body = children ?? COPY[variant];

  return (
    <div style={wrapStyle(open)}>
      <div style={headRowStyle} onClick={() => setOpen((o) => !o)}>
        <WarningTriangleIcon color={tokens.warningAlt} />
        <span style={{ fontSize: 12.5, fontWeight: 600, color: tokens.warningAlt, flex: 1 }}>{title}</span>
        <ChevronIcon color={tokens.warningAlt} open={open} />
      </div>
      {open && <p style={textStyle}>{body}</p>}
    </div>
  );
}
