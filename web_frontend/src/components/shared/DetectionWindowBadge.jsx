import { tokens, pillStyle } from "./tokens";
import { ClockIcon } from "./icons";

const MS_PER_DAY = 86_400_000;

// Generic eDNA degradation window -- SYNTHVEDA_BUILD_SPEC.md 0.3 gives
// 1-14 days as the default range "adjustable per water temp/environment if
// backend supports it." The backend doesn't model water-temp-adjusted decay
// yet, so this stays a fixed default until that exists.
const DEFAULT_WINDOW_DAYS = [1, 14];

/**
 * Detection Window badge -- shared component 0.3. "Detected — genetic
 * trace consistent with presence ~X–Y days prior to sample collection."
 *
 * @param {string|Date|null} sampleTimestamp - when the sample was collected
 * @param {[number, number]} windowDays - [min, max] days pre-sample
 */
export default function DetectionWindowBadge({ sampleTimestamp = null, windowDays = DEFAULT_WINDOW_DAYS }) {
  if (!sampleTimestamp) {
    return (
      <span style={pillStyle("pending")} title="No sample timestamp on this upload">
        <ClockIcon color={tokens.pending} />
        Detection window: unavailable (no sample timestamp)
      </span>
    );
  }

  const collected = new Date(sampleTimestamp);
  const daysAgo = Math.max(0, Math.round((Date.now() - collected.getTime()) / MS_PER_DAY));
  const [minDays, maxDays] = windowDays;

  return (
    <span style={pillStyle("accent")}>
      <ClockIcon color={tokens.accentCyan} />
      Detected — trace consistent with presence ~{minDays}–{maxDays} days prior to collection
      {daysAgo > 0 && ` (sampled ${daysAgo}d ago)`}
    </span>
  );
}
