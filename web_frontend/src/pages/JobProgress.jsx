import React, { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import NavBar from "../components/NavBar";
import { getJob } from "../lib/api";

const PAGE = {
  background: "radial-gradient(ellipse at center, #002266 0%, #001133 100%)",
  minHeight: "100vh",
  color: "#ffffff",
  fontFamily: "'Inter', system-ui, sans-serif",
};

const STAGES = [
  "queued", "parsing", "qc", "routing",
  "inferencing", "novelty_scoring", "reporting", "completed",
];
const STAGE_LABELS = {
  queued: "Queued",
  parsing: "Parsing sequences",
  qc: "Quality control",
  routing: "Taxonomic routing",
  inferencing: "Running inference",
  novelty_scoring: "Novelty scoring",
  reporting: "Building report",
  completed: "Complete",
  failed: "Failed",
};

function StageBar({ state }) {
  const idx = STAGES.indexOf(state);
  const isFailed = state === "failed";
  return (
    <div style={{ margin: "2rem 0" }}>
      <div style={{ display: "flex", position: "relative", justifyContent: "space-between" }}>
        {/* Track line */}
        <div style={{
          position: "absolute", top: 12, left: "6%", right: "6%", height: 2,
          background: "rgba(255,255,255,0.1)", zIndex: 0,
        }} />
        {isFailed ? null : (
          <div style={{
            position: "absolute", top: 12, left: "6%",
            width: `${Math.max(0, (idx / (STAGES.length - 1)) * 88)}%`,
            height: 2,
            background: "linear-gradient(90deg, #0066ff, #00d4ff)",
            zIndex: 1,
            transition: "width 0.6s ease",
          }} />
        )}
        {STAGES.filter((s) => s !== "failed").map((s, i) => {
          const done = STAGES.indexOf(state) > i;
          const active = s === state;
          return (
            <div key={s} style={{ display: "flex", flexDirection: "column", alignItems: "center", zIndex: 2, flex: 1 }}>
              <div style={{
                width: 24, height: 24, borderRadius: "50%",
                background: done ? "#00d4ff" : active ? "#0066ff" : "rgba(255,255,255,0.1)",
                border: active ? "3px solid #00d4ff" : done ? "none" : "2px solid rgba(255,255,255,0.2)",
                display: "flex", alignItems: "center", justifyContent: "center",
                fontSize: 11, color: done || active ? "#000" : "#7eb3ff",
                fontWeight: 700, boxShadow: active ? "0 0 12px rgba(0,212,255,0.5)" : "none",
                transition: "all 0.3s",
              }}>
                {done ? "✓" : i + 1}
              </div>
              <div style={{
                marginTop: 8, fontSize: "0.65rem", color: done || active ? "#b3d9ff" : "#5a7a9a",
                textAlign: "center", maxWidth: 60, lineHeight: 1.3,
                fontWeight: active ? 700 : 400,
              }}>
                {STAGE_LABELS[s]}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default function JobProgress() {
  const { job_id } = useParams();
  const navigate = useNavigate();
  const [job, setJob] = useState(null);
  const [error, setError] = useState("");
  const intervalRef = useRef(null);
  const pollCount = useRef(0);

  const poll = async () => {
    try {
      const data = await getJob(job_id);
      setJob(data);
      if (data.state === "completed" && data.analysis_id) {
        clearInterval(intervalRef.current);
      }
      if (data.state === "failed") {
        clearInterval(intervalRef.current);
      }
    } catch (e) {
      setError(e.message || "Failed to load job status.");
      clearInterval(intervalRef.current);
    }
    pollCount.current += 1;
    if (pollCount.current > 200) clearInterval(intervalRef.current); // 10-min safety stop
  };

  useEffect(() => {
    poll();
    intervalRef.current = setInterval(poll, 3000);
    return () => clearInterval(intervalRef.current);
  }, [job_id]); // eslint-disable-line react-hooks/exhaustive-deps

  const isComplete = job?.state === "completed";
  const isFailed = job?.state === "failed";

  return (
    <div style={PAGE}>
      <NavBar />
      <div style={{ maxWidth: 800, margin: "0 auto", padding: "2rem 1.5rem" }}>
        <Link to="/dashboard" style={{ color: "#7eb3ff", textDecoration: "none", fontSize: "0.85rem" }}>
          ← Dashboard
        </Link>
        <h1 style={{
          fontSize: "1.75rem", fontWeight: 800, margin: "0.75rem 0 0.5rem",
          background: "linear-gradient(135deg, #0066ff 0%, #00d4ff 100%)",
          WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent", backgroundClip: "text",
        }}>
          Analysis Job
        </h1>
        <p style={{ color: "#7eb3ff", fontSize: "0.85rem", marginBottom: "2rem" }}>
          Job ID: <code style={{ fontFamily: "monospace", color: "#00d4ff" }}>{job_id}</code>
        </p>

        {error && (
          <div style={{
            padding: "1rem", borderRadius: 12,
            background: "rgba(255,80,80,0.08)", border: "1px solid rgba(255,80,80,0.2)",
            color: "#ff9b9b", marginBottom: "1.5rem",
          }}>
            {error}
          </div>
        )}

        {job && (
          <div style={{
            background: "rgba(255,255,255,0.05)", border: "1px solid rgba(255,255,255,0.1)",
            borderRadius: 16, padding: "2rem",
          }}>
            {/* State badge */}
            <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: "1rem" }}>
              <div style={{
                padding: "4px 14px", borderRadius: 999, fontWeight: 700, fontSize: "0.85rem",
                background: isComplete ? "rgba(0,255,136,0.15)" : isFailed ? "rgba(255,80,80,0.15)" : "rgba(0,102,255,0.15)",
                border: `1px solid ${isComplete ? "rgba(0,255,136,0.3)" : isFailed ? "rgba(255,80,80,0.3)" : "rgba(0,102,255,0.3)"}`,
                color: isComplete ? "#00ff88" : isFailed ? "#ff9b9b" : "#00d4ff",
              }}>
                {STAGE_LABELS[job.state] || job.state}
              </div>
              {!isComplete && !isFailed && (
                <div style={{ color: "#7eb3ff", fontSize: "0.85rem" }}>
                  <span style={{
                    display: "inline-block",
                    animation: "pulse 1.5s ease-in-out infinite",
                  }}>
                    ⟳
                  </span>{" "}
                  Updating every 3s...
                </div>
              )}
            </div>

            <StageBar state={job.state} />

            {/* Job details */}
            <div style={{
              display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))",
              gap: "1rem", marginTop: "1.5rem",
            }}>
              {[
                { label: "Upload ID", value: job.upload_id },
                { label: "Mode", value: job.mode },
                { label: "Created", value: job.created_at ? new Date(job.created_at).toLocaleString() : "—" },
                { label: "Updated", value: job.updated_at ? new Date(job.updated_at).toLocaleString() : "—" },
              ].map(({ label, value }) => (
                <div key={label} style={{
                  background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.06)",
                  borderRadius: 10, padding: "0.75rem 1rem",
                }}>
                  <div style={{ color: "#7eb3ff", fontSize: "0.7rem", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 4 }}>
                    {label}
                  </div>
                  <div style={{ color: "#b3d9ff", fontSize: "0.85rem", wordBreak: "break-all" }}>
                    {value || "—"}
                  </div>
                </div>
              ))}
            </div>

            {/* Error detail on failure */}
            {isFailed && job.error_detail && (
              <div style={{
                marginTop: "1.25rem", padding: "1rem", borderRadius: 10,
                background: "rgba(255,80,80,0.06)", border: "1px solid rgba(255,80,80,0.15)",
                color: "#ff9b9b", fontSize: "0.875rem",
              }}>
                <strong>Error: </strong>{job.error_detail}
              </div>
            )}

            {/* Action buttons */}
            <div style={{ marginTop: "1.5rem", display: "flex", gap: "1rem" }}>
              {isComplete && job.analysis_id && (
                <Link
                  to={`/analysis/${job.analysis_id}`}
                  style={{
                    padding: "0.7rem 1.5rem", borderRadius: 12,
                    background: "linear-gradient(135deg, #0066ff 0%, #00d4ff 100%)",
                    color: "white", textDecoration: "none", fontWeight: 700, fontSize: "0.95rem",
                  }}
                >
                  View Report →
                </Link>
              )}
              {isFailed && (
                <Link
                  to="/upload"
                  style={{
                    padding: "0.7rem 1.5rem", borderRadius: 12,
                    background: "rgba(255,255,255,0.08)", color: "#b3d9ff",
                    textDecoration: "none", fontWeight: 600, fontSize: "0.9rem",
                    border: "1px solid rgba(255,255,255,0.1)",
                  }}
                >
                  Try Again
                </Link>
              )}
            </div>
          </div>
        )}

        {!job && !error && (
          <div style={{ textAlign: "center", padding: "3rem", color: "#7eb3ff" }}>
            Loading job status...
          </div>
        )}
      </div>
      <style>{`@keyframes pulse{0%,100%{opacity:1}50%{opacity:0.3}}`}</style>
    </div>
  );
}
