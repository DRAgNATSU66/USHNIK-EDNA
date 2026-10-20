import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import SidebarMenu from "../../components/sidebar/SidebarMenu";
import { tokens, pillStyle } from "../../components/shared/tokens";
import { WarningTriangleIcon } from "../../components/shared/icons";
import { useAuth } from "../../contexts/AuthContext";
import {
  getReport,
  listReports,
  exportReportJson,
  exportReportCsv,
  exportReportFair,
  getEnvironmentContext,
  getPartnerSummary,
  getPartnerCooccurrence,
  getPartnerRhythms,
} from "../../lib/api";
import { useNoveltyThreshold } from "../../lib/noveltyThreshold";
import { parseApiDateTime } from "../../lib/sampleMetadata";
import jellyfishArt from "../../assets/jellyfish.png";
import { revealStyle } from "../../styles/reveal";

// Every panel on this page reads a real API response (t-1027-1, M3):
//   environment   GET /environment/uploads/{upload_id}  (+ coverage from GET /partner/summary)
//   co-occurrence GET /partner/cooccurrence              (top-50 taxon pairs per sample)
//   rhythms       GET /partner/rhythms                   (uploads/detections by UTC hour, weekday)
//   export        GET /reports/{id}/export/{json,csv,fair}
// Panels the deployment has no data source for (toxicity, hydrophone,
// multi-omics overlay, acoustic backscatter) were removed rather than shown
// with sample data.

// Single scale factor applied to every size on this page (container width,
// card padding, gauges, font sizes) -- keeps every ratio identical to the
// pre-scale design, just larger throughout, per feedback that the cards
// should be bigger and cover more of the screen.
const SCALE = 1.18;
const s = (n) => Math.round(n * SCALE * 10) / 10;

const NET_COLORS = [tokens.accentBlue, tokens.accentCyan, "#146EFF", tokens.purple];

// Order offered in the co-occurrence rank picker (deepest first); the API
// also accepts "any" = every taxon at whatever rank it was recorded.
const RANK_ORDER = ["species", "genus", "family", "order", "class", "phylum", "kingdom", "superkingdom"];

const ENV_VARIABLES = [
  { key: "temperature", label: "TEMPERATURE" },
  { key: "salinity", label: "SALINITY" },
  { key: "dissolved_oxygen", label: "DISSOLVED OXYGEN" },
  { key: "ph", label: "pH" },
  { key: "current", label: "CURRENT SPEED" },
  { key: "wind", label: "WIND SPEED · 10 m" },
];

const ENV_STATUS_TONE = { complete: "success", partial: "warning", pending: "pending", failed: "danger", not_applicable: "pending" };

function fmtDateTime(v) {
  const d = parseApiDateTime(v);
  return d ? d.toLocaleString(undefined, { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", timeZoneName: "short" }) : "—";
}

function fmtNum(v, digits = 2) {
  if (v == null || Number.isNaN(Number(v))) return "—";
  const n = Number(v);
  return Math.abs(n) >= 100 ? n.toFixed(0) : n.toFixed(digits);
}

// Filename from the API's Content-Disposition (exposed by CORS in
// services/api/app/main.py), so the saved file keeps the server's timestamped name.
function filenameFrom(resp, fallback) {
  const cd = resp.headers?.get?.("content-disposition") || "";
  const m = cd.match(/filename="?([^";]+)"?/i);
  return m ? m[1] : fallback;
}

// ---------------------------------------------------------------------------
// Decorative hero art -- the low-poly jellyfish behind the sampling station
// card's copy. Purely visual, not a data representation.
// ---------------------------------------------------------------------------

// Semi-circular range gauge for a real reading (salinity, pH). The arc's
// min/max are a fixed display scale, printed under the arc.
function RangeGauge({ value, min, max, unit }) {
  const cx = 90, cy = 84, r = 56;
  const hasValue = value != null;
  const frac = hasValue ? Math.max(0, Math.min(1, (value - min) / (max - min))) : 0;
  const arc = (f0, f1, color, w, animate) => {
    const a0 = Math.PI + f0 * Math.PI, a1 = Math.PI + f1 * Math.PI;
    return (
      <path
        key={color + f0}
        d={`M${cx + Math.cos(a0) * r} ${cy + Math.sin(a0) * r} A${r} ${r} 0 0 1 ${cx + Math.cos(a1) * r} ${cy + Math.sin(a1) * r}`}
        pathLength={animate ? 1 : undefined}
        className={animate ? "sv-draw-path" : undefined}
        fill="none"
        stroke={color}
        strokeWidth={w}
        strokeLinecap="round"
      />
    );
  };
  return (
    <svg viewBox="0 0 180 132" style={{ width: "100%", maxWidth: s(190), margin: "0 auto", display: "block" }}>
      {arc(0, 1, "#14233C", 15)}
      {hasValue && arc(0, frac, tokens.accentBlue, 15, true)}
      <text className="sv-fade-in-late" x={cx} y={cy - 20} fill={hasValue ? tokens.textPrimary : tokens.pending} fontSize={25} fontWeight={600} textAnchor="middle">{hasValue ? Number(value).toFixed(2) : "—"}</text>
      <text x={cx - r} y={cy + 26} fill={tokens.pending} fontSize={9} textAnchor="middle">{min}{unit}</text>
      <text x={cx + r} y={cy + 26} fill={tokens.pending} fontSize={9} textAnchor="middle">{max}{unit}</text>
    </svg>
  );
}

function ThermoIcon() {
  return (
    <svg width={20} height={44} viewBox="0 0 16 44" fill="none">
      <rect x={5} y={3} width={6} height={27} rx={3} stroke={tokens.accentCyan} strokeWidth={1.6} />
      <circle cx={8} cy={36} r={5.5} fill="rgba(59,158,255,0.25)" stroke={tokens.accentCyan} strokeWidth={1.6} />
      <line x1={8} y1={33} x2={8} y2={17} stroke={tokens.accentCyan} strokeWidth={2.4} strokeLinecap="round" />
    </svg>
  );
}

// Smooth trend line over a provider's by-day series (wind, current).
function TrendSVG({ points, unit }) {
  const vals = points.map((p) => p.value);
  const hi = Math.max(...vals) * 1.15 || 1;
  const lo = 0;
  const W = 460, H = 150, x0 = 40, x1 = W - 14, yT = 18, yB = H - 30;
  const X = (i) => x0 + (i * (x1 - x0)) / Math.max(1, vals.length - 1);
  const Y = (v) => yB - ((v - lo) / (hi - lo)) * (yB - yT);
  let d = "";
  for (let i = 0; i < vals.length; i++) {
    if (!i) { d = `M${X(0)} ${Y(vals[0]).toFixed(1)}`; continue; }
    const xc = (X(i - 1) + X(i)) / 2;
    d += ` C${xc} ${Y(vals[i - 1]).toFixed(1)} ${xc} ${Y(vals[i]).toFixed(1)} ${X(i)} ${Y(vals[i]).toFixed(1)}`;
  }
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto", display: "block" }} role="img" aria-label={`Daily mean by date, ${unit}`}>
      {[hi, (hi + lo) / 2, lo].map((v, i) => {
        const y = yT + (i * (yB - yT)) / 2;
        return (
          <g key={i}>
            <line x1={x0} y1={y} x2={x1} y2={y} stroke="#14233C" strokeWidth={1} />
            <text x={x0 - 8} y={y + 3.5} fill={tokens.pending} fontSize={9.5} textAnchor="end">{v.toFixed(v < 1 ? 2 : 1)}</text>
          </g>
        );
      })}
      <path d={d} pathLength={1} className="sv-draw-path" fill="none" stroke={tokens.wordmark} strokeWidth={2} strokeLinecap="round" />
      {points.map((p, i) => (
        <g key={p.date}>
          <circle cx={X(i)} cy={Y(p.value)} r={2.4} fill={tokens.accentCyan} className="sv-fade-in-late"><title>{`${p.date}: ${p.value} ${unit}`}</title></circle>
          <text className="sv-fade-in-late" x={X(i)} y={H - 8} fill={tokens.pending} fontSize={9.5} textAnchor="middle">{p.date.slice(5)}</text>
        </g>
      ))}
    </svg>
  );
}

