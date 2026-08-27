import React, { useEffect, useState, useCallback } from "react";
import SidebarMenu from "../components/sidebar/SidebarMenu";
import { tokens } from "../components/shared/tokens";
import { useAuth } from "../contexts/AuthContext";
import {
  getExpeditions, createExpedition, activateExpedition,
  getPackManifest, issueLicense,
} from "../lib/api";
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

function ExpeditionCard({ exp, onRefresh }) {
  const [manifest, setManifest] = useState(null);
  const [license, setLicense] = useState(null);
  const [duration, setDuration] = useState(14);
  const [expanded, setExpanded] = useState(false);
  const [activating, setActivating] = useState(false);
  const [issuingLicense, setIssuingLicense] = useState(false);
  const [loadingManifest, setLoadingManifest] = useState(false);
  const [err, setErr] = useState("");

  const handleActivate = async () => {
    setActivating(true);
    setErr("");
    try {
      await activateExpedition(exp.expedition_id);
      onRefresh();
    } catch (e) { setErr(e.message); }
    finally { setActivating(false); }
  };

  const handleManifest = async () => {
    setLoadingManifest(true);
    setErr("");
    try {
      const m = await getPackManifest(exp.expedition_id);
      setManifest(m);
    } catch (e) { setErr(e.message); }
    finally { setLoadingManifest(false); }
  };

  const handleIssueLicense = async () => {
    setIssuingLicense(true);
    setErr("");
    try {
      const l = await issueLicense(exp.expedition_id, duration);
      setLicense(l);
    } catch (e) { setErr(e.message); }
    finally { setIssuingLicense(false); }
  };

  const tone = STATUS_TONE[exp.status] || "pending";
  const statusColor = tokens[tone] ?? tokens.pending;

  return (
    <div style={accentPanelStyle(statusColor)}>
      <div style={{ display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: 10 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
          <span style={{ fontSize: 15, fontWeight: 600 }}>{exp.expedition_name || exp.expedition_id}</span>
          <span style={{ fontSize: 12, color: tokens.sectionSubtext }}>
            {exp.destination_region && <span>{exp.destination_region} · </span>}
            ID: <span style={{ fontFamily: "ui-monospace,monospace", color: tokens.wordmark }}>{exp.expedition_id}</span>
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

      {exp.departure_date && (
        <span style={{ fontSize: 12, color: tokens.sectionSubtext }}>
          Departure: {new Date(exp.departure_date).toLocaleDateString()}
          {exp.planned_duration_days && ` · ${exp.planned_duration_days} days`}
        </span>
      )}

      {expanded && (
        <div style={{ display: "flex", flexDirection: "column", gap: 14, paddingTop: 4, borderTop: `1px solid ${tokens.sectionBorder}` }}>
          {/* Activate */}
          {exp.status === "pre_departure" && (
            <div>
              <SolidButton tone="success" onClick={handleActivate} disabled={activating}>
                {activating ? "Activating..." : "Activate Expedition"}
              </SolidButton>
            </div>
          )}

          {/* Pack manifest */}
          {exp.status === "active" && (
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

          {/* Issue license */}
          {exp.status === "active" && (
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
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
                <SolidButton onClick={handleIssueLicense} disabled={issuingLicense}>
                  {issuingLicense ? "Issuing..." : "Issue Offline License"}
                </SolidButton>
              </div>
              {license && (
                <div style={{ padding: "12px 14px", borderRadius: 6, border: `1px solid ${tokens.warningBorder}`, background: tokens.warningBg, fontSize: 12 }}>
                  <div style={{ color: tokens.warningAlt, fontWeight: 600, marginBottom: 6 }}>Offline License Issued</div>
                  <div style={{ color: tokens.sectionSubtext, marginBottom: 6 }}>
                    Expires: {license.expires_at ? new Date(license.expires_at).toLocaleString() : "—"}
                  </div>
                  <div style={{ color: tokens.warningAlt, fontSize: 11 }}>
                    ⚠ Store this token securely on your field device. It cannot be revoked.
                  </div>
                  <textarea
                    readOnly
                    value={license.offline_license_token || license.token || ""}
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

          {err && <span style={{ fontSize: 12, color: tokens.danger }}>{err}</span>}
        </div>
      )}
    </div>
  );
}

export default function AbyssSetup() {
  const { user, isExpeditionOp } = useAuth();
  const [expeditions, setExpeditions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // Create form
  const [form, setForm] = useState({
    expedition_name: "",
    destination_region: "",
    departure_date: "",
    planned_duration_days: 14,
    expected_sequence_count: "",
  });
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

  const handleCreate = async (e) => {
    e.preventDefault();
    if (!form.expedition_name.trim()) { setCreateError("Name is required."); return; }
    setCreating(true);
    setCreateError("");
    try {
      await createExpedition({
        ...form,
        planned_duration_days: Number(form.planned_duration_days),
        expected_sequence_count: form.expected_sequence_count ? Number(form.expected_sequence_count) : undefined,
        created_by: user?.user_id,
      });
      setForm({ expedition_name: "", destination_region: "", departure_date: "", planned_duration_days: 14, expected_sequence_count: "" });
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
            Deep-sea expedition setup — pack manifests and offline licenses for disconnected fieldwork.
          </p>
        </div>

        {/* Create expedition */}
        {isExpeditionOp && (
          <div style={accentPanelStyle(tokens.purple)}>
            <span style={{ fontSize: 13, fontWeight: 600, color: tokens.purple, letterSpacing: "0.04em" }}>NEW EXPEDITION</span>
            <form onSubmit={handleCreate} style={{ display: "flex", flexDirection: "column", gap: 14 }}>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: 14 }}>
                {[
                  { key: "expedition_name", label: "Expedition Name", type: "text", placeholder: "Deep Sea Expedition Alpha" },
                  { key: "destination_region", label: "Destination Region", type: "text", placeholder: "Indian Ocean Zone 7" },
                  { key: "departure_date", label: "Departure Date", type: "date" },
                  { key: "planned_duration_days", label: "Duration (days)", type: "number" },
                  { key: "expected_sequence_count", label: "Expected Sequences", type: "number", placeholder: "500" },
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
              <ExpeditionCard key={exp.expedition_id} exp={exp} onRefresh={load} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
