import { tokens, pillStyle } from "./tokens";
import { DatabaseIcon } from "./icons";

const PENDING_LABEL = "Reference DB: pending configuration";

/**
 * Provenance tag -- shared component 0.2. "Reference DB: [name] v[version]
 * · Pipeline: v[X] · Matched [date]", attached to any species/taxonomic
 * call, anywhere it's displayed.
 *
 * referenceDb/referenceDbVersion are nullable. Orchestrated results carry
 * them per sequence (decision.reference_db / reference_db_version, e.g.
 * "synthveda-reference/fish" + "v2"); rows written before the orchestrator
 * do not. Rather than fabricate a DB name, a missing DB renders a clearly
 * labeled state (`missingLabel`) -- fake provenance would defeat the entire
 * point of the component.
 *
 * @param {string|null} referenceDb
 * @param {string|null} referenceDbVersion - "v2" or "2"; one "v" is shown
 * @param {string} missingLabel - text when referenceDb is null
 * @param {string|null} pipelineVersion
 * @param {string|Date|null} matchedAt
 * @param {boolean} matched - false when the DB was searched but nothing was
 *   assigned (decision.reference_db set, predicted_taxon null): the tag then
 *   reads "Searched [date] · no assignment" instead of "Matched [date]".
 * @param {"pill"|"plain"} variant - "pill" for table rows/cards (default),
 *   "plain" for centered footer placement -- matches the reference mockup's
 *   Analysis Report footer exactly (no border/background, just muted text).
 */
export default function ProvenanceTag({
  referenceDb = null,
  referenceDbVersion = null,
  pipelineVersion = null,
  matchedAt = null,
  matched = true,
  variant = "pill",
  missingLabel = PENDING_LABEL,
}) {
  const hasDb = Boolean(referenceDb);
  const dateLabel = matchedAt
    ? new Date(matchedAt).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" })
    : null;

  const version = referenceDbVersion ? String(referenceDbVersion).replace(/^v/i, "") : null;
  const label = hasDb
    ? `Reference DB: ${referenceDb}${version ? ` v${version}` : ""}${pipelineVersion ? ` · Pipeline: v${pipelineVersion}` : ""}${
        matched
          ? (dateLabel ? ` · Matched ${dateLabel}` : "")
          : `${dateLabel ? ` · Searched ${dateLabel}` : ""} · no assignment`
      }`
    : missingLabel;

  if (variant === "plain") {
    return <span style={{ fontSize: 11, color: tokens.pending }}>{label}</span>;
  }

  return (
    <span style={pillStyle("pending")} title={hasDb || missingLabel !== PENDING_LABEL ? undefined : "Reference database not yet configured on this deployment"}>
      <DatabaseIcon color={tokens.pending} />
      {label}
    </span>
  );
}
