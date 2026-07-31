import React, { useEffect, useState, useCallback } from "react";
import NavBar from "../components/NavBar";
import { useAuth } from "../contexts/AuthContext";
import {
  getExpeditions, createExpedition, activateExpedition,
  getPackManifest, issueLicense,
} from "../lib/api";

const PAGE = {
  background: "radial-gradient(ellipse at center, #002266 0%, #001133 100%)",
  minHeight: "100vh",
  color: "#ffffff",
  fontFamily: "'Inter', system-ui, sans-serif",
};

const CARD = (accent = "#00d4ff") => ({
  background: "rgba(255,255,255,0.04)",
  border: "1px solid rgba(255,255,255,0.08)",
  borderTop: `2px solid ${accent}`,
  borderRadius: 14,
  padding: "1.5rem",
  marginBottom: "1.25rem",
});

const INPUT = {
  padding: "10px 14px",
  borderRadius: 10,
  border: "1px solid rgba(255,255,255,0.12)",
  background: "rgba(0,0,0,0.25)",
  color: "#ffffff",
  fontSize: "0.9rem",
  outline: "none",
  width: "100%",
};

const BTN = (color = "#00d4ff", fill = false) => ({
  padding: "0.5rem 1.1rem",
  borderRadius: 10,
  border: fill ? "none" : `1px solid ${color}55`,
  background: fill ? color : `${color}18`,
  color: fill ? "#000" : color,
  fontWeight: 600,
  fontSize: "0.85rem",
  cursor: "pointer",
});

const STATUS_COLOR = {
  pre_departure: "#7eb3ff",
  active: "#00ff88",
  synced: "#a78bfa",
  archived: "#5a7a9a",
};

