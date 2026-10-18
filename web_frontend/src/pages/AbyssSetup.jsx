import React, { useEffect, useState, useCallback } from "react";
import SidebarMenu from "../components/sidebar/SidebarMenu";
import { tokens } from "../components/shared/tokens";
import { useAuth } from "../contexts/AuthContext";
import {
  getExpeditions, getExpedition, createExpedition, activateExpedition,
  getPackManifest, issueLicense, createExpeditionSession, verifyExpeditionSession,
  runAbyssAnalysis, syncExpedition,
} from "../lib/api";
import {
  readExpedition, updateExpedition, getDeviceId, deviceLog, parseFasta, toSyncedAnalysis,
} from "../lib/abyssDevice";
import whaleArt from "../assets/abyss-whale.png";

const pageStyle = {
  position: "relative",
  background: tokens.pageBg,
  minHeight: "100vh",
  color: tokens.textPrimary,
  fontFamily: "'Instrument Sans', system-ui, sans-serif",
};

const ambientGlow = {
  position: "fixed",
  inset: 0,
  pointerEvents: "none",
  background: "radial-gradient(70% 40% at 55% 0%, rgba(20,110,255,0.10) 0%, rgba(2,6,15,0) 60%)",
};

// Backgrounds here run noticeably more opaque than the panelStyle this was
// copied from elsewhere in the app -- this is the one page with a large
// decorative image sitting behind the whole layout, so cards need to read
// as solid enough to stay legible over it rather than the usual light wash.
const panelStyle = {
  display: "flex",
  flexDirection: "column",
  gap: 16,
  padding: "18px 22px",
  borderRadius: 9,
  border: "1px solid rgba(140,170,230,0.14)",
  background: "linear-gradient(180deg, rgba(140,170,230,0.08) 0%, rgba(4,7,12,0.94) 100%)",
  boxShadow: "inset 0 1px 0 rgba(255,255,255,0.10), 0 14px 34px rgba(0,0,0,0.4)",
};

// Left-border accent variant -- same language as the Legislative report's
// alert cards (severity color as a left stripe rather than a full-card
// wash), reused here for expedition status.
function accentPanelStyle(color) {
  return { ...panelStyle, borderLeft: `3px solid ${color}` };
}

const fieldStyle = {
  padding: "11px 14px",
  borderRadius: 6,
  border: `1px solid ${tokens.sectionBorder}`,
  background: "#080F1C",
  fontFamily: "inherit",
  fontSize: 13,
  color: tokens.textPrimary,
  outline: "none",
  width: "100%",
  boxSizing: "border-box",
};

const labelStyle = { display: "block", marginBottom: 5, fontSize: 10.5, letterSpacing: "0.08em", color: tokens.labelText, fontWeight: 600 };

// Plain colored text instead of a pill badge -- per direct feedback to
// de-pill status tags app-wide, same color/weight the pill used to carry.
function plainTagStyle(tone = "pending") {
  return { color: tokens[tone] ?? tokens.pending, fontSize: 11.5, fontWeight: 600, letterSpacing: "0.04em" };
}

// Matches SpeciesCorrection.jsx's SolidButton -- the shared gradient
// button language for this tier of page (Partner Report pages use
// liquidGlass() instead; that recipe is specific to those three pages).
function SolidButton({ children, onClick, disabled, tone = "accent" }) {
  const bg =
    tone === "danger"
      ? "linear-gradient(180deg, #E06A4F 0%, #C24A32 100%)"
      : tone === "purple"
      ? `linear-gradient(180deg, ${tokens.purple} 0%, #6C5CC2 100%)`
      : "linear-gradient(180deg, #459AF5 0%, #1A71F0 48%, #0D57D1 100%)";
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      style={{
        padding: "9px 18px",
        borderRadius: 10,
        border: "1px solid rgba(160,205,255,0.5)",
        background: disabled ? "linear-gradient(180deg, #2A3B58 0%, #1C2A42 100%)" : bg,
        boxShadow: disabled ? "none" : "inset 0 1.5px 0 rgba(255,255,255,0.4), 0 8px 24px rgba(20,110,255,0.28)",
        color: disabled ? "#7A8699" : "#FFFFFF",
        fontFamily: "inherit",
        fontSize: 12.5,
        fontWeight: 600,
        cursor: disabled ? "not-allowed" : "pointer",
      }}
    >
      {children}
    </button>
  );
}

