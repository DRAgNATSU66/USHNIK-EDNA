import { tokens, pillStyle } from "./tokens";
import { DatabaseIcon } from "./icons";

/**
 * Provenance tag -- shared component 0.2. "Reference DB: [name] v[version]
 * · Pipeline: v[X] · Matched [date]", attached to any species/taxonomic
 * call, anywhere it's displayed.
 *
 * referenceDb/referenceDbVersion are intentionally nullable: the backend
 * does not populate a reference database name/version anywhere yet
 * (analysis_results currently only carries model_version_set: "stub_none").
 * Rather than fabricate a DB name, this renders a clearly-labeled pending
 * state -- fake provenance would defeat the entire point of the component.
 *
 * @param {string|null} referenceDb
 * @param {string|null} referenceDbVersion
 * @param {string|null} pipelineVersion
 * @param {string|Date|null} matchedAt
 * @param {"pill"|"plain"} variant - "pill" for table rows/cards (default),
 *   "plain" for centered footer placement -- matches the reference mockup's
 *   Analysis Report footer exactly (no border/background, just muted text).
 */
export default function ProvenanceTag({
  referenceDb = null,
  referenceDbVersion = null,
  pipelineVersion = null,
  matchedAt = null,
  variant = "pill",
}) {
  const hasDb = Boolean(referenceDb);
  const dateLabel = matchedAt
    ? new Date(matchedAt).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" })
    : null;

  const label = hasDb
    ? `Reference DB: ${referenceDb}${referenceDbVersion ? ` v${referenceDbVersion}` : ""}${pipelineVersion ? ` · Pipeline: v${pipelineVersion}` : ""}${dateLabel ? ` · Matched ${dateLabel}` : ""}`
    : "Reference DB: pending configuration";

  if (variant === "plain") {
    return <span style={{ fontSize: 11, color: tokens.pending }}>{label}</span>;
  }

  return (
    <span style={pillStyle("pending")} title={hasDb ? undefined : "Reference database not yet configured on this deployment"}>
      <DatabaseIcon color={tokens.pending} />
      {label}
    </span>
  );
}
