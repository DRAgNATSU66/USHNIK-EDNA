import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import SidebarMenu from "../../components/sidebar/SidebarMenu";
import ProvenanceTag from "../../components/shared/ProvenanceTag";
import { tokens } from "../../components/shared/tokens";
import Dropdown from "../../components/shared/Dropdown";
import { getReport, listReports } from "../../lib/api";

// Same reasoning as Analysis Report's novelty gauge: the backend only
// returns per-sequence scores for entries already above its 0.45 flagging
// cutoff, so the mockup's 40-97% slider range is clamped to 45-97 here --
// there's no real data to slide into below the floor.
const NOVELTY_FLOOR_PCT = 45;

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

const panelStyle = {
  display: "flex",
  flexDirection: "column",
  gap: 16,
  padding: "18px 22px",
  borderRadius: 9,
  border: "1px solid rgba(140,170,230,0.14)",
  background: "linear-gradient(180deg, rgba(140,170,230,0.06) 0%, rgba(6,10,20,0.7) 100%)",
  boxShadow: "inset 0 1px 0 rgba(255,255,255,0.10), 0 14px 34px rgba(0,0,0,0.4)",
};

// Plain colored text, no capsule chrome -- same tone→color mapping as
// pillStyle (tokens.js), minus the padding/border/pill background, for the
// candidate list's inline tags. pillStyle itself stays untouched since it's
// shared with other pages (severity pills, MockTag-adjacent badges
// elsewhere) that weren't asked to change.
function plainTagStyle(tone = "pending") {
  return {
    color: tokens[tone] ?? tokens.pending,
    fontSize: 12.5,
    fontWeight: 600,
    letterSpacing: "0.02em",
    whiteSpace: "nowrap",
  };
}

function noveltyTierStyle(pct) {
  return plainTagStyle(pct >= 75 ? "accent" : "pending");
}

function SolidButton({ children, onClick, disabled, title }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      title={title}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 9,
        padding: "9px 18px",
        borderRadius: 12,
        border: "1px solid rgba(160,205,255,0.55)",
        background: disabled
          ? "linear-gradient(180deg, #2A3B58 0%, #1C2A42 100%)"
          : "linear-gradient(180deg, #459AF5 0%, #1A71F0 48%, #0D57D1 100%)",
        boxShadow: disabled ? "none" : "inset 0 1.5px 0 rgba(255,255,255,0.55), inset 0 -3px 8px rgba(8,50,140,0.45), 0 10px 30px rgba(30,123,255,0.38)",
        color: disabled ? "#7A8699" : "#FFFFFF",
        textShadow: disabled ? "none" : "0 1px 2px rgba(8,50,140,0.4)",
        fontFamily: "inherit",
        fontSize: 13.5,
        fontWeight: 600,
        cursor: disabled ? "not-allowed" : "pointer",
      }}
    >
      {children}
    </button>
  );
}

// Same joined-table language as Species Correction's match table (one
// shared bordered container, a header row, per-row borderBottom dividers)
// instead of a stack of separately-bordered/rounded cards, so the two
// Researcher Mode list pages read as one consistent design.
const GRID_COLS = "26px 170px 1fr 1.4fr 168px";

