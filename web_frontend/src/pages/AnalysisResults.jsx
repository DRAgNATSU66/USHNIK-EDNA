import React, { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import NavBar from "../components/NavBar";
import { getReport, exportReportJson } from "../lib/api";

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
  padding: "1.25rem 1.5rem",
  marginBottom: "1.25rem",
});

const H = (size = "1rem", color = "#b3d9ff") => ({
  fontSize: size, fontWeight: 700, color, marginBottom: "1rem",
});

const DISCLAIMER_STYLE = {
  padding: "12px 16px",
  borderRadius: 10,
  background: "rgba(255,165,0,0.06)",
  border: "1px solid rgba(255,165,0,0.2)",
  color: "#ffaa55",
  fontSize: "0.8rem",
  lineHeight: 1.5,
  marginBottom: "1.5rem",
};

const BADGE = (color) => ({
  display: "inline-block",
  padding: "2px 10px",
  borderRadius: 999,
  fontSize: "0.7rem",
  fontWeight: 700,
  background: `${color}22`,
  border: `1px solid ${color}55`,
  color,
});

function StatCard({ label, value, accent = "#00d4ff" }) {
  return (
    <div style={{
      background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)",
      borderRadius: 12, padding: "1.25rem", textAlign: "center",
    }}>
      <div style={{ fontSize: "2rem", fontWeight: 800, color: accent, marginBottom: 4 }}>
        {value}
      </div>
      <div style={{ color: "#7eb3ff", fontSize: "0.75rem", textTransform: "uppercase", letterSpacing: "0.05em" }}>
        {label}
      </div>
    </div>
  );
}

function ProgressBar({ fraction, color = "#00d4ff" }) {
  return (
    <div style={{ height: 8, background: "rgba(255,255,255,0.08)", borderRadius: 4, overflow: "hidden" }}>
      <div style={{
        height: "100%", width: `${Math.min(fraction * 100, 100)}%`,
        background: `linear-gradient(90deg, ${color}, ${color}aa)`,
        borderRadius: 4, transition: "width 0.6s",
      }} />
    </div>
  );
}

