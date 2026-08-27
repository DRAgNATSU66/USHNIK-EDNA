import { tokens, pillStyle } from "./tokens";
import { TrendIcon } from "./icons";

/**
 * Confidence / Source Citation chip -- shared component 0.4. Attaches to
 * any predictive or financial figure (Industrial's Time-to-Failure,
 * Remediation ROI, Legislative's Economic Risk numbers) so no number ever
 * appears as unqualified fact.
 *
 * @param {string} basis - e.g. "12 samples" or "external cost DB (2026 fine schedule)"
 * @param {string|null} confidence - e.g. "±15%", or null to render "low sample size"
 */
export default function ConfidenceChip({ basis, confidence = null }) {
  const confidenceLabel = confidence ?? "low sample size";
  return (
    <span style={pillStyle("warning")} title="This figure is a modeled estimate, not a direct eDNA measurement">
      <TrendIcon color={tokens.warningAlt} />
      Modeled estimate — based on {basis} · Confidence: {confidenceLabel}
    </span>
  );
}