function CandidateRow({ n, i, bulkMode, selected, onToggleSelect, onOpen }) {
  const pct = (n.novelty_score * 100).toFixed(1);
  return (
    <div
      onClick={onOpen}
      style={{ display: "grid", gridTemplateColumns: GRID_COLS, gap: 16, alignItems: "center", padding: "18px 24px", borderBottom: "1px solid #0C1526", cursor: "pointer", background: selected ? "rgba(59,158,255,0.06)" : "transparent" }}
    >
      {bulkMode ? (
        <div
          onClick={(e) => { e.stopPropagation(); onToggleSelect(); }}
          style={{
            width: 22,
            height: 22,
            borderRadius: 5,
            flexShrink: 0,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontSize: 13,
            fontWeight: 700,
            cursor: "pointer",
            border: `1.5px solid ${selected ? tokens.accentBlue : "#2A3B58"}`,
            background: selected ? "rgba(59,158,255,0.25)" : "rgba(8,14,26,0.6)",
            color: tokens.accentCyan,
          }}
        >
          {selected ? "✓" : ""}
        </div>
      ) : (
        // Light grey radiating-glow row marker (sv-dot-ripple/sv-dot-core-
        // pulse, shared with Species Correction's tier dots) -- same
        // visual convention as that page's per-row dot, just plain light
        // grey here since Novelty candidates don't have a tier to
        // color-code. tokens.wordmark instead of the darker
        // tokens.sectionSubtext, per direct request to lighten it.
        <span style={{ position: "relative", display: "inline-flex", flexShrink: 0, width: 13, height: 13 }}>
          <span
            className="sv-dot-ripple"
            style={{ position: "absolute", inset: 0, borderRadius: "50%", background: tokens.wordmark, animationDelay: `${i * 0.12}s` }}
          />
          <span
            className="sv-dot-core"
            style={{ width: 13, height: 13, borderRadius: "50%", background: tokens.wordmark, boxShadow: `0 0 10px ${tokens.wordmark}88`, animationDelay: `${i * 0.12}s` }}
          />
        </span>
      )}
      <span style={{ fontSize: 15, fontWeight: 600, fontFamily: "ui-monospace,monospace", wordBreak: "break-all", overflowWrap: "anywhere" }}>{n.sequence_id}</span>
      <span style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
        <span style={noveltyTierStyle(n.novelty_score * 100)}>{pct}% novel</span>
        <span style={plainTagStyle("accent")}>{n.route}</span>
        <span style={plainTagStyle(n.requires_cloud_confirmation ? "warning" : "success")}>
          {n.requires_cloud_confirmation ? "cloud confirm needed" : n.abyss_recommendation}
        </span>
      </span>
      <span style={{ fontSize: 12, color: tokens.pending }}>{n.reason_codes?.length > 0 ? n.reason_codes.join(" · ") : "—"}</span>
      <SolidButton
        disabled
        title="Cloud Confirm (deeper reference search) isn't wired to a compute backend on this deployment yet"
        onClick={(e) => e.stopPropagation()}
      >
        Cloud Confirm
      </SolidButton>
    </div>
  );
}