// Stacked bars for one rhythm axis (24 hours or 7 weekdays).
function RhythmBars({ bins, metric }) {
  const W = 540, H = 170, x0 = 30, x1 = W - 8, yT = 14, yB = H - 26;
  const totals = bins.map((b) => (metric === "uploads" ? b.uploads : b.detections));
  const max = Math.max(1, ...totals);
  const slot = (x1 - x0) / bins.length;
  const bw = Math.max(2, slot * 0.68);
  const Y = (v) => yB - (v / max) * (yB - yT);
  const every = bins.length > 12 ? 3 : 1;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto", display: "block" }}>
      {(max >= 2 ? [0, Math.round(max / 2), max] : [0, max]).map((v, i) => (
        <g key={i}>
          <line x1={x0} y1={Y(v)} x2={x1} y2={Y(v)} stroke="#14233C" strokeWidth={1} />
          <text x={x0 - 6} y={Y(v) + 3.5} fill={tokens.pending} fontSize={9.5} textAnchor="end">{v}</text>
        </g>
      ))}
      {bins.map((b, i) => {
        const x = x0 + i * slot + (slot - bw) / 2;
        const segs = metric === "uploads"
          ? [{ v: b.uploads_collected_at, c: tokens.accentCyan }, { v: b.uploads_upload_time, c: tokens.purple }]
          : [{ v: b.detections, c: tokens.success }];
        let base = yB;
        const tip = metric === "uploads"
          ? `${b.label} UTC: ${b.uploads} upload${b.uploads === 1 ? "" : "s"} (${b.uploads_collected_at} by collection time, ${b.uploads_upload_time} by upload time)`
          : `${b.label} UTC: ${b.detections} detection${b.detections === 1 ? "" : "s"}`;
        return (
          <g key={b.bin}>
            <title>{tip}</title>
            {segs.map((sg, j) => {
              if (!sg.v) return null;
              const h = (sg.v / max) * (yB - yT);
              base -= h;
              return <rect key={j} x={x} y={base} width={bw} height={h} rx={1.5} fill={sg.c} opacity={0.85} className="sv-fade-in-late" />;
            })}
            {i % every === 0 && <text x={x + bw / 2} y={H - 8} fill={tokens.pending} fontSize={9.5} textAnchor="middle">{b.label}</text>}
          </g>
        );
      })}
    </svg>
  );
}

