import React, { useEffect, useState, useCallback } from "react";
import { Link } from "react-router-dom";
import SidebarMenu from "../components/sidebar/SidebarMenu";
import { useAuth } from "../contexts/AuthContext";
import {
  getReviewStats,
  createTrainingBatch,
  freezeTrainingBatch,
  authRedeemKey,
  getModels,
  promoteModel,
  getModelPromotions,
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
  marginBottom: "1.5rem",
});

const INPUT = {
  padding: "10px 14px",
  borderRadius: 10,
  border: "1px solid rgba(255,255,255,0.12)",
  background: "rgba(0,0,0,0.25)",
  color: "#ffffff",
  fontSize: "0.9rem",
  outline: "none",
};

const BTN = (color = "#00d4ff", fill = false) => ({
  padding: "0.5rem 1.25rem",
  borderRadius: 10,
  border: fill ? "none" : `1px solid ${color}55`,
  background: fill ? color : `${color}18`,
  color: fill ? "#000" : color,
  fontWeight: 600,
  fontSize: "0.875rem",
  cursor: "pointer",
  transition: "all 0.2s",
});

export default function Admin() {
  const { user, isAdmin } = useAuth();

  // Review stats
  const [stats, setStats] = useState(null);
  const [statsError, setStatsError] = useState("");

  // Batch creation
  const [batchRoute, setBatchRoute] = useState("fish");
  const [batchMonth, setBatchMonth] = useState("");
  const [creatingBatch, setCreatingBatch] = useState(false);
  const [batchResult, setBatchResult] = useState(null);
  const [batchError, setBatchError] = useState("");

  // Batch freeze
  const [freezeBatchId, setFreezeBatchId] = useState("");
  const [freezing, setFreezing] = useState(false);
  const [freezeResult, setFreezeResult] = useState("");
  const [freezeError, setFreezeError] = useState("");

  // Invite key redeem (admin can test key redemption)
  const [inviteKey, setInviteKey] = useState("");
  const [redeemResult, setRedeemResult] = useState(null);
  const [redeemError, setRedeemError] = useState("");
  const [redeeming, setRedeeming] = useState(false);

  const loadStats = useCallback(async () => {
    setStatsError("");
    try {
      const s = await getReviewStats();
      setStats(s);
    } catch (e) {
      setStatsError(e.message || "Failed to load stats.");
    }
  }, []);

  useEffect(() => { loadStats(); }, [loadStats]);

  const handleCreateBatch = async (e) => {
    e.preventDefault();
    if (!batchMonth) { setBatchError("Month is required (YYYY-MM)."); return; }
    setCreatingBatch(true);
    setBatchError("");
    setBatchResult(null);
    try {
      const result = await createTrainingBatch({
        route: batchRoute,
        month_year: batchMonth,
        created_by: user?.user_id,
      });
      setBatchResult(result);
      loadStats();
    } catch (e) {
      setBatchError(e.message || "Failed to create batch.");
    } finally {
      setCreatingBatch(false);
    }
  };

  const handleFreeze = async (e) => {
    e.preventDefault();
    if (!freezeBatchId.trim()) { setFreezeError("Batch ID is required."); return; }
    setFreezing(true);
    setFreezeError("");
    setFreezeResult("");
    try {
      await freezeTrainingBatch(freezeBatchId.trim());
      setFreezeResult(`Batch ${freezeBatchId.trim()} frozen successfully.`);
      setFreezeBatchId("");
    } catch (e) {
      setFreezeError(e.message || "Failed to freeze batch.");
    } finally {
      setFreezing(false);
    }
  };

  const handleRedeem = async (e) => {
    e.preventDefault();
    if (inviteKey.length !== 8) { setRedeemError("Key must be exactly 8 alphanumeric characters."); return; }
    setRedeeming(true);
    setRedeemError("");
    setRedeemResult(null);
    try {
      const result = await authRedeemKey(inviteKey);
      setRedeemResult(result);
      setInviteKey("");
    } catch (e) {
      setRedeemError(e.message || "Key invalid, expired, or already used.");
    } finally {
      setRedeeming(false);
    }
  };

  if (!isAdmin) {
    return (
      <div style={PAGE}>
        <SidebarMenu />
        <div style={{ textAlign: "center", padding: "4rem", color: "#ff9b9b" }}>
          <div style={{ fontSize: "2rem", marginBottom: 12 }}>🔒</div>
          Access denied. Admin role required.
          <div style={{ marginTop: 16 }}>
            <Link to="/upload" style={{ color: "#00d4ff", textDecoration: "none" }}>← New Analysis</Link>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div style={PAGE}>
      <SidebarMenu />
      <div style={{ maxWidth: 960, margin: "0 auto", padding: "2rem 1.5rem" }}>
        <h1 style={{
          fontSize: "1.75rem", fontWeight: 800, marginBottom: "0.5rem",
          background: "linear-gradient(135deg, #ff6b6b 0%, #ff9b9b 100%)",
          WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent", backgroundClip: "text",
        }}>
          Admin Panel
        </h1>
        <p style={{ color: "#b3d9ff", fontSize: "0.9rem", marginBottom: "2rem" }}>
          Training batch management, model promotion, review stats, and role administration.
        </p>

        {/* Review stats */}
        <div style={CARD("#ff6b6b")}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
            <h2 style={{ fontSize: "1rem", fontWeight: 700, color: "#ff9b9b" }}>Review Stats</h2>
            <button onClick={loadStats} style={BTN("#7eb3ff")}>↻ Refresh</button>
          </div>
          {statsError ? (
            <div style={{ color: "#ff9b9b", fontSize: "0.85rem" }}>{statsError}</div>
          ) : stats ? (
            <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap" }}>
              {[
                ["Total Pending", stats.total_pending, "#00d4ff"],
                ["Auto-Novelty", stats.auto_novelty_pending, "#ffd700"],
                ["Auto-Contamination", stats.auto_contamination_pending, "#ff9b9b"],
                ...Object.entries(stats.by_state || {}).map(([k, v]) => [k, v, "#7eb3ff"]),
              ].map(([label, value, color]) => (
                <div key={label} style={{
                  padding: "8px 16px", borderRadius: 10,
                  background: `${color}10`, border: `1px solid ${color}30`, fontSize: "0.85rem",
                }}>
                  <span style={{ color: "#7eb3ff" }}>{label}: </span>
                  <strong style={{ color }}>{value ?? "—"}</strong>
                </div>
              ))}
            </div>
          ) : (
            <div style={{ color: "#7eb3ff", fontSize: "0.85rem" }}>Loading stats...</div>
          )}
        </div>

        {/* Create Training Batch */}
        <div style={CARD("#00ff88")}>
          <h2 style={{ fontSize: "1rem", fontWeight: 700, color: "#00ff88", marginBottom: "1rem" }}>
            Create Monthly Training Batch
          </h2>
          <p style={{ color: "#7eb3ff", fontSize: "0.8rem", marginBottom: "1rem", lineHeight: 1.6 }}>
            Collects all <code style={{ color: "#00d4ff" }}>accepted</code> reviews for the specified route and month into
            a curated training batch. Models update only from curated monthly batches — never from live user input.
          </p>
          <form onSubmit={handleCreateBatch} style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
            <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap" }}>
              <div style={{ flex: 1, minWidth: 200 }}>
                <label style={{ display: "block", marginBottom: 6, fontSize: "0.75rem", color: "#7eb3ff", fontWeight: 600, textTransform: "uppercase" }}>
                  Route
                </label>
                <select
                  value={batchRoute}
                  onChange={(e) => setBatchRoute(e.target.value)}
                  style={{ ...INPUT, width: "100%" }}
                >
                  {["fish", "plant", "bacteria_pathogen", "bacteria_environmental",
                    "fungi", "invertebrate", "mammal", "human_domestic_contamination",
                    "lab_reagent_contamination", "misc_unknown"].map((r) => (
                    <option key={r} value={r}>{r}</option>
                  ))}
                </select>
              </div>
              <div style={{ flex: 1, minWidth: 200 }}>
                <label style={{ display: "block", marginBottom: 6, fontSize: "0.75rem", color: "#7eb3ff", fontWeight: 600, textTransform: "uppercase" }}>
                  Month (YYYY-MM)
                </label>
                <input
                  type="month"
                  value={batchMonth}
                  onChange={(e) => setBatchMonth(e.target.value)}
                  style={{ ...INPUT, width: "100%" }}
                  required
                />
              </div>
            </div>
            {batchError && <div style={{ color: "#ff9b9b", fontSize: "0.85rem" }}>{batchError}</div>}
            {batchResult && (
              <div style={{
                padding: "10px 14px", borderRadius: 10,
                background: "rgba(0,255,136,0.06)", border: "1px solid rgba(0,255,136,0.2)",
                color: "#00ff88", fontSize: "0.85rem",
              }}>
                Batch created: <strong>{batchResult.batch_id}</strong> · {batchResult.sequence_count ?? 0} sequences
                {batchResult.status === "assembled_local_only" && (
                  <span style={{ color: "#ffd700", marginLeft: 10 }}>⚠ Local only (Supabase unavailable)</span>
                )}
              </div>
            )}
            <div>
              <button type="submit" disabled={creatingBatch} style={BTN("#00ff88", true)}>
                {creatingBatch ? "Creating..." : "Create Batch"}
              </button>
            </div>
          </form>
        </div>

        {/* Freeze Batch */}
        <div style={CARD("#ffd700")}>
          <h2 style={{ fontSize: "1rem", fontWeight: 700, color: "#ffd700", marginBottom: "1rem" }}>
            Freeze Training Batch
          </h2>
          <p style={{ color: "#7eb3ff", fontSize: "0.8rem", marginBottom: "1rem" }}>
            Freezing a batch marks it as ready for model training. Frozen batches cannot be modified.
          </p>
          <form onSubmit={handleFreeze} style={{ display: "flex", gap: "1rem", flexWrap: "wrap", alignItems: "flex-end" }}>
            <div style={{ flex: 1, minWidth: 280 }}>
              <label style={{ display: "block", marginBottom: 6, fontSize: "0.75rem", color: "#7eb3ff", fontWeight: 600, textTransform: "uppercase" }}>
                Batch ID
              </label>
              <input
                type="text"
                value={freezeBatchId}
                onChange={(e) => setFreezeBatchId(e.target.value)}
                placeholder="e.g. batch_abc123..."
                style={{ ...INPUT, width: "100%" }}
              />
            </div>
            <button type="submit" disabled={freezing || !freezeBatchId.trim()} style={BTN("#ffd700", true)}>
              {freezing ? "Freezing..." : "Freeze Batch"}
            </button>
          </form>
          {freezeError && <div style={{ marginTop: 8, color: "#ff9b9b", fontSize: "0.85rem" }}>{freezeError}</div>}
          {freezeResult && <div style={{ marginTop: 8, color: "#00ff88", fontSize: "0.85rem" }}>{freezeResult}</div>}
        </div>

        <ModelPromotionCard />

        {/* Role key redemption */}
        <div style={CARD("#a78bfa")}>
          <h2 style={{ fontSize: "1rem", fontWeight: 700, color: "#a78bfa", marginBottom: "0.5rem" }}>
            Redeem Invite Key
          </h2>
          <p style={{ color: "#7eb3ff", fontSize: "0.8rem", marginBottom: "1rem" }}>
            Redeem an 8-character alphanumeric invite key to elevate your own role.
            Keys are hashed on the server — plaintext is never stored.
          </p>
          <form onSubmit={handleRedeem} style={{ display: "flex", gap: "1rem", flexWrap: "wrap", alignItems: "flex-end" }}>
            <div style={{ flex: 1, minWidth: 240 }}>
              <label style={{ display: "block", marginBottom: 6, fontSize: "0.75rem", color: "#7eb3ff", fontWeight: 600, textTransform: "uppercase" }}>
                Invite Key (8 chars)
              </label>
              <input
                type="text"
                value={inviteKey}
                onChange={(e) => setInviteKey(e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, 8))}
                placeholder="ABCD1234"
                maxLength={8}
                style={{ ...INPUT, fontFamily: "monospace", letterSpacing: "0.15em", width: "100%" }}
              />
            </div>
            <button type="submit" disabled={redeeming || inviteKey.length !== 8} style={BTN("#a78bfa", true)}>
              {redeeming ? "Redeeming..." : "Redeem Key"}
            </button>
          </form>
          {redeemError && <div style={{ marginTop: 8, color: "#ff9b9b", fontSize: "0.85rem" }}>{redeemError}</div>}
          {redeemResult && (
            <div style={{
              marginTop: 8, padding: "10px 14px", borderRadius: 10,
              background: "rgba(167,139,250,0.08)", border: "1px solid rgba(167,139,250,0.2)",
              color: "#a78bfa", fontSize: "0.85rem",
            }}>
              Role granted: <strong>{redeemResult.role_granted}</strong>
              {redeemResult.access_token && " · New token issued — re-login to apply."}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Model promotion (B8)
//
// Lists registry entries per route with the one the worker serves now. Promote
// asks the API for a dry-run plan and shows it in place: what serves the route
// now, metric deltas, what gets demoted, comparability warnings. The admin
// types the model_id to confirm; only then is the real promotion sent, with
// the current model_id the plan showed (the API refuses with 409 if the route
// changed in between). No window.confirm.
// ---------------------------------------------------------------------------

const PROMOTABLE = new Set(["candidate", "experimental", "staging"]);

const STATUS_COLOR = {
  production: "#00ff88",
  staging: "#00d4ff",
  experimental: "#7eb3ff",
  candidate: "#ffd700",
  retired: "#888",
};

function fmtMetric(v) {
  if (v === null || v === undefined) return "—";
  return Number.isInteger(v) ? String(v) : v.toFixed(4);
}

function fmtDelta(v) {
  if (v === null || v === undefined) return "—";
  const s = Number.isInteger(v) ? String(Math.abs(v)) : Math.abs(v).toFixed(4);
  return `${v > 0 ? "+" : v < 0 ? "−" : "±"}${s}`;
}

function ModelPromotionCard() {
  const [registry, setRegistry] = useState(null);
  const [loadError, setLoadError] = useState("");
  const [events, setEvents] = useState([]);

  // In-page confirmation state for one model at a time.
  const [plan, setPlan] = useState(null);       // dry-run response
  const [planFor, setPlanFor] = useState("");   // model_id being reviewed
  const [planning, setPlanning] = useState(false);
  const [typed, setTyped] = useState("");
  const [notes, setNotes] = useState("");
  const [promoting, setPromoting] = useState(false);
  const [actionError, setActionError] = useState("");
  const [done, setDone] = useState(null);

  const load = useCallback(async () => {
    setLoadError("");
    try {
      setRegistry(await getModels());
    } catch (e) {
      setLoadError(e.message || "Failed to load the model registry.");
    }
    try {
      setEvents((await getModelPromotions(10)).events || []);
    } catch {
      setEvents([]); // the history list is secondary; the registry error above is what matters
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const cancel = () => {
    setPlan(null);
    setPlanFor("");
    setTyped("");
    setNotes("");
    setActionError("");
  };

  const review = async (modelId) => {
    cancel();
    setDone(null);
    setPlanFor(modelId);
    setPlanning(true);
    try {
      setPlan(await promoteModel(modelId, { dry_run: true }));
    } catch (e) {
      setActionError(e.message || "The API refused the promotion plan.");
    } finally {
      setPlanning(false);
    }
  };

  const confirm = async () => {
    if (!plan || typed !== plan.model_id) return;
    setPromoting(true);
    setActionError("");
    try {
      const result = await promoteModel(plan.model_id, {
        expected_current_model_id: plan.current_model_id,
        notes: notes.trim() || null,
      });
      setDone(result);
      cancel();
      load();
    } catch (e) {
      setActionError(
        e.status === 409
          ? `${e.message} Review the comparison again before promoting.`
          : e.message || "Promotion failed."
      );
    } finally {
      setPromoting(false);
    }
  };

  const byRoute = {};
  for (const m of registry?.models || []) (byRoute[m.route] ||= []).push(m);
  const routes = Object.keys(byRoute).sort();
  const selected = registry?.selected_by_route || {};

  return (
    <div style={CARD("#00d4ff")}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.5rem" }}>
        <h2 style={{ fontSize: "1rem", fontWeight: 700, color: "#00d4ff" }}>Model Promotion</h2>
        <button onClick={load} style={BTN("#7eb3ff")}>↻ Refresh</button>
      </div>
      <p style={{ color: "#7eb3ff", fontSize: "0.8rem", marginBottom: "1rem", lineHeight: 1.6 }}>
        The worker serves, per route, the newest <code style={{ color: "#00ff88" }}>production</code> entry,
        else staging, else experimental. Registered <code style={{ color: "#ffd700" }}>candidate</code>s are
        never served until promoted. Promoting re-verifies the artifact checksum, demotes the route's
        previous production model to staging, and records the change in the audit log and model_eval_metrics.
      </p>

      {done && (
        <div style={{
          padding: "10px 14px", borderRadius: 10, marginBottom: "1rem",
          background: "rgba(0,255,136,0.06)", border: "1px solid rgba(0,255,136,0.2)",
          color: "#00ff88", fontSize: "0.85rem",
        }}>
          <strong>{done.model_id}</strong> now serves route <strong>{done.route}</strong>
          {done.current_model_id ? ` (was ${done.current_model_id})` : ""}.
          {done.supabase_mirror === "failed" && (
            <span style={{ color: "#ffd700", marginLeft: 10 }}>⚠ Supabase mirror failed; registry and audit log are written.</span>
          )}
          <div style={{ color: "#7eb3ff", marginTop: 4 }}>Commit the changed models/registry/*.json files.</div>
        </div>
      )}

      {loadError ? (
        <div style={{ color: "#ff9b9b", fontSize: "0.85rem" }}>{loadError}</div>
      ) : !registry ? (
        <div style={{ color: "#7eb3ff", fontSize: "0.85rem" }}>Loading registry...</div>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.82rem" }}>
            <thead>
              <tr style={{ color: "#7eb3ff", textAlign: "left" }}>
                {["Route", "Model", "Status", "Trained", "Test acc.", "Test macro-F1", ""].map((h) => (
                  <th key={h} style={{ padding: "6px 8px", borderBottom: "1px solid rgba(255,255,255,0.1)", fontWeight: 600 }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {routes.flatMap((route) =>
                byRoute[route]
                  .slice()
                  .sort((a, b) => (b.created_at || "").localeCompare(a.created_at || ""))
                  .map((m) => {
                    const serving = selected[route] === m.model_id;
                    const status = m.status || "experimental";
                    const canPromote = PROMOTABLE.has(status) && m.artifact_uri;
                    return (
                      <tr key={m.model_id} style={{ background: planFor === m.model_id ? "rgba(0,212,255,0.06)" : "transparent" }}>
                        <td style={{ padding: "6px 8px", color: "#b3d9ff" }}>{route}</td>
                        <td style={{ padding: "6px 8px", fontFamily: "monospace" }}>
                          {m.model_id}
                          {serving && <span style={{ marginLeft: 8, color: "#00ff88", fontFamily: "Inter, sans-serif" }}>● serving</span>}
                        </td>
                        <td style={{ padding: "6px 8px", color: STATUS_COLOR[status] || "#ccc" }}>{status}</td>
                        <td style={{ padding: "6px 8px", color: "#b3d9ff" }}>{m.created_at || "—"}</td>
                        <td style={{ padding: "6px 8px" }}>{fmtMetric(m.metrics?.test_accuracy)}</td>
                        <td style={{ padding: "6px 8px" }}>{fmtMetric(m.metrics?.test_macro_f1)}</td>
                        <td style={{ padding: "6px 8px", textAlign: "right" }}>
                          {canPromote && (
                            <button
                              onClick={() => review(m.model_id)}
                              disabled={planning || promoting}
                              style={{ ...BTN("#00d4ff"), padding: "0.3rem 0.9rem" }}
                            >
                              {planning && planFor === m.model_id ? "Checking..." : "Promote…"}
                            </button>
                          )}
                        </td>
                      </tr>
                    );
                  })
              )}
            </tbody>
          </table>
        </div>
      )}

      {planFor && !plan && actionError && (
        <div style={{ marginTop: 12, color: "#ff9b9b", fontSize: "0.85rem" }}>
          Cannot promote {planFor}: {actionError}
          <button onClick={cancel} style={{ ...BTN("#7eb3ff"), marginLeft: 12, padding: "0.25rem 0.8rem" }}>Dismiss</button>
        </div>
      )}

      {plan && (
        <div
          role="region"
          aria-label={`Confirm promotion of ${plan.model_id}`}
          style={{
            marginTop: "1rem", padding: "1rem 1.25rem", borderRadius: 12,
            border: "1px solid rgba(255,215,0,0.35)", background: "rgba(255,215,0,0.05)",
          }}
        >
          <div style={{ fontWeight: 700, color: "#ffd700", marginBottom: 8 }}>
            Confirm: promote {plan.model_id} to production on route {plan.route}
          </div>
          <div style={{ fontSize: "0.85rem", color: "#b3d9ff", lineHeight: 1.7 }}>
            <div>Currently serving: <strong style={{ color: "#fff" }}>{plan.current_model_id || "nothing"}</strong>
              {plan.current_status ? ` (${plan.current_status})` : ""}</div>
            <div>{plan.model_id} is now: {plan.from_status}</div>
            {plan.demoted_model_ids?.length > 0 && (
              <div>Demoted to staging: {plan.demoted_model_ids.join(", ")}</div>
            )}
          </div>

          <table style={{ marginTop: 10, borderCollapse: "collapse", fontSize: "0.82rem" }}>
            <thead>
              <tr style={{ color: "#7eb3ff", textAlign: "left" }}>
                {["Metric", plan.model_id, plan.current_model_id || "current", "Δ"].map((h) => (
                  <th key={h} style={{ padding: "4px 12px 4px 0", fontWeight: 600 }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {plan.metric_deltas.map((d) => (
                <tr key={d.metric}>
                  <td style={{ padding: "3px 12px 3px 0", color: "#b3d9ff" }}>{d.metric}</td>
                  <td style={{ padding: "3px 12px 3px 0" }}>{fmtMetric(d.candidate)}</td>
                  <td style={{ padding: "3px 12px 3px 0" }}>{fmtMetric(d.current)}</td>
                  <td style={{
                    padding: "3px 12px 3px 0",
                    color: d.delta > 0 ? "#00ff88" : d.delta < 0 ? "#ff9b9b" : "#ccc",
                  }}>{fmtDelta(d.delta)}</td>
                </tr>
              ))}
            </tbody>
          </table>

          {plan.warnings?.length > 0 && (
            <ul style={{ margin: "10px 0 0", paddingLeft: 18, color: "#ffd700", fontSize: "0.8rem" }}>
              {plan.warnings.map((w) => <li key={w}>{w}</li>)}
            </ul>
          )}

          <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap", marginTop: 14 }}>
            <div style={{ flex: 2, minWidth: 240 }}>
              <label style={{ display: "block", marginBottom: 6, fontSize: "0.75rem", color: "#7eb3ff", fontWeight: 600, textTransform: "uppercase" }}>
                Notes (kept in the audit log)
              </label>
              <input
                type="text"
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                maxLength={2000}
                placeholder="Why this model, what was checked"
                style={{ ...INPUT, width: "100%" }}
              />
            </div>
            <div style={{ flex: 1, minWidth: 220 }}>
              <label style={{ display: "block", marginBottom: 6, fontSize: "0.75rem", color: "#7eb3ff", fontWeight: 600, textTransform: "uppercase" }}>
                Type {plan.model_id} to confirm
              </label>
              <input
                type="text"
                value={typed}
                onChange={(e) => setTyped(e.target.value.trim())}
                autoComplete="off"
                spellCheck={false}
                style={{ ...INPUT, fontFamily: "monospace", width: "100%" }}
              />
            </div>
          </div>

          {actionError && <div style={{ marginTop: 10, color: "#ff9b9b", fontSize: "0.85rem" }}>{actionError}</div>}

          <div style={{ display: "flex", gap: "0.75rem", marginTop: 14 }}>
            <button
              onClick={confirm}
              disabled={promoting || typed !== plan.model_id}
              style={{ ...BTN("#ffd700", true), opacity: typed === plan.model_id ? 1 : 0.5 }}
            >
              {promoting ? "Promoting..." : "Promote to production"}
            </button>
            <button onClick={cancel} disabled={promoting} style={BTN("#7eb3ff")}>Cancel</button>
          </div>
        </div>
      )}

      {events.length > 0 && (
        <div style={{ marginTop: "1.25rem" }}>
          <div style={{ fontSize: "0.75rem", color: "#7eb3ff", fontWeight: 600, textTransform: "uppercase", marginBottom: 6 }}>
            Recent registrations and promotions
          </div>
          {events.map((ev, i) => (
            <div key={`${ev.model_id}-${ev.timestamp}-${i}`} style={{ fontSize: "0.8rem", color: "#b3d9ff", padding: "2px 0" }}>
              <span style={{ color: "#7eb3ff" }}>{ev.timestamp ? new Date(ev.timestamp).toLocaleString() : "—"}</span>{" · "}
              {ev.action === "model_promoted" ? "promoted" : "registered"}{" "}
              <code style={{ color: "#fff" }}>{ev.model_id}</code> on {ev.route}
              {ev.action === "model_promoted" && ev.previous_model_id ? ` (replacing ${ev.previous_model_id})` : ""}
              {ev.actor_email ? ` by ${ev.actor_email}` : ""}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
