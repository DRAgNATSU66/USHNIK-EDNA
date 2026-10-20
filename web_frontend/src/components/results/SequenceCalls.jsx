import { useMemo, useState } from "react";
import ConfidenceChip from "../shared/ConfidenceChip";
import ProvenanceTag from "../shared/ProvenanceTag";
import { tokens, pillStyle } from "../shared/tokens";
import DecisionTrace from "./DecisionTrace";
import { getAnalysis } from "../../lib/api";
import { formatIdentity, formatScore, ruleText, taxonCall } from "../../lib/decision";

// Per-sequence final calls for one analysis (GET /analysis/{id}, rows
// loaded without traces). Each row: final taxon + rank + % identity + the
// reference DB version it was matched against (ProvenanceTag) and the route
// head's class score (ConfidenceChip), plus an expandable "Why this answer"
// that renders the stored decision_trace. Traces are fetched once, on the
// first expand, with GET /analysis/{id}?include_trace=true: the API has no
// per-sequence trace endpoint, so one request brings every trace.

const PAGE_SIZE = 20;
const GRID = "minmax(150px, 1.1fr) minmax(200px, 1.6fr) 90px minmax(150px, 1fr) minmax(140px, 1fr) 150px";

const CLASS_TONE = {
  known_species: "success",
  known_species_not_novelty: "success",
  likely_taxonomic_group: "accent",
  possible_novelty: "purple",
  possible_contamination: "warning",
  low_quality_unusable: "danger",
  unknown_needs_online_confirmation: "pending",
};

function confidenceProps(row, call) {
  const model = row.model_version_used;
  if (call.hasDecision) {
    if (call.confidence == null) return { basis: "no route-head prediction", confidence: "not scored" };
    return { basis: `${model ?? "route head"} class score`, confidence: `${formatScore(call.confidence)} (uncalibrated)` };
  }
  if (row.inference_mode === "stub" || (model ?? "").includes("stub")) {
    return { basis: "stub inference (no head weights)", confidence: "not scored" };
  }
  return { basis: `${model ?? "route head"} class score`, confidence: `${formatScore(call.confidence) ?? "—"} (uncalibrated)` };
}

function missingDbLabel(call) {
  if (!call.hasDecision) return "Reference DB: none recorded (pre-orchestrator result)";
  if (call.finalRoute === "low_quality") return "Reference DB: not searched (low-quality read)";
  return "Reference DB: no lookup result (see Why this answer)";
}

function TaxonCell({ call }) {
  if (call.taxon) {
    return (
      <span style={{ display: "flex", flexDirection: "column", gap: 2 }}>
        <span style={{ fontSize: 14.5, fontStyle: "italic", color: tokens.textPrimary }}>{call.taxon}</span>
        <span style={{ fontSize: 11.5, color: tokens.pending }}>{call.rank ?? "rank not recorded"}</span>
      </span>
    );
  }
  return (
    <span style={{ fontSize: 13, color: tokens.pending }}>
      {call.hasDecision ? "No reference assignment" : "No taxon recorded"}
    </span>
  );
}