// Circular layout of the taxa named in the returned pairs. Edge width ∝
// samples together; opacity ∝ Jaccard. No positions are randomised.
function CooccurrenceGraph({ pairs, nodes }) {
  const W = 760, H = 420, cx = W / 2, cy = H / 2;
  const n = nodes.length;
  const rx = n > 1 ? W / 2 - 150 : 0, ry = n > 1 ? H / 2 - 40 : 0;
  const key = (t, r) => `${t}\u0000${r}`;
  const pos = new Map();
  nodes.forEach((nd, i) => {
    const a = -Math.PI / 2 + (i / Math.max(1, n)) * 2 * Math.PI;
    pos.set(key(nd.taxon, nd.rank), { x: cx + Math.cos(a) * rx, y: cy + Math.sin(a) * ry, a });
  });
  const maxTogether = Math.max(1, ...pairs.map((p) => p.samples_together));
  const maxSamples = Math.max(1, ...nodes.map((nd) => nd.samples));
  const showLabels = n <= 30;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto", display: "block", borderRadius: 6, border: "1px solid #101D33", background: "#04070E" }} role="img" aria-label="Taxon co-occurrence network">
      {pairs.map((p, i) => {
        const a = pos.get(key(p.taxon_a, p.rank_a)), b = pos.get(key(p.taxon_b, p.rank_b));
        if (!a || !b) return null;
        return (
          <line key={i} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke={tokens.accentBlue} strokeWidth={0.8 + 3.2 * (p.samples_together / maxTogether)} opacity={0.2 + 0.6 * p.jaccard} className="sv-fade-in-late">
            <title>{`${p.taxon_a} + ${p.taxon_b}: together in ${p.samples_together} sample(s); Jaccard ${p.jaccard}`}</title>
          </line>
        );
      })}
      {nodes.map((nd, i) => {
        const p = pos.get(key(nd.taxon, nd.rank));
        const r = 3 + 6 * Math.sqrt(nd.samples / maxSamples);
        const c = NET_COLORS[i % NET_COLORS.length];
        const right = Math.cos(p.a) >= 0;
        const label = nd.taxon.length > 26 ? `${nd.taxon.slice(0, 25)}…` : nd.taxon;
        return (
          <g key={key(nd.taxon, nd.rank)} className="sv-fade-in-late">
            <title>{`${nd.taxon} (${nd.rank}): in ${nd.samples} sample(s), ${nd.sequences} sequence(s)`}</title>
            <circle cx={p.x} cy={p.y} r={r} fill="#04070E" stroke={c} strokeWidth={1.4} style={{ filter: `drop-shadow(0 0 4px ${c})` }} />
            <circle cx={p.x} cy={p.y} r={Math.max(1, r * 0.35)} fill={c} />
            {showLabels && (
              <text x={p.x + (right ? r + 5 : -r - 5)} y={p.y + 3.5} fill={tokens.sectionSubtext} fontSize={10.5} fontStyle={nd.rank === "species" || nd.rank === "genus" ? "italic" : "normal"} textAnchor={right ? "start" : "end"}>{label}</text>
            )}
          </g>
        );
      })}
    </svg>
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
const noteStyle = { fontSize: s(10.5), lineHeight: 1.55, color: tokens.pending };
const smallBtn = { padding: `${s(4)}px ${s(11)}px`, border: `1px solid ${tokens.sectionBorder}`, borderRadius: s(10), background: "#080F1C", fontFamily: "inherit", fontSize: s(11), fontWeight: 500, color: tokens.wordmark, cursor: "pointer" };
const exportBtn = (active, dim) => ({ padding: `${s(8)}px ${s(18)}px`, border: "1px solid rgba(160,205,255,0.55)", borderRadius: s(12), background: "linear-gradient(180deg, #459AF5 0%, #1A71F0 48%, #0D57D1 100%)", boxShadow: "inset 0 1.5px 0 rgba(255,255,255,0.55), inset 0 -3px 8px rgba(8,50,140,0.45), 0 10px 30px rgba(30,123,255,0.38)", fontFamily: "inherit", fontSize: s(12), fontWeight: 600, color: "#FFFFFF", textShadow: "0 1px 2px rgba(8,50,140,0.4)", cursor: active ? "default" : "pointer", opacity: dim ? 0.5 : 1 });

function Segmented({ options, value, onChange, label }) {
  return (
    <div role="group" aria-label={label} style={{ display: "inline-flex", border: `1px solid ${tokens.sectionBorder}`, borderRadius: 999, overflow: "hidden" }}>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          aria-pressed={value === o.value}
          onClick={() => onChange(o.value)}
          style={{ padding: `${s(3)}px ${s(11)}px`, border: "none", background: value === o.value ? "rgba(59,158,255,0.18)" : "transparent", color: value === o.value ? tokens.accentCyan : tokens.sectionSubtext, fontFamily: "inherit", fontSize: s(10.5), fontWeight: 600, cursor: "pointer" }}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

function PanelError({ text }) {
  return <span role="alert" style={{ fontSize: s(11.5), color: tokens.danger }}>{text}</span>;
}

function Notes({ notes }) {
  if (!notes?.length) return null;
  return (
    <ul style={{ margin: 0, paddingLeft: s(16), display: "flex", flexDirection: "column", gap: 3 }}>
      {notes.map((n) => <li key={n} style={noteStyle}>{n}</li>)}
    </ul>
  );
}

// Where one environmental value came from, in one line.
function SourceLine({ v }) {
  if (v.status === "user_provided") {
    const pub = v.public;
    return (
      <span style={noteStyle}>
        Entered on the upload ({v.user_value?.field}).
        {pub ? ` Public value alongside: ${fmtNum(pub.value)} ${pub.unit} from ${pub.source}.` : v.public_reason ? ` Public value: ${v.public_reason}` : ""}
      </span>
    );
  }
  const p = v.public;
  if (!p) return <span style={noteStyle}>{v.reason || "Not available."}</span>;
  const gp = p.grid_point || {};
  const where = `${fmtNum(gp.latitude, 3)}, ${fmtNum(gp.longitude, 3)}${gp.depth_m != null ? ` · ${fmtNum(gp.depth_m, 1)} m` : ""}`;
  return (
    <span style={noteStyle}>
      {p.source} · {p.dataset_id} ({p.kind}) · cell {where}
      {gp.distance_km != null ? ` (${fmtNum(gp.distance_km, 1)} km away)` : ""} · time step {String(gp.time || "").slice(0, 16).replace("T", " ")} UTC · retrieved {fmtDateTime(p.retrieved_at)}
    </span>
  );
}

function EnvVariableCard({ spec, v, index }) {
  const has = v && v.value != null;
  const unit = v?.unit || "";
  const dirDeg = v?.public?.details?.direction_deg;
  const dirConv = v?.public?.details?.direction_convention;
  const series = (v?.public?.series || [])
    .map((p) => ({ date: p.date, value: p.speed ?? p.mean }))
    .filter((p) => p.value != null && p.date);
  const profile = v?.public?.details?.profile;
  return (
    <div data-testid={`env-${spec.key}`} style={{ ...cardBase, ...revealStyle(index), justifyContent: "space-between" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <span style={panelLabelStyle}>{spec.label}</span>
        {v && (
          <span style={pillStyle(v.status === "ok" ? "accent" : v.status === "user_provided" ? "success" : "pending")}>
            {v.status === "ok" ? "PUBLIC MODEL" : v.status === "user_provided" ? "USER-ENTERED" : "UNAVAILABLE"}
          </span>
        )}
      </div>
      {spec.key === "salinity" && has && <RangeGauge value={v.value} min={30} max={40} unit="" />}
      {spec.key === "ph" && has && <RangeGauge value={v.value} min={7} max={9} unit="" />}
      {spec.key !== "salinity" && spec.key !== "ph" && has && (
        <div style={{ display: "flex", alignItems: "center", gap: s(10) }}>
          {spec.key === "temperature" && <ThermoIcon />}
          <span style={{ fontSize: s(38), fontWeight: 600, letterSpacing: "-0.02em", lineHeight: 1 }}>{fmtNum(v.value)}</span>
          <span style={{ fontSize: s(12), color: tokens.sectionSubtext }}>
            {unit}
            {dirDeg != null ? ` · ${Math.round(dirDeg)}° ${dirConv ? `(${dirConv})` : ""}` : ""}
          </span>
        </div>
      )}
      {(spec.key === "salinity" || spec.key === "ph") && has && (
        <span style={{ ...noteStyle, textAlign: "center" }}>{unit} · gauge scale {spec.key === "ph" ? "7–9" : "30–40"}</span>
      )}
      {!has && <span style={{ fontSize: s(28), fontWeight: 600, color: tokens.pending }}>—</span>}
      {Array.isArray(profile) && profile.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          {profile.map((lv) => (
            <span key={lv.level} style={{ fontSize: s(10.5), color: lv.value != null ? tokens.sectionSubtext : tokens.pending }}>
              {lv.level.replace("_", " ")}: {lv.value != null ? `${fmtNum(lv.value)} °C at ${fmtNum(lv.depth_m, 1)} m` : `no value${lv.reason ? ` (${lv.reason})` : ""}`}
            </span>
          ))}
        </div>
      )}
      {series.length > 1 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <span style={{ fontSize: s(9.5), letterSpacing: "0.07em", color: tokens.sectionSubtext }}>DAILY MEAN, {series.length} DAYS TO COLLECTION DATE ({unit})</span>
          <TrendSVG points={series} unit={unit} />
        </div>
      )}
      {v ? <SourceLine v={v} /> : <span style={noteStyle}>Not returned by the environment service.</span>}
    </div>
  );
}

export default function Academia() {
  const [searchParams] = useSearchParams();
  const requestedId = searchParams.get("analysis_id");
  const { user } = useAuth();
  const canSeeAll = ["admin", "company_owner"].includes(user?.role);

  const [analysisId, setAnalysisId] = useState(requestedId);
  const [report, setReport] = useState(null);
  const [error, setError] = useState("");
  // Novelty threshold is reported by the API (GET /health); "unavailable"
  // rather than a guessed number when it isn't.
  const { threshold: noveltyThreshold } = useNoveltyThreshold();
  const noveltyParam = noveltyThreshold == null ? "unavailable" : `≥ ${noveltyThreshold.toFixed(2)}`;

  const [env, setEnv] = useState(null);
  const [envError, setEnvError] = useState("");
  const [scope, setScope] = useState("mine");
  const [summary, setSummary] = useState(null);
  const [summaryError, setSummaryError] = useState("");
  const [rank, setRank] = useState("species");
  const [cooc, setCooc] = useState(null);
  const [coocError, setCoocError] = useState("");
  const [rhythms, setRhythms] = useState(null);
  const [rhythmsError, setRhythmsError] = useState("");
  const [rhythmMetric, setRhythmMetric] = useState("uploads");

  const [copied, setCopied] = useState(false);
  const [downloadingFormat, setDownloadingFormat] = useState(null);
  const [exportStatus, setExportStatus] = useState(null); // {ok, text}

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
    getReport(analysisId).then(setReport).catch((e) => setError(e.message || "Failed to load report."));
  }, [analysisId]);

  const uploadId = report?.metadata?.upload_id;
  const loadEnv = useCallback(() => {
    if (!uploadId) return;
    setEnvError("");
    getEnvironmentContext(uploadId).then(setEnv).catch((e) => setEnvError(e.message || "Failed to load environmental context."));
  }, [uploadId]);
  useEffect(() => { loadEnv(); }, [loadEnv]);

  useEffect(() => {
    setSummary(null);
    setSummaryError("");
    getPartnerSummary({ scope }).then(setSummary).catch((e) => setSummaryError(e.message || "Failed to load coverage."));
    setRhythms(null);
    setRhythmsError("");
    getPartnerRhythms({ scope }).then(setRhythms).catch((e) => setRhythmsError(e.message || "Failed to load activity rhythms."));
  }, [scope]);

  useEffect(() => {
    setCoocError("");
    getPartnerCooccurrence({ scope, rank, limit: 50 }).then(setCooc).catch((e) => setCoocError(e.message || "Failed to load co-occurrence."));
  }, [scope, rank]);

  const handleExport = async (format) => {
    setDownloadingFormat(format);
    setExportStatus(null);
    try {
      const resp = format === "csv" ? await exportReportCsv(analysisId)
        : format === "fair" ? await exportReportFair(analysisId)
        : await exportReportJson(analysisId);
      const ext = format === "fair" ? "zip" : format;
      const name = filenameFrom(resp, `synthveda_${format === "fair" ? "fair" : "report"}_${analysisId}.${ext}`);
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = name;
      a.click();
      URL.revokeObjectURL(url);
      setExportStatus({ ok: true, text: `Downloaded ${name} (${blob.size.toLocaleString()} bytes).` });
    } catch (e) {
      setExportStatus({ ok: false, text: `Export failed: ${e.message}` });
    } finally {
      setDownloadingFormat(null);
    }
  };

  const citation = report
    ? `SynthVeda eDNA Analysis Platform ${report.metadata.model_version_set || "(model version not recorded)"} (${new Date(report.generated_at).getFullYear()}). Taxonomic assignments generated by DNABERT2-based classification; reference databases and versions per sequence are listed in provenance.json of the FAIR export. Run ${report.metadata.analysis_id}; parameters: novelty threshold ${noveltyParam}, contamination gate ≥ 0.50.`
    : "";

  const copyCitation = () => {
    if (!citation) return;
    navigator.clipboard?.writeText(citation);
    setCopied(true);
    setTimeout(() => setCopied(false), 1600);
  };

  if (error) {
    return (
      <div style={pageStyle}>
        <div style={ambientGlow} />
        <SidebarMenu />
        <div style={{ position: "relative", maxWidth: 800, margin: "4rem auto", padding: "0 1.5rem", textAlign: "center" }}>
          <div style={{ fontSize: "2.5rem", marginBottom: 16 }}>⚠</div>
          <div style={{ color: tokens.danger, fontSize: "1.1rem" }}>{error}</div>
        </div>
      </div>
    );
  }

  if (!report) {
    return (
      <div style={pageStyle}>
        <div style={ambientGlow} />
        <SidebarMenu />
        <div style={{ position: "relative", textAlign: "center", padding: "4rem", color: tokens.sectionSubtext }}>Loading dashboard...</div>
      </div>
    );
  }

  const bio = report.biodiversity;
  const upload = report.metadata; // location_label / depth_meters live here already
  const cov = summary?.environment;
  const rankOptions = (() => {
    const avail = cooc?.taxa_by_rank || {};
    const ranks = RANK_ORDER.filter((r) => avail[r] || r === rank);
    return [...ranks.map((r) => ({ value: r, label: `${r} (${avail[r] || 0} taxa)` })), { value: "any", label: "any rank (mixed)" }];
  })();
  const rt = rhythms?.totals;

  return (
    <div style={pageStyle}>
      <div style={ambientGlow} />
      <SidebarMenu />
      <div style={{ position: "relative", maxWidth: s(1560), margin: "0 auto", padding: `${s(32)}px ${s(44)}px ${s(44)}px`, display: "flex", flexDirection: "column", gap: s(18) }}>
        {/* Header */}
        <div style={{ display: "flex", flexDirection: "column", gap: s(6) }}>
          <div style={{ fontSize: s(12), letterSpacing: "0.08em", color: tokens.labelText }}>PARTNER REPORT › ACADEMIA</div>
          <h1 style={{ margin: 0, fontSize: s(27), fontWeight: 600, letterSpacing: "-0.01em" }}>Marine Environment &amp; Bio-Activity Dashboard</h1>
          <p style={{ margin: 0, fontSize: s(14), color: tokens.sectionSubtext }}>
            {upload.location_label || "Location not recorded"} · eDNA-derived biology paired with public environmental context
          </p>
        </div>

        <div style={{ display: "flex", gap: s(12), alignItems: "center", padding: `${s(10)}px ${s(16)}px`, borderRadius: s(6), border: "1px solid rgba(217,150,60,0.28)", background: "rgba(217,150,60,0.05)" }}>
          <WarningTriangleIcon size={s(15)} color={tokens.warning} />
          <span style={{ fontSize: s(12), lineHeight: 1.5, color: "#C8B79A" }}>
            Preliminary eDNA-derived results from SynthVeda&rsquo;s classification pipeline. Environmental values are public ocean and atmosphere model or satellite products matched to the sample&rsquo;s coordinates and collection date (or values entered on the upload), not on-site sensor readings. Every panel states its source.
          </span>
        </div>

        {/* Sampling station + environmental coverage */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: s(14), alignItems: "stretch" }}>
          <div style={{ ...cardBase, position: "relative", justifyContent: "space-between", background: "linear-gradient(180deg, rgba(20,110,255,0.10) 0%, rgba(6,10,20,0.75) 100%)", overflow: "hidden" }}>
            {/* Sits behind the card's copy, anchored to the right edge and
                bleeding past the top and bottom so it reads as an animal
                drifting behind the panel. pointerEvents:none keeps it from
                swallowing clicks meant for the stats. */}
            <img
              src={jellyfishArt}
              alt=""
              aria-hidden="true"
              className="sv-jelly"
              style={{ position: "absolute", right: s(6), top: s(-2), width: s(234), pointerEvents: "none", userSelect: "none", opacity: 0.5 }}
            />
            <div style={{ position: "relative", display: "flex", flexDirection: "column", gap: s(5) }}>
              <span style={{ fontSize: s(11), letterSpacing: "0.08em", color: tokens.labelText }}>SAMPLING STATION</span>
              <span style={{ fontSize: s(20), fontWeight: 600, letterSpacing: "-0.01em" }}>{upload.location_label || "Location not recorded"}</span>
              <span style={{ fontSize: s(12), color: tokens.sectionSubtext }}>
                {upload.depth_meters != null ? `${upload.depth_meters.toLocaleString()} m` : "Depth not recorded"} · collected {upload.collected_at ? fmtDateTime(upload.collected_at) : "— not recorded"}
              </span>
            </div>
            <div style={{ position: "relative", display: "flex", gap: s(18), flexWrap: "wrap" }}>
              <div style={{ display: "flex", flexDirection: "column" }}><span style={{ fontSize: s(10), letterSpacing: "0.07em", color: tokens.pending }}>TAXA DETECTED</span><span style={{ fontSize: s(16), fontWeight: 600, color: tokens.accentCyan }}>{bio.predicted_taxon_richness}</span></div>
              <div style={{ display: "flex", flexDirection: "column" }}><span style={{ fontSize: s(10), letterSpacing: "0.07em", color: tokens.pending }}>SEQUENCES</span><span style={{ fontSize: s(16), fontWeight: 600 }}>{report.qc_summary.total_sequences.toLocaleString()}</span></div>
              <div style={{ display: "flex", flexDirection: "column" }}><span style={{ fontSize: s(10), letterSpacing: "0.07em", color: tokens.pending }}>RUN</span><span style={{ fontSize: s(16), fontWeight: 600, fontFamily: "ui-monospace,monospace", color: tokens.wordmark }}>{report.metadata.analysis_id.replace("ana_", "")}</span></div>
            </div>
          </div>

          <div data-testid="env-context" style={{ ...cardBase, ...revealStyle(0) }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
              <span style={panelLabelStyle}>ENVIRONMENTAL CONTEXT · THIS SAMPLE</span>
              {env && <span style={pillStyle(ENV_STATUS_TONE[env.status] || "pending")}>{env.status.replace("_", " ").toUpperCase()}</span>}
            </div>
            {envError && <PanelError text={envError} />}
            {!env && !envError && <span style={noteStyle}>Loading environmental context…</span>}
            {env && (
              <>
                {env.query ? (
                  <span style={{ fontSize: s(12), color: tokens.sectionSubtext, lineHeight: 1.6 }}>
                    Looked up at {fmtNum(env.query.lookup_latitude, 2)}, {fmtNum(env.query.lookup_longitude, 2)} on {env.query.date} (UTC),{" "}
                    {env.query.target_level === "sample_depth" ? `at the sample depth (${fmtNum(env.query.depth_m, 0)} m)` : "at the surface (no depth recorded)"}.
                  </span>
                ) : null}
                {env.reason && <span style={{ fontSize: s(12), color: env.status === "failed" ? tokens.danger : tokens.sectionSubtext, lineHeight: 1.6 }}>{env.reason}</span>}
                {env.retrieved_at && <span style={noteStyle}>Retrieved {fmtDateTime(env.retrieved_at)}{env.cache_hit ? " (shared cache)" : ""}</span>}
                {env.sources?.length > 0 && (
                  <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
                    {env.sources.map((src) => (
                      <span key={src.provider} style={noteStyle}><strong style={{ color: tokens.sectionSubtext }}>{src.source}</strong> — {src.attribution}. {src.licence}.</span>
                    ))}
                  </div>
                )}
                {env.status === "pending" && (
                  <button type="button" onClick={loadEnv} style={{ ...smallBtn, alignSelf: "flex-start" }}>Check again</button>
                )}
              </>
            )}
            <div style={{ borderTop: `1px solid ${tokens.sectionBorder}`, paddingTop: s(8), display: "flex", flexDirection: "column", gap: 4 }}>
              <span style={{ fontSize: s(10), letterSpacing: "0.07em", color: tokens.sectionSubtext }}>COVERAGE · {scope === "all" ? "ALL USERS" : "YOUR UPLOADS"}</span>
              {summaryError && <PanelError text={summaryError} />}
              {!cov && !summaryError && <span style={noteStyle}>Loading coverage…</span>}
              {cov && (
                <span data-testid="env-coverage" style={{ fontSize: s(11.5), color: tokens.sectionSubtext, lineHeight: 1.6 }}>
                  {cov.eligible} of {cov.uploads_in_scope} upload{cov.uploads_in_scope === 1 ? "" : "s"} have coordinates and a collection date (needed for a lookup); {cov.not_applicable} do not.
                  {" "}Of those eligible: {cov.by_status.complete ?? 0} complete, {cov.by_status.partial ?? 0} partial, {cov.by_status.pending ?? 0} pending, {cov.by_status.failed ?? 0} failed, {cov.by_status.not_requested ?? 0} not looked up yet.
                  {cov.latest_retrieved_at ? ` Latest retrieval ${fmtDateTime(cov.latest_retrieved_at)}.` : ""}
                </span>
              )}
              {cov?.sources?.length > 0 && (
                <span style={noteStyle}>Sources in scope: {cov.sources.map((x) => `${x.source} (${x.uploads} upload${x.uploads === 1 ? "" : "s"})`).join(" · ")}</span>
              )}
            </div>
          </div>
        </div>

        {/* Per-variable environmental panels (only when a lookup is possible) */}
        {env && env.status !== "not_applicable" && (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", gap: s(14), alignItems: "stretch" }}>
            {ENV_VARIABLES.map((spec, i) => (
              <EnvVariableCard key={spec.key} spec={spec} v={env.variables?.[spec.key]} index={i + 1} />
            ))}
          </div>
        )}

        {/* Scope for the cross-sample panels */}
        <div style={{ display: "flex", alignItems: "center", gap: s(12), flexWrap: "wrap" }}>
          <span style={{ fontSize: s(11), letterSpacing: "0.08em", color: tokens.labelText }}>ACROSS SAMPLES</span>
          {canSeeAll ? (
            <Segmented label="Scope" value={scope} onChange={setScope} options={[{ value: "mine", label: "My uploads" }, { value: "all", label: "All users" }]} />
          ) : (
            <span style={noteStyle}>Your uploads (one sample = one upload, its newest analysis)</span>
          )}
        </div>

        {/* Activity rhythms */}
        <div data-testid="rhythms" style={{ ...cardBase, ...revealStyle(7) }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: s(12), flexWrap: "wrap" }}>
            <span style={panelLabelStyle}>ACTIVITY RHYTHMS · TIME OF DAY &amp; DAY OF WEEK (UTC)</span>
            <Segmented label="Rhythm metric" value={rhythmMetric} onChange={setRhythmMetric} options={[{ value: "uploads", label: "Samples" }, { value: "detections", label: "Detections" }]} />
          </div>
          {rhythmsError && <PanelError text={rhythmsError} />}
          {!rhythms && !rhythmsError && <span style={noteStyle}>Loading…</span>}
          {rhythms && (
            <>
              <span data-testid="rhythms-basis" style={{ fontSize: s(11.5), color: tokens.sectionSubtext, lineHeight: 1.6 }}>
                {rt.uploads} sample{rt.uploads === 1 ? "" : "s"}: {rt.uploads_collected_at} timed by <strong>collected_at</strong> (when the sample was taken), {rt.uploads_upload_time} by <strong>upload time</strong> (no collection time recorded)
                {rt.uploads_without_timestamp ? `, ${rt.uploads_without_timestamp} without any timestamp` : ""}. {rt.detections.toLocaleString()} detection{rt.detections === 1 ? "" : "s"} (sequences with a taxon, contamination-flagged excluded) from {rt.samples_analysed} analysed sample{rt.samples_analysed === 1 ? "" : "s"}.
              </span>
              {rhythmMetric === "uploads" && (
                <div style={{ display: "flex", gap: s(14), flexWrap: "wrap", fontSize: s(10.5), color: tokens.sectionSubtext }}>
                  <span style={{ display: "flex", alignItems: "center", gap: 6 }}><span style={{ width: 12, height: 10, background: tokens.accentCyan, display: "inline-block", borderRadius: 2 }} />Timed by collected_at</span>
                  <span style={{ display: "flex", alignItems: "center", gap: 6 }}><span style={{ width: 12, height: 10, background: tokens.purple, display: "inline-block", borderRadius: 2 }} />Timed by upload time</span>
                </div>
              )}
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(360px, 1fr))", gap: s(14) }}>
                <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                  <span style={{ fontSize: s(9.5), letterSpacing: "0.07em", color: tokens.sectionSubtext }}>HOUR OF DAY · UTC</span>
                  <RhythmBars bins={rhythms.by_hour} metric={rhythmMetric} />
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                  <span style={{ fontSize: s(9.5), letterSpacing: "0.07em", color: tokens.sectionSubtext }}>DAY OF WEEK · UTC</span>
                  <RhythmBars bins={rhythms.by_weekday} metric={rhythmMetric} />
                </div>
              </div>
              <Notes notes={rhythms.notes} />
              <span style={noteStyle}>{rhythms.definitions?.interpretation} {rhythms.definitions?.timezone}</span>
            </>
          )}
        </div>

        {/* Co-occurrence top-50 */}
        <div data-testid="cooccurrence" style={{ ...cardBase, ...revealStyle(8) }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: s(14), flexWrap: "wrap" }}>
            <span style={panelLabelStyle}>TAXON CO-OCCURRENCE · TOP 50 PAIRS</span>
            <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: s(10.5), letterSpacing: "0.06em", color: tokens.sectionSubtext }}>
              RANK
              <select
                aria-label="Taxonomic rank"
                value={rank}
                onChange={(e) => setRank(e.target.value)}
                style={{ background: "#080F1C", color: tokens.wordmark, border: `1px solid ${tokens.sectionBorder}`, borderRadius: 6, padding: "3px 8px", fontFamily: "inherit", fontSize: s(11) }}
              >
                {rankOptions.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
            </label>
          </div>
          {coocError && <PanelError text={coocError} />}
          {!cooc && !coocError && <span style={noteStyle}>Loading…</span>}
          {cooc && (
            <>
              <span data-testid="cooccurrence-basis" style={{ fontSize: s(11.5), color: tokens.sectionSubtext, lineHeight: 1.6 }}>
                Taxa at {cooc.rank === "any" ? "any recorded rank" : <>rank <strong>{cooc.rank}</strong></>} (decision.predicted_taxon) present in the same sample. {cooc.samples_with_taxa} of {cooc.samples} analysed sample{cooc.samples === 1 ? "" : "s"} have taxa at this rank; {cooc.taxa} distinct taxa; {cooc.pairs_total} pair{cooc.pairs_total === 1 ? "" : "s"}, showing {cooc.pairs.length}. {cooc.contamination_sequences_excluded} contamination-flagged sequence{cooc.contamination_sequences_excluded === 1 ? "" : "s"} excluded.
              </span>
              {cooc.pairs.length > 0 ? (
                <>
                  <div style={{ display: "flex", gap: s(16), flexWrap: "wrap", fontSize: s(10.5), color: tokens.sectionSubtext }}>
                    <span style={{ display: "flex", alignItems: "center", gap: 6 }}><span style={{ width: 18, height: 3, background: tokens.accentBlue, display: "inline-block" }} />Line width ∝ samples together · opacity ∝ Jaccard</span>
                    <span>Node size ∝ samples containing the taxon</span>
                  </div>
                  <CooccurrenceGraph pairs={cooc.pairs} nodes={cooc.nodes} />
                  <div style={{ overflowX: "auto", maxHeight: s(360), overflowY: "auto", border: `1px solid ${tokens.sectionBorder}`, borderRadius: 6 }}>
                    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: s(11.5) }}>
                      <thead>
                        <tr style={{ color: tokens.sectionSubtext, textAlign: "left", position: "sticky", top: 0, background: "#060B16" }}>
                          {["#", "Taxon A", "Taxon B", "Samples together", "With A", "With B", "Jaccard"].map((h) => (
                            <th key={h} style={{ padding: "7px 10px", fontWeight: 600, fontSize: s(10), letterSpacing: "0.05em", borderBottom: `1px solid ${tokens.sectionBorder}` }}>{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {cooc.pairs.map((p, i) => (
                          <tr key={`${p.taxon_a}|${p.rank_a}|${p.taxon_b}|${p.rank_b}`} style={{ borderBottom: "1px solid #0C1526" }}>
                            <td style={{ padding: "6px 10px", color: tokens.pending }}>{i + 1}</td>
                            <td style={{ padding: "6px 10px" }}><em>{p.taxon_a}</em>{cooc.rank === "any" && <span style={{ color: tokens.pending }}> · {p.rank_a}</span>}</td>
                            <td style={{ padding: "6px 10px" }}><em>{p.taxon_b}</em>{cooc.rank === "any" && <span style={{ color: tokens.pending }}> · {p.rank_b}</span>}</td>
                            <td style={{ padding: "6px 10px", color: tokens.accentCyan, fontWeight: 600 }}>{p.samples_together}</td>
                            <td style={{ padding: "6px 10px" }}>{p.samples_a}</td>
                            <td style={{ padding: "6px 10px" }}>{p.samples_b}</td>
                            <td style={{ padding: "6px 10px" }}>{p.jaccard.toFixed(2)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </>
              ) : (
                <span style={{ fontSize: s(12), color: tokens.sectionSubtext }}>No taxon pairs at this rank in scope.</span>
              )}
              <Notes notes={cooc.notes} />
              <span style={noteStyle}>{cooc.definitions?.interpretation} Pairs are ordered by samples together, then Jaccard, then name.</span>
            </>
          )}
        </div>

        {/* Export engine */}
        <div style={cardBase}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: s(12), flexWrap: "wrap" }}>
            <span style={panelLabelStyle}>PUBLISH-READY EXPORT</span>
            <div style={{ display: "flex", gap: s(8), flexWrap: "wrap" }}>
              <button onClick={() => handleExport("fair")} disabled={downloadingFormat !== null} style={exportBtn(downloadingFormat, downloadingFormat && downloadingFormat !== "fair")}>
                {downloadingFormat === "fair" ? "Building ZIP..." : "⬇ FAIR ZIP"}
              </button>
              <button onClick={() => handleExport("json")} disabled={downloadingFormat !== null} style={exportBtn(downloadingFormat, downloadingFormat && downloadingFormat !== "json")}>
                {downloadingFormat === "json" ? "Exporting..." : "⬇ Download JSON"}
              </button>
              <button onClick={() => handleExport("csv")} disabled={downloadingFormat !== null} style={exportBtn(downloadingFormat, downloadingFormat && downloadingFormat !== "csv")}>
                {downloadingFormat === "csv" ? "Exporting..." : "⬇ Download CSV"}
              </button>
            </div>
          </div>
          <span style={{ fontSize: s(11), color: tokens.pending, lineHeight: 1.6 }}>
            The FAIR ZIP holds README.md, results.csv, sample_metadata.json, provenance.json (models, reference databases), decision traces when recorded, the chain-of-custody log, a manifest of sha256 checksums and — when its checksum still verifies and you may read the upload — the raw uploaded file. Each export is recorded on the sample&rsquo;s custody chain.
          </span>
          {exportStatus && (
            <span role={exportStatus.ok ? "status" : "alert"} style={{ fontSize: s(11.5), color: exportStatus.ok ? tokens.success : tokens.danger }}>{exportStatus.text}</span>
          )}
          <div style={{ display: "flex", flexDirection: "column", gap: s(7) }}>
            <span style={{ fontSize: s(11), letterSpacing: "0.08em", color: tokens.sectionSubtext }}>AUTO-CITATION GENERATOR</span>
            <textarea
              readOnly
              rows={3}
              value={citation}
              style={{ width: "100%", boxSizing: "border-box", padding: `${s(12)}px ${s(14)}px`, border: `1px solid ${tokens.sectionBorder}`, borderRadius: s(3), background: "#04070E", color: tokens.accentCyan, fontFamily: "ui-monospace,monospace", fontSize: s(11.5), lineHeight: 1.7, resize: "vertical", outline: "none" }}
            />
            <button onClick={copyCitation} style={{ ...smallBtn, alignSelf: "flex-start", padding: `${s(6)}px ${s(14)}px`, fontSize: s(11.5) }}>
              {copied ? "Copied ✓" : "Copy citation"}
            </button>
          </div>
          <span style={{ fontSize: s(10), color: tokens.pending, fontFamily: "ui-monospace,monospace" }}>
            Novelty threshold {noveltyParam} · Contamination gate ≥ 0.50 · Models: {report.model_versions_used.map((m) => m.model_version_used).join(", ") || "none recorded"}
          </span>
        </div>

        <div style={{ display: "flex", justifyContent: "center", padding: `${s(8)}px 0 ${s(2)}px`, borderTop: `1px solid ${tokens.sectionBorder}` }}>
          <span style={{ fontSize: s(11), color: tokens.pending, textAlign: "center" }}>
            Run {report.metadata.analysis_id} · Pipeline: {report.metadata.model_version_set || "not recorded"} · Generated {new Date(report.generated_at).toLocaleString()}
          </span>
        </div>
      </div>
    </div>
  );
}
