import { useEffect, useState } from "react";
import { healthCheck } from "./api";

// The novelty flagging threshold is owned by the API (GET /health ->
// novelty_threshold), the same way the upload size limit is
// (max_upload_size_mb). The frontend never carries its own copy: if /health
// doesn't report it, callers get `null` and must say "threshold unavailable"
// rather than fall back to a guessed number.

let cached = null; // Promise<number> once a real value has been seen

function fetchNoveltyThreshold() {
  if (cached) return cached;
  const p = healthCheck()
    .then((h) => (Number.isFinite(h?.novelty_threshold) ? h.novelty_threshold : null))
    .catch(() => null);
  // Only memoise a real value -- an absent field (older API) or a failed
  // request is retried on the next mount instead of being stuck as null.
  p.then((v) => { if (v !== null) cached = p; });
  return p;
}

/** Returns { loading, threshold } where threshold is a 0-1 float or null. */
export function useNoveltyThreshold() {
  const [state, setState] = useState({ loading: true, threshold: null });
  useEffect(() => {
    let live = true;
    fetchNoveltyThreshold().then((threshold) => {
      if (live) setState({ loading: false, threshold });
    });
    return () => { live = false; };
  }, []);
  return state;
}

/** Display helper: the threshold as a whole percentage string, or null when unknown. */
export function formatThresholdPct(threshold) {
  return threshold == null ? null : `${Math.round(threshold * 100)}%`;
}
