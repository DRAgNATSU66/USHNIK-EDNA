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
    } catch {}
    const e = new Error(detail);
    e.status = resp.status;
    throw e;
  }

  const ct = resp.headers.get("content-type") || "";
  if (ct.includes("application/json")) return resp.json();
  // Return raw Response for non-JSON (e.g., file downloads)
  return resp;
}

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------

/** Exchange a Google ID token for a Synth Veda JWT + user profile. */
export const authGoogleExchange = (id_token) =>
  request("POST", "/auth/google/exchange", { body: { id_token } });

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

export const getAnalysis = (analysis_id) =>
  request("GET", `/analysis/${analysis_id}`);

// ---------------------------------------------------------------------------
// Reports
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Reviews
// ---------------------------------------------------------------------------

export const getReviewStats = () => request("GET", "/reviews/stats");

export const getReviewQueue = (params) =>
  request("GET", "/reviews", { params });

export const getReview = (review_id) =>
  request("GET", `/reviews/${review_id}`);

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
// Models
// ---------------------------------------------------------------------------

export const getModels = () => request("GET", "/models");

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

export const syncExpedition = (expedition_id, syncData) =>
  request("POST", `/abyss/expeditions/${expedition_id}/sync`, {
    body: syncData,
  });

// ---------------------------------------------------------------------------
// Health
// ---------------------------------------------------------------------------

export const healthCheck = () => request("GET", "/health");