export default function AnalysisResults() {
  const { analysis_id } = useParams();
  const [report, setReport] = useState(null);
  const [error, setError] = useState("");
  const [downloading, setDownloading] = useState(false);

  useEffect(() => {
    getReport(analysis_id)
      .then(setReport)
      .catch((e) => setError(e.message || "Failed to load report."));
  }, [analysis_id]);

  const handleExport = async () => {
    setDownloading(true);
    try {
      const resp = await exportReportJson(analysis_id);
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `synthveda_report_${analysis_id}.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      alert("Export failed: " + e.message);
    } finally {
      setDownloading(false);
    }
  };

  if (error) {
    return (
      <div style={PAGE}>
        <NavBar />
        <div style={{ maxWidth: 800, margin: "4rem auto", padding: "0 1.5rem", textAlign: "center" }}>
          <div style={{ fontSize: "2.5rem", marginBottom: 16 }}>⚠</div>
          <div style={{ color: "#ff9b9b", fontSize: "1.1rem", marginBottom: 16 }}>{error}</div>
          <Link to="/dashboard" style={{ color: "#00d4ff", textDecoration: "none" }}>← Dashboard</Link>
        </div>
      </div>
    );
  }

  if (!report) {
    return (
      <div style={PAGE}>
        <NavBar />
        <div style={{ textAlign: "center", padding: "4rem", color: "#7eb3ff" }}>Loading report...</div>
      </div>
    );
  }

  const { metadata, qc_summary, biodiversity, route_distribution, known_species,
          possible_novelty, contamination_warnings, model_versions_used,
          review_status, disclaimer } = report;

  return (
    <div style={PAGE}>
      <NavBar />
      <div style={{ maxWidth: 1100, margin: "0 auto", padding: "2rem 1.5rem" }}>
        {/* Header */}
        <div style={{ display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: "1rem", marginBottom: "1.5rem" }}>
          <div>
            <Link to="/dashboard" style={{ color: "#7eb3ff", textDecoration: "none", fontSize: "0.85rem" }}>
              ← Dashboard
            </Link>
            <h1 style={{
              fontSize: "1.75rem", fontWeight: 800, marginTop: 8,
              background: "linear-gradient(135deg, #0066ff 0%, #00d4ff 100%)",
              WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent", backgroundClip: "text",
            }}>
              Analysis Report
            </h1>
            <p style={{ color: "#7eb3ff", fontSize: "0.85rem" }}>
              {metadata?.source_file && <span>{metadata.source_file} · </span>}
              {analysis_id}
            </p>
          </div>
          <button
            onClick={handleExport}
            disabled={downloading}
            style={{
              padding: "0.6rem 1.25rem", borderRadius: 10, border: "1px solid rgba(0,212,255,0.3)",
              background: "rgba(0,212,255,0.08)", color: "#00d4ff", fontWeight: 600, cursor: "pointer",
              alignSelf: "flex-end",
            }}
          >
            {downloading ? "Exporting..." : "⬇ Export JSON"}
          </button>
        </div>

        {/* Disclaimer */}
        {disclaimer && <div style={DISCLAIMER_STYLE}>⚠ {disclaimer}</div>}

        {/* Biodiversity KPIs */}
        {biodiversity && (
          <div style={{
            display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))",
            gap: "1rem", marginBottom: "1.5rem",
          }}>
            <StatCard label="Sequences" value={biodiversity.total_sequences} />
            <StatCard label="Route Richness" value={biodiversity.route_richness} accent="#00ff88" />
            <StatCard label="Shannon H" value={biodiversity.shannon_diversity_index?.toFixed(3)} accent="#00d4ff" />
            <StatCard label="Novelty %" value={`${(biodiversity.novelty_fraction * 100).toFixed(1)}%`} accent="#ffd700" />
            <StatCard label="Contam. %" value={`${(biodiversity.contamination_fraction * 100).toFixed(1)}%`} accent="#ff6b6b" />
            {biodiversity.dominant_route && (
              <StatCard label="Dominant Route" value={biodiversity.dominant_route} accent="#a78bfa" />
            )}
          </div>
        )}

        {/* QC Summary */}
        {qc_summary && (
          <div style={CARD("#00ff88")}>
            <h2 style={H("1rem", "#00ff88")}>Quality Control</h2>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))", gap: "0.75rem" }}>
              {[
                ["Total Sequences", qc_summary.total_sequences],
                ["Passed QC", qc_summary.passed_qc],
                ["Low Quality", qc_summary.low_quality_count],
                ["Mean Length", `${qc_summary.mean_length} bp`],
                ["Mean GC Ratio", qc_summary.mean_gc_ratio?.toFixed(3)],
                ["Invalid Chars", qc_summary.has_invalid_chars_count],
              ].map(([k, v]) => (
                <div key={k} style={{ fontSize: "0.85rem" }}>
                  <span style={{ color: "#7eb3ff" }}>{k}: </span>
                  <strong style={{ color: "#ffffff" }}>{v ?? "—"}</strong>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Route Distribution */}
        {route_distribution?.length > 0 && (
          <div style={CARD("#a78bfa")}>
            <h2 style={H("1rem", "#a78bfa")}>Route Distribution</h2>
            <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
              {route_distribution.map(({ route, count, fraction }) => (
                <div key={route}>
                  <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
                    <span style={{ color: "#b3d9ff", fontSize: "0.85rem" }}>{route}</span>
                    <span style={{ color: "#7eb3ff", fontSize: "0.8rem" }}>{count} ({(fraction * 100).toFixed(1)}%)</span>
                  </div>
                  <ProgressBar fraction={fraction} color="#a78bfa" />
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Known Species */}
        {known_species?.length > 0 && (
          <div style={CARD("#00ff88")}>
            <h2 style={H("1rem", "#00ff88")}>Known Species ({known_species.length})</h2>
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.85rem" }}>
                <thead>
                  <tr style={{ borderBottom: "1px solid rgba(255,255,255,0.08)" }}>
                    {["Sequence ID", "Taxon", "Route", "Confidence", "Model"].map((h) => (
                      <th key={h} style={{ padding: "6px 10px", textAlign: "left", color: "#7eb3ff", fontWeight: 600 }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {known_species.map((sp) => (
                    <tr key={sp.sequence_id} style={{ borderBottom: "1px solid rgba(255,255,255,0.04)" }}>
                      <td style={{ padding: "6px 10px", color: "#b3d9ff" }}>{sp.sequence_id}</td>
                      <td style={{ padding: "6px 10px", color: "#00ff88", fontStyle: "italic" }}>{sp.predicted_taxon || "—"}</td>
                      <td style={{ padding: "6px 10px", color: "#b3d9ff" }}>{sp.route}</td>
                      <td style={{ padding: "6px 10px", color: "#00d4ff" }}>{(sp.confidence * 100).toFixed(1)}%</td>
                      <td style={{ padding: "6px 10px", color: "#7eb3ff", fontSize: "0.75rem" }}>{sp.model_version_used || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Possible Novelty */}
        {possible_novelty?.length > 0 && (
          <div style={CARD("#ffd700")}>
            <h2 style={H("1rem", "#ffd700")}>Possible Novelty ({possible_novelty.length})</h2>
            <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
              {possible_novelty.map((n) => (
                <div key={n.sequence_id} style={{
                  background: "rgba(255,215,0,0.04)", border: "1px solid rgba(255,215,0,0.12)",
                  borderRadius: 10, padding: "0.875rem 1rem",
                }}>
                  <div style={{ display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: 8, marginBottom: 8 }}>
                    <span style={{ color: "#b3d9ff", fontFamily: "monospace", fontSize: "0.85rem" }}>
                      {n.sequence_id}
                    </span>
                    <div style={{ display: "flex", gap: 6 }}>
                      <span style={BADGE("#ffd700")}>novelty {(n.novelty_score * 100).toFixed(1)}%</span>
                      <span style={BADGE("#7eb3ff")}>{n.novelty_level}</span>
                      {n.requires_cloud_confirmation && (
                        <span style={BADGE("#ff9b9b")}>cloud confirm needed</span>
                      )}
                    </div>
                  </div>
                  <div style={{ color: "#7eb3ff", fontSize: "0.8rem" }}>
                    Route: {n.route} · Recommendation: <strong style={{ color: "#ffd700" }}>{n.abyss_recommendation}</strong>
                  </div>
                  {n.reason_codes?.length > 0 && (
                    <div style={{ marginTop: 6, color: "#5a8fb3", fontSize: "0.75rem" }}>
                      Reason codes: {n.reason_codes.join(", ")}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Contamination Warnings */}
        {contamination_warnings?.length > 0 && (
          <div style={CARD("#ff6b6b")}>
            <h2 style={H("1rem", "#ff6b6b")}>Contamination Warnings ({contamination_warnings.length})</h2>
            <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
              {contamination_warnings.map((w) => (
                <div key={w.sequence_id} style={{
                  background: "rgba(255,80,80,0.04)", border: "1px solid rgba(255,80,80,0.12)",
                  borderRadius: 10, padding: "0.875rem 1rem",
                }}>
                  <div style={{ display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: 8, marginBottom: 8 }}>
                    <span style={{ color: "#b3d9ff", fontFamily: "monospace", fontSize: "0.85rem" }}>{w.sequence_id}</span>
                    <span style={BADGE("#ff6b6b")}>contam {(w.contamination_score * 100).toFixed(1)}%</span>
                  </div>
                  <div style={{ color: "#7eb3ff", fontSize: "0.8rem" }}>
                    Route: {w.route}
                    {w.contamination_type && <> · Type: <strong style={{ color: "#ff9b9b" }}>{w.contamination_type}</strong></>}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Model Versions */}
        {model_versions_used?.length > 0 && (
          <div style={CARD("#7eb3ff")}>
            <h2 style={H("1rem", "#7eb3ff")}>Model Versions Used</h2>
            <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
              {model_versions_used.map((m, i) => (
                <div key={i} style={{ display: "flex", justifyContent: "space-between", fontSize: "0.85rem", padding: "4px 0" }}>
                  <span style={{ color: "#b3d9ff", fontFamily: "monospace" }}>{m.model_version_used}</span>
                  <span style={{ color: "#7eb3ff" }}>{m.route} · {m.sequence_count} seqs</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Review Status */}
        {review_status && review_status.total_reviews > 0 && (
          <div style={CARD("#00d4ff")}>
            <h2 style={H("1rem", "#00d4ff")}>Review Status</h2>
            <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
              {[
                ["Total", review_status.total_reviews, "#b3d9ff"],
                ["Submitted", review_status.submitted, "#7eb3ff"],
                ["Accepted", review_status.accepted, "#00ff88"],
                ["Rejected", review_status.rejected, "#ff6b6b"],
                ["Auto-Novelty", review_status.auto_novelty_reviews, "#ffd700"],
                ["Auto-Contamination", review_status.auto_contamination_reviews, "#ff9b9b"],
              ].filter(([, v]) => v > 0).map(([label, value, color]) => (
                <div key={label} style={{
                  padding: "4px 12px", borderRadius: 999,
                  background: `${color}18`, border: `1px solid ${color}44`,
                  color, fontSize: "0.8rem", fontWeight: 600,
                }}>
                  {label}: {value}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Empty state */}
        {!possible_novelty?.length && !contamination_warnings?.length && !known_species?.length && (
          <div style={{
            textAlign: "center", padding: "2rem",
            color: "#7eb3ff", border: "1px solid rgba(255,255,255,0.06)",
            borderRadius: 14, background: "rgba(255,255,255,0.02)",
          }}>
            No species identified yet. Results will appear once the analysis pipeline completes.
          </div>
        )}
      </div>
    </div>
  );
}