function AlignmentViewerDrawer({ candidate, onClose }) {
  if (!candidate) return null;
  const pct = (candidate.novelty_score * 100).toFixed(1);
  const fastaLines = candidate.sequence ? candidate.sequence.match(/.{1,60}/g) ?? [] : [];

  return (
    <>
      <div
        onClick={onClose}
        style={{ position: "fixed", inset: 0, background: "rgba(2,4,9,0.6)", backdropFilter: "blur(3px)", zIndex: 40 }}
      />
      <div
        style={{
          position: "fixed",
          top: 0,
          right: 0,
          bottom: 0,
          width: 620,
          maxWidth: "92vw",
          zIndex: 41,
          display: "flex",
          flexDirection: "column",
          gap: 20,
          padding: "28px 32px",
          boxSizing: "border-box",
          borderLeft: `1px solid ${tokens.sectionBorder}`,
          background: "#050912",
          boxShadow: "-30px 0 80px rgba(0,0,0,0.6)",
          overflowY: "auto",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
            <span style={{ fontSize: 11.5, letterSpacing: "0.08em", color: tokens.labelText }}>DEEP ALIGNMENT VIEWER</span>
            <span style={{ fontSize: 20, fontWeight: 600, fontFamily: "ui-monospace,monospace" }}>{candidate.sequence_id}</span>
          </div>
          <button
            onClick={onClose}
            style={{
              width: 34,
              height: 34,
              borderRadius: 8,
              border: `1px solid ${tokens.sectionBorder}`,
              background: "#080F1C",
              color: tokens.wordmark,
              fontSize: 15,
              cursor: "pointer",
            }}
          >
            ✕
          </button>
        </div>

        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          <span style={noveltyTierStyle(candidate.novelty_score * 100)}>{pct}% novel</span>
          <span style={plainTagStyle("accent")}>{candidate.route}</span>
          <span style={plainTagStyle(candidate.contamination_score >= 0.5 ? "warning" : "pending")}>
            contamination {(candidate.contamination_score * 100).toFixed(1)}%
          </span>
        </div>

        <div>
          <div style={{ fontSize: 12, letterSpacing: "0.08em", color: tokens.labelText, marginBottom: 8 }}>REASON CODES</div>
          <div style={{ fontSize: 12.5, color: tokens.sectionSubtext, lineHeight: 1.6 }}>
            {candidate.reason_codes?.length > 0 ? candidate.reason_codes.join(" · ") : "—"}
          </div>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <span style={{ fontSize: 12, letterSpacing: "0.08em", color: tokens.labelText }}>RAW SEQUENCE (FASTA)</span>
          <div
            style={{
              padding: "16px 18px",
              borderRadius: 4,
              border: `1px solid ${tokens.sectionBorder}`,
              background: "#04070E",
              fontFamily: "ui-monospace,monospace",
              fontSize: 12,
              lineHeight: 1.7,
              color: "#8FB4E6",
              wordBreak: "break-all",
              maxHeight: 220,
              overflowY: "auto",
            }}
          >
            &gt;{candidate.sequence_id}
            {fastaLines.length > 0
              ? fastaLines.map((line, i) => <div key={i}>{line}</div>)
              : <div style={{ color: tokens.pending }}>Sequence not available for this entry.</div>}
          </div>
        </div>

        <div
          style={{
            padding: "14px 18px",
            borderRadius: 6,
            border: `1px solid ${tokens.warningBorder}`,
            background: tokens.warningBg,
            fontSize: 12.5,
            lineHeight: 1.6,
            color: "#C8B79A",
          }}
        >
          <span style={{ fontWeight: 600, color: tokens.warningAlt }}>Closest match, alignment identity, E-value, and query coverage aren't available. </span>
          This deployment scores novelty from DNABERT-2 embeddings only — it doesn't run a reference alignment step (BLAST/DIAMOND) against a curated database yet, so there's no real closest-hit comparison to show.
        </div>

        <SolidButton disabled title="Cloud Confirm (deeper reference search) isn't wired to a compute backend on this deployment yet">
          Cloud Confirm
        </SolidButton>
      </div>
    </>
  );
}

export default function NoveltyDNA() {
  const [searchParams] = useSearchParams();
  const requestedId = searchParams.get("analysis_id");

  const [analysisId, setAnalysisId] = useState(requestedId);
  const [report, setReport] = useState(null);
  const [error, setError] = useState("");
  const [threshold, setThreshold] = useState(NOVELTY_FLOOR_PCT);
  const [routeFilter, setRouteFilter] = useState("All");
  const [sortBy, setSortBy] = useState("novelty");
  const [bulkMode, setBulkMode] = useState(false);
  const [selected, setSelected] = useState({});
  const [drawerId, setDrawerId] = useState(null);

  // Resolve which analysis to show: an explicit ?analysis_id= wins;
  // otherwise fall back to the user's most recent one. The sidebar's
  // "Novelty DNA" link is global (no analysis context), so this page has
  // to be able to pick a sensible default on its own.
  useEffect(() => {
    if (requestedId) {
      setAnalysisId(requestedId);
      return;
    }
    listReports(1)
      .then((rows) => {
        if (rows.length === 0) {
          setError("No analyses yet — upload a sample first.");
        } else {
          setAnalysisId(rows[0].analysis_id);
        }
      })
      .catch((e) => setError(e.message || "Failed to load your analyses."));
  }, [requestedId]);

  useEffect(() => {
    if (!analysisId) return;
    getReport(analysisId)
      .then(setReport)
      .catch((e) => setError(e.message || "Failed to load report."));
  }, [analysisId]);

  const routes = useMemo(() => {
    if (!report) return [];
    return [...new Set(report.possible_novelty.map((n) => n.route))].sort();
  }, [report]);

  const rows = useMemo(() => {
    if (!report) return [];
    let list = report.possible_novelty.filter(
      (n) => n.novelty_score * 100 >= threshold && (routeFilter === "All" || n.route === routeFilter)
    );
    list = [...list].sort((a, b) =>
      sortBy === "contamination" ? b.contamination_score - a.contamination_score : b.novelty_score - a.novelty_score
    );
    return list;
  }, [report, threshold, routeFilter, sortBy]);

  const selCount = Object.values(selected).filter(Boolean).length;
  const drawerCandidate = report?.possible_novelty.find((n) => n.sequence_id === drawerId) ?? null;

  const toggleBulk = () => {
    setBulkMode((b) => !b);
    setSelected({});
  };

  if (error) {
    return (
      <div style={pageStyle}>
        <div style={ambientGlow} />
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
      <div style={pageStyle}>
        <div style={ambientGlow} />
        <SidebarMenu />
        <div style={{ position: "relative", textAlign: "center", padding: "4rem", color: tokens.sectionSubtext }}>
          Loading candidates...
        </div>
      </div>
    );
  }

  return (
    <div style={pageStyle}>
      <div style={ambientGlow} />
      <SidebarMenu />
      <div style={{ position: "relative", maxWidth: 1900, margin: "0 auto", padding: "32px 44px 44px", display: "flex", flexDirection: "column", gap: 20 }}>
        {/* Header */}
        <div style={{ display: "flex", flexDirection: "column", gap: 6, alignItems: "center", textAlign: "center" }}>
          <div style={{ fontSize: 12, letterSpacing: "0.08em", color: tokens.labelText }}>RESEARCHER MODE</div>
          <h1 style={{ margin: 0, fontSize: 27, fontWeight: 600, letterSpacing: "-0.01em" }}>Novelty DNA</h1>
          <p style={{ margin: 0, fontSize: 14, color: tokens.sectionSubtext }}>
            Sequences with no confident reference match — review, confirm, or discard candidates below.
          </p>
          <div style={{ display: "flex", justifyContent: "center", alignItems: "center", gap: 10, marginTop: 4, fontSize: 12.5, color: tokens.sectionSubtext, flexWrap: "wrap" }}>
            <span>
              {report.metadata.source_file ?? "Unnamed upload"}
              {report.metadata.location_label && ` · ${report.metadata.location_label}`}
              {report.metadata.depth_meters != null && ` · ${report.metadata.depth_meters.toLocaleString()} m`}
            </span>
            <span style={{ color: tokens.headerDot }}>·</span>
            <ProvenanceTag referenceDb={null} variant="plain" />
          </div>
        </div>

        {/* Filter bar */}
        <div style={{ ...panelStyle, flexDirection: "row", alignItems: "center", gap: 26, flexWrap: "wrap" }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 7, minWidth: 200 }}>
            <span style={{ fontSize: 11.5, letterSpacing: "0.08em", color: tokens.labelText }}>
              NOVELTY THRESHOLD · <span style={{ color: tokens.accentCyan, fontWeight: 600 }}>{threshold}%</span>
            </span>
            <input
              type="range"
              className="sv-novelty-slider"
              min={NOVELTY_FLOOR_PCT}
              max={97}
              value={threshold}
              onChange={(e) => setThreshold(+e.target.value)}
            />
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
            <span style={{ fontSize: 11.5, letterSpacing: "0.08em", color: tokens.labelText }}>ROUTE</span>
            <Dropdown
              value={routeFilter}
              onChange={setRouteFilter}
              options={[{ value: "All", label: "All routes" }, ...routes.map((r) => ({ value: r, label: r }))]}
            />
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
            <span style={{ fontSize: 11.5, letterSpacing: "0.08em", color: tokens.labelText }}>SORT BY</span>
            <Dropdown
              value={sortBy}
              onChange={setSortBy}
              options={[
                { value: "novelty", label: "Novelty %" },
                { value: "contamination", label: "Contamination score" },
              ]}
            />
          </div>
          <div style={{ flex: 1 }} />
          <button
            onClick={toggleBulk}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 9,
              padding: "10px 18px",
              borderRadius: 10,
              fontFamily: "inherit",
              fontSize: 13.5,
              fontWeight: 600,
              cursor: "pointer",
              border: `1px solid ${bulkMode ? tokens.cardBorderActive : tokens.sectionBorder}`,
              background: bulkMode ? "rgba(20,110,255,0.18)" : "#080F1C",
              color: bulkMode ? tokens.accentCyan : tokens.wordmark,
            }}
          >
            Bulk select
          </button>
        </div>

        {/* Contextual bulk action bar */}
        {bulkMode && selCount > 0 && (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 18,
              padding: "14px 20px",
              borderRadius: 9,
              border: `1px solid ${tokens.cardBorderActive}`,
              background: "linear-gradient(180deg, rgba(20,110,255,0.16), rgba(9,16,30,0.7))",
            }}
          >
            <span style={{ fontSize: 14, color: tokens.wordmark }}>
              <span style={{ fontWeight: 600, color: tokens.textPrimary }}>{selCount}</span> selected
            </span>
            <div style={{ flex: 1 }} />
            <SolidButton disabled title="Cloud Confirm (deeper reference search) isn't wired to a compute backend on this deployment yet">
              Cloud Confirm Selected
            </SolidButton>
          </div>
        )}

        {/* Candidate list */}
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <span style={{ fontSize: 13, letterSpacing: "0.08em", color: tokens.labelText }}>
            {rows.length} OF {report.possible_novelty.length} CANDIDATES SHOWN · THRESHOLD ≥ {threshold}%
          </span>

          {rows.length > 0 ? (
            <div style={{ border: "1px solid rgba(140,170,230,0.14)", borderRadius: 9, background: "linear-gradient(180deg, rgba(140,170,230,0.04) 0%, rgba(6,10,20,0.7) 100%)", boxShadow: "inset 0 1px 0 rgba(255,255,255,0.08), 0 14px 34px rgba(0,0,0,0.4)" }}>
              <div style={{ overflowX: "auto", borderRadius: 9 }}>
                <div style={{ minWidth: 1000 }}>
                  <div style={{ display: "grid", gridTemplateColumns: GRID_COLS, gap: 16, alignItems: "center", padding: "14px 24px", borderBottom: "1px solid #101D33", fontSize: 11.5, letterSpacing: "0.08em", color: tokens.pending }}>
                    <span />
                    <span>SEQ ID</span>
                    <span>NOVELTY / ROUTE / STATUS</span>
                    <span>REASON CODES</span>
                    <span />
                  </div>
                  {rows.map((n, i) => (
                    <CandidateRow
                      key={n.sequence_id}
                      n={n}
                      i={i}
                      bulkMode={bulkMode}
                      selected={!!selected[n.sequence_id]}
                      onToggleSelect={() => setSelected((s) => ({ ...s, [n.sequence_id]: !s[n.sequence_id] }))}
                      onOpen={() => setDrawerId(n.sequence_id)}
                    />
                  ))}
                </div>
              </div>
            </div>
          ) : (
            <div
              style={{
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                gap: 12,
                padding: "70px 24px",
                borderRadius: 9,
                border: "1px dashed #17253D",
                background: "rgba(6,10,20,0.4)",
              }}
            >
              <svg width={34} height={34} viewBox="0 0 26 26" fill="none">
                <path d="M6 2c0 6 14 8 14 13S6 20 6 24" stroke="#2A4A7A" strokeWidth="2" strokeLinecap="round" />
                <path d="M20 2c0 6-14 8-14 13s14 5 14 9" stroke="#17253D" strokeWidth="2" strokeLinecap="round" />
              </svg>
              <span style={{ fontSize: 15.5, fontWeight: 500, color: tokens.wordmark }}>No candidates match the current threshold</span>
              <span style={{ fontSize: 13, color: tokens.sectionSubtext }}>Try lowering the novelty cutoff below {threshold}%.</span>
            </div>
          )}
        </div>

        {/* Provenance footer */}
        <div style={{ display: "flex", justifyContent: "center", padding: "8px 0 2px", borderTop: `1px solid ${tokens.sectionBorder}` }}>
          <ProvenanceTag
            referenceDb={null}
            pipelineVersion={report.metadata.model_version_set !== "stub_none" ? report.metadata.model_version_set : null}
            matchedAt={report.metadata.created_at}
            variant="plain"
          />
        </div>
      </div>

      <AlignmentViewerDrawer candidate={drawerCandidate} onClose={() => setDrawerId(null)} />
    </div>
  );
}
