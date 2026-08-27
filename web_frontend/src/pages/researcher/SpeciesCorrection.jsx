import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import SidebarMenu from "../../components/sidebar/SidebarMenu";
import ProvenanceTag from "../../components/shared/ProvenanceTag";
import { tokens } from "../../components/shared/tokens";
import Dropdown from "../../components/shared/Dropdown";
import { useAuth } from "../../contexts/AuthContext";
import { getReport, listReports, listReviewsForSequence, submitReview } from "../../lib/api";

const TIER_COLOR = { green: tokens.success, amber: tokens.warningAlt, red: tokens.danger };
const TIER_LABEL = { green: "● Green", amber: "● Amber", red: "● Red" };

// Confidence-tier marker dot with a radiating glow ring behind it (sv-dot-
// ripple/sv-dot-core-pulse, shared with Novelty DNA's status dots) instead
// of a flat static circle -- delay is per-row so a whole table doesn't
// pulse in lockstep.
function TierDot({ tier, size = 13, delay = 0 }) {
  const color = TIER_COLOR[tier];
  return (
    <span style={{ position: "relative", display: "inline-flex", flexShrink: 0, width: size, height: size }}>
      <span
        className="sv-dot-ripple"
        style={{ position: "absolute", inset: 0, borderRadius: "50%", background: color, animationDelay: `${delay}s` }}
      />
      <span
        className="sv-dot-core"
        style={{ width: size, height: size, borderRadius: "50%", background: color, boxShadow: `0 0 ${size < 12 ? 8 : 10}px ${color}88`, animationDelay: `${delay}s` }}
      />
    </span>
  );
}

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

const GRID_COLS = "26px 200px 1.4fr 110px 110px 1fr 130px";

function SolidButton({ children, onClick, disabled, title, tone = "accent" }) {
  const bg =
    tone === "danger"
      ? "linear-gradient(180deg, #E06A4F 0%, #C24A32 100%)"
      : "linear-gradient(180deg, #459AF5 0%, #1A71F0 48%, #0D57D1 100%)";
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      title={title}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 8,
        padding: "11px 22px",
        borderRadius: 12,
        border: "1px solid rgba(160,205,255,0.5)",
        background: disabled ? "linear-gradient(180deg, #2A3B58 0%, #1C2A42 100%)" : bg,
        boxShadow: disabled ? "none" : "inset 0 1.5px 0 rgba(255,255,255,0.4), 0 8px 24px rgba(20,110,255,0.3)",
        color: disabled ? "#7A8699" : "#FFFFFF",
        fontFamily: "inherit",
        fontSize: 13,
        fontWeight: 600,
        cursor: disabled ? "not-allowed" : "pointer",
      }}
    >
      {children}
    </button>
  );
}

