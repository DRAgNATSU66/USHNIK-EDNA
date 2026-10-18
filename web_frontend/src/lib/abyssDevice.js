/**
 * Abyss Mode field-device storage and FASTA parsing.
 *
 * Abyss runs on a device that goes offline. What the device must keep between
 * sessions lives here, in localStorage, per expedition:
 *   - license: the offline license token /abyss/analyze requires
 *   - session: the /auth/expedition/session token and its /verify result
 *   - pending: analyses run on this device and not yet synced
 *   - logs:    device events, sent as local_logs on sync
 *   - lastSync: the server's response to the last successful sync
 *
 * None of these tokens authenticate API calls (the API rejects them as bearer
 * tokens); they only unlock offline analysis.
 */

const KEY = "sv_abyss_device_v1";
export const MAX_SEQUENCES = 500; // server cap per /abyss/analyze call

function load() {
  try {
    const raw = localStorage.getItem(KEY);
    const parsed = raw ? JSON.parse(raw) : null;
    if (parsed && typeof parsed === "object") return parsed;
  } catch {
    // Unreadable or blocked storage: start empty (nothing persisted).
  }
  return { expeditions: {} };
}

function save(state) {
  try {
    localStorage.setItem(KEY, JSON.stringify(state));
    return true;
  } catch {
    return false;
  }
}

function newDeviceId() {
  const rnd =
    typeof crypto !== "undefined" && crypto.randomUUID
      ? crypto.randomUUID().replace(/-/g, "").slice(0, 16)
      : Math.random().toString(16).slice(2, 18);
  return `dev_${rnd}`;
}

/** Stable id for this browser, used as device_id and device_fingerprint. */
export function getDeviceId() {
  const state = load();
  if (!state.device_id) {
    state.device_id = newDeviceId();
    save(state);
  }
  return state.device_id;
}

const EMPTY = { license: null, session: null, pending: [], logs: [], lastSync: null };

export function readExpedition(expeditionId) {
  const state = load();
  return { ...EMPTY, ...(state.expeditions?.[expeditionId] || {}) };
}

/** Apply `fn(record) -> record` to one expedition's record and persist it. */
export function updateExpedition(expeditionId, fn) {
  const state = load();
  state.expeditions = state.expeditions || {};
  const next = fn({ ...EMPTY, ...(state.expeditions[expeditionId] || {}) });
  state.expeditions[expeditionId] = next;
  if (!save(state)) {
    throw new Error("This browser blocked local storage, so nothing can be kept on the device.");
  }
  return next;
}

export function deviceLog(event, extra = {}) {
  return { event, at: new Date().toISOString(), device_id: getDeviceId(), ...extra };
}

/**
 * Parse FASTA text into /abyss/analyze sequence inputs.
 * Returns { sequences, errors }. Text without any ">" header is read as one
 * unnamed sequence. Whitespace inside sequences is removed.
 */
export function parseFasta(text) {
  const errors = [];
  const sequences = [];
  const src = (text || "").replace(/\r/g, "");
  if (!src.trim()) return { sequences, errors: ["Paste FASTA or choose a file first."] };

  if (!src.includes(">")) {
    const seq = src.replace(/\s+/g, "");
    sequences.push({ sequence_id: "seq_1", sequence: seq });
    return { sequences, errors };
  }

  let current = null;
  const ids = new Set();
  src.split("\n").forEach((line, i) => {
    const t = line.trim();
    if (!t) return;
    if (t.startsWith(">")) {
      const header = t.slice(1).trim();
      const [id, ...rest] = header.split(/\s+/);
      let seqId = id || `seq_${sequences.length + 1}`;
      if (ids.has(seqId)) seqId = `${seqId}_${sequences.length + 1}`;
      ids.add(seqId);
      current = { sequence_id: seqId, sequence: "" };
      if (rest.length) current.description = rest.join(" ");
      sequences.push(current);
    } else if (!current) {
      errors.push(`Line ${i + 1}: sequence data before the first ">" header.`);
    } else {
      current.sequence += t.replace(/\s+/g, "");
    }
  });

  sequences.forEach((s) => {
    if (!s.sequence) errors.push(`${s.sequence_id}: empty sequence.`);
  });
  if (sequences.length > MAX_SEQUENCES) {
    errors.push(`${sequences.length} sequences; one triage run takes at most ${MAX_SEQUENCES}.`);
  }
  return { sequences: errors.length ? [] : sequences, errors };
}

/** AbyssAnalysisResult -> OfflineSyncedAnalysis (the /abyss/sync body item). */
export function toSyncedAnalysis(result) {
  return {
    abyss_analysis_id: result.analysis_id,
    sequences_analyzed: result.sequences_analyzed,
    possible_novelty_count: result.possible_novelty_count,
    contamination_flag_count: result.contamination_flag_count,
    analyzed_at: result.analyzed_at,
    device_id: result.device_id,
    raw_results: result.results || [],
    router: result.router || null,
  };
}
