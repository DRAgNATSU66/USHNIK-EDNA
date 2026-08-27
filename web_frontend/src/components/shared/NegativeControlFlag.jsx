import { tokens } from "./tokens";

// Matches the reference mockup's negative-control badge exactly
// (frontend_zips_claude_design/_extracted_fasta_output/Analysis Report.dc.html):
// small solid dot + pill, not an icon.
function dotStyle(color) {
  return { width: 6, height: 6, borderRadius: "50%", background: color, flexShrink: 0 };
}

function pillStyle(color, bg, border) {
  return {
    display: "inline-flex",
    alignItems: "center",
    gap: 8,
    fontSize: 12,
    fontWeight: 500,
    padding: "5px 14px",
    borderRadius: 999,
    border: `1px solid ${border}`,
    background: bg,
    color,
  };
}

/**
 * Negative Control flag -- shared component 0.5. Shown on Upload Analysis /
 * Analysis Report and Researcher Mode header: "Negative control:
 * [Included / Not included]". Optional-but-flagged default (locked
 * 2026-08-15): absence renders a visible warning, not a block.
 *
 * @param {boolean|null} included - null = not yet known (e.g. job still processing)
 */
export default function NegativeControlFlag({ included = null }) {
  if (included === null) {
    return (
      <span style={pillStyle(tokens.pending, tokens.pendingBg, tokens.pendingBorder)}>
        <span style={dotStyle(tokens.pending)} />
        Negative control: pending
      </span>
    );
  }

  if (included) {
    return (
      <span style={pillStyle(tokens.success, tokens.successBg, tokens.successBorder)}>
        <span style={dotStyle(tokens.success)} />
        Negative control: Included
      </span>
    );
  }

  return (
    <span
      style={pillStyle(tokens.warningAlt, tokens.warningBg, tokens.warningBorder)}
      title="Contamination cross-check is unavailable for this run"
    >
      <span style={dotStyle(tokens.warningAlt)} />
      Negative control: Not included — contamination cross-check unavailable
    </span>
  );
}