function ExpeditionCard({ exp, onRefresh }) {
  const { user } = useAuth();
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

  const statusColor = STATUS_COLOR[exp.status] || "#7eb3ff";

  return (
    <div style={{ ...CARD(statusColor), padding: "1.25rem" }}>
      <div style={{ display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: 8, marginBottom: 8 }}>
        <div>
          <h3 style={{ fontSize: "1rem", fontWeight: 700, color: "#ffffff", marginBottom: 4 }}>
            {exp.expedition_name || exp.expedition_id}
          </h3>
          <div style={{ color: "#7eb3ff", fontSize: "0.8rem" }}>
            {exp.destination_region && <span>{exp.destination_region} · </span>}
            ID: <code style={{ color: "#00d4ff", fontFamily: "monospace" }}>{exp.expedition_id}</code>
          </div>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <div style={{
            padding: "3px 12px", borderRadius: 999, fontSize: "0.75rem", fontWeight: 700,
            background: `${statusColor}18`, border: `1px solid ${statusColor}44`, color: statusColor,
          }}>
            {exp.status}
          </div>
          <button onClick={() => setExpanded((v) => !v)} style={BTN("#7eb3ff")}>
            {expanded ? "▲" : "▼"}
          </button>
        </div>
      </div>

      {exp.departure_date && (
        <div style={{ fontSize: "0.8rem", color: "#7eb3ff" }}>
          Departure: {new Date(exp.departure_date).toLocaleDateString()}
          {exp.planned_duration_days && ` · ${exp.planned_duration_days} days`}
        </div>
      )}

      {expanded && (
        <div style={{ marginTop: "1rem", display: "flex", flexDirection: "column", gap: "0.75rem" }}>
          {/* Activate */}
          {exp.status === "pre_departure" && (
            <button onClick={handleActivate} disabled={activating} style={BTN("#00ff88", true)}>
              {activating ? "Activating..." : "Activate Expedition"}
            </button>
          )}

          {/* Pack manifest */}
          {exp.status === "active" && (
            <div>
              <button onClick={handleManifest} disabled={loadingManifest} style={BTN("#00d4ff")}>
                {loadingManifest ? "Loading..." : "Get Pack Manifest"}
              </button>
              {manifest && (
                <div style={{
                  marginTop: 8, padding: "10px 14px", borderRadius: 10,
                  background: "rgba(0,212,255,0.06)", border: "1px solid rgba(0,212,255,0.2)",
                  fontSize: "0.82rem",
                }}>
                  <div style={{ color: "#00d4ff", fontWeight: 600, marginBottom: 6 }}>Pack Manifest</div>
                  {manifest.components?.map((c, i) => (
                    <div key={i} style={{ color: "#b3d9ff", marginBottom: 2 }}>
                      {c.name || c.component_type}: <span style={{
                        color: c.status === "available" ? "#00ff88" : "#ffd700",
                      }}>{c.status}</span>
                      {c.size_mb && <span style={{ color: "#7eb3ff" }}> · {c.size_mb} MB</span>}
                    </div>
                  ))}
                  {manifest.total_size_mb != null && (
                    <div style={{ color: "#7eb3ff", marginTop: 6 }}>
                      Total: {manifest.total_size_mb} MB
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {/* Issue license */}
          {exp.status === "active" && (
            <div>
              <div style={{ display: "flex", gap: 8, alignItems: "flex-end", flexWrap: "wrap" }}>
                <div style={{ flex: 1, minWidth: 140 }}>
                  <label style={{ display: "block", marginBottom: 4, fontSize: "0.75rem", color: "#7eb3ff", fontWeight: 600, textTransform: "uppercase" }}>
                    License Duration (days, max 90)
                  </label>
                  <input
                    type="number"
                    min={1}
                    max={90}
                    value={duration}
                    onChange={(e) => setDuration(Number(e.target.value))}
                    style={{ ...INPUT, width: "auto", minWidth: 100 }}
                  />
                </div>
                <button onClick={handleIssueLicense} disabled={issuingLicense} style={BTN("#ffd700", true)}>
                  {issuingLicense ? "Issuing..." : "Issue Offline License"}
                </button>
              </div>
              {license && (
                <div style={{
                  marginTop: 8, padding: "10px 14px", borderRadius: 10,
                  background: "rgba(255,215,0,0.06)", border: "1px solid rgba(255,215,0,0.2)",
                  fontSize: "0.8rem",
                }}>
                  <div style={{ color: "#ffd700", fontWeight: 600, marginBottom: 6 }}>Offline License Issued</div>
                  <div style={{ color: "#b3d9ff", marginBottom: 4 }}>
                    Expires: {license.expires_at ? new Date(license.expires_at).toLocaleString() : "—"}
                  </div>
                  <div style={{ color: "#ffaa55", fontSize: "0.75rem" }}>
                    ⚠ Store this token securely on your field device. It cannot be revoked.
                  </div>
                  <textarea
                    readOnly
                    value={license.offline_license_token || license.token || ""}
                    rows={3}
                    style={{
                      marginTop: 8, width: "100%", padding: "8px",
                      borderRadius: 8, border: "1px solid rgba(255,255,255,0.1)",
                      background: "rgba(0,0,0,0.3)", color: "#00d4ff",
                      fontFamily: "monospace", fontSize: "0.7rem",
                      resize: "none",
                    }}
                    onClick={(e) => e.target.select()}
                  />
                </div>
              )}
            </div>
          )}

          {err && <div style={{ color: "#ff9b9b", fontSize: "0.82rem" }}>{err}</div>}
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
    <div style={PAGE}>
      <NavBar />
      <div style={{ maxWidth: 980, margin: "0 auto", padding: "2rem 1.5rem" }}>
        <h1 style={{
          fontSize: "1.75rem", fontWeight: 800, marginBottom: "0.5rem",
          background: "linear-gradient(135deg, #0066ff 0%, #00d4ff 100%)",
          WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent", backgroundClip: "text",
        }}>
          Abyss Mode
        </h1>
        <p style={{ color: "#b3d9ff", fontSize: "0.9rem", marginBottom: "1rem" }}>
          Field-triage system for offline deep-sea expeditions.
        </p>
        <div style={{
          padding: "10px 16px", borderRadius: 10,
          background: "rgba(255,165,0,0.06)", border: "1px solid rgba(255,165,0,0.2)",
          color: "#ffaa55", fontSize: "0.8rem", marginBottom: "1.75rem", lineHeight: 1.5,
        }}>
          ⚠ Abyss Mode is a field-triage system. Results are preliminary and must be confirmed
          by full online analysis after reconnecting.
        </div>

        {/* Create expedition */}
        {isExpeditionOp && (
          <div style={CARD("#a78bfa")}>
            <h2 style={{ fontSize: "1rem", fontWeight: 700, color: "#a78bfa", marginBottom: "1rem" }}>
              New Expedition
            </h2>
            <form onSubmit={handleCreate} style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: "1rem" }}>
                {[
                  { key: "expedition_name", label: "Expedition Name", type: "text", placeholder: "Deep Sea Expedition Alpha" },
                  { key: "destination_region", label: "Destination Region", type: "text", placeholder: "Indian Ocean Zone 7" },
                  { key: "departure_date", label: "Departure Date", type: "date" },
                  { key: "planned_duration_days", label: "Duration (days)", type: "number" },
                  { key: "expected_sequence_count", label: "Expected Sequences", type: "number", placeholder: "500" },
                ].map(({ key, label, type, placeholder }) => (
                  <div key={key}>
                    <label style={{ display: "block", marginBottom: 4, fontSize: "0.75rem", color: "#7eb3ff", fontWeight: 600, textTransform: "uppercase" }}>
                      {label}
                    </label>
                    <input type={type} placeholder={placeholder || ""} value={form[key]} onChange={setField(key)} style={INPUT} />
                  </div>
                ))}
              </div>
              {createError && <div style={{ color: "#ff9b9b", fontSize: "0.85rem" }}>{createError}</div>}
              <div>
                <button type="submit" disabled={creating} style={BTN("#a78bfa", true)}>
                  {creating ? "Creating..." : "Create Expedition"}
                </button>
              </div>
            </form>
          </div>
        )}

        {/* Expeditions list */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
          <h2 style={{ fontSize: "1.1rem", fontWeight: 700, color: "#b3d9ff" }}>
            Expeditions ({expeditions.length})
          </h2>
          <button onClick={load} style={BTN("#7eb3ff")}>↻ Refresh</button>
        </div>

        {error && (
          <div style={{
            padding: "12px 16px", borderRadius: 10,
            background: "rgba(255,80,80,0.08)", border: "1px solid rgba(255,80,80,0.2)",
            color: "#ff9b9b", marginBottom: "1rem",
          }}>
            {error}
          </div>
        )}

        {loading ? (
          <div style={{ textAlign: "center", padding: "3rem", color: "#7eb3ff" }}>Loading expeditions...</div>
        ) : expeditions.length === 0 ? (
          <div style={{
            textAlign: "center", padding: "3rem", color: "#7eb3ff",
            border: "1px solid rgba(255,255,255,0.06)", borderRadius: 14,
            background: "rgba(255,255,255,0.02)",
          }}>
            No expeditions yet.{isExpeditionOp ? " Create one above." : " Contact an expedition operator."}
          </div>
        ) : (
          expeditions.map((exp) => (
            <ExpeditionCard key={exp.expedition_id} exp={exp} onRefresh={load} />
          ))
        )}
      </div>
    </div>
  );
}
