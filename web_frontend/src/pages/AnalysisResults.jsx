import React, { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import SidebarMenu from "../components/sidebar/SidebarMenu";
import ProvenanceTag from "../components/shared/ProvenanceTag";
import NegativeControlFlag from "../components/shared/NegativeControlFlag";
import { tokens } from "../components/shared/tokens";
import { ArrowRightIcon } from "../components/shared/icons";
import { useAuth } from "../contexts/AuthContext";
import { getReport, exportReportJson, exportReportCsv } from "../lib/api";
import { revealStyle } from "../styles/reveal";

// Single scale factor applied to every size value on this page (container
// width, font sizes, padding, gaps, icon/avatar dimensions) -- per direct
// feedback that the page read as too congested in the middle of wide
// viewports. One multiplier keeps every ratio (text-to-card, icon-to-label,
// etc.) identical to the pre-scale design, just larger throughout, rather
// than hand-picking new numbers per element.
const SCALE = 1.25;
const s = (n) => Math.round(n * SCALE * 10) / 10;

const PAGE = {
  position: "relative",
  background: tokens.pageBg,
  minHeight: "100vh",
  color: tokens.textPrimary,
  fontFamily: "'Instrument Sans', system-ui, sans-serif",
};

const AMBIENT_GLOW = {
  position: "fixed",
  inset: 0,
  pointerEvents: "none",
  background:
    "radial-gradient(70% 40% at 50% 0%, rgba(20,110,255,0.10) 0%, rgba(2,6,15,0) 60%), radial-gradient(50% 40% at 90% 100%, rgba(59,158,255,0.06) 0%, rgba(2,6,15,0) 55%)",
};

const panelStyle = {
  display: "flex",
  flexDirection: "column",
  gap: s(14),
  padding: `${s(22)}px ${s(24)}px`,
  borderRadius: 9,
  border: "1px solid rgba(140,170,230,0.14)",
  background: "linear-gradient(180deg, rgba(140,170,230,0.06) 0%, rgba(6,10,20,0.7) 100%)",
  boxShadow: "inset 0 1px 0 rgba(255,255,255,0.10), 0 14px 34px rgba(0,0,0,0.4)",
};

const panelLabelStyle = { fontSize: s(13), fontWeight: 600, letterSpacing: "0.08em", color: tokens.wordmark, width: "100%", textAlign: "center" };

// Same color/size/weight as pillStyle(tone), minus the capsule enclosure
// (border/background/padding/border-radius) -- for the Possible Novelty
// preview tags, per direct feedback to de-pill them.
const PIE_COLORS = [tokens.accentBlue, tokens.accentCyan, tokens.purple, tokens.warningAlt, tokens.success, tokens.danger];

// The containing panel has its own fade+rise entrance (revealStyle) that's
// still running when a chart's own entrance animation would otherwise
// start at t=0 -- both fire from mount simultaneously, so the chart is
// already fully drawn by the time the still-fading-in panel becomes
// visible enough to see it happen. Every chart-content entrance below is
// delayed past this so it visibly plays *after* its panel has appeared,
// not hidden underneath it.
const PANEL_REVEAL_S = 0.65;

// Triage category breakdown as a hover-reactive pie. Whole chart pops in as
// one unit rather than per-slice, since each wedge's own bounding-box
// center differs and scaling them independently reads as chaotic rather
// than "the pie chart appearing." transform-origin is given as an explicit
// pixel coordinate (not the `center` keyword) because transform-box:
// fill-box on a <g> wrapping multiple children is unreliable across
// browsers -- some compute an empty/wrong bounding box for it, which would
// silently no-op the whole entrance animation.
function TriagePieChart({ data, hovered, setHovered }) {
  const cx = 90, cy = 90, r = 80;
  let a0 = -Math.PI / 2;
  const slices = data.map(({ route, fraction }, i) => {
    const a1 = a0 + fraction * 2 * Math.PI;
    const large = a1 - a0 > Math.PI ? 1 : 0;
    const x0 = cx + Math.cos(a0) * r, y0 = cy + Math.sin(a0) * r;
    const x1 = cx + Math.cos(a1) * r, y1 = cy + Math.sin(a1) * r;
    const path =
      fraction >= 1
        ? `M${cx} ${cy - r} A${r} ${r} 0 1 1 ${cx - 0.01} ${cy - r} Z`
        : `M${cx} ${cy} L${x0} ${y0} A${r} ${r} 0 ${large} 1 ${x1} ${y1} Z`;
    a0 = a1;
    return { route, path, color: PIE_COLORS[i % PIE_COLORS.length] };
  });
  const activeIdx = hovered;
  const active = activeIdx != null ? data[activeIdx] : null;
  return (
    <svg viewBox="0 0 180 205" width={s(180)} style={{ height: "auto", flexShrink: 0, display: "block" }}>
      <g
        className="sv-scale-in"
        style={{ transformBox: "view-box", transformOrigin: `${cx}px ${cy}px`, animationDelay: `${PANEL_REVEAL_S}s` }}
      >
        {slices.map((sl, i) => (
          <path
            key={sl.route}
            d={sl.path}
            fill={sl.color}
            opacity={activeIdx == null || activeIdx === i ? 0.9 : 0.4}
            stroke="#04070E"
            strokeWidth={activeIdx === i ? 2.5 : 1.5}
            onMouseEnter={() => setHovered(i)}
            onMouseLeave={() => setHovered(null)}
            style={{ cursor: "pointer", transition: "opacity .12s ease, stroke-width .12s ease" }}
          />
        ))}
      </g>
      {active && (
        <text x={cx} y={cy + r + 22} fill={tokens.textPrimary} fontSize={11} fontWeight={600} textAnchor="middle">
          {active.route} · {(active.fraction * 100).toFixed(1)}%
        </text>
      )}
    </svg>
  );
}

function plainTagStyle(tone = "pending") {
  return {
    color: tokens[tone] ?? tokens.pending,
    fontSize: s(11.5),
    fontWeight: 600,
    letterSpacing: "0.04em",
    whiteSpace: "nowrap",
  };
}

function KpiCard({ label, value, valueColor, sub, highlight = false }) {
  return (
    <div
      style={{
        ...panelStyle,
        gap: s(8),
        padding: s(18),
        alignItems: "center",
        textAlign: "center",
        ...(highlight ? { border: `1px solid ${tokens.cardBorderActive}`, background: `linear-gradient(180deg, ${tokens.accentBg}, #060A14)` } : {}),
      }}
    >
      <span style={{ fontSize: s(11), fontWeight: 600, letterSpacing: "0.09em", color: highlight ? tokens.badgeText : tokens.labelText }}>
        {label}
      </span>
      <span style={{ fontSize: s(26), fontWeight: 600, letterSpacing: "-0.02em", color: valueColor ?? tokens.textPrimary }}>{value}</span>
      {sub && <span style={{ fontSize: s(11.5), color: tokens.sectionSubtext }}>{sub}</span>}
    </div>
  );
}

export default function AnalysisResults() {
  const { user } = useAuth();
  const { analysis_id } = useParams();
  const [report, setReport] = useState(null);
  const [error, setError] = useState("");
  const [downloadingFormat, setDownloadingFormat] = useState(null);
  const [hoveredRoute, setHoveredRoute] = useState(null);
  const [hoveredQcRow, setHoveredQcRow] = useState(null);

  useEffect(() => {
    getReport(analysis_id)
      .then(setReport)
      .catch((e) => setError(e.message || "Failed to load report."));
  }, [analysis_id]);

  const handleExport = async (format) => {
    setDownloadingFormat(format);
    try {
      const resp = format === "csv" ? await exportReportCsv(analysis_id) : await exportReportJson(analysis_id);
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `synthveda_report_${analysis_id}.${format}`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      alert("Export failed: " + e.message);
    } finally {
      setDownloadingFormat(null);
    }
  };

  if (error) {
    return (
      <div style={PAGE}>
        <div style={AMBIENT_GLOW} />
        <SidebarMenu />
        <div style={{ position: "relative", maxWidth: 800, margin: "4rem auto", padding: "0 1.5rem", textAlign: "center" }}>
          <div style={{ fontSize: "2.5rem", marginBottom: 16 }}>⚠</div>
          <div style={{ color: tokens.danger, fontSize: "1.1rem", marginBottom: 16 }}>{error}</div>
          <Link to="/upload" style={{ color: tokens.accentBlue, textDecoration: "none" }}>← New Analysis</Link>
        </div>
      </div>
    );
  }

  if (!report) {
    return (
      <div style={PAGE}>
        <div style={AMBIENT_GLOW} />
        <SidebarMenu />
        <div style={{ position: "relative", textAlign: "center", padding: "4rem", color: tokens.sectionSubtext }}>
          Loading report...
        </div>
      </div>
    );
  }

  const { metadata, qc_summary, biodiversity, route_distribution, possible_novelty } = report;
  const passedQcPct = qc_summary ? ((qc_summary.passed_qc / qc_summary.total_sequences) * 100).toFixed(1) : null;
  const attritionCount = qc_summary ? qc_summary.total_sequences - qc_summary.passed_qc : 0;
  const previewNovelty = possible_novelty?.slice(0, 3) ?? [];

  return (
    <div style={PAGE}>
      <div style={AMBIENT_GLOW} />
      <SidebarMenu />
      <div
        style={{
          position: "relative",
          maxWidth: s(1560),
          margin: "0 auto",
          boxSizing: "border-box",
          padding: `${s(28)}px ${s(56)}px ${s(40)}px`,
          display: "flex",
          flexDirection: "column",
          gap: s(20),
        }}
      >
        {/* Header -- logo/wordmark, title group, actions + user block, all in
            one row, matching the reference mockup exactly (SidebarMenu is a
            collapsed-by-default overlay, so this page needs its own
            persistent brand anchor rather than relying on the drawer). */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: s(24), flexWrap: "wrap" }}>
          <div style={{ display: "flex", alignItems: "center", gap: s(22), flexWrap: "wrap" }}>
            <div style={{ display: "flex", alignItems: "center", gap: s(11) }}>
              <svg width={s(24)} height={s(24)} viewBox="0 0 26 26" fill="none">
                <path d="M6 2c0 6 14 8 14 13S6 20 6 24" stroke={tokens.accentBlue} strokeWidth="2" strokeLinecap="round" />
                <path d="M20 2c0 6-14 8-14 13s14 5 14 9" stroke={tokens.accentCyan} strokeWidth="2" strokeLinecap="round" />
              </svg>
              <span style={{ fontWeight: 600, letterSpacing: "0.22em", fontSize: s(12), color: tokens.wordmark }}>SYNTH VEDA</span>
            </div>
            <div style={{ width: 1, height: s(28), background: tokens.sectionBorder }} />
            <div style={{ display: "flex", flexDirection: "column", gap: s(3) }}>
              <div style={{ display: "flex", alignItems: "center", gap: s(12) }}>
                <h1 style={{ margin: 0, fontSize: s(22), fontWeight: 600, letterSpacing: "-0.01em" }}>Analysis Report</h1>
                <span style={plainTagStyle("accent")}>{metadata?.mode === "abyss_synced" ? "Abyss Synced" : "Online Full"}</span>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: s(10), fontSize: s(12.5), color: tokens.labelText }}>
                {metadata?.source_file && <span style={{ color: tokens.wordmark }}>{metadata.source_file}</span>}
                <span style={{ color: tokens.headerDot }}>·</span>
                <span>Run ID {analysis_id}</span>
              </div>
            </div>
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: s(12), flexWrap: "wrap" }}>
            <Link to="/upload" style={{ color: tokens.sectionSubtext, textDecoration: "none", fontSize: s(13.1) }}>
              ← New Analysis
            </Link>
            {["json", "csv"].map((format) => (
              <button
                key={format}
                onClick={() => handleExport(format)}
                disabled={downloadingFormat !== null}
                style={{
                  padding: `${s(8)}px ${s(18)}px`,
                  borderRadius: 12,
                  border: "1px solid rgba(160,205,255,0.55)",
                  background: "linear-gradient(180deg, #459AF5 0%, #1A71F0 48%, #0D57D1 100%)",
                  boxShadow: "inset 0 1.5px 0 rgba(255,255,255,0.55), inset 0 -3px 8px rgba(8,50,140,0.45), 0 10px 30px rgba(30,123,255,0.38)",
                  color: "#FFFFFF",
                  textShadow: "0 1px 2px rgba(8,50,140,0.4)",
                  fontFamily: "inherit",
                  fontSize: s(13),
                  fontWeight: 600,
                  cursor: downloadingFormat === null ? "pointer" : "default",
                  transition: "all .15s ease",
                }}
              >
                {downloadingFormat === format ? "Exporting..." : `⬇ Export ${format.toUpperCase()}`}
              </button>
            ))}
            {user && (
              <div style={{ display: "flex", alignItems: "center", gap: s(10), padding: `${s(6)}px ${s(14)}px ${s(6)}px ${s(6)}px`, border: `1px solid ${tokens.sectionBorder}`, borderRadius: 999, background: "rgba(8,16,32,0.6)" }}>
                <div
                  style={{
                    width: s(28),
                    height: s(28),
                    borderRadius: "50%",
                    background: `linear-gradient(135deg, #146EFF, ${tokens.accentCyan})`,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontSize: s(12),
                    fontWeight: 600,
                    color: "#04101F",
                  }}
                >
                  {(user.display_name || user.email || "?").slice(0, 2).toUpperCase()}
                </div>
                <div style={{ display: "flex", flexDirection: "column", lineHeight: 1.2 }}>
                  <span style={{ fontSize: s(12.5), fontWeight: 500 }}>{user.display_name || user.email}</span>
                  <span style={{ fontSize: s(10.5), color: tokens.labelText, textTransform: "capitalize" }}>{user.role}</span>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Negative control */}
        <div style={{ display: "flex", alignItems: "center", gap: s(10) }}>
          <NegativeControlFlag included={metadata?.negative_control_included ?? null} />
        </div>

        {/* KPI row -- matches the reference mockup's 6 cards exactly */}
        {biodiversity && qc_summary && (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(6, 1fr)", gap: s(14) }}>
            <KpiCard label="TOTAL SEQUENCES" value={qc_summary.total_sequences.toLocaleString()} sub="raw reads ingested" />
            <KpiCard
              label="PASSED QC"
              value={`${passedQcPct}%`}
              valueColor={tokens.success}
              sub={`${qc_summary.passed_qc.toLocaleString()} reads retained`}
            />
            <KpiCard label="ROUTE RICHNESS" value={biodiversity.route_richness} sub="triage buckets, pre-taxonomic" />
            <KpiCard
              label="CONTAMINATION"
              value={`${(biodiversity.contamination_fraction * 100).toFixed(1)}%`}
              valueColor={tokens.warningAlt}
              sub={biodiversity.dominant_route ? `dominant: ${biodiversity.dominant_route}` : undefined}
            />
            {/* Muted/pending treatment, not the accent-highlighted style --
                the highlighted look is reserved for a genuine positive
                "Detected" result, which this deployment can't produce yet. */}
            <div style={{ ...panelStyle, gap: s(7), padding: s(18), opacity: 0.75, alignItems: "center", textAlign: "center" }}>
              <span style={{ fontSize: s(11), fontWeight: 600, letterSpacing: "0.09em", color: tokens.labelText }}>eDNA TARGET STATUS</span>
              <span style={{ fontSize: s(13), color: tokens.pending, lineHeight: 1.4 }}>
                Not available — targeted-detection mode isn't supported by this deployment yet
              </span>
            </div>
            <div style={{ ...panelStyle, gap: s(7), padding: s(18), alignItems: "center", textAlign: "center" }}>
              <span style={{ fontSize: s(11), fontWeight: 600, letterSpacing: "0.09em", color: tokens.labelText }}>NOVELTY</span>
              <span style={{ fontSize: s(26), fontWeight: 600, letterSpacing: "-0.02em", color: tokens.accentCyan }}>
                {(biodiversity.novelty_fraction * 100).toFixed(1)}%
              </span>
              {/* Read-only fill bar out of 100 -- the fill width IS the real
                  novelty percentage, not a user-adjustable threshold. Same
                  fill-bar language as Triage Category Distribution below,
                  not a draggable/dot gauge. */}
              <div style={{ width: "100%", height: s(8), borderRadius: 4, background: "#0A1526", overflow: "hidden" }}>
                <div
                  style={{
                    width: `${Math.min(biodiversity.novelty_fraction * 100, 100)}%`,
                    height: "100%",
                    borderRadius: 4,
                    background: `linear-gradient(90deg, ${tokens.accentBlue}, ${tokens.accentCyan})`,
                    boxShadow: `0 0 8px ${tokens.accentBlue}55`,
                  }}
                />
              </div>
              <span style={{ fontSize: s(11), color: tokens.pending }}>
                of total sequences at ≥45% novelty confidence (this deployment's flagging cutoff)
              </span>
            </div>
          </div>
        )}

        {/* QC + Triage panels */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: s(14) }}>
          {qc_summary && (
            <div style={{ ...panelStyle, ...revealStyle(0) }}>
              <span style={panelLabelStyle}>QUALITY CONTROL SUMMARY</span>
              {/* Same bar-row layout Triage Category Distribution used to
                  have. Only Passed QC / Low Quality / Mean GC get bars --
                  each is honestly expressible as a fraction of a real whole
                  (total_sequences, or GC's own 0-1 ratio). Mean Length
                  (bp) has no natural 0-100% denominator, so inventing one
                  to force it into a bar would just be made-up scale --
                  it stays a plain figure below instead. */}
              <div style={{ display: "flex", flexDirection: "column", gap: s(11) }}>
                {[
                  ["Passed QC", qc_summary.passed_qc, qc_summary.passed_qc / qc_summary.total_sequences, tokens.success, `${qc_summary.passed_qc} of ${qc_summary.total_sequences} sequences retained after quality filtering`],
                  ["Low quality", qc_summary.low_quality_count, qc_summary.low_quality_count / qc_summary.total_sequences, tokens.danger, `${qc_summary.low_quality_count} of ${qc_summary.total_sequences} sequences discarded for low quality`],
                  ["Mean GC ratio", qc_summary.mean_gc_ratio?.toFixed(2), qc_summary.mean_gc_ratio ?? 0, tokens.accentBlue, "Average GC content across passed sequences"],
                ].map(([label, value, fraction, color, hint], i) => {
                  const active = hoveredQcRow === i;
                  return (
                    <div
                      key={label}
                      onMouseEnter={() => setHoveredQcRow(i)}
                      onMouseLeave={() => setHoveredQcRow(null)}
                      style={{ display: "flex", flexDirection: "column", gap: s(3), cursor: "default" }}
                    >
                      <div style={{ display: "flex", alignItems: "center", gap: s(12) }}>
                        <span style={{ width: s(120), flexShrink: 0, fontSize: s(12.5), fontWeight: active ? 600 : 400, color: active ? tokens.textPrimary : tokens.wordmark, transition: "color .12s ease, font-weight .12s ease" }}>{label}</span>
                        <div style={{ flex: 1, height: s(8), borderRadius: 4, background: "#0A1526", overflow: "hidden" }}>
                          <div
                            className="sv-grow-x"
                            style={{
                              width: `${Math.min(fraction * 100, 100)}%`,
                              height: "100%",
                              borderRadius: 4,
                              background: color,
                              boxShadow: `0 0 ${active ? 14 : 8}px ${color}${active ? "AA" : "55"}`,
                              opacity: active ? 1 : 0.85,
                              transition: "box-shadow .12s ease, opacity .12s ease",
                              animationDelay: `${PANEL_REVEAL_S + i * 0.1}s`,
                            }}
                          />
                        </div>
                        <span style={{ width: s(46), textAlign: "right", fontSize: s(12), color: tokens.sectionSubtext, flexShrink: 0 }}>{value ?? "—"}</span>
                        <span style={{ width: s(46), textAlign: "right", fontSize: s(12), fontWeight: 600, color: tokens.textPrimary, flexShrink: 0 }}>
                          {(fraction * 100).toFixed(1)}%
                        </span>
                      </div>
                      {active && (
                        <span style={{ fontSize: s(10.5), color: tokens.sectionSubtext, paddingLeft: s(132) }}>{hint}</span>
                      )}
                    </div>
                  );
                })}
              </div>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: s(16), fontSize: s(11.5), color: tokens.sectionSubtext }}>
                <span>{qc_summary.total_sequences.toLocaleString()} total sequences</span>
                <span>·</span>
                <span>Mean length {qc_summary.mean_length} bp</span>
              </div>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: s(8), fontSize: s(12.5), color: tokens.sectionSubtext }}>
                <ArrowRightIcon size={s(13)} color={tokens.accentBlue} />
                <span>
                  {attritionCount.toLocaleString()} of {qc_summary.total_sequences.toLocaleString()} reads filtered —{" "}
                  <Link to={`/researcher-mode/novelty-dna?analysis_id=${analysis_id}`} style={{ color: tokens.accentBlue }}>full attrition breakdown in Researcher Mode</Link>
                </span>
              </div>
            </div>
          )}

          {route_distribution?.length > 0 && (
            <div style={{ ...panelStyle, ...revealStyle(1) }}>
              <span style={panelLabelStyle}>TRIAGE CATEGORY DISTRIBUTION</span>
              <div style={{ display: "flex", alignItems: "center", gap: s(24), flexWrap: "wrap", justifyContent: "center" }}>
                <TriagePieChart data={route_distribution} hovered={hoveredRoute} setHovered={setHoveredRoute} />
                <div style={{ display: "flex", flexDirection: "column", gap: s(9) }}>
                  {route_distribution.map(({ route, count, fraction }, i) => {
                    const active = hoveredRoute === i;
                    return (
                      <div
                        key={route}
                        onMouseEnter={() => setHoveredRoute(i)}
                        onMouseLeave={() => setHoveredRoute(null)}
                        style={{ display: "flex", alignItems: "center", gap: s(9), cursor: "pointer", opacity: hoveredRoute == null || active ? 1 : 0.5, transition: "opacity .12s ease" }}
                      >
                        <span style={{ width: 10, height: 10, borderRadius: "50%", flexShrink: 0, background: PIE_COLORS[i % PIE_COLORS.length], boxShadow: active ? `0 0 8px ${PIE_COLORS[i % PIE_COLORS.length]}` : "none" }} />
                        <span style={{ fontSize: s(12.5), fontWeight: active ? 600 : 400, color: active ? tokens.textPrimary : tokens.wordmark, fontFamily: "ui-monospace,monospace" }}>{route}</span>
                        <span style={{ fontSize: s(12), color: tokens.sectionSubtext }}>{count}</span>
                        <span style={{ fontSize: s(12), fontWeight: 600, color: tokens.textPrimary }}>{(fraction * 100).toFixed(1)}%</span>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Possible Novelty -- preview only, full list lives in Novelty DNA */}
        {previewNovelty.length > 0 && (
          <div style={panelStyle}>
            <span style={panelLabelStyle}>POSSIBLE NOVELTY — PREVIEW</span>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: s(14) }}>
              {previewNovelty.map((n) => (
                <div key={n.sequence_id} style={{ display: "flex", flexDirection: "column", alignItems: "center", textAlign: "center", gap: s(10), padding: `${s(16)}px ${s(18)}px`, borderRadius: 6, border: "1px solid #152439", background: "rgba(8,14,26,0.5)" }}>
                  <div style={{ display: "flex", justifyContent: "center", alignItems: "center", gap: s(8), flexWrap: "wrap" }}>
                    <span style={{ fontSize: s(13), fontWeight: 600, fontFamily: "ui-monospace,monospace" }}>{n.sequence_id}</span>
                    <span style={plainTagStyle("accent")}>{(n.novelty_score * 100).toFixed(1)}% novel</span>
                  </div>
                  <div style={{ display: "flex", justifyContent: "center", gap: s(8), flexWrap: "wrap" }}>
                    <span style={plainTagStyle("accent")}>{n.route}</span>
                    <span style={plainTagStyle(n.requires_cloud_confirmation ? "warning" : "success")}>
                      {n.requires_cloud_confirmation ? "cloud confirm needed" : n.abyss_recommendation}
                    </span>
                  </div>
                  {n.reason_codes?.length > 0 && (
                    <span style={{ fontSize: s(11), color: tokens.pending, lineHeight: 1.5 }}>{n.reason_codes.join(" · ")}</span>
                  )}
                </div>
              ))}
            </div>
            {possible_novelty.length > 3 && (
              <Link to={`/researcher-mode/novelty-dna?analysis_id=${analysis_id}`} style={{ alignSelf: "flex-end", fontSize: s(12.5), color: tokens.accentBlue }}>
                View all {possible_novelty.length} in Novelty DNA →
              </Link>
            )}
          </div>
        )}

        {/* Provenance footer -- component 0.2, plain variant per reference mockup */}
        <div style={{ display: "flex", justifyContent: "center", padding: `${s(6)}px 0 ${s(4)}px`, borderTop: `1px solid ${tokens.sectionBorder}` }}>
          <ProvenanceTag
            referenceDb={null}
            pipelineVersion={metadata?.model_version_set !== "stub_none" ? metadata?.model_version_set : null}
            matchedAt={metadata?.created_at}
            variant="plain"
          />
        </div>
      </div>
    </div>
  );
}
