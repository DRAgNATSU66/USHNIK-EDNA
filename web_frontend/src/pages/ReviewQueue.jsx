import React, { useEffect, useState, useCallback } from "react";
import { Link } from "react-router-dom";
import SidebarMenu from "../components/sidebar/SidebarMenu";
import { useAuth } from "../contexts/AuthContext";
import {
  getReviewStats, getReviewQueue, triageReview,
  addEvidence, makeDecision,
} from "../lib/api";

const PAGE = {
  background: "radial-gradient(ellipse at center, #002266 0%, #001133 100%)",
  minHeight: "100vh",
  color: "#ffffff",
  fontFamily: "'Inter', system-ui, sans-serif",
};

const CARD = {
  background: "rgba(255,255,255,0.04)",
  border: "1px solid rgba(255,255,255,0.08)",
  borderRadius: 14,
  padding: "1.25rem 1.5rem",
  marginBottom: "1rem",
};

const BTN = (color = "#00d4ff", fill = false) => ({
  padding: "0.45rem 1rem",
  borderRadius: 8,
  border: fill ? "none" : `1px solid ${color}55`,
  background: fill ? color : `${color}15`,
  color: fill ? "#000" : color,
  fontWeight: 600,
  fontSize: "0.8rem",
  cursor: "pointer",
  transition: "all 0.15s",
});

const PRIORITY_COLOR = { urgent: "#ff6b6b", normal: "#00d4ff", low: "#7eb3ff" };
const TYPE_COLOR = {
  auto_novelty: "#ffd700",
  auto_contamination: "#ff9b9b",
  manual_correction: "#00d4ff",
  manual_novelty: "#ffd700",
  manual_contamination: "#ff9b9b",
};

const STATE_ORDER = ["submitted", "triaged", "needs_evidence", "accepted", "rejected", "duplicate", "company_verified"];

function ReviewCard({ review, onRefresh }) {
  const { user } = useAuth();
  const [expanded, setExpanded] = useState(false);
  const [evidenceText, setEvidenceText] = useState("");
  const [adding, setAdding] = useState(false);
  const [deciding, setDeciding] = useState(false);
  const [triaging, setTriaging] = useState(false);
  const [actionError, setActionError] = useState("");

  const isClosed = ["accepted", "rejected", "duplicate", "company_verified", "included_in_training_batch"].includes(review.state);

  const handleTriage = async (priority) => {
    setTriaging(true);
    setActionError("");
    try {
      await triageReview(review.review_id, { priority, triaged_by: user?.user_id, notes: "" });
      onRefresh();
    } catch (e) { setActionError(e.message); }
    finally { setTriaging(false); }
  };

  const handleAddEvidence = async () => {
    if (!evidenceText.trim()) return;
    setAdding(true);
    setActionError("");
    try {
      await addEvidence(review.review_id, { evidence_text: evidenceText, submitted_by: user?.user_id });
      setEvidenceText("");
      onRefresh();
    } catch (e) { setActionError(e.message); }
    finally { setAdding(false); }
  };

  const handleDecision = async (decision) => {
    setDeciding(true);
    setActionError("");
    try {
      await makeDecision(review.review_id, { decision, decided_by: user?.user_id, notes: "" });
      onRefresh();
    } catch (e) { setActionError(e.message); }
    finally { setDeciding(false); }
  };

  return (
    <div style={{
      ...CARD,
      borderLeft: `3px solid ${PRIORITY_COLOR[review.triage_priority] || "#7eb3ff"}`,
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: 8, marginBottom: 8 }}>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <span style={{
            padding: "2px 10px", borderRadius: 999, fontSize: "0.7rem", fontWeight: 700,
            background: `${TYPE_COLOR[review.review_type] || "#7eb3ff"}22`,
            border: `1px solid ${TYPE_COLOR[review.review_type] || "#7eb3ff"}44`,
            color: TYPE_COLOR[review.review_type] || "#7eb3ff",
          }}>
            {review.review_type?.replace(/_/g, " ")}
          </span>
          <span style={{
            padding: "2px 10px", borderRadius: 999, fontSize: "0.7rem", fontWeight: 700,
            background: "rgba(255,255,255,0.06)", color: "#b3d9ff",
          }}>
            {review.state}
          </span>
          {review.triage_priority && (
            <span style={{
              padding: "2px 10px", borderRadius: 999, fontSize: "0.7rem", fontWeight: 700,
              background: `${PRIORITY_COLOR[review.triage_priority]}22`,
              color: PRIORITY_COLOR[review.triage_priority],
            }}>
              {review.triage_priority}
            </span>
          )}
        </div>
        <button onClick={() => setExpanded((v) => !v)} style={{ ...BTN("#7eb3ff"), background: "transparent" }}>
          {expanded ? "▲ Collapse" : "▼ Details"}
        </button>
      </div>

      <div style={{ display: "flex", gap: "1.5rem", flexWrap: "wrap", fontSize: "0.82rem", color: "#7eb3ff" }}>
        <span><strong style={{ color: "#b3d9ff" }}>Review:</strong> {review.review_id}</span>
        <span><strong style={{ color: "#b3d9ff" }}>Seq:</strong> {review.sequence_id || "—"}</span>
        {review.novelty_score != null && (
          <span><strong style={{ color: "#ffd700" }}>Novelty:</strong> {(review.novelty_score * 100).toFixed(1)}%</span>
        )}
        {review.contamination_score != null && (
          <span><strong style={{ color: "#ff9b9b" }}>Contam:</strong> {(review.contamination_score * 100).toFixed(1)}%</span>
        )}
      </div>

      {expanded && (
        <div style={{ marginTop: "1rem" }}>
          {review.notes && (
            <div style={{ color: "#b3d9ff", fontSize: "0.85rem", marginBottom: 8, fontStyle: "italic" }}>
              "{review.notes}"
            </div>
          )}

          {/* Triage actions (when submitted) */}
          {review.state === "submitted" && !isClosed && (
            <div style={{ display: "flex", gap: 8, marginBottom: "0.75rem", flexWrap: "wrap" }}>
              <span style={{ color: "#7eb3ff", fontSize: "0.8rem", alignSelf: "center" }}>Set priority:</span>
              {["urgent", "normal", "low"].map((p) => (
                <button key={p} onClick={() => handleTriage(p)} disabled={triaging} style={BTN(PRIORITY_COLOR[p])}>
                  {p}
                </button>
              ))}
            </div>
          )}

          {/* Evidence form */}
          {!isClosed && (
            <div style={{ marginBottom: "0.75rem" }}>
              <textarea
                value={evidenceText}
                onChange={(e) => setEvidenceText(e.target.value)}
                placeholder="Add evidence or notes..."
                rows={3}
                style={{
                  width: "100%", padding: "8px 12px",
                  borderRadius: 8, border: "1px solid rgba(255,255,255,0.12)",
                  background: "rgba(0,0,0,0.25)", color: "#fff",
                  fontSize: "0.85rem", resize: "vertical", fontFamily: "inherit",
                }}
              />
              <button
                onClick={handleAddEvidence}
                disabled={adding || !evidenceText.trim()}
                style={{ ...BTN("#00d4ff"), marginTop: 6 }}
              >
                {adding ? "Adding..." : "Add Evidence"}
              </button>
            </div>
          )}

          {/* Decision buttons */}
          {review.state !== "submitted" && !isClosed && (
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <span style={{ color: "#7eb3ff", fontSize: "0.8rem", alignSelf: "center" }}>Decision:</span>
              {[
                { d: "accepted", color: "#00ff88" },
                { d: "rejected", color: "#ff6b6b" },
                { d: "duplicate", color: "#7eb3ff" },
                { d: "needs_evidence", color: "#ffd700" },
              ].map(({ d, color }) => (
                <button key={d} onClick={() => handleDecision(d)} disabled={deciding} style={BTN(color)}>
                  {d.replace(/_/g, " ")}
                </button>
              ))}
            </div>
          )}

          {actionError && (
            <div style={{ marginTop: 8, color: "#ff9b9b", fontSize: "0.8rem" }}>{actionError}</div>
          )}
        </div>
      )}
    </div>
  );
}

