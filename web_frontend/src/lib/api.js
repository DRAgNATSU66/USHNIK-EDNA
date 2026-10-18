/**
 * Synth Veda API client.
 * All HTTP calls to the backend go through this module.
 * No hardcoded localhost — base URL comes from VITE_API_URL env var.
 */

export const API_BASE =
  (typeof import.meta !== "undefined" && import.meta.env?.VITE_API_URL) ||
  "http://127.0.0.1:8000";

function getToken() {
  try {
    return localStorage.getItem("sv_access_token");
  } catch {
    return null;
  }
}

/**
 * Core fetch wrapper. Throws ApiError on non-2xx responses.
 * @param {string} method
 * @param {string} path
 * @param {{ body?: object|FormData, params?: object }} [opts]
 */
async function request(method, path, opts = {}) {
  const { body, params } = opts;
  const tok = getToken();

  const url = new URL(`${API_BASE.replace(/\/$/, "")}${path}`);
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null) url.searchParams.set(k, String(v));
    }
  }

  const headers = { Accept: "application/json" };
  if (tok) headers["Authorization"] = `Bearer ${tok}`;
  if (body && !(body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
  }

  const resp = await fetch(url.toString(), {
    method,
    headers,
    body:
      body instanceof FormData
        ? body
        : body !== undefined
        ? JSON.stringify(body)
        : undefined,
  });

  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`;
    try {
      const err = await resp.json();
      detail = err.detail || err.message || detail;
    } catch {
      // Error body wasn't JSON -- keep the generic "HTTP {status}" detail.
    }
    const e = new Error(detail);
    e.status = resp.status;
    throw e;
  }

  const ct = resp.headers.get("content-type") || "";
  const isDownload = (resp.headers.get("content-disposition") || "").includes("attachment");
  if (ct.includes("application/json") && !isDownload) return resp.json();
  // Return raw Response for non-JSON, and for JSON marked as a file download
  // (e.g. /export/json, which is application/json but must stay a Response
  // so callers can call .blob() on it) -- content-type alone isn't enough.
  return resp;
}

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------

/** Exchange a Google OAuth 2.0 authorization code for a Synth Veda JWT + user profile. */
export const authGoogleCodeExchange = (code) =>
  request("POST", "/auth/google/code-exchange", { body: { code } });

/** Get current user profile from JWT (validates token). */
export const authMe = () => request("GET", "/auth/me");

/** Exchange a Supabase Auth session access token for a Synth Veda JWT + user profile. */
export const authSupabaseExchange = (access_token) =>
  request("POST", "/auth/supabase/exchange", { body: { access_token } });

/** Redeem an admin invite key to elevate role. */
export const authRedeemKey = (key) =>
  request("POST", "/auth/admin-key/redeem", { body: { key } });

// ---------------------------------------------------------------------------
// Uploads
// ---------------------------------------------------------------------------

/**
 * Upload a FASTA/JSON file with optional environmental metadata.
 * @param {FormData} formData - must include `file` field + optional metadata fields
 */
export const createUpload = (formData) =>
  request("POST", "/uploads", { body: formData });

export const getUpload = (upload_id) =>
  request("GET", `/uploads/${upload_id}`);

// ---------------------------------------------------------------------------
// Analysis jobs
// ---------------------------------------------------------------------------

export const createAnalysisJob = (upload_id, mode = "online_full") =>
  request("POST", "/analysis/jobs", { body: { upload_id, mode } });

export const getJob = (job_id) => request("GET", `/analysis/jobs/${job_id}`);

// No getAnalysis (GET /analysis/{id}) helper: it returns the raw stored
// result with every per-sequence row, and every page that shows an analysis
// needs the assembled report (/reports/{id} or its narrow sub-endpoints).

// ---------------------------------------------------------------------------
// Reports
// ---------------------------------------------------------------------------

/** List the current user's own analyses, most recent first (summary fields only). */
export const listReports = (limit) =>
  request("GET", "/reports", { params: { limit } });

export const getReport = (analysis_id) =>
  request("GET", `/reports/${analysis_id}`);

export const getReportSummary = (analysis_id) =>
  request("GET", `/reports/${analysis_id}/summary`);

export const getNoveltyTable = (analysis_id, min_score) =>
  request("GET", `/reports/${analysis_id}/novelty`, {
    params: { min_score },
  });

export const getContaminationWarnings = (analysis_id) =>
  request("GET", `/reports/${analysis_id}/contamination`);

/** Returns a raw Response — caller should create object URL for download. */
export const exportReportJson = (analysis_id) =>
  request("GET", `/reports/${analysis_id}/export/json`);

/** Returns a raw Response — caller should create object URL for download. */
export const exportReportCsv = (analysis_id) =>
  request("GET", `/reports/${analysis_id}/export/csv`);

// ---------------------------------------------------------------------------
// Reviews
// ---------------------------------------------------------------------------

export const getReviewStats = () => request("GET", "/reviews/stats");

export const getReviewQueue = (params) =>
  request("GET", "/reviews/queue", { params });

// No getReview (GET /reviews/{id}) helper: the queue already returns full
// review docs, triage/decision change state (which can move the review out
// of the state-filtered queue, so the page reloads the queue), and
// POST /evidence already returns the updated doc.

/** Correction history for one sequence -- conflict detection + version history. */
export const listReviewsForSequence = (analysis_id, sequence_id) =>
  request("GET", "/reviews/by-sequence", { params: { analysis_id, sequence_id } });

export const submitReview = (data) =>
  request("POST", "/reviews", { body: data });

export const triageReview = (review_id, data) =>
  request("POST", `/reviews/${review_id}/triage`, { body: data });

export const addEvidence = (review_id, data) =>
  request("POST", `/reviews/${review_id}/evidence`, { body: data });

export const makeDecision = (review_id, data) =>
  request("POST", `/reviews/${review_id}/decision`, { body: data });

export const createTrainingBatch = (data) =>
  request("POST", "/reviews/batch/create", { body: data });

export const freezeTrainingBatch = (batch_id) =>
  request("POST", `/reviews/batch/${batch_id}/freeze`, { body: {} });

// ---------------------------------------------------------------------------
// Field Log (notes + team discussion)
// ---------------------------------------------------------------------------

export const listFieldEntries = (analysis_id, kind) =>
  request("GET", "/field-log/entries", { params: { analysis_id, kind } });

export const createFieldEntry = (data) =>
  request("POST", "/field-log/entries", { body: data });

// No getFieldEntry (GET /field-log/entries/{id}) helper: the list already
// carries every entry's `edits`, and PATCH returns the updated entry.

/**
 * Edit an entry's `body` and/or `anchor_sequence_id`. The server appends
 * {editor, edited_at, changes: [{field, old, new}]} to `edits`; 409 means
 * someone else edited it first.
 */
export const updateFieldEntry = (entry_id, changes) =>
  request("PATCH", `/field-log/entries/${entry_id}`, { body: changes });

export const listFieldAttachments = (analysis_id) =>
  request("GET", "/field-log/attachments", { params: { analysis_id } });

/** PDF, JPEG or PNG; the server checks size, type (by content) and sha256. */
export const uploadFieldAttachment = (analysis_id, file, entry_id) => {
  const form = new FormData();
  form.append("analysis_id", analysis_id);
  if (entry_id) form.append("entry_id", entry_id);
  form.append("file", file);
  return request("POST", "/field-log/attachments", { body: form });
};

/** Returns a raw Response (Content-Disposition: attachment) — call .blob(). */
export const downloadFieldAttachment = (attachment_id) =>
  request("GET", `/field-log/attachments/${attachment_id}/download`);

// ---------------------------------------------------------------------------
// Models
// ---------------------------------------------------------------------------

export const getModels = () => request("GET", "/models/registry");

/**
 * Promote a registered model to production for its route (admin only, B8).
 * { dry_run: true } returns the plan (current model, metric deltas, demotions,
 * warnings) and writes nothing. The real call should pass
 * expected_current_model_id from that plan; 409 means the route changed since.
 */
export const promoteModel = (model_id, body) =>
  request("POST", `/models/${encodeURIComponent(model_id)}/promote`, { body });

/** Recent model_registered / model_promoted audit events, newest first (admin only). */
export const getModelPromotions = (limit = 10) =>
  request("GET", "/models/promotions", { params: { limit } });

// ---------------------------------------------------------------------------
// Abyss Mode
// ---------------------------------------------------------------------------

export const getExpeditions = () =>
  request("GET", "/abyss/expeditions");

export const createExpedition = (data) =>
  request("POST", "/abyss/expeditions", { body: data });

export const getExpedition = (expedition_id) =>
  request("GET", `/abyss/expeditions/${expedition_id}`);

export const activateExpedition = (expedition_id) =>
  request("POST", `/abyss/expeditions/${expedition_id}/activate`);

export const getPackManifest = (expedition_id) =>
  request("GET", `/abyss/expeditions/${expedition_id}/pack-manifest`);

export const issueLicense = (expedition_id, duration_days) =>
  request("POST", `/abyss/expeditions/${expedition_id}/license`, {
    body: { duration_days },
  });

/** Field triage. The body carries the offline license token (not a bearer token). */
export const runAbyssAnalysis = (body) =>
  request("POST", "/abyss/analyze", { body });

/** Offline expedition session token for this device (U4). */
export const createExpeditionSession = (expedition_id, device_fingerprint) =>
  request("POST", "/auth/expedition/session", {
    body: { expedition_id, device_fingerprint },
  });

export const verifyExpeditionSession = (expedition_session_token) =>
  request("POST", "/auth/expedition/verify", {
    body: { expedition_session_token },
  });

export const syncExpedition = (expedition_id, syncData) =>
  request("POST", "/abyss/sync", {
    body: { ...syncData, expedition_id },
  });

// ---------------------------------------------------------------------------
// Health
// ---------------------------------------------------------------------------

export const healthCheck = () => request("GET", "/health");