function GhostButton({ children, onClick }) {
  return (
    <button
      onClick={onClick}
      style={{
        padding: "9px 16px",
        borderRadius: 10,
        border: `1px solid ${tokens.sectionBorder}`,
        background: "#080F1C",
        color: tokens.wordmark,
        fontFamily: "inherit",
        fontSize: 12.5,
        fontWeight: 500,
        cursor: "pointer",
      }}
    >
      {children}
    </button>
  );
}

const STATUS_TONE = {
  pre_departure: "accent",
  active: "success",
  synced: "purple",
  archived: "pending",
};

const boxStyle = {
  padding: "12px 14px",
  borderRadius: 6,
  border: `1px solid ${tokens.sectionBorder}`,
  background: "rgba(8,14,26,0.5)",
  fontSize: 12,
  display: "flex",
  flexDirection: "column",
  gap: 6,
};

const stepTitleStyle = { fontSize: 11.5, fontWeight: 600, letterSpacing: "0.06em", color: tokens.accentCyan };

const fmtDate = (v) => (v ? new Date(v).toLocaleString() : "—");

function ExpeditionCard({ exp, onUpdated }) {
  const id = exp.expedition_id;
  const [manifest, setManifest] = useState(null);
  const [issuedLicense, setIssuedLicense] = useState(null);
  const [duration, setDuration] = useState(14);
  const [expanded, setExpanded] = useState(false);
  const [activating, setActivating] = useState(false);
  const [issuingLicense, setIssuingLicense] = useState(false);
  const [loadingManifest, setLoadingManifest] = useState(false);
  const [err, setErr] = useState("");

  // What this browser holds for the expedition (lib/abyssDevice.js). Kept
  // apart from sv_access_token: these offline credentials are rejected by
  // the API as bearer tokens (auth/deps.py) and must never be sent as one.
  const [device, setDevice] = useState(() => readExpedition(id));
  const [sessionBusy, setSessionBusy] = useState(false);
  const [sessionErr, setSessionErr] = useState("");
  const [fasta, setFasta] = useState("");
  const [triageBusy, setTriageBusy] = useState(false);
  const [triageErr, setTriageErr] = useState("");
  const [lastTriage, setLastTriage] = useState(null);
  const [syncBusy, setSyncBusy] = useState(false);
  const [syncErr, setSyncErr] = useState("");
  const [syncWarn, setSyncWarn] = useState("");

  const store = (fn) => setDevice(updateExpedition(id, fn));

  // After an action changes this one expedition, re-read just it
  // (GET /abyss/expeditions/{id}) instead of reloading the whole list.
  const refreshThis = async () => {
    onUpdated(await getExpedition(id));
  };

  const handleActivate = async () => {
    setActivating(true);
    setErr("");
    try {
      await activateExpedition(id);
      store((r) => ({ ...r, logs: [...r.logs, deviceLog("expedition_activated")] }));
      await refreshThis();
    } catch (e) { setErr(e.message); }
    finally { setActivating(false); }
  };

  const handleManifest = async () => {
    setLoadingManifest(true);
    setErr("");
    try {
      const m = await getPackManifest(id);
      setManifest(m);
    } catch (e) { setErr(e.message); }
    finally { setLoadingManifest(false); }
  };

  const handleIssueLicense = async () => {
    setIssuingLicense(true);
    setErr("");
    try {
      const l = await issueLicense(id, duration);
      setIssuedLicense(l);
      // /abyss/analyze needs this token in its body, so the device keeps it.
      store((r) => ({
        ...r,
        license: { token: l.offline_license_token, expires_at: l.expires_at, duration_days: l.duration_days },
        logs: [...r.logs, deviceLog("offline_license_stored", { expires_at: l.expires_at })],
      }));
      // Issuing sets offline_license_issued / offline_license_expires_at
      // on the expedition record.
      await refreshThis();
    } catch (e) { setErr(e.message); }
    finally { setIssuingLicense(false); }
  };

  // POST /auth/expedition/session, then POST /auth/expedition/verify on the
  // returned token; only a token the server verified is kept on the device.
  const handleCreateSession = async () => {
    setSessionBusy(true);
    setSessionErr("");
    try {
      const created = await createExpeditionSession(id, getDeviceId());
      const verified = await verifyExpeditionSession(created.expedition_session_token);
      store((r) => ({
        ...r,
        session: {
          token: created.expedition_session_token,
          expires_in_days: created.expires_in_days,
          verified,
          verified_at: new Date().toISOString(),
        },
        logs: [...r.logs, deviceLog("expedition_session_created", { expires_at: verified.expires_at })],
      }));
    } catch (e) { setSessionErr(e.message); }
    finally { setSessionBusy(false); }
  };

  const handleVerifySession = async () => {
    if (!device.session?.token) return;
    setSessionBusy(true);
    setSessionErr("");
    try {
      const verified = await verifyExpeditionSession(device.session.token);
      store((r) => ({ ...r, session: { ...r.session, verified, verified_at: new Date().toISOString(), invalid: null } }));
    } catch (e) {
      setSessionErr(e.message);
      if (e.status === 401) {
        store((r) => ({ ...r, session: { ...r.session, verified: null, invalid: e.message } }));
      }
    } finally { setSessionBusy(false); }
  };

  const handleFastaFile = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try { setFasta(await file.text()); } catch (ex) { setTriageErr(`Could not read ${file.name}: ${ex.message}`); }
    e.target.value = "";
  };

  const handleTriage = async () => {
    setTriageErr("");
    const { sequences, errors } = parseFasta(fasta);
    if (errors.length) { setTriageErr(errors.join(" ")); return; }
    if (!device.license?.token) { setTriageErr("No offline license on this device."); return; }
    setTriageBusy(true);
    try {
      const result = await runAbyssAnalysis({
        expedition_id: id,
        offline_license_token: device.license.token,
        sequences,
        device_id: getDeviceId(),
        local_timestamp: new Date().toISOString(),
      });
      // The device id the request carried is what sync records.
      const synced = toSyncedAnalysis({ ...result, device_id: getDeviceId() });
      store((r) => ({
        ...r,
        pending: [...r.pending, synced],
        logs: [...r.logs, deviceLog("abyss_analysis_run", { abyss_analysis_id: result.analysis_id })],
      }));
      setLastTriage(result);
      setFasta("");
    } catch (e) { setTriageErr(e.message); }
    finally { setTriageBusy(false); }
  };

  // POST /abyss/sync with expedition_id in the body (F3). Only what was sent
  // and acknowledged leaves the device; anything recorded while the request
  // was in flight stays pending for the next sync.
  const handleSync = async () => {
    setSyncBusy(true);
    setSyncErr("");
    setSyncWarn("");
    const snapshot = readExpedition(id);
    const sentAnalyses = new Set(snapshot.pending.map((a) => a.abyss_analysis_id));
    const sentLogs = new Set(snapshot.logs.map((l) => l.log_id));
    let resp;
    try {
      resp = await syncExpedition(id, {
        local_logs: snapshot.logs,
        local_analyses: snapshot.pending,
      });
    } catch (e) {
      setSyncErr(e.message);
      setSyncBusy(false);
      return;
    }
    try {
      store((r) => ({
        ...r,
        pending: r.pending.filter((a) => !sentAnalyses.has(a.abyss_analysis_id)),
        logs: r.logs.filter((l) => !sentLogs.has(l.log_id)),
        lastSync: { ...resp, synced_at: new Date().toISOString() },
      }));
    } catch (e) {
      setSyncWarn(`Synced, but this device could not record it: ${e.message}`);
    }
    try {
      await refreshThis();
    } catch (e) {
      setSyncWarn(`Synced, but reloading the expedition failed: ${e.message}`);
    } finally {
      setSyncBusy(false);
    }
  };

  // Storage-throwing handlers (blocked localStorage) surface through err.
  const guard = (fn) => async (...args) => {
    try { await fn(...args); } catch (e) { setErr(e.message); }
  };

  const tone = STATUS_TONE[exp.status] || "pending";
  const statusColor = tokens[tone] ?? tokens.pending;
  const preparing = exp.status === "pre_departure";
  const inField = exp.status === "active";
  const canSync = exp.status === "active" || exp.status === "synced";
  const session = device.session;

  return (
    <div style={accentPanelStyle(statusColor)}>
      <div style={{ display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: 10 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
          <span style={{ fontSize: 15, fontWeight: 600 }}>{exp.name || id}</span>
          <span style={{ fontSize: 12, color: tokens.sectionSubtext }}>
            {exp.location_label && <span>{exp.location_label} · </span>}{exp.vessel && <span>{exp.vessel} · </span>}
            ID: <span style={{ fontFamily: "ui-monospace,monospace", color: tokens.wordmark }}>{id}</span>
          </span>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <span style={plainTagStyle(tone)}>{exp.status}</span>
          <button
            onClick={() => setExpanded((v) => !v)}
            style={{ width: 30, height: 30, borderRadius: 8, border: `1px solid ${tokens.sectionBorder}`, background: "#080F1C", color: tokens.wordmark, fontSize: 11, cursor: "pointer" }}
          >
            {expanded ? "▲" : "▼"}
          </button>
        </div>
      </div>

      {exp.planned_start && (
        <span style={{ fontSize: 12, color: tokens.sectionSubtext }}>
          Departure: {new Date(exp.planned_start).toLocaleDateString()}
          {exp.planned_end && ` · return ${new Date(exp.planned_end).toLocaleDateString()}`}
        </span>
      )}

      {expanded && (
        <div style={{ display: "flex", flexDirection: "column", gap: 14, paddingTop: 4, borderTop: `1px solid ${tokens.sectionBorder}` }}>
          {/* Pack manifest */}
          {(preparing || inField) && (
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              <div>
                <GhostButton onClick={handleManifest}>{loadingManifest ? "Loading..." : "Get Pack Manifest"}</GhostButton>
              </div>
              {manifest && (
                <div style={{ padding: "12px 14px", borderRadius: 6, border: `1px solid ${tokens.sectionBorder}`, background: "rgba(8,14,26,0.5)", fontSize: 12 }}>
                  <div style={{ color: tokens.accentCyan, fontWeight: 600, marginBottom: 6 }}>Pack Manifest</div>
                  {manifest.components?.map((c, i) => (
                    <div key={i} style={{ color: tokens.sectionSubtext, marginBottom: 3 }}>
                      {c.name || c.component_type}:{" "}
                      <span style={{ color: c.status === "available" ? tokens.success : tokens.warningAlt }}>{c.status}</span>
                      {c.size_mb && <span style={{ color: tokens.pending }}> · {c.size_mb} MB</span>}
                    </div>
                  ))}
                  {manifest.total_size_mb != null && (
                    <div style={{ color: tokens.pending, marginTop: 6 }}>Total: {manifest.total_size_mb} MB</div>
                  )}
                </div>
              )}
            </div>
          )}

          {/* 1. Offline license. Issued before departure: /activate requires it. */}
          {(preparing || inField) && (
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              <span style={stepTitleStyle}>OFFLINE LICENSE</span>
              <span style={{ fontSize: 12, color: tokens.sectionSubtext }}>
                {device.license
                  ? `On this device, expires ${fmtDate(device.license.expires_at)}.`
                  : exp.offline_license_issued
                  ? "Issued, but not stored on this device. Issue again here to run field triage from this browser."
                  : "Not issued yet. Activation needs one."}
              </span>
              <div style={{ display: "flex", gap: 10, alignItems: "flex-end", flexWrap: "wrap" }}>
                <div style={{ minWidth: 140 }}>
                  <label style={labelStyle}>License Duration (days, max 90)</label>
                  <input
                    type="number"
                    min={1}
                    max={90}
                    value={duration}
                    onChange={(e) => setDuration(Number(e.target.value))}
                    style={{ ...fieldStyle, width: "auto", minWidth: 100 }}
                  />
                </div>
                <SolidButton onClick={guard(handleIssueLicense)} disabled={issuingLicense}>
                  {issuingLicense ? "Issuing..." : "Issue Offline License"}
                </SolidButton>
              </div>
              {issuedLicense && (
                <div style={{ padding: "12px 14px", borderRadius: 6, border: `1px solid ${tokens.warningBorder}`, background: tokens.warningBg, fontSize: 12 }}>
                  <div style={{ color: tokens.warningAlt, fontWeight: 600, marginBottom: 6 }}>Offline License Issued</div>
                  <div style={{ color: tokens.sectionSubtext, marginBottom: 6 }}>
                    Expires: {fmtDate(issuedLicense.expires_at)} · stored on this device for field triage
                  </div>
                  <div style={{ color: tokens.warningAlt, fontSize: 11 }}>
                    ⚠ It cannot be revoked. It only unlocks field triage; it does not sign in to the API.
                  </div>
                  <textarea
                    readOnly
                    value={issuedLicense.offline_license_token || ""}
                    rows={3}
                    style={{
                      marginTop: 8,
                      width: "100%",
                      padding: "8px",
                      borderRadius: 4,
                      border: `1px solid ${tokens.sectionBorder}`,
                      background: "#04070E",
                      color: tokens.accentCyan,
                      fontFamily: "ui-monospace,monospace",
                      fontSize: 11,
                      resize: "none",
                      boxSizing: "border-box",
                    }}
                    onClick={(e) => e.target.select()}
                  />
                </div>
              )}
            </div>
          )}

          {/* 2. Expedition session for this device (U4). */}
          {(preparing || inField) && (
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              <span style={stepTitleStyle}>THIS DEVICE</span>
              <div style={boxStyle}>
                <span style={{ color: tokens.sectionSubtext }}>
                  Device ID: <span style={{ fontFamily: "ui-monospace,monospace", color: tokens.wordmark }}>{getDeviceId()}</span>
                </span>
                {!session ? (
                  <span style={{ color: tokens.sectionSubtext }}>No expedition session on this device.</span>
                ) : session.invalid ? (
                  <span style={{ color: tokens.danger }}>Session rejected by the server: {session.invalid}</span>
                ) : (
                  <span style={{ color: tokens.success }}>
                    Session verified {fmtDate(session.verified_at)} · role {session.verified?.role} · expires {fmtDate(session.verified?.expires_at)}
                  </span>
                )}
              </div>
              <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                <SolidButton onClick={guard(handleCreateSession)} disabled={sessionBusy}>
                  {sessionBusy ? "Working..." : session ? "Create New Session" : "Create Device Session"}
                </SolidButton>
                {session && (
                  <GhostButton onClick={guard(handleVerifySession)}>{sessionBusy ? "Verifying..." : "Verify Session"}</GhostButton>
                )}
              </div>
              {sessionErr && <span style={{ fontSize: 12, color: tokens.danger }}>{sessionErr}</span>}
            </div>
          )}

          {/* 3. Activate */}
          {preparing && (
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <div>
                <SolidButton tone="success" onClick={guard(handleActivate)} disabled={activating || !exp.offline_license_issued}>
                  {activating ? "Activating..." : "Activate Expedition"}
                </SolidButton>
              </div>
              {!exp.offline_license_issued && (
                <span style={{ fontSize: 12, color: tokens.sectionSubtext }}>Issue an offline license first.</span>
              )}
              {exp.offline_license_issued && !session && (
                <span style={{ fontSize: 12, color: tokens.warningAlt }}>This device has no expedition session yet.</span>
              )}
            </div>
          )}

          {/* Field triage: results stay on the device until synced. */}
          {inField && (
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              <span style={stepTitleStyle}>FIELD TRIAGE</span>
              <textarea
                value={fasta}
                onChange={(e) => setFasta(e.target.value)}
                placeholder={">sample_1\nACGT..."}
                rows={4}
                style={{ ...fieldStyle, fontFamily: "ui-monospace,monospace", fontSize: 12, resize: "vertical" }}
              />
              <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                <input type="file" accept=".fa,.fasta,.fna,.txt" onChange={handleFastaFile} style={{ fontSize: 12, color: tokens.sectionSubtext }} />
                <SolidButton onClick={guard(handleTriage)} disabled={triageBusy || !device.license}>
                  {triageBusy ? "Running..." : "Run Triage"}
                </SolidButton>
              </div>
              {!device.license && (
                <span style={{ fontSize: 12, color: tokens.sectionSubtext }}>Triage needs the offline license stored on this device.</span>
              )}
              {triageErr && <span style={{ fontSize: 12, color: tokens.danger }}>{triageErr}</span>}
              {lastTriage && (
                <div style={boxStyle}>
                  <span style={{ color: tokens.wordmark }}>
                    {lastTriage.sequences_analyzed} sequences · {lastTriage.possible_novelty_count} possible novelty ·{" "}
                    {lastTriage.contamination_flag_count} contamination flags · risk {lastTriage.batch_risk_level}
                  </span>
                  <span style={{ color: tokens.sectionSubtext }}>
                    Router: {lastTriage.router?.method || "unknown"}
                    {lastTriage.router?.fallback_reason ? ` (${lastTriage.router.fallback_reason})` : ""}
                  </span>
                  <span style={{ color: tokens.sectionSubtext }}>{lastTriage.batch_recommendation}</span>
                  <span style={{ color: tokens.warningAlt, fontSize: 11 }}>Preliminary. Requires cloud confirmation after sync.</span>
                </div>
              )}
            </div>
          )}

          {/* Sync now (F3) */}
          {canSync && (
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              <span style={stepTitleStyle}>SYNC</span>
              <span style={{ fontSize: 12, color: tokens.sectionSubtext }}>
                On this device: {device.pending.length} unsynced analyses, {device.logs.length} device log entries.
              </span>
              <div>
                <SolidButton tone="purple" onClick={guard(handleSync)} disabled={syncBusy}>
                  {syncBusy ? "Syncing..." : "Sync Now"}
                </SolidButton>
              </div>
              {syncErr && <span style={{ fontSize: 12, color: tokens.danger }}>Sync failed: {syncErr}</span>}
              {syncWarn && <span style={{ fontSize: 12, color: tokens.warningAlt }}>{syncWarn}</span>}
              {device.lastSync && (
                <div style={boxStyle}>
                  <span style={{ color: tokens.success }}>
                    Last sync {fmtDate(device.lastSync.synced_at)}: {device.lastSync.analyses_stored} analyses and{" "}
                    {device.lastSync.logs_stored} log entries stored, {device.lastSync.reanalysis_jobs_queued} re-analysis jobs queued.
                  </span>
                </div>
              )}
            </div>
          )}

          {err && <span style={{ fontSize: 12, color: tokens.danger }}>{err}</span>}
        </div>
      )}
    </div>
  );
}

// Field names follow CreateExpeditionRequest (abyss/router.py); duration
// is turned into planned_end on submit.
const EMPTY_FORM = { name: "", location_label: "", vessel: "", planned_start: "", planned_duration_days: 14 };

export default function AbyssSetup() {
  const { isExpeditionOp } = useAuth();
  const [expeditions, setExpeditions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // Create form
  const [form, setForm] = useState(EMPTY_FORM);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await getExpeditions();
      setExpeditions(Array.isArray(data) ? data : data?.expeditions || []);
    } catch (e) {
      setError(e.message || "Failed to load expeditions.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const replaceExpedition = useCallback((updated) => {
    setExpeditions((list) => list.map((e) => (e.expedition_id === updated.expedition_id ? updated : e)));
  }, []);

  const handleCreate = async (e) => {
    e.preventDefault();
    if (!form.name.trim()) { setCreateError("Name is required."); return; }
    const days = Number(form.planned_duration_days);
    let planned_start;
    let planned_end;
    if (form.planned_start) {
      const start = new Date(`${form.planned_start}T00:00:00Z`);
      planned_start = start.toISOString();
      if (days > 0) planned_end = new Date(start.getTime() + days * 86400000).toISOString();
    }
    setCreating(true);
    setCreateError("");
    try {
      // created_by is set server-side from the signed-in user.
      await createExpedition({
        name: form.name.trim(),
        location_label: form.location_label.trim() || undefined,
        vessel: form.vessel.trim() || undefined,
        planned_start,
        planned_end,
      });
      setForm(EMPTY_FORM);
      load();
    } catch (e) {
      setCreateError(e.message || "Failed to create expedition.");
    } finally {
      setCreating(false);
    }
  };

  const setField = (k) => (e) => setForm((prev) => ({ ...prev, [k]: e.target.value }));

  return (
    <div style={pageStyle}>
      <div style={ambientGlow} />
      {/* Decorative background, not a real deep-sea telemetry feed --
          centered and pinned behind everything, no pointer events so it
          never blocks the actual UI. The artwork's own pose already reads
          as a top-right (head) to bottom-left (tail) diagonal, so it needs
          just centering plus a slight added clockwise tilt. Kept much
          fainter than the Academia jellyfish -- that one only ever sits in
          a single card's corner, this spans nearly the whole page behind
          body text, so the same 0.5 opacity that worked there read as way
          too loud here. Rotation lives on this wrapper's transform, not
          the img's -- the img's own transform is owned by .sv-jelly's
          keyframes (the translateY bob), and a CSS animation's transform
          fully replaces the base value rather than composing with it. */}
      <div
        style={{
          position: "fixed",
          top: "50%",
          left: "50%",
          transform: "translate(-50%, -50%) rotate(20deg)",
          width: "82vw",
          maxWidth: 1300,
          minWidth: 600,
          pointerEvents: "none",
          zIndex: 0,
        }}
      >
        <img
          src={whaleArt}
          alt=""
          aria-hidden="true"
          className="sv-jelly"
          style={{
            display: "block",
            width: "100%",
            height: "auto",
            opacity: 0.14,
            filter: "drop-shadow(0 0 60px rgba(59,158,255,0.25))",
          }}
        />
      </div>
      <SidebarMenu />
      <div style={{ position: "relative", zIndex: 1, maxWidth: 1100, margin: "0 auto", padding: "32px 44px 44px", display: "flex", flexDirection: "column", gap: 20 }}>
        {/* Header */}
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <div style={{ fontSize: 12, letterSpacing: "0.08em", color: tokens.labelText }}>OFFLINE FIELD TRIAGE</div>
          <h1 style={{ margin: 0, fontSize: 27, fontWeight: 600, letterSpacing: "-0.01em" }}>Abyss Mode</h1>
          <p style={{ margin: 0, fontSize: 14, color: tokens.sectionSubtext }}>
            Deep-sea expedition setup — offline licenses, device sessions, field triage and sync back.
          </p>
        </div>

        {/* Create expedition */}
        {isExpeditionOp && (
          <div style={accentPanelStyle(tokens.purple)}>
            <span style={{ fontSize: 13, fontWeight: 600, color: tokens.purple, letterSpacing: "0.04em" }}>NEW EXPEDITION</span>
            <form onSubmit={handleCreate} style={{ display: "flex", flexDirection: "column", gap: 14 }}>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: 14 }}>
                {[
                  { key: "name", label: "Expedition Name", type: "text", placeholder: "Deep Sea Expedition Alpha" },
                  { key: "location_label", label: "Destination Region", type: "text", placeholder: "Indian Ocean Zone 7" },
                  { key: "vessel", label: "Vessel", type: "text", placeholder: "RV Sagar Nidhi" },
                  { key: "planned_start", label: "Departure Date", type: "date" },
                  { key: "planned_duration_days", label: "Duration (days)", type: "number" },
                ].map(({ key, label, type, placeholder }) => (
                  <div key={key}>
                    <label style={labelStyle}>{label}</label>
                    <input type={type} placeholder={placeholder || ""} value={form[key]} onChange={setField(key)} style={fieldStyle} />
                  </div>
                ))}
              </div>
              {createError && <span style={{ fontSize: 12.5, color: tokens.danger }}>{createError}</span>}
              <div>
                <SolidButton tone="purple" disabled={creating}>
                  {creating ? "Creating..." : "Create Expedition"}
                </SolidButton>
              </div>
            </form>
          </div>
        )}

        {/* Expeditions list */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span style={{ fontSize: 13, fontWeight: 600, color: tokens.wordmark, letterSpacing: "0.04em" }}>
            EXPEDITIONS ({expeditions.length})
          </span>
          <GhostButton onClick={load}>↻ Refresh</GhostButton>
        </div>

        {error && (
          <div style={{ padding: "12px 16px", borderRadius: 6, border: `1px solid ${tokens.dangerBorder}`, background: tokens.dangerBg, color: tokens.danger, fontSize: 13 }}>
            {error}
          </div>
        )}

        {loading ? (
          <div style={{ textAlign: "center", padding: "3rem", color: tokens.sectionSubtext }}>Loading expeditions...</div>
        ) : expeditions.length === 0 ? (
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 10, padding: "60px 20px", borderRadius: 9, border: "1px dashed #17253D", background: "rgba(4,7,12,0.9)" }}>
            <span style={{ fontSize: 14, fontWeight: 500, color: tokens.wordmark }}>No expeditions yet</span>
            <span style={{ fontSize: 12.5, color: tokens.sectionSubtext }}>
              {isExpeditionOp ? "Create one above." : "Contact an expedition operator."}
            </span>
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            {expeditions.map((exp) => (
              <ExpeditionCard key={exp.expedition_id} exp={exp} onUpdated={replaceExpedition} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
