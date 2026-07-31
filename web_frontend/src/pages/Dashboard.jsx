import React, { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";
import NavBar from "../components/NavBar";
import DnaHelixViz from "../components/DnaHelixViz";
import { getReviewStats } from "../lib/api";

const PAGE = {
  background: "radial-gradient(ellipse at center, #002266 0%, #001133 100%)",
  minHeight: "100vh",
  color: "#ffffff",
  fontFamily: "'Inter', system-ui, sans-serif",
};

const CARD = {
  background: "rgba(255,255,255,0.05)",
  backdropFilter: "blur(20px)",
  border: "1px solid rgba(255,255,255,0.1)",
  borderRadius: 16,
  padding: "1.5rem",
};

const GRID = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
  gap: "1.25rem",
  margin: "0 auto",
  maxWidth: 1200,
  padding: "1.5rem",
};

const STAT_CARD = {
  ...CARD,
  textAlign: "center",
  position: "relative",
  overflow: "hidden",
};

const ACTION_BTN = {
  display: "inline-flex",
  alignItems: "center",
  gap: 8,
  padding: "0.6rem 1.25rem",
  borderRadius: 10,
  border: "none",
  cursor: "pointer",
  fontWeight: 600,
  fontSize: "0.9rem",
  textDecoration: "none",
  transition: "all 0.2s",
};