export default function SequenceCalls({ analysisId, analysis, error }) {
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  const [open, setOpen] = useState(() => new Set());
  const [traces, setTraces] = useState({ status: "idle", byId: null, error: "" });

  const rows = useMemo(() => analysis?.results ?? [], [analysis]);
  const decided = useMemo(() => rows.filter((r) => r.decision).length, [rows]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter((r) => {
      const c = taxonCall(r);
      return r.sequence_id.toLowerCase().includes(q) || (c.taxon ?? "").toLowerCase().includes(q)
        || (c.resultClass ?? "").toLowerCase().includes(q) || (c.finalRoute ?? "").toLowerCase().includes(q);
    });
  }, [rows, query]);

  const pages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const current = Math.min(page, pages - 1);
  const visible = filtered.slice(current * PAGE_SIZE, (current + 1) * PAGE_SIZE);

  const loadTraces = () => {
    setTraces({ status: "loading", byId: null, error: "" });
    getAnalysis(analysisId, { includeTrace: true })
      .then((full) => {
        const byId = {};
        for (const r of full?.results ?? []) byId[r.sequence_id] = r.decision_trace ?? null;
        setTraces({ status: "ready", byId, error: "" });
      })
      .catch((e) => setTraces({ status: "error", byId: null, error: e.message || "request failed" }));
  };

  const toggle = (row) => {
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(row.sequence_id)) next.delete(row.sequence_id);
      else next.add(row.sequence_id);
      return next;
    });
    if (row.decision && traces.status === "idle") loadTraces();
  };

  if (error) {
    return <span style={{ fontSize: 13, color: tokens.danger }}>Could not load the per-sequence results: {error}</span>;
  }
  if (!analysis) {
    return <span style={{ fontSize: 13, color: tokens.sectionSubtext }}>Loading per-sequence results…</span>;
  }
  if (rows.length === 0) {
    return <span style={{ fontSize: 13, color: tokens.sectionSubtext }}>This analysis stored no per-sequence results.</span>;
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <span style={{ fontSize: 12.5, color: tokens.sectionSubtext }}>
          {rows.length.toLocaleString()} sequences · {decided.toLocaleString()} with an orchestrator decision
          {analysis.orchestrator_version ? ` (${analysis.orchestrator_version})` : ""}
        </span>
        <input
          className="sv-upload-field"
          type="text"
          aria-label="Filter sequences"
          placeholder="Filter by sequence, taxon, class or route…"
          value={query}
          onChange={(e) => { setQuery(e.target.value); setPage(0); }}
          style={{ marginLeft: "auto", minWidth: 260, boxSizing: "border-box" }}
        />
      </div>

      {decided === 0 && (
        <div style={{ ...pillStyle("pending"), borderRadius: 8, padding: "10px 14px", whiteSpace: "normal", lineHeight: 1.5 }}>
          This analysis was stored before the orchestrator: no row has a decision or a decision trace, and no
          reference database is recorded.
        </div>
      )}

      <div style={{ overflowX: "auto", border: "1px solid rgba(140,170,230,0.14)", borderRadius: 9 }}>
        <div style={{ minWidth: 960 }}>
          <div style={{ display: "grid", gridTemplateColumns: GRID, gap: 14, padding: "12px 18px", borderBottom: "1px solid #101D33", fontSize: 11, letterSpacing: "0.08em", color: tokens.pending }}>
            <span>SEQUENCE</span>
            <span>FINAL TAXON · RANK</span>
            <span>% IDENTITY</span>
            <span>RESULT CLASS</span>
            <span>ROUTE</span>
            <span />
          </div>
          {visible.map((row) => {
            const call = taxonCall(row);
            const isOpen = open.has(row.sequence_id);
            const moved = call.routerRoute && call.finalRoute && call.routerRoute !== call.finalRoute;
            return (
              <div key={row.sequence_id} data-testid="sequence-call" style={{ borderBottom: "1px solid #0C1526" }}>
                <div style={{ display: "grid", gridTemplateColumns: GRID, gap: 14, alignItems: "center", padding: "14px 18px 8px" }}>
                  <span style={{ fontSize: 13, fontFamily: "ui-monospace,monospace", color: tokens.wordmark, overflowWrap: "anywhere" }}>{row.sequence_id}</span>
                  <TaxonCell call={call} />
                  <span style={{ fontSize: 13.5, fontWeight: 600, color: call.percentIdentity != null ? tokens.textPrimary : tokens.pending }}>
                    {formatIdentity(call.percentIdentity) ?? "—"}
                  </span>
                  <span style={{ display: "flex", flexDirection: "column", gap: 3, alignItems: "flex-start" }}>
                    <span style={{ ...pillStyle(CLASS_TONE[call.resultClass] ?? "pending"), fontSize: 11, padding: "2px 9px" }}>{call.resultClass ?? "—"}</span>
                    {call.rule && <span style={{ fontSize: 11, color: tokens.pending }} title={ruleText(call.rule)}>rule {call.rule}</span>}
                  </span>
                  <span style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                    <span style={{ fontSize: 12.5, fontFamily: "ui-monospace,monospace", color: tokens.wordmark }}>{call.finalRoute ?? "—"}</span>
                    {moved && <span style={{ fontSize: 11, color: tokens.warning }}>router picked {call.routerRoute}</span>}
                  </span>
                  <button
                    type="button"
                    aria-expanded={isOpen}
                    onClick={() => toggle(row)}
                    style={{ padding: "7px 12px", borderRadius: 9, border: "1px solid rgba(160,205,255,0.4)", background: isOpen ? "rgba(20,110,255,0.2)" : "#080F1C", color: "#BFDCFF", fontFamily: "inherit", fontSize: 12.5, fontWeight: 600, cursor: "pointer" }}
                  >
                    {isOpen ? "Hide" : "Why this answer"}
                  </button>
                </div>
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap", padding: "0 18px 12px" }}>
                  <ConfidenceChip {...confidenceProps(row, call)} />
                  <ProvenanceTag
                    referenceDb={call.referenceDb}
                    referenceDbVersion={call.referenceDbVersion}
                    matchedAt={analysis.created_at}
                    missingLabel={missingDbLabel(call)}
                  />
                </div>
                {isOpen && (
                  <div style={{ padding: "0 18px 16px" }}>
                    <DecisionTrace
                      decision={row.decision ?? null}
                      trace={traces.byId?.[row.sequence_id] ?? null}
                      status={traces.status === "idle" ? "loading" : traces.status}
                      error={traces.error}
                      onRetry={loadTraces}
                    />
                  </div>
                )}
              </div>
            );
          })}
          {visible.length === 0 && (
            <div style={{ padding: "28px 18px", fontSize: 13, color: tokens.sectionSubtext, textAlign: "center" }}>No sequence matches the filter.</div>
          )}
        </div>
      </div>

      {pages > 1 && (
        <div style={{ display: "flex", alignItems: "center", justifyContent: "flex-end", gap: 10, fontSize: 12.5, color: tokens.sectionSubtext }}>
          <button type="button" disabled={current === 0} onClick={() => setPage(current - 1)} style={pagerStyle(current === 0)}>← Prev</button>
          <span>Page {current + 1} of {pages} · {filtered.length.toLocaleString()} shown</span>
          <button type="button" disabled={current >= pages - 1} onClick={() => setPage(current + 1)} style={pagerStyle(current >= pages - 1)}>Next →</button>
        </div>
      )}
    </div>
  );
}

function pagerStyle(disabled) {
  return {
    padding: "6px 12px",
    borderRadius: 8,
    border: `1px solid ${tokens.sectionBorder}`,
    background: "#080F1C",
    color: disabled ? tokens.pending : tokens.wordmark,
    fontFamily: "inherit",
    fontSize: 12.5,
    cursor: disabled ? "default" : "pointer",
  };
}
