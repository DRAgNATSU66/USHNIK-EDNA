import { useEffect, useState, Fragment } from "react";
import { Link } from "react-router-dom";
import { MapContainer, TileLayer, Rectangle, CircleMarker, Popup, useMap } from "react-leaflet";
import "leaflet/dist/leaflet.css";
import SidebarMenu from "../../components/sidebar/SidebarMenu";
import { tokens } from "../../components/shared/tokens";
import { useAuth } from "../../contexts/AuthContext";
import {
  getPartnerAlerts,
  getPartnerHotspots,
  getPartnerSummary,
  getReportCustody,
  exportReportFair,
} from "../../lib/api";
import { liquidGlass } from "../../styles/liquidGlass";
import { revealStyle } from "../../styles/reveal";

// Legislative partner report (t-1027-3, M2). Every number on this page comes
// from the API on load: GET /partner/hotspots (grid-aggregated uploads),
// GET /partner/alerts (analyses with real flags / open urgent reviews),
// GET /partner/summary (time series for the flag-rate indicators), and, per
// alert, GET /reports/{id}/custody + the FAIR ZIP export. Panels that had no
// data source behind them (economic exposure, habitat decline, illustrative
// current-flow lines, a fixed Bay of Bengal hotspot list) were removed.

// Same per-page scale convention as Academia.jsx -- keeps card padding, radii
// and type sizes on the same ratio across every Partner Report screen.
const SCALE = 1.18;
const s = (n) => Math.round(n * SCALE * 10) / 10;

const ALL_DATA_ROLES = ["admin", "company_owner"];
const CELL_SIZES = [0.25, 0.5, 1, 2, 5];
const ALERT_LIMIT = 100;

// Cell / alert tone. Only two states carry a rule from the API: an open
// urgent review (triage_priority urgent) and at least one novelty or
// contamination flag. Nothing else is ranked.
const TONE = {
  urgent: { color: tokens.danger, label: "Open urgent review" },
  flagged: { color: tokens.warningAlt, label: "Novelty or contamination flag" },
  clear: { color: tokens.accentBlue, label: "Sampled, no flags" },
};

function cellTone(c) {
  if (c.open_urgent_reviews > 0) return "urgent";
  if (c.novelty_flags + c.contamination_flags > 0) return "flagged";
  return "clear";
}

const REASON_LABEL = {
  open_urgent_review: "open urgent review",
  contamination_flags: "contamination flags",
  novelty_flags: "novelty flags",
};

// API datetimes are UTC; stored naive ones come back without an offset.
function asDate(iso) {
  if (!iso) return null;
  const d = new Date(/[zZ]|[+-]\d\d:\d\d$/.test(iso) ? iso : `${iso}Z`);
  return Number.isNaN(d.getTime()) ? null : d;
}

function fmtDate(iso) {
  const d = asDate(iso);
  return d ? d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric", timeZone: "UTC" }) : "—";
}

function fmtDateTime(iso) {
  const d = asDate(iso);
  return d ? `${d.toISOString().slice(0, 16).replace("T", " ")} UTC` : "—";
}

function fmtCoord(v, pos, neg) {
  return `${Math.abs(v).toFixed(2)}°${v >= 0 ? pos : neg}`;
}

function short(hash) {
  return hash ? `${hash.slice(0, 10)}…${hash.slice(-8)}` : "—";
}

// ---------------------------------------------------------------------------
// Downloads (client-side CSV of exactly what the API returned; server-side
// FAIR ZIP / custody JSON)
// ---------------------------------------------------------------------------

function saveBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function csvCell(v) {
  if (v === null || v === undefined) return "";
  const str = String(v);
  return /[",\n\r]/.test(str) ? `"${str.replace(/"/g, '""')}"` : str;
}

function toCsv(columns, rows) {
  return [columns.join(","), ...rows.map((r) => columns.map((c) => csvCell(r[c])).join(","))].join("\n") + "\n";
}

function stamp(iso) {
  return (iso || new Date().toISOString()).slice(0, 19).replace(/[-:]/g, "").replace("T", "_");
}

function exportCellsCsv(hotspots) {
  const columns = [
    "cell_id", "cell_deg", "lat_min", "lat_max", "lng_min", "lng_max", "uploads", "analyses", "sequences",
    "sequences_with_taxon", "distinct_taxa", "novelty_flags", "contamination_flags", "open_reviews",
    "open_urgent_reviews", "top_taxa", "location_labels", "first_collected_at", "last_collected_at", "generated_at",
  ];
  const rows = hotspots.cells.map((c) => ({
    ...c,
    cell_deg: hotspots.cell_deg,
    top_taxa: c.top_taxa.map((t) => `${t.taxon} (${t.sequences})`).join("; "),
    location_labels: c.location_labels.join("; "),
    generated_at: hotspots.generated_at,
  }));
  saveBlob(new Blob([toCsv(columns, rows)], { type: "text/csv" }), `synthveda_hotspots_${stamp(hotspots.generated_at)}.csv`);
}

function exportAlertsCsv(alerts) {
  const columns = [
    "analysis_id", "upload_id", "priority", "reasons", "location_label", "latitude", "longitude", "collected_at",
    "analysis_created_at", "sequences", "novelty_flags", "contamination_flags", "contamination_types",
    "open_reviews", "open_urgent_reviews", "original_filename", "generated_at",
  ];
  const rows = alerts.alerts.map((a) => ({
    ...a,
    reasons: a.reasons.join("; "),
    contamination_types: Object.entries(a.contamination_types).map(([k, v]) => `${k}:${v}`).join("; "),
    generated_at: alerts.generated_at,
  }));
  saveBlob(new Blob([toCsv(columns, rows)], { type: "text/csv" }), `synthveda_alerts_${stamp(alerts.generated_at)}.csv`);
}

// ---------------------------------------------------------------------------
// Map
// ---------------------------------------------------------------------------

function FitToCells({ cells }) {
  const map = useMap();
  useEffect(() => {
    if (!cells.length) return;
    const pts = cells.flatMap((c) => [[c.lat_min, c.lng_min], [c.lat_max, c.lng_max]]);
    map.fitBounds(pts, { padding: [28, 28], maxZoom: 7 });
  }, [map, cells]);
  return null;
}

function MapLegend() {
  return (
    <div
      style={{
        position: "absolute",
        left: 10,
        bottom: 10,
        zIndex: 1500,
        padding: "10px 12px",
        borderRadius: 8,
        background: "rgba(8,14,26,0.88)",
        border: "1px solid #1C2E4C",
        display: "flex",
        flexDirection: "column",
        gap: 5,
        fontSize: 11,
        color: tokens.wordmark,
        pointerEvents: "none",
      }}
    >
      <span style={{ fontWeight: 600, marginBottom: 2 }}>Grid cell key</span>
      {Object.entries(TONE).map(([k, t]) => (
        <span key={k} style={{ display: "flex", alignItems: "center", gap: 7 }}>
          <span style={{ width: 9, height: 9, borderRadius: 2, background: t.color }} /> {t.label}
        </span>
      ))}
    </div>
  );
}

function CellPopup({ c, cellDeg }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 3, minWidth: 210 }}>
      <strong>
        Cell {fmtCoord(c.lat_min, "N", "S")}–{fmtCoord(c.lat_max, "N", "S")}, {fmtCoord(c.lng_min, "E", "W")}–{fmtCoord(c.lng_max, "E", "W")}
      </strong>
      <span>{cellDeg}° grid · {c.location_labels.length ? c.location_labels.join(", ") : "no location label"}</span>
      <span>{c.uploads} upload(s) · {c.analyses} analysis(es) · {c.sequences} sequences</span>
      <span>Novelty flags: {c.novelty_flags} · Contamination flags: {c.contamination_flags}</span>
      <span>Open reviews: {c.open_reviews} ({c.open_urgent_reviews} urgent)</span>
      <span>Distinct taxa: {c.distinct_taxa}{c.top_taxa.length ? ` — ${c.top_taxa.map((t) => `${t.taxon} (${t.sequences})`).join(", ")}` : ""}</span>
      <span>Collected: {c.first_collected_at ? `${fmtDate(c.first_collected_at)} – ${fmtDate(c.last_collected_at)}` : "date not recorded"}</span>
    </div>
  );
}

// isolation:"isolate" on the wrapper is load-bearing: Leaflet's own panes and
// controls carry z-index up to 1000, and without a wrapper that establishes
// its own stacking context that would fight the legend overlay and the
// app's fixed sidebar/modals. Rendered fresh in both the inline card and the
// fullscreen modal (each instance measures its own container on mount).
function HotspotMap({ hotspots, height = 340 }) {
  const cells = hotspots?.cells || [];
  return (
    <div style={{ position: "relative", width: "100%", height, isolation: "isolate" }}>
      {/* attributionControl={false} was an explicit earlier request; CARTO's
          free basemap and OSM data normally expect attribution, so revisit
          before this ships publicly. */}
      <MapContainer className="sv-legis-map" center={[10, 80]} zoom={2} minZoom={2} maxZoom={10} worldCopyJump scrollWheelZoom attributionControl={false} style={{ width: "100%", height: "100%", background: "#0A1526" }}>
        <TileLayer url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png" subdomains="abcd" maxZoom={19} />
        <FitToCells cells={cells} />
        {cells.map((c, i) => {
          const tone = TONE[cellTone(c)];
          return (
            <Fragment key={c.cell_id}>
              <Rectangle
                bounds={[[c.lat_min, c.lng_min], [c.lat_max, c.lng_max]]}
                pathOptions={{ color: tone.color, weight: 1.5, fillColor: tone.color, fillOpacity: 0.18, className: `sv-scale-in sv-scale-in-${Math.min(i, 9)}` }}
              >
                <Popup className="sv-map-popup">
                  <CellPopup c={c} cellDeg={hotspots.cell_deg} />
                </Popup>
              </Rectangle>
              {/* Fixed-size center dot so a cell stays visible when zoomed out. */}
              <CircleMarker
                center={[c.center_lat, c.center_lng]}
                radius={3.5}
                interactive={false}
                pathOptions={{ color: tone.color, weight: 0, fillColor: tone.color, fillOpacity: 1 }}
              />
            </Fragment>
          );
        })}
      </MapContainer>
      <MapLegend />
      {hotspots && !cells.length && (
        <div style={{ position: "absolute", inset: 0, zIndex: 1400, display: "flex", alignItems: "center", justifyContent: "center", pointerEvents: "none" }}>
          <span style={{ padding: "10px 16px", borderRadius: 8, background: "rgba(8,14,26,0.9)", border: "1px solid #1C2E4C", fontSize: 13, color: tokens.wordmark }}>
            No uploads with coordinates in this scope
          </span>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Flag-rate indicators (no species list needed)
// ---------------------------------------------------------------------------

function FlagRateSVG({ series }) {
  const W = 570, H = 170, L = 40, R = 556, T = 12, B = 132;
  const pts = series.map((p) => ({
    label: p.period_start,
    seq: p.sequences,
    nov: p.sequences ? p.novelty_flags / p.sequences : null,
    con: p.sequences ? p.contamination_flags / p.sequences : null,
  }));
  const maxRate = Math.max(0.1, ...pts.flatMap((p) => [p.nov ?? 0, p.con ?? 0]));
  const top = Math.ceil(maxRate * 10) / 10;
  const X = (i) => (pts.length === 1 ? (L + R) / 2 : L + (i * (R - L)) / (pts.length - 1));
  const Y = (v) => B - (v / top) * (B - T);
  // Periods with no sequences break the line (no rate exists there).
  const path = (key) =>
    pts.reduce((d, p, i) => {
      if (p[key] == null) return d;
      const prev = i > 0 && pts[i - 1][key] != null;
      return `${d}${prev ? "L" : "M"}${X(i).toFixed(1)} ${Y(p[key]).toFixed(1)} `;
    }, "");
  const grid = [0, 0.25, 0.5, 0.75, 1].map((f) => f * top);
  const labelEvery = Math.max(1, Math.ceil(pts.length / 8));
  const lines = [
    ["nov", tokens.accentCyan],
    ["con", tokens.warning],
  ];
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto", display: "block" }} role="img" aria-label="Novelty and contamination flag rate per period">
      {grid.map((v) => (
        <g key={v}>
          <line x1={L} y1={Y(v)} x2={R} y2={Y(v)} stroke="#3D4F6E" strokeWidth={1} strokeOpacity={0.6} />
          <text x={L - 6} y={Y(v) + 3} fill={tokens.pending} fontSize={9} textAnchor="end">{Math.round(v * 100)}%</text>
        </g>
      ))}
      {lines.map(([key, color]) => (
        <Fragment key={key}>
          <path d={path(key)} pathLength={1} className="sv-draw-path" fill="none" stroke={color} strokeWidth={2} strokeLinecap="round" />
          {pts.map((p, i) => (p[key] == null ? null : <circle key={i} cx={X(i)} cy={Y(p[key])} r={2.6} className="sv-fade-in-late" fill={color} />))}
        </Fragment>
      ))}
      {pts.map((p, i) =>
        i % labelEvery === 0 || i === pts.length - 1 ? (
          <text key={p.label} x={X(i)} y={B + 16} fill={tokens.pending} fontSize={9} textAnchor="middle">{fmtDate(p.label)}</text>
        ) : null
      )}
      {pts.map((p, i) =>
        i % labelEvery === 0 || i === pts.length - 1 ? (
          <text key={`n${p.label}`} x={X(i)} y={B + 30} fill={tokens.sectionSubtext} fontSize={8.5} textAnchor="middle">n={p.seq}</text>
        ) : null
      )}
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

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

const cardBase = {
  minWidth: 0,
  display: "flex",
  flexDirection: "column",
  gap: s(10),
  padding: `${s(20)}px ${s(22)}px`,
  borderRadius: s(9),
  border: "1px solid rgba(140,170,230,0.14)",
  background: "linear-gradient(180deg, rgba(140,170,230,0.06) 0%, rgba(6,10,20,0.7) 100%)",
  boxShadow: "inset 0 1px 0 rgba(255,255,255,0.10), 0 14px 34px rgba(0,0,0,0.4)",
};

const panelLabelStyle = { fontSize: s(11), fontWeight: 600, letterSpacing: "0.08em", color: tokens.wordmark };
const captionStyle = { fontSize: s(10.5), color: tokens.pending, lineHeight: 1.5 };
const emptyStyle = { padding: `${s(14)}px ${s(16)}px`, borderRadius: s(6), border: "1px dashed #1C2E4C", fontSize: s(12), lineHeight: 1.55, color: tokens.sectionSubtext };

// The map's own accent frame -- the "electric blue" glow language used for
// focus rings and glowing chrome elsewhere in the app.
const mapFrameStyle = {
  border: "1px solid rgba(59,158,255,0.45)",
  boxShadow: "0 0 0 1px rgba(59,158,255,0.12), 0 0 32px rgba(59,158,255,0.22)",
};

// Buttons use the app's shared liquid-glass material (styles/liquidGlass.js).
const ghostBtnStyle = {
  padding: `${s(7)}px ${s(14)}px`,
  borderRadius: 999,
  fontFamily: "inherit",
  fontSize: s(11.5),
  fontWeight: 500,
  color: tokens.wordmark,
  cursor: "pointer",
  ...liquidGlass({
    top: "rgba(255,255,255,0.10)",
    bottom: "rgba(255,255,255,0.02)",
    border: "rgba(255,255,255,0.18)",
    highlight: "rgba(255,255,255,0.28)",
    innerShadow: "rgba(0,0,0,0.12)",
    outerShadow: "0 6px 16px rgba(0,0,0,0.32)",
    blur: 12,
  }),
};

const disabledBtnStyle = { ...ghostBtnStyle, opacity: 0.5, cursor: "default" };

const selectStyle = {
  padding: `${s(5)}px ${s(10)}px`,
  borderRadius: s(6),
  border: "1px solid #1C2E4C",
  background: "#080F1C",
  color: tokens.wordmark,
  fontFamily: "inherit",
  fontSize: s(11.5),
};

function Definition({ label, text }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
      <span style={{ fontSize: s(10.5), fontWeight: 600, color: tokens.wordmark }}>{label}</span>
      <span style={captionStyle}>{text}</span>
    </div>
  );
}

function ReasonChip({ children, color }) {
  return (
    <span style={{ fontSize: s(10.5), padding: "1px 8px", borderRadius: 999, border: `1px solid ${color}55`, color, whiteSpace: "nowrap" }}>
      {children}
    </span>
  );
}

function alertTitle(a) {
  return a.location_label || a.original_filename || a.upload_id || a.analysis_id;
}

// ---------------------------------------------------------------------------
// Chain of custody (GET /reports/{id}/custody) for one alert
// ---------------------------------------------------------------------------

const INTEGRITY_TEXT = {
  results: {
    match: ["Stored results match the hash recorded at completion", "success"],
    mismatch: ["Stored results differ from the hash recorded at completion", "danger"],
    not_recorded: ["No results hash recorded yet", "pending"],
  },
  metadata: {
    unchanged: ["Sample metadata unchanged since recorded", "success"],
    changed_since_recorded: ["Sample metadata changed since recorded (may be a later correction)", "warning"],
    not_recorded: ["No metadata hash recorded", "pending"],
    upload_not_found: ["Upload record not found", "danger"],
  },
  file: {
    verified: ["Uploaded file re-hashed: matches the checksum taken at upload", "success"],
    mismatch: ["Uploaded file no longer matches its upload checksum", "danger"],
    unverifiable: ["File read, but no upload checksum exists to compare (pre-checksum upload)", "warning"],
    unavailable: ["Uploaded file could not be checked", "pending"],
    not_checked: ["File not checked", "pending"],
  },
};

function IntegrityLine({ kind, status, reason }) {
  const [text, tone] = INTEGRITY_TEXT[kind][status] || [`${kind}: ${status}`, "pending"];
  return (
    <span style={{ color: tokens[tone] ?? tokens.pending }}>
      {text}{reason ? ` — ${reason}` : ""}
    </span>
  );
}

function CustodyPanel({ analysisId }) {
  const [state, setState] = useState({ loading: true, data: null, error: "" });
  const [busy, setBusy] = useState("");

  useEffect(() => {
    let live = true;
    setState({ loading: true, data: null, error: "" });
    getReportCustody(analysisId)
      .then((data) => live && setState({ loading: false, data, error: "" }))
      .catch((e) => live && setState({ loading: false, data: null, error: e.message || "Custody could not be loaded." }));
    return () => {
      live = false;
    };
  }, [analysisId]);

  const downloadCustody = () => {
    saveBlob(
      new Blob([JSON.stringify(state.data, null, 2)], { type: "application/json" }),
      `synthveda_custody_${analysisId}.json`
    );
  };

  const downloadFair = async () => {
    setBusy("fair");
    try {
      const resp = await exportReportFair(analysisId);
      saveBlob(await resp.blob(), `synthveda_fair_${analysisId}.zip`);
    } catch (e) {
      setState((st) => ({ ...st, error: `FAIR export failed: ${e.message}` }));
    } finally {
      setBusy("");
    }
  };

  const d = state.data;
  const v = d?.verification;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: s(8), padding: `${s(14)}px ${s(16)}px`, borderRadius: s(6), border: "1px solid #101D33", background: "rgba(8,14,26,0.5)" }}>
      <span style={{ ...panelLabelStyle, fontSize: s(10.5) }}>CHAIN OF CUSTODY</span>
      {state.loading && <span style={captionStyle}>Verifying chain of custody…</span>}
      {state.error && <span style={{ fontSize: s(11.5), color: tokens.danger }}>{state.error}</span>}
      {d && (
        <div style={{ display: "flex", flexDirection: "column", gap: s(5), fontSize: s(11.5), fontFamily: "ui-monospace,monospace", color: tokens.wordmark }}>
          {d.upload && (
            <>
              <span>source: {d.upload.original_filename || "—"}</span>
              <span>uploaded: {fmtDateTime(d.upload.uploaded_at)} · by user {d.upload.uploaded_by || "—"}</span>
              <span style={{ wordBreak: "break-all" }}>upload sha-256: {short(d.upload.checksum_sha256)}</span>
            </>
          )}
          <span style={{ color: v.valid ? tokens.success : tokens.danger }}>
            {v.valid
              ? `Chain intact — ${v.length} event(s), every hash recomputed`
              : `Chain broken at event ${v.first_break?.seq}: ${v.first_break?.reason}`}
          </span>
          <span style={{ wordBreak: "break-all" }}>head hash: {short(v.head_hash)} · checked {fmtDateTime(v.checked_at)}</span>
          <IntegrityLine kind="results" status={d.results_integrity.status} />
          <IntegrityLine kind="metadata" status={d.metadata_integrity.status} />
          <IntegrityLine kind="file" status={d.file_integrity.status} reason={d.file_integrity.status === "verified" ? null : d.file_integrity.reason} />
        </div>
      )}
      <div style={{ display: "flex", gap: s(8), flexWrap: "wrap" }}>
        <button onClick={downloadCustody} disabled={!d} style={d ? ghostBtnStyle : disabledBtnStyle}>Download custody JSON</button>
        <button onClick={downloadFair} disabled={busy === "fair"} style={busy === "fair" ? disabledBtnStyle : ghostBtnStyle}>
          {busy === "fair" ? "Preparing FAIR ZIP…" : "Download FAIR ZIP"}
        </button>
      </div>
      <span style={captionStyle}>Every FAIR export is itself recorded on this sample's custody chain before the file is sent.</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

// One API panel: refetches whenever `key` (the serialised request params)
// changes; a stale response from an earlier key is dropped.
function usePanel(load, key) {
  const [state, setState] = useState({ loading: true, data: null, error: "" });
  useEffect(() => {
    let live = true;
    setState((st) => ({ ...st, loading: true, error: "" }));
    load()
      .then((data) => live && setState({ loading: false, data, error: "" }))
      .catch((e) => live && setState({ loading: false, data: null, error: e.message || "Failed to load." }));
    return () => {
      live = false;
    };
    // `load` is a fresh closure every render; `key` carries its inputs.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return state;
}

export default function Legislative() {
  const { user } = useAuth();
  const privileged = ALL_DATA_ROLES.includes(user?.role);
  const [scope, setScope] = useState("mine");
  const [cellDeg, setCellDeg] = useState(1);
  const [trendInterval, setTrendInterval] = useState("week");
  const [mapOpen, setMapOpen] = useState(false);
  const [alertId, setAlertId] = useState(null);
  const [showDefs, setShowDefs] = useState(false);

  const scopeParam = privileged && scope === "all" ? "all" : undefined;
  const hotspots = usePanel(() => getPartnerHotspots({ scope: scopeParam, cell_deg: cellDeg }), `${scopeParam}|${cellDeg}`);
  const alerts = usePanel(() => getPartnerAlerts({ scope: scopeParam, limit: ALERT_LIMIT }), `${scopeParam}`);
  const summary = usePanel(
    () => getPartnerSummary({ scope: scopeParam, interval: trendInterval, top_taxa: 1 }),
    `${scopeParam}|${trendInterval}`
  );

  const hs = hotspots.data;
  const al = alerts.data;
  const series = summary.data?.time_series || [];
  const totals = summary.data?.totals;
  const activeAlert = al?.alerts.find((a) => a.analysis_id === alertId);
  const scopeLabel = scopeParam === "all" ? "all users' uploads" : "your uploads";
  const periodsWithSequences = series.filter((p) => p.sequences > 0).length;

  return (
    <div style={pageStyle}>
      <div style={ambientGlow} />
      <SidebarMenu />
      <div style={{ position: "relative", maxWidth: s(1560), margin: "0 auto", padding: `${s(32)}px ${s(44)}px ${s(44)}px`, display: "flex", flexDirection: "column", gap: s(18) }}>
        {/* Header */}
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", textAlign: "center", gap: s(6) }}>
          <div style={{ fontSize: s(12), letterSpacing: "0.08em", color: tokens.labelText }}>PARTNER REPORT › LEGISLATIVE</div>
          <h1 style={{ margin: 0, fontSize: s(27), fontWeight: 600, letterSpacing: "-0.01em" }}>eDNA Biodiversity Analyzer</h1>
          <p style={{ margin: 0, fontSize: s(14), color: tokens.sectionSubtext }}>Policymaker · Regional biodiversity &amp; policy</p>
          {privileged && (
            <label style={{ display: "flex", alignItems: "center", gap: s(8), fontSize: s(12), color: tokens.sectionSubtext, marginTop: s(4) }}>
              Scope
              <select aria-label="Scope" value={scope} onChange={(e) => setScope(e.target.value)} style={selectStyle}>
                <option value="mine">My uploads</option>
                <option value="all">All users</option>
              </select>
            </label>
          )}
        </div>

        {/* Map + alerts */}
        <div style={{ display: "grid", gridTemplateColumns: "1.5fr 1fr", gap: s(18), alignItems: "start" }}>
          <div style={{ ...cardBase, ...revealStyle(0) }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: s(12), flexWrap: "wrap" }}>
              <span style={panelLabelStyle}>SAMPLING HOTSPOT MAP · {cellDeg}° GRID</span>
              <div style={{ display: "flex", gap: s(8), alignItems: "center" }}>
                <select aria-label="Grid cell size" value={cellDeg} onChange={(e) => setCellDeg(Number(e.target.value))} style={selectStyle}>
                  {CELL_SIZES.map((d) => <option key={d} value={d}>{d}° cells</option>)}
                </select>
                <button onClick={() => setMapOpen(true)} style={ghostBtnStyle}>Open Map</button>
                <button onClick={() => hs && exportCellsCsv(hs)} disabled={!hs?.cells.length} style={hs?.cells.length ? ghostBtnStyle : disabledBtnStyle}>
                  Export Cells CSV
                </button>
              </div>
            </div>
            <div style={{ position: "relative", borderRadius: s(6), overflow: "hidden", ...mapFrameStyle }}>
              <HotspotMap hotspots={hs} height={s(340)} />
            </div>
            {hotspots.error && <span style={{ fontSize: s(12), color: tokens.danger }}>Hotspots could not be loaded: {hotspots.error}</span>}
            {hs && (
              <span style={captionStyle} data-testid="hotspot-coverage">
                {hs.cells.length} cell(s) from {hs.coverage.uploads_with_coordinates} of {hs.coverage.uploads_in_scope} upload(s) in scope
                {hs.coverage.uploads_without_coordinates ? ` · ${hs.coverage.uploads_without_coordinates} without coordinates (not mapped)` : ""}.
                {" "}Each upload is placed in the {hs.cell_deg}° × {hs.cell_deg}° latitude/longitude cell containing its recorded coordinates; a cell is an aggregation unit, not a detection radius or drift model. Click a cell for its counts and taxa.
              </span>
            )}
            {hs?.notes.filter((n) => !n.startsWith("No uploads")).map((n) => <span key={n} style={captionStyle}>{n}</span>)}
          </div>

          <div style={{ ...cardBase, ...revealStyle(1) }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: s(8), flexWrap: "wrap" }}>
              <span style={panelLabelStyle}>ALERTS{al ? ` · ${al.total}` : ""}{al?.urgent ? ` (${al.urgent} URGENT)` : ""}</span>
              <div style={{ display: "flex", gap: s(8) }}>
                <button onClick={() => setShowDefs((v) => !v)} style={ghostBtnStyle} aria-expanded={showDefs}>
                  {showDefs ? "Hide definitions" : "How alerts are defined"}
                </button>
                <button onClick={() => al && exportAlertsCsv(al)} disabled={!al?.alerts.length} style={al?.alerts.length ? ghostBtnStyle : disabledBtnStyle}>
                  Export CSV
                </button>
              </div>
            </div>
            {showDefs && al && (
              <div style={{ display: "flex", flexDirection: "column", gap: s(8), padding: `${s(10)}px ${s(12)}px`, borderRadius: s(6), border: "1px solid #101D33", background: "rgba(8,14,26,0.5)" }}>
                <Definition label="Alert" text={al.definitions.alert} />
                <Definition label="Priority" text={al.definitions.priority} />
                <Definition label="Novelty flag" text={al.definitions.novelty_flag} />
                <Definition label="Contamination flag" text={al.definitions.contamination_flag} />
              </div>
            )}
            {alerts.loading && !al && <span style={captionStyle}>Loading alerts…</span>}
            {alerts.error && <span style={{ fontSize: s(12), color: tokens.danger }}>Alerts could not be loaded: {alerts.error}</span>}
            {al && !al.alerts.length && <div style={emptyStyle}>{al.notes[0] || "No alerts in this scope."}</div>}
            <div style={{ display: "flex", flexDirection: "column", gap: s(10), maxHeight: s(470), overflowY: "auto" }}>
              {al?.alerts.map((a) => {
                const color = a.priority === "urgent" ? TONE.urgent.color : TONE.flagged.color;
                return (
                  <button
                    key={a.analysis_id}
                    onClick={() => setAlertId(a.analysis_id)}
                    style={{ all: "unset", display: "flex", flexDirection: "column", gap: s(5), padding: `${s(12)}px ${s(14)}px`, borderRadius: s(6), cursor: "pointer", border: "1px solid #101D33", borderLeft: `3px solid ${color}`, background: "rgba(8,14,26,0.55)" }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: s(8) }}>
                      <span style={{ display: "flex", alignItems: "center", gap: s(8), fontSize: s(13), fontWeight: 600, color: tokens.textPrimary }}>
                        <span style={{ width: s(8), height: s(8), borderRadius: "50%", background: color, boxShadow: `0 0 8px ${color}88`, flexShrink: 0 }} />
                        {alertTitle(a)}
                      </span>
                      <span style={{ fontSize: s(10.5), fontWeight: 600, color }}>{a.priority === "urgent" ? "Urgent" : "Flagged"}</span>
                    </div>
                    <div style={{ display: "flex", gap: s(6), flexWrap: "wrap" }}>
                      {a.open_urgent_reviews > 0 && <ReasonChip color={TONE.urgent.color}>{a.open_urgent_reviews} open urgent review(s)</ReasonChip>}
                      {a.contamination_flags > 0 && <ReasonChip color={tokens.warning}>{a.contamination_flags} contamination flag(s)</ReasonChip>}
                      {a.novelty_flags > 0 && <ReasonChip color={tokens.accentCyan}>{a.novelty_flags} novelty flag(s)</ReasonChip>}
                    </div>
                    <span style={captionStyle}>
                      {a.sequences} sequences · analysed {fmtDate(a.analysis_created_at)}
                      {a.collected_at ? ` · collected ${fmtDate(a.collected_at)}` : ""}
                      {a.latitude != null ? ` · ${fmtCoord(a.latitude, "N", "S")}, ${fmtCoord(a.longitude, "E", "W")}` : " · no coordinates"}
                    </span>
                  </button>
                );
              })}
            </div>
            {al?.truncated && <span style={captionStyle}>{al.notes.find((n) => n.startsWith("alerts lists"))}</span>}
          </div>
        </div>

        {/* Indicators */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: s(18) }}>
          <div style={{ ...cardBase, ...revealStyle(2) }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: s(8), flexWrap: "wrap" }}>
              <span style={panelLabelStyle}>FLAG-RATE INDICATORS</span>
              <select aria-label="Trend period" value={trendInterval} onChange={(e) => setTrendInterval(e.target.value)} style={selectStyle}>
                <option value="week">Weekly</option>
                <option value="month">Monthly</option>
              </select>
            </div>
            <span style={captionStyle}>
              Rule (needs no species list): for each {trendInterval === "week" ? "ISO week" : "month"} (UTC, by analysis date), novelty-flag rate = novelty-flagged sequences ÷ sequences analysed, and contamination-flag rate = contamination-flagged sequences ÷ sequences analysed. Periods with no analysed sequences have no rate and break the line; n = sequences analysed.
            </span>
            {summary.error && <span style={{ fontSize: s(12), color: tokens.danger }}>Trend could not be loaded: {summary.error}</span>}
            {summary.data && periodsWithSequences === 0 && <div style={emptyStyle}>No analysed sequences in this scope yet, so there is no rate to plot.</div>}
            {summary.data && periodsWithSequences > 0 && (
              <>
                <div style={{ display: "flex", gap: s(16), fontSize: s(11), color: tokens.sectionSubtext }}>
                  <span style={{ display: "flex", alignItems: "center", gap: 6 }}><span style={{ width: 14, height: 2, background: tokens.accentCyan }} /> Novelty-flag rate</span>
                  <span style={{ display: "flex", alignItems: "center", gap: 6 }}><span style={{ width: 14, height: 2, background: tokens.warning }} /> Contamination-flag rate</span>
                </div>
                <FlagRateSVG series={series} />
                {totals && (
                  <span style={captionStyle}>
                    All periods: {totals.novelty_flags} novelty and {totals.contamination_flags} contamination flags over {totals.sequences} sequences in {totals.analyses} analyses.
                  </span>
                )}
              </>
            )}
          </div>
          <div style={{ ...cardBase, ...revealStyle(3) }}>
            <span style={panelLabelStyle}>INDICATOR SPECIES TREND</span>
            <div style={emptyStyle} data-testid="indicator-species-pending">
              Indicator-species list pending. No list of indicator species has been supplied for this deployment yet, so no
              indicator-species trend is computed. Once the list is provided, this panel will track how often those taxa are
              detected per period; no species are assumed in the meantime.
            </div>
          </div>
        </div>

        <div style={{ display: "flex", justifyContent: "center", padding: `${s(8)}px 0 2px`, borderTop: "1px solid #0C1526" }}>
          <span style={{ fontSize: s(11), color: tokens.pending }}>
            Counted from the database on load{hs ? ` at ${fmtDateTime(hs.generated_at)}` : ""} · scope: {scopeLabel} · CSV exports contain exactly the rows shown
          </span>
        </div>
      </div>

      {/* Fullscreen map modal */}
      {mapOpen && (
        <>
          <div onClick={() => setMapOpen(false)} style={{ position: "fixed", inset: 0, background: "rgba(2,4,9,0.75)", backdropFilter: "blur(4px)", zIndex: 40 }} />
          <div style={{ position: "fixed", inset: "5%", zIndex: 41, display: "flex", flexDirection: "column", gap: s(14), padding: `${s(22)}px ${s(26)}px`, borderRadius: s(12), border: "1px solid #1C2E4C", background: "#050912", boxShadow: "0 40px 120px rgba(0,0,0,0.7)" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span style={{ fontSize: s(13), fontWeight: 600, letterSpacing: "0.08em", color: tokens.wordmark }}>SAMPLING HOTSPOT MAP · {cellDeg}° GRID · FULLSCREEN</span>
              <button onClick={() => setMapOpen(false)} style={ghostBtnStyle}>Close ✕</button>
            </div>
            <div style={{ flex: 1, minHeight: 0, borderRadius: s(6), overflow: "hidden", ...mapFrameStyle, display: "flex" }}>
              <HotspotMap hotspots={hs} height="100%" />
            </div>
          </div>
        </>
      )}

      {/* Alert detail modal */}
      {activeAlert && (
        <>
          <div onClick={() => setAlertId(null)} style={{ position: "fixed", inset: 0, background: "rgba(2,4,9,0.7)", backdropFilter: "blur(4px)", zIndex: 40 }} />
          <div role="dialog" aria-label={`Alert: ${alertTitle(activeAlert)}`} style={{ position: "fixed", top: "50%", left: "50%", transform: "translate(-50%,-50%)", width: s(600), maxWidth: "92vw", maxHeight: "90vh", overflowY: "auto", zIndex: 41, display: "flex", flexDirection: "column", gap: s(14), padding: `${s(24)}px ${s(28)}px`, borderRadius: s(12), border: "1px solid #1C2E4C", background: "#050912", boxShadow: "0 40px 120px rgba(0,0,0,0.7)" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: s(10) }}>
              <span style={{ display: "flex", alignItems: "center", gap: s(10), fontSize: s(16), fontWeight: 600 }}>
                <span style={{ width: s(10), height: s(10), borderRadius: "50%", background: activeAlert.priority === "urgent" ? TONE.urgent.color : TONE.flagged.color }} />
                {alertTitle(activeAlert)}
              </span>
              <button onClick={() => setAlertId(null)} aria-label="Close alert" style={{ width: s(30), height: s(30), borderRadius: s(8), border: "1px solid #17253D", background: "#080F1C", color: tokens.wordmark, fontSize: s(14), cursor: "pointer" }}>✕</button>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: s(10) }}>
              {[
                ["SEQUENCES", activeAlert.sequences],
                ["NOVELTY FLAGS", activeAlert.novelty_flags],
                ["CONTAMINATION FLAGS", activeAlert.contamination_flags],
                ["OPEN REVIEWS", activeAlert.open_reviews],
                ["OPEN URGENT", activeAlert.open_urgent_reviews],
                ["PRIORITY", activeAlert.priority === "urgent" ? "Urgent" : "Flagged"],
              ].map(([k, v]) => (
                <div key={k} style={{ display: "flex", flexDirection: "column", gap: 3, padding: `${s(9)}px ${s(11)}px`, borderRadius: s(6), border: "1px solid #101D33", background: "rgba(8,14,26,0.5)" }}>
                  <span style={{ fontSize: s(9.5), letterSpacing: "0.07em", color: tokens.sectionSubtext }}>{k}</span>
                  <span style={{ fontSize: s(17), fontWeight: 600 }}>{v}</span>
                </div>
              ))}
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: s(4), fontSize: s(12), color: tokens.wordmark, lineHeight: 1.55 }}>
              <span>Why listed: {activeAlert.reasons.map((r) => REASON_LABEL[r] || r).join(", ")}.</span>
              {Object.keys(activeAlert.contamination_types).length > 0 && (
                <span>Contamination types: {Object.entries(activeAlert.contamination_types).map(([k, v]) => `${k.replace(/_/g, " ")} (${v})`).join(", ")}.</span>
              )}
              {Object.keys(activeAlert.open_reviews_by_type).length > 0 && (
                <span>Open reviews: {Object.entries(activeAlert.open_reviews_by_type).map(([k, v]) => `${k.replace(/_/g, " ")} (${v})`).join(", ")}.</span>
              )}
              <span style={captionStyle}>
                Analysis {activeAlert.analysis_id} · analysed {fmtDateTime(activeAlert.analysis_created_at)}
                {activeAlert.collected_at ? ` · collected ${fmtDateTime(activeAlert.collected_at)}` : " · collection date not recorded"}
                {activeAlert.latitude != null ? ` · ${fmtCoord(activeAlert.latitude, "N", "S")}, ${fmtCoord(activeAlert.longitude, "E", "W")}` : " · no coordinates recorded"}
                {!activeAlert.upload_found ? " · upload record no longer exists" : ""}
              </span>
              <Link to={`/analysis/${activeAlert.analysis_id}`} style={{ color: "#6FBAFF", fontSize: s(12) }}>Open the full analysis →</Link>
            </div>
            <CustodyPanel analysisId={activeAlert.analysis_id} />
          </div>
        </>
      )}
    </div>
  );
}
