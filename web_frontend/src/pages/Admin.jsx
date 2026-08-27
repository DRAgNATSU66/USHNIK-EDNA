import React, { useEffect, useState, useCallback } from "react";
import { Link } from "react-router-dom";
import SidebarMenu from "../components/sidebar/SidebarMenu";
import { useAuth } from "../contexts/AuthContext";
import {
  getReviewStats,
  createTrainingBatch,
  freezeTrainingBatch,
  authRedeemKey,
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
          Training batch management, review stats, and role administration.
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