function OverrideDrawer({ analysisId, entry, onClose }) {
  const { user } = useAuth();
  const [proposed, setProposed] = useState("");
  const [justification, setJustification] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [history, setHistory] = useState(null);
  const [historyError, setHistoryError] = useState("");

  useEffect(() => {
    if (!entry) return;
    setProposed("");
    setJustification("");
    setConfirming(false);
    setSubmitted(false);
    setHistory(null);
    setHistoryError("");
    listReviewsForSequence(analysisId, entry.sequence_id)
      .then(setHistory)
      .catch((e) => setHistoryError(e.message || "Failed to load correction history."));
  }, [analysisId, entry]);

  if (!entry) return null;

  const priorProposals = (history ?? []).filter((r) => r.proposed_taxon);
  const hasConflict = priorProposals.length > 0;

  const handleSubmit = async () => {
    setSubmitting(true);
    try {
      await submitReview({
        analysis_id: analysisId,
        sequence_id: entry.sequence_id,
        correction_type: "species_correction",
        proposed_taxon: proposed.trim(),
        evidence_notes: justification.trim() || null,
      });
      setSubmitted(true);
      setConfirming(false);
      const refreshed = await listReviewsForSequence(analysisId, entry.sequence_id);
      setHistory(refreshed);
    } catch (e) {
      alert("Submit failed: " + e.message);
      setConfirming(false);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <>
      <div onClick={onClose} style={{ position: "fixed", inset: 0, background: "rgba(2,4,9,0.6)", backdropFilter: "blur(3px)", zIndex: 40 }} />
      <div
        style={{
          position: "fixed",
          top: 0,
          right: 0,
          bottom: 0,
          width: 620,
          maxWidth: "94vw",
          zIndex: 41,
          display: "flex",
          flexDirection: "column",
          gap: 18,
          padding: "28px 32px 32px",
          boxSizing: "border-box",
          borderLeft: `1px solid ${tokens.sectionBorder}`,
          background: "#050912",
          boxShadow: "-30px 0 80px rgba(0,0,0,0.6)",
          overflowY: "auto",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
            <span style={{ fontSize: 11, letterSpacing: "0.08em", color: tokens.labelText }}>
              MANUAL OVERRIDE · <span style={{ fontFamily: "ui-monospace,monospace", color: tokens.wordmark }}>{entry.sequence_id}</span>
            </span>
            <span style={{ fontSize: 19, fontWeight: 600 }}>Review assignment</span>
          </div>
          <button
            onClick={onClose}
            style={{ width: 34, height: 34, borderRadius: 8, border: `1px solid ${tokens.sectionBorder}`, background: "#080F1C", color: tokens.wordmark, fontSize: 15, cursor: "pointer" }}
          >
            ✕
          </button>
        </div>

        {/* Original assignment baseline */}
        <div style={{ display: "flex", flexDirection: "column", gap: 8, padding: "16px 18px", borderRadius: 6, border: `1px solid ${tokens.sectionBorder}`, background: "rgba(8,14,26,0.5)" }}>
          <span style={{ fontSize: 10.5, letterSpacing: "0.08em", color: tokens.labelText }}>AUTOMATED ASSIGNMENT (BASELINE — UNCHANGED)</span>
          <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
            <TierDot tier={entry.confidence_tier} size={10} />
            <span style={{ fontSize: 17, fontStyle: entry.predicted_taxon ? "italic" : "normal", fontWeight: 600, color: entry.predicted_taxon ? tokens.textPrimary : tokens.pending }}>
              {entry.predicted_taxon || "No taxonomic assignment yet"}
            </span>
            <span style={{ fontSize: 11.5, fontWeight: 600, color: TIER_COLOR[entry.confidence_tier] }}>
              {(entry.confidence * 100).toFixed(1)}% confidence
            </span>
          </div>
          <span style={{ fontSize: 11.5, color: tokens.sectionSubtext }}>
            {entry.length.toLocaleString()} bp · route {entry.route} · matched against{" "}
            <span style={{ fontFamily: "ui-monospace,monospace" }}>pending configuration</span>
          </span>
        </div>

        {/* Conflict indicator */}
        {hasConflict && (
          <div style={{ display: "flex", flexDirection: "column", gap: 10, padding: "14px 18px", borderRadius: 6, border: `1px solid ${tokens.warningBorder}`, background: `linear-gradient(180deg, ${tokens.warningBg}, rgba(224,168,92,0.03))` }}>
            <span style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, fontWeight: 600, color: tokens.warningAlt }}>
              Prior correction{priorProposals.length > 1 ? "s exist" : " exists"} — review before submitting a competing proposal
            </span>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
              {priorProposals.map((p) => (
                <div key={p.review_id} style={{ display: "flex", flexDirection: "column", gap: 4, padding: "11px 13px", borderRadius: 4, border: `1px solid ${tokens.sectionBorder}`, background: "rgba(8,14,26,0.6)" }}>
                  <span style={{ fontSize: 12.5, fontStyle: "italic" }}>{p.proposed_taxon}</span>
                  <span style={{ fontSize: 10.5, color: tokens.sectionSubtext }}>
                    {p.submitted_by} · {new Date(p.created_at).toLocaleString()}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {!submitted && (
          <>
            {/* Override form */}
            <div style={{ display: "flex", flexDirection: "column", gap: 13 }}>
              <label style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                <span style={{ fontSize: 11, fontWeight: 600, letterSpacing: "0.06em", color: tokens.wordmark }}>PROPOSED SPECIES NAME</span>
                <input
                  className="sv-upload-field"
                  type="text"
                  placeholder="e.g. Thunnus obesus"
                  value={proposed}
                  onChange={(e) => setProposed(e.target.value)}
                  style={{ fontStyle: "italic" }}
                />
              </label>
              <label style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                <span style={{ fontSize: 11, fontWeight: 600, letterSpacing: "0.06em", color: tokens.wordmark }}>
                  SUBMITTER ID <span style={{ fontWeight: 400, color: tokens.pending }}>· auto-filled, audit trail</span>
                </span>
                <input className="sv-upload-field" type="text" value={`${user?.display_name || "Researcher"} · ${user?.email || ""}`} disabled style={{ color: tokens.sectionSubtext, cursor: "not-allowed" }} />
              </label>
              <label style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                <span style={{ fontSize: 11, fontWeight: 600, letterSpacing: "0.06em", color: tokens.wordmark }}>JUSTIFICATION</span>
                <textarea
                  className="sv-upload-field"
                  placeholder="Cite supporting literature or DOI… e.g. doi:10.1093/icesjms/fsab123"
                  value={justification}
                  onChange={(e) => setJustification(e.target.value)}
                  style={{ resize: "vertical", minHeight: 74, fontFamily: "inherit" }}
                />
              </label>
            </div>

            {/* Data integrity preview */}
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <span style={{ fontSize: 11, letterSpacing: "0.08em", color: tokens.labelText }}>DATA INTEGRITY PREVIEW — WRITE ON SUBMIT</span>
              <div style={{ padding: "14px 16px", borderRadius: 4, border: `1px solid ${tokens.sectionBorder}`, background: "#04070E", fontFamily: "ui-monospace,monospace", fontSize: 11.5, lineHeight: 1.75, overflowX: "auto" }}>
                <div style={{ color: tokens.pending }}>{`{ "sequence": "${entry.sequence_id}", "correction": {`}</div>
                <div style={{ color: tokens.danger, background: "rgba(255,90,90,0.07)" }}>{`-  "assignment": "${entry.predicted_taxon || "null"}"`}</div>
                <div style={{ color: tokens.success, background: "rgba(70,200,150,0.07)" }}>{`+  "assignment": "${proposed || "⟨proposed name⟩"}"`}</div>
                <div style={{ color: tokens.pending }}>{`  "submitter": "${user?.email || "unknown"}" } }`}</div>
              </div>
            </div>

            {/* Actions */}
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              {!confirming ? (
                <>
                  <SolidButton disabled={!proposed.trim()} onClick={() => setConfirming(true)}>
                    Submit Correction
                  </SolidButton>
                  <button onClick={onClose} style={{ padding: "11px 18px", border: `1px solid ${tokens.sectionBorder}`, borderRadius: 12, background: "#080F1C", fontFamily: "inherit", fontSize: 13, fontWeight: 500, color: tokens.wordmark, cursor: "pointer" }}>
                    Cancel
                  </button>
                </>
              ) : (
                <>
                  <SolidButton tone="danger" onClick={handleSubmit} disabled={submitting}>
                    {submitting ? "Submitting..." : "Confirm — log to audit trail"}
                  </SolidButton>
                  <button onClick={() => setConfirming(false)} style={{ padding: "11px 16px", border: "none", background: "none", fontFamily: "inherit", fontSize: 12.5, color: tokens.sectionSubtext, cursor: "pointer" }}>
                    Back
                  </button>
                </>
              )}
            </div>
            <p style={{ margin: 0, fontSize: 11, color: tokens.pending, lineHeight: 1.5 }}>
              Submitting logs this correction to the audit trail for curator review — it does not immediately retrain any
              model. Corrections only reach a model after a curator accepts them and an admin explicitly freezes a
              monthly training batch.
            </p>
          </>
        )}

        {submitted && (
          <span style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12.5, color: tokens.success }}>
            ✓ Correction logged to audit trail — pending curator review.
          </span>
        )}

        {/* Version history */}
        <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 4 }}>
          <span style={{ fontSize: 11, letterSpacing: "0.08em", color: tokens.labelText }}>VERSION HISTORY</span>
          {historyError && <span style={{ fontSize: 12, color: tokens.danger }}>{historyError}</span>}
          {!historyError && history?.length === 0 && (
            <span style={{ fontSize: 12, color: tokens.pending }}>No corrections submitted yet for this sequence.</span>
          )}
          {history && history.length > 0 && (
            <div style={{ display: "flex", flexDirection: "column", border: `1px solid ${tokens.sectionBorder}`, borderRadius: 4, background: "rgba(8,14,26,0.4)" }}>
              {history.map((h) => (
                <div key={h.review_id} style={{ display: "flex", alignItems: "baseline", gap: 12, padding: "10px 14px", borderBottom: "1px solid #0C1526", fontSize: 11.5 }}>
                  <span style={{ color: tokens.pending, fontFamily: "ui-monospace,monospace", flexShrink: 0, width: 140 }}>
                    {new Date(h.created_at).toLocaleString()}
                  </span>
                  <span style={{ color: tokens.wordmark, flexShrink: 0, width: 130 }}>{h.submitted_by}</span>
                  <span style={{ color: tokens.sectionSubtext }}>
                    {h.proposed_taxon ? `proposed → ${h.proposed_taxon} (${h.state})` : `${h.correction_type} (${h.state})`}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </>
  );
}

export default function SpeciesCorrection() {
  const [searchParams] = useSearchParams();
  const requestedId = searchParams.get("analysis_id");

  const [analysisId, setAnalysisId] = useState(requestedId);
  const [report, setReport] = useState(null);
  const [error, setError] = useState("");
  const [confFilter, setConfFilter] = useState("All");
  const [routeFilter, setRouteFilter] = useState("All");
  const [query, setQuery] = useState("");
  const [sortBy, setSortBy] = useState("confidence");
  const [drawerSeqId, setDrawerSeqId] = useState(null);

  useEffect(() => {
    if (requestedId) {
      setAnalysisId(requestedId);
      return;
    }
    listReports(1)
      .then((rows) => {
        if (rows.length === 0) setError("No analyses yet — upload a sample first.");
        else setAnalysisId(rows[0].analysis_id);
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
    return [...new Set(report.taxonomic_assignments.map((a) => a.route))].sort();
  }, [report]);

  const rows = useMemo(() => {
    if (!report) return [];
    const q = query.trim().toLowerCase();
    let list = report.taxonomic_assignments.filter(
      (a) =>
        (confFilter === "All" || a.confidence_tier === confFilter) &&
        (routeFilter === "All" || a.route === routeFilter) &&
        (!q || a.sequence_id.toLowerCase().includes(q) || (a.predicted_taxon ?? "").toLowerCase().includes(q))
    );
    list = [...list].sort((a, b) => (sortBy === "length" ? b.length - a.length : b.confidence - a.confidence));
    return list;
  }, [report, confFilter, routeFilter, query, sortBy]);

  const drawerEntry = report?.taxonomic_assignments.find((a) => a.sequence_id === drawerSeqId) ?? null;

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
        <div style={{ position: "relative", textAlign: "center", padding: "4rem", color: tokens.sectionSubtext }}>Loading assignments...</div>
      </div>
    );
  }

  return (
    <div style={pageStyle}>
      <div style={ambientGlow} />
      <SidebarMenu />
      <div style={{ position: "relative", maxWidth: 1900, margin: "0 auto", padding: "32px 44px 44px", display: "flex", flexDirection: "column", gap: 20 }}>
        {/* Header */}
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", textAlign: "center", gap: 6 }}>
          <div style={{ fontSize: 12, letterSpacing: "0.08em", color: tokens.labelText }}>RESEARCHER MODE</div>
          <h1 style={{ margin: 0, fontSize: 27, fontWeight: 600, letterSpacing: "-0.01em" }}>Species Correction</h1>
          <p style={{ margin: 0, fontSize: 14, color: tokens.sectionSubtext }}>
            Review automated taxonomic assignments — verify, override, or flag low-confidence matches.
          </p>
          <div style={{ display: "flex", justifyContent: "center", alignItems: "center", gap: 10, marginTop: 4, fontSize: 12.5, color: tokens.sectionSubtext, flexWrap: "wrap" }}>
            <span>{report.metadata.source_file ?? "Unnamed upload"}</span>
            <span style={{ color: tokens.headerDot }}>·</span>
            <ProvenanceTag referenceDb={null} variant="plain" />
          </div>
        </div>

        {/* Filter bar */}
        <div style={{ ...panelStyle, flexDirection: "row", alignItems: "flex-end", gap: 22, flexWrap: "wrap" }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
            <span style={{ fontSize: 10.5, letterSpacing: "0.08em", color: tokens.labelText }}>CONFIDENCE</span>
            <div style={{ display: "flex", gap: 6 }}>
              {["All", "green", "amber", "red"].map((tier) => (
                <button
                  key={tier}
                  onClick={() => setConfFilter(tier)}
                  style={{
                    padding: "8px 13px",
                    borderRadius: 3,
                    fontFamily: "inherit",
                    fontSize: 12,
                    fontWeight: 600,
                    cursor: "pointer",
                    border: `1px solid ${confFilter === tier ? tokens.cardBorderActive : tokens.sectionBorder}`,
                    background: confFilter === tier ? "rgba(20,110,255,0.16)" : "#080F1C",
                    color: tier === "All" ? tokens.wordmark : TIER_COLOR[tier],
                  }}
                >
                  {tier === "All" ? "All" : TIER_LABEL[tier]}
                </button>
              ))}
            </div>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
            <span style={{ fontSize: 10.5, letterSpacing: "0.08em", color: tokens.labelText }}>ROUTE</span>
            <Dropdown
              value={routeFilter}
              onChange={setRouteFilter}
              options={[{ value: "All", label: "All routes" }, ...routes.map((r) => ({ value: r, label: r }))]}
            />
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 7, flex: 1, minWidth: 200 }}>
            <span style={{ fontSize: 10.5, letterSpacing: "0.08em", color: tokens.labelText }}>SEARCH</span>
            <input
              className="sv-upload-field"
              type="text"
              placeholder="Sequence ID or species name…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              style={{ width: "100%", boxSizing: "border-box" }}
            />
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
            <span style={{ fontSize: 10.5, letterSpacing: "0.08em", color: tokens.labelText }}>SORT BY</span>
            <Dropdown
              value={sortBy}
              onChange={setSortBy}
              options={[
                { value: "confidence", label: "Confidence score" },
                { value: "length", label: "Sequence length" },
              ]}
            />
          </div>
        </div>

        {/* Match table */}
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <span style={{ fontSize: 13, letterSpacing: "0.08em", color: tokens.labelText }}>
            {rows.length} OF {report.taxonomic_assignments.length} MATCHED ASSIGNMENTS SHOWN
          </span>

          {rows.length > 0 ? (
            <div style={{ border: `1px solid rgba(140,170,230,0.14)`, borderRadius: 9, background: "linear-gradient(180deg, rgba(140,170,230,0.04) 0%, rgba(6,10,20,0.7) 100%)", boxShadow: "inset 0 1px 0 rgba(255,255,255,0.08), 0 14px 34px rgba(0,0,0,0.4)" }}>
              <div style={{ overflowX: "auto", borderRadius: 9 }}>
                <div style={{ minWidth: 1000 }}>
                  <div style={{ display: "grid", gridTemplateColumns: GRID_COLS, gap: 16, alignItems: "center", padding: "14px 24px", borderBottom: "1px solid #101D33", fontSize: 11.5, letterSpacing: "0.08em", color: tokens.pending }}>
                    <span />
                    <span>SEQ ID</span>
                    <span>AUTOMATED ASSIGNMENT</span>
                    <span>CONF.</span>
                    <span>LENGTH</span>
                    <span>MATCHED AGAINST</span>
                    <span />
                  </div>
                  {rows.map((r, i) => (
                    <div
                      key={r.sequence_id}
                      onClick={() => setDrawerSeqId(r.sequence_id)}
                      style={{ display: "grid", gridTemplateColumns: GRID_COLS, gap: 16, alignItems: "center", padding: "20px 24px", borderBottom: "1px solid #0C1526", cursor: "pointer" }}
                    >
                      <TierDot tier={r.confidence_tier} size={13} delay={i * 0.12} />
                      <span style={{ fontSize: 15, fontFamily: "ui-monospace,monospace", color: tokens.wordmark, wordBreak: "break-all", overflowWrap: "anywhere" }}>{r.sequence_id}</span>
                      <span style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                        <span style={{ fontSize: 16, fontStyle: r.predicted_taxon ? "italic" : "normal", color: r.predicted_taxon ? tokens.textPrimary : tokens.pending }}>
                          {r.predicted_taxon || "No assignment yet"}
                        </span>
                        <span style={{ fontSize: 12.5, color: tokens.pending }}>{r.route}</span>
                      </span>
                      <span style={{ fontSize: 15.5, fontWeight: 600, color: TIER_COLOR[r.confidence_tier] }}>{(r.confidence * 100).toFixed(1)}%</span>
                      <span style={{ fontSize: 14.5, color: tokens.sectionSubtext }}>{r.length.toLocaleString()} bp</span>
                      <span style={{ fontSize: 13, color: tokens.pending, fontFamily: "ui-monospace,monospace" }}>pending configuration</span>
                      <button
                        onClick={(e) => { e.stopPropagation(); setDrawerSeqId(r.sequence_id); }}
                        style={
                          r.confidence_tier === "green"
                            ? { padding: "9px 18px", border: `1px solid ${tokens.sectionBorder}`, borderRadius: 10, background: "#080F1C", fontFamily: "inherit", fontSize: 13.5, fontWeight: 500, color: tokens.sectionSubtext, cursor: "pointer" }
                            : { padding: "9px 18px", border: "1px solid rgba(160,205,255,0.4)", borderRadius: 10, background: "linear-gradient(180deg, rgba(69,154,245,0.28) 0%, rgba(13,87,209,0.22) 100%)", fontFamily: "inherit", fontSize: 13.5, fontWeight: 600, color: "#BFDCFF", cursor: "pointer" }
                        }
                      >
                        Review
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 10, padding: "60px 20px", borderRadius: 9, border: "1px dashed #17253D", background: "rgba(6,10,20,0.4)" }}>
              <span style={{ fontSize: 14, fontWeight: 500, color: tokens.wordmark }}>No assignments match the current filters</span>
              <span style={{ fontSize: 12.5, color: tokens.sectionSubtext }}>Clear the search or widen the confidence filter.</span>
            </div>
          )}
        </div>

        <div style={{ display: "flex", justifyContent: "center", padding: "8px 0 2px", borderTop: `1px solid ${tokens.sectionBorder}` }}>
          <ProvenanceTag
            referenceDb={null}
            pipelineVersion={report.metadata.model_version_set !== "stub_none" ? report.metadata.model_version_set : null}
            matchedAt={report.metadata.created_at}
            variant="plain"
          />
        </div>
      </div>

      <OverrideDrawer analysisId={analysisId} entry={drawerEntry} onClose={() => setDrawerSeqId(null)} />
    </div>
  );
}
