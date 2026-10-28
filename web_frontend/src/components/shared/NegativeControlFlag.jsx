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

// Fallback wording, identical to the API's (services/api/app/uploads/
// context.py), used only if a result arrives without its flag message.
const FALLBACK_MESSAGE = {
  not_included: "No negative control, contamination not ruled out.",
  not_recorded: "Negative control not recorded, contamination not ruled out.",
};

// The raw `negative_control_included` value (true / false / null) mapped to
// the same three states the API's context block uses.
const FROM_BOOLEAN = new Map([
  [true, "included"],
  [false, "not_included"],
  [null, "not_recorded"],
]);

/**
 * Negative Control flag -- shared component 0.5. Renders the three states
 * of `context.negative_control` from the result API. Optional-but-flagged
 * (decisions.md 2026-10-14 Q4): both "not included" and "not recorded"
 * show a visible warning carrying the API's `no_negative_control` flag
 * message; the upload is never blocked on it.
 *
 * @param {"included"|"not_included"|"not_recorded"|boolean|null|undefined} state -
 *   the API's context state, or the raw metadata boolean (true = included,
 *   false = not included, null = not recorded). undefined = not yet known
 *   (still loading).
 * @param {string} [message] - the API flag message for the warning states
 */
export default function NegativeControlFlag({ state, message }) {
  const resolved = FROM_BOOLEAN.has(state) ? FROM_BOOLEAN.get(state) : state;

  if (resolved === "included") {
    return (
      <span style={pillStyle(tokens.success, tokens.successBg, tokens.successBorder)}>
        <span style={dotStyle(tokens.success)} />
        Negative control: Included
      </span>
    );
  }

  if (resolved === "not_included" || resolved === "not_recorded") {
    return (
      <span style={pillStyle(tokens.warningAlt, tokens.warningBg, tokens.warningBorder)}>
        <span style={dotStyle(tokens.warningAlt)} />
        {message || FALLBACK_MESSAGE[resolved]}
      </span>
    );
  }

  return (
    <span style={pillStyle(tokens.pending, tokens.pendingBg, tokens.pendingBorder)}>
      <span style={dotStyle(tokens.pending)} />
      Negative control: pending
    </span>
  );
}