export default function ReviewQueue() {
  const [stats, setStats] = useState(null);
  const [queue, setQueue] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState("submitted");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [s, q] = await Promise.all([
        getReviewStats(),
        getReviewQueue({ state: filter }),
      ]);
      setStats(s);
      setQueue(q?.reviews || q || []);
    } catch (e) {
      setError(e.message || "Failed to load review queue.");
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => { load(); }, [load]);

  return (
    <div style={PAGE}>
      <SidebarMenu />
      <div style={{ maxWidth: 1000, margin: "0 auto", padding: "2rem 1.5rem" }}>
        <h1 style={{
          fontSize: "1.75rem", fontWeight: 800, marginBottom: 8,
          background: "linear-gradient(135deg, #0066ff 0%, #00d4ff 100%)",
          WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent", backgroundClip: "text",
        }}>
          Review Queue
        </h1>

        {/* Stats bar */}
        {stats && (
          <div style={{
            display: "flex", gap: "1rem", flexWrap: "wrap",
            margin: "1rem 0 1.5rem",
          }}>
            {[
              ["Total Pending", stats.total_pending, "#00d4ff"],
              ["Auto-Novelty", stats.auto_novelty_pending, "#ffd700"],
              ["Auto-Contam.", stats.auto_contamination_pending, "#ff9b9b"],
            ].map(([label, value, color]) => (
              <div key={label} style={{
                padding: "8px 16px", borderRadius: 10,
                background: `${color}10`, border: `1px solid ${color}30`,
                fontSize: "0.85rem",
              }}>
                <span style={{ color: "#7eb3ff" }}>{label}: </span>
                <strong style={{ color }}>{value ?? "—"}</strong>
              </div>
            ))}
          </div>
        )}

        {/* State filter */}
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: "1.25rem" }}>
          {STATE_ORDER.map((s) => (
            <button
              key={s}
              onClick={() => setFilter(s)}
              style={{
                padding: "5px 14px", borderRadius: 999, border: "1px solid rgba(255,255,255,0.15)",
                background: filter === s ? "rgba(0,212,255,0.15)" : "transparent",
                color: filter === s ? "#00d4ff" : "#7eb3ff",
                fontWeight: filter === s ? 700 : 400,
                fontSize: "0.8rem", cursor: "pointer",
              }}
            >
              {s.replace(/_/g, " ")}
            </button>
          ))}
          <button
            onClick={load}
            style={{ padding: "5px 14px", borderRadius: 999, border: "1px solid rgba(255,255,255,0.1)", background: "transparent", color: "#7eb3ff", cursor: "pointer", fontSize: "0.8rem" }}
          >
            ↻ Refresh
          </button>
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
          <div style={{ textAlign: "center", padding: "3rem", color: "#7eb3ff" }}>Loading reviews...</div>
        ) : queue.length === 0 ? (
          <div style={{
            textAlign: "center", padding: "3rem", color: "#7eb3ff",
            border: "1px solid rgba(255,255,255,0.06)", borderRadius: 14,
            background: "rgba(255,255,255,0.02)",
          }}>
            No reviews in state "{filter.replace(/_/g, " ")}".
          </div>
        ) : (
          queue.map((review) => (
            <ReviewCard key={review.review_id} review={review} onRefresh={load} />
          ))
        )}
      </div>
    </div>
  );
}
