import React, { useEffect, useState } from "react";
import NavBar from "../components/NavBar";
import { getModels } from "../lib/api";

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
  transition: "border-color 0.2s",
};

const STATUS_COLOR = {
  active: "#00ff88",
  inactive: "#7eb3ff",
  deprecated: "#ff9b9b",
  stub: "#ffd700",
};

export default function ModelStatus() {
  const [models, setModels] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getModels()
      .then((data) => {
        // backend may return array or {models: [...]}
        setModels(Array.isArray(data) ? data : data?.models || data?.items || []);
      })
      .catch((e) => setError(e.message || "Failed to load models."))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div style={PAGE}>
      <NavBar />
      <div style={{ maxWidth: 1000, margin: "0 auto", padding: "2rem 1.5rem" }}>
        <h1 style={{
          fontSize: "1.75rem", fontWeight: 800, marginBottom: "0.5rem",
          background: "linear-gradient(135deg, #0066ff 0%, #00d4ff 100%)",
          WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent", backgroundClip: "text",
        }}>
          Model Registry
        </h1>
        <p style={{ color: "#b3d9ff", fontSize: "0.9rem", marginBottom: "1.75rem" }}>
          All registered eDNA classification models. Models update only after curated monthly retraining —
          never from live user feedback.
        </p>

        <div style={{
          padding: "10px 16px",
          borderRadius: 10,
          background: "rgba(255,165,0,0.06)",
          border: "1px solid rgba(255,165,0,0.2)",
          color: "#ffaa55",
          fontSize: "0.8rem",
          marginBottom: "1.5rem",
        }}>
          ⚠ Anti-poisoning policy: model weights update only after expert-curated monthly training batches.
          User feedback is stored for curation review; it never directly modifies live model weights.
        </div>

        {loading && <div style={{ textAlign: "center", padding: "3rem", color: "#7eb3ff" }}>Loading models...</div>}

        {error && (
          <div style={{
            padding: "12px 16px", borderRadius: 10,
            background: "rgba(255,80,80,0.08)", border: "1px solid rgba(255,80,80,0.2)",
            color: "#ff9b9b",
          }}>
            {error}
          </div>
        )}

        {models && models.length === 0 && !error && (
          <div style={{
            textAlign: "center", padding: "3rem", color: "#7eb3ff",
            border: "1px solid rgba(255,255,255,0.06)", borderRadius: 14,
            background: "rgba(255,255,255,0.02)",
          }}>
            No models registered yet. Models are added during monthly training releases.
          </div>
        )}

        {models && models.map((m, i) => {
          const statusColor = STATUS_COLOR[m.status] || STATUS_COLOR[m.is_active ? "active" : "inactive"] || "#7eb3ff";
          return (
            <div key={m.model_id || m.version || i} style={{
              ...CARD,
              borderLeft: `3px solid ${statusColor}`,
            }}>
              <div style={{ display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: 8, marginBottom: 8 }}>
                <div>
                  <h3 style={{ fontSize: "1rem", fontWeight: 700, color: "#ffffff", marginBottom: 2 }}>
                    {m.model_version || m.version || m.name || `Model ${i + 1}`}
                  </h3>
                  <div style={{ color: "#7eb3ff", fontSize: "0.8rem" }}>
                    {m.route && <span>Route: <strong style={{ color: "#b3d9ff" }}>{m.route}</strong> · </span>}
                    {m.model_type && <span>Type: <strong style={{ color: "#b3d9ff" }}>{m.model_type}</strong></span>}
                  </div>
                </div>
                <div style={{
                  padding: "4px 12px", borderRadius: 999, fontSize: "0.75rem", fontWeight: 700, alignSelf: "flex-start",
                  background: `${statusColor}18`, border: `1px solid ${statusColor}44`, color: statusColor,
                }}>
                  {m.status || (m.is_active ? "active" : "inactive")}
                </div>
              </div>

              <div style={{ display: "flex", gap: "1.5rem", flexWrap: "wrap", fontSize: "0.82rem", color: "#7eb3ff" }}>
                {m.base_model_name && <span>Base: <strong style={{ color: "#b3d9ff" }}>{m.base_model_name}</strong></span>}
                {m.training_batch_id && <span>Batch: <code style={{ color: "#00d4ff", fontFamily: "monospace" }}>{m.training_batch_id}</code></span>}
                {m.accuracy_on_holdout != null && (
                  <span>Holdout acc: <strong style={{ color: "#00ff88" }}>{(m.accuracy_on_holdout * 100).toFixed(1)}%</strong></span>
                )}
                {m.f1_on_holdout != null && (
                  <span>F1: <strong style={{ color: "#00ff88" }}>{m.f1_on_holdout.toFixed(3)}</strong></span>
                )}
                {m.param_count_millions != null && (
                  <span>{m.param_count_millions}M params</span>
                )}
                {m.created_at && (
                  <span>Created: {new Date(m.created_at).toLocaleDateString()}</span>
                )}
              </div>

              {m.notes && (
                <div style={{ marginTop: 8, color: "#5a8fb3", fontSize: "0.8rem", fontStyle: "italic" }}>{m.notes}</div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