export default function Dashboard() {
  const { user, isCurator, isAdmin } = useAuth();
  const navigate = useNavigate();
  const [reviewStats, setReviewStats] = useState(null);
  const [statsError, setStatsError] = useState(null);

  useEffect(() => {
    if (isCurator) {
      getReviewStats()
        .then(setReviewStats)
        .catch((e) => setStatsError(e.message));
    }
  }, [isCurator]);

  return (
    <div style={PAGE}>
      <NavBar />
      <div style={{ maxWidth: 1200, margin: "0 auto", padding: "2rem 1.5rem" }}>
        {/* Welcome header */}
        <div style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: "1.5rem",
          flexWrap: "wrap",
          marginBottom: "2rem",
        }}>
          <div>
            <h1 style={{
              fontSize: "clamp(1.5rem, 3vw, 2rem)",
              fontWeight: 800,
              background: "linear-gradient(135deg, #0066ff 0%, #00d4ff 100%)",
              WebkitBackgroundClip: "text",
              WebkitTextFillColor: "transparent",
              backgroundClip: "text",
              marginBottom: 6,
            }}>
              Welcome back{user?.display_name ? `, ${user.display_name}` : ""}
            </h1>
            <p style={{ color: "#b3d9ff", fontSize: "0.95rem" }}>
              {user?.email} · <span style={{
                textTransform: "uppercase",
                fontSize: "0.75rem",
                background: "rgba(0,102,255,0.2)",
                border: "1px solid rgba(0,102,255,0.4)",
                padding: "2px 8px",
                borderRadius: 999,
                color: "#7eb3ff",
              }}>{user?.role}</span>
            </p>
          </div>
          <div style={{ width: 220, minWidth: 180, flexShrink: 0 }}>
            <DnaHelixViz height={180} />
          </div>
        </div>

        {/* Primary actions */}
        <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap", marginBottom: "2rem" }}>
          <Link to="/upload" style={{
            ...ACTION_BTN,
            background: "linear-gradient(135deg, #0066ff 0%, #00d4ff 100%)",
            color: "white",
            boxShadow: "0 8px 24px rgba(0,102,255,0.3)",
          }}>
            ↑ Upload New Sample
          </Link>
          <Link to="/models" style={{
            ...ACTION_BTN,
            background: "rgba(255,255,255,0.08)",
            color: "#b3d9ff",
            border: "1px solid rgba(255,255,255,0.1)",
          }}>
            ◈ Model Status
          </Link>
          <Link to="/abyss" style={{
            ...ACTION_BTN,
            background: "rgba(255,255,255,0.08)",
            color: "#b3d9ff",
            border: "1px solid rgba(255,255,255,0.1)",
          }}>
            ⬡ Abyss Mode
          </Link>
        </div>

        {/* Quick-start guide when no analyses yet */}
        <div style={GRID}>
          <div style={CARD}>
            <div style={{ fontSize: "1.75rem", marginBottom: 10 }}>①</div>
            <h3 style={{ fontSize: "1rem", fontWeight: 700, marginBottom: 8, color: "#00d4ff" }}>
              Upload a Sample
            </h3>
            <p style={{ color: "#b3d9ff", fontSize: "0.875rem", lineHeight: 1.6, marginBottom: 12 }}>
              Submit a FASTA or JSON file with optional environmental metadata
              (depth, GPS coordinates, habitat type).
            </p>
            <Link to="/upload" style={{ color: "#00d4ff", fontSize: "0.85rem", textDecoration: "none" }}>
              Go to Upload →
            </Link>
          </div>

          <div style={CARD}>
            <div style={{ fontSize: "1.75rem", marginBottom: 10 }}>②</div>
            <h3 style={{ fontSize: "1rem", fontWeight: 700, marginBottom: 8, color: "#00d4ff" }}>
              Track Your Job
            </h3>
            <p style={{ color: "#b3d9ff", fontSize: "0.875rem", lineHeight: 1.6 }}>
              After submission, watch the pipeline progress through QC → routing →
              inference → novelty scoring → report generation.
            </p>
          </div>

          <div style={CARD}>
            <div style={{ fontSize: "1.75rem", marginBottom: 10 }}>③</div>
            <h3 style={{ fontSize: "1rem", fontWeight: 700, marginBottom: 8, color: "#00d4ff" }}>
              Review Results
            </h3>
            <p style={{ color: "#b3d9ff", fontSize: "0.875rem", lineHeight: 1.6 }}>
              Get a full biodiversity report: Shannon diversity index, novelty flags,
              contamination warnings, and known species table.
            </p>
          </div>

          {/* Curator stats card */}
          {isCurator && (
            <div style={STAT_CARD}>
              <div style={{ fontSize: "1.75rem", marginBottom: 10 }}>📋</div>
              <h3 style={{ fontSize: "1rem", fontWeight: 700, marginBottom: 8, color: "#00d4ff" }}>
                Review Queue
              </h3>
              {reviewStats ? (
                <>
                  <div style={{ fontSize: "2.5rem", fontWeight: 800, color: "#00d4ff", marginBottom: 4 }}>
                    {reviewStats.total_pending ?? "—"}
                  </div>
                  <div style={{ color: "#7eb3ff", fontSize: "0.8rem", marginBottom: 12 }}>
                    pending reviews
                    {reviewStats.auto_novelty_pending > 0 && (
                      <span style={{ display: "block", marginTop: 4, color: "#ffd700" }}>
                        {reviewStats.auto_novelty_pending} novelty flags
                      </span>
                    )}
                  </div>
                </>
              ) : statsError ? (
                <div style={{ color: "#ff9b9b", fontSize: "0.8rem", marginBottom: 12 }}>{statsError}</div>
              ) : (
                <div style={{ color: "#7eb3ff", fontSize: "0.85rem", marginBottom: 12 }}>Loading...</div>
              )}
              <Link to="/reviews" style={{ color: "#00d4ff", fontSize: "0.85rem", textDecoration: "none" }}>
                Open Queue →
              </Link>
            </div>
          )}

          {/* Admin card */}
          {isAdmin && (
            <div style={STAT_CARD}>
              <div style={{ fontSize: "1.75rem", marginBottom: 10 }}>🔧</div>
              <h3 style={{ fontSize: "1rem", fontWeight: 700, marginBottom: 8, color: "#ff6b6b" }}>
                Admin Panel
              </h3>
              <p style={{ color: "#b3d9ff", fontSize: "0.875rem", lineHeight: 1.6, marginBottom: 12 }}>
                Manage training batches, freeze curated data, and monitor model health.
              </p>
              <Link to="/admin" style={{ color: "#ff6b6b", fontSize: "0.85rem", textDecoration: "none" }}>
                Open Admin →
              </Link>
            </div>
          )}

          <div style={CARD}>
            <div style={{ fontSize: "1.75rem", marginBottom: 10 }}>⚡</div>
            <h3 style={{ fontSize: "1rem", fontWeight: 700, marginBottom: 8, color: "#00d4ff" }}>
              Abyss Mode
            </h3>
            <p style={{ color: "#b3d9ff", fontSize: "0.875rem", lineHeight: 1.6, marginBottom: 12 }}>
              Field-triage system for offline deep-sea expeditions. Requires an
              offline license valid up to 90 days.
            </p>
            <div style={{
              padding: "8px 12px",
              background: "rgba(255,165,0,0.08)",
              border: "1px solid rgba(255,165,0,0.2)",
              borderRadius: 8,
              fontSize: "0.75rem",
              color: "#ffaa55",
            }}>
              ⚠ Results are preliminary — confirm with full online analysis.
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
