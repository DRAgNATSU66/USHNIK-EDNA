import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import SidebarMenu from "../../components/sidebar/SidebarMenu";
import { tokens } from "../../components/shared/tokens";
import MockTag from "../../components/shared/MockTag";
import { WarningTriangleIcon } from "../../components/shared/icons";
import { getReport, listReports, exportReportJson, exportReportCsv } from "../../lib/api";
import jellyfishArt from "../../assets/jellyfish.png";
import { revealStyle } from "../../styles/reveal";

// Deterministic pseudo-random source (same trick used across the app's other
// generative visuals) so decorative art and the co-occurrence network redraw
// identically every time instead of reshuffling on each render.
function rnd(i) {
  const x = Math.sin(i * 127.1) * 43758.5453;
  return x - Math.floor(x);
}

// Single scale factor applied to every size on this page (container width,
// card padding, gauges, font sizes) -- keeps every ratio identical to the
// pre-scale design, just larger throughout, per feedback that the cards
// should be bigger and cover more of the screen.
const SCALE = 1.18;
const s = (n) => Math.round(n * SCALE * 10) / 10;

const NET_COLORS = [tokens.accentBlue, tokens.accentCyan, "#146EFF", tokens.purple];

// ---------------------------------------------------------------------------
// Decorative hero art -- the low-poly jellyfish behind the sampling station
// card's copy. This is the supplied artwork rather than generated geometry: a
// procedural mesh can approximate the look but never match a specific piece of
// art, and this panel is meant to match the design exactly. Purely visual, not
// a data representation, so it carries no MOCK tag (same as an icon wouldn't).
// ---------------------------------------------------------------------------

function OxygenGauge({ pct }) {
  const N = 44, cx = 80, cy = 80, r = 58;
  const E = [];
  for (let i = 0; i < N; i++) {
    const a = -Math.PI / 2 + (i / N) * 2 * Math.PI;
    const on = i / N <= pct / 100;
    const x1 = cx + Math.cos(a) * (r - 7), y1 = cy + Math.sin(a) * (r - 7);
    const x2 = cx + Math.cos(a) * (r + (on ? 4 : 1)), y2 = cy + Math.sin(a) * (r + (on ? 4 : 1));
    const tickOpacity = on ? 0.55 + 0.45 * (i / N) : 1;
    E.push(
      <line
        key={i}
        x1={x1} y1={y1} x2={x2} y2={y2}
        className="sv-fade-in-late"
        style={{ "--sv-fade-to": tickOpacity, animationDelay: `${(i / N) * 0.6}s`, animationDuration: "0.2s" }}
        stroke={on ? tokens.accentBlue : "#14233C"}
        strokeWidth={on ? 3.4 : 2.4}
        strokeLinecap="round"
      />
    );
  }
  return (
    <svg width={s(140)} height={s(140)} viewBox="0 0 160 160" style={{ filter: "drop-shadow(0 0 12px rgba(59,158,255,0.35))" }}>
      {E}
      <circle cx={cx} cy={cy} r={r - 16} fill="none" stroke="#101D33" strokeWidth={1} />
      <text x={cx} y={cy + 2} fill={tokens.accentCyan} fontSize={27} fontWeight={600} textAnchor="middle">{pct}%</text>
      <text x={cx} y={cy + 20} fill={tokens.pending} fontSize={8.5} textAnchor="middle" letterSpacing={1}>O2 SATURATION</text>
    </svg>
  );
}

// Semi-circular range gauge -- reused for real salinity readings (the mockup
// used this shape for pH, which we don't collect; salinity_ppt is a real
// upload field, so this instance is honest, unlike the oxygen gauge above).
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
    // Extra vertical room (viewBox height 132 vs the arc's ~140-unit span)
    // keeps the value text and the min/max foot labels from crowding each
    // other -- they collided when both sat close to the feet line.
    <svg viewBox="0 0 180 132" style={{ width: "100%", maxWidth: s(210), margin: "0 auto", display: "block" }}>
      {arc(0, 1, "#14233C", 15)}
      {hasValue && arc(0, frac, tokens.accentBlue, 15, true)}
      <text className="sv-fade-in-late" x={cx} y={cy - 20} fill={hasValue ? tokens.textPrimary : tokens.pending} fontSize={25} fontWeight={600} textAnchor="middle">{hasValue ? value.toFixed(1) : "—"}</text>
      <text x={cx - r} y={cy + 26} fill={tokens.pending} fontSize={9} textAnchor="middle">{min}{unit}</text>
      <text x={cx + r} y={cy + 26} fill={tokens.pending} fontSize={9} textAnchor="middle">{max}{unit}</text>
    </svg>
  );
}

// Small sine-wave glyph for the surface/midwater/seabed depth-tier legend --
// dim gray for the two tiers not being read, bright cyan for the active one.
// q/t quadratic-bezier chain -- each t repeats the previous curve's control
// point reflected through its endpoint, which is what keeps the three humps
// smooth and even. The old cubic path (c ... s ... s ...) fought itself at
// each join and read as jagged; this is a real sine, not an approximation.
function WaveIcon({ active }) {
  // viewBox is cropped to the wave's actual vertical extent (peaks/troughs
  // sit at y=5/15 around the y=10 baseline) rather than the full 20px box
  // the reference used -- that box's empty top/bottom margin was what made
  // the three stacked rows read as too spaced out.
  return (
    <svg width={58} height={14} viewBox="0 3 58 14" fill="none">
      <path
        d="M4 10 q7 -5 14 0 t14 0 t14 0"
        stroke={active ? tokens.accentCyan : tokens.accentBlue}
        strokeWidth={active ? 2.2 : 1.5}
        strokeLinecap="round"
        opacity={active ? 1 : 0.3}
        style={active ? { filter: "drop-shadow(0 0 4px rgba(127,212,255,0.9))" } : undefined}
      />
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

// Smooth trend line -- reused for the mock pollutant/wind/current cards.
function TrendSVG({ vals, labels, lo, hi }) {
  const W = 460, H = 150, x0 = 34, x1 = W - 14, yT = 18, yB = H - 30;
  const X = (i) => x0 + (i * (x1 - x0)) / (vals.length - 1);
  const Y = (v) => yB - ((v - lo) / (hi - lo)) * (yB - yT);
  let d = "";
  for (let i = 0; i < vals.length; i++) {
    if (!i) { d = `M${X(0)} ${Y(vals[0]).toFixed(1)}`; continue; }
    const xc = (X(i - 1) + X(i)) / 2;
    d += ` C${xc} ${Y(vals[i - 1]).toFixed(1)} ${xc} ${Y(vals[i]).toFixed(1)} ${X(i)} ${Y(vals[i]).toFixed(1)}`;
  }
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto", display: "block" }}>
      {[hi, (hi + lo) / 2, lo].map((v, i) => {
        const y = yT + (i * (yB - yT)) / 2;
        return (
          <g key={i}>
            <line x1={x0} y1={y} x2={x1} y2={y} stroke="#14233C" strokeWidth={1} />
            <text x={x0 - 8} y={y + 3.5} fill={tokens.pending} fontSize={9.5} textAnchor="end">{v}</text>
          </g>
        );
      })}
      <path d={d} pathLength={1} className="sv-draw-path" fill="none" stroke={tokens.wordmark} strokeWidth={2} strokeLinecap="round" />
      {labels.map((m, i) => <text key={m} className="sv-fade-in-late" x={X((i * (vals.length - 1)) / (labels.length - 1))} y={H - 8} fill={tokens.pending} fontSize={9.5} textAnchor="middle">{m}</text>)}
    </svg>
  );
}

function WavesSVG() {
  const W = 1100, H = 240, cy = H / 2;
  const series = [
    { c: tokens.accentCyan, amp: 1.0, w: 2 },
    { c: tokens.accentBlue, amp: 0.74, w: 1.6 },
    { c: "#146EFF", amp: 0.5, w: 1.4 },
    { c: tokens.purple, amp: 0.3, w: 1.2 },
  ];
  const env = (x) => {
    const t = (x / W) * 3 * Math.PI;
    return Math.abs(Math.sin(t)) * (x < W / 3 ? 92 : x < (2 * W) / 3 ? 66 : 44);
  };
  const E = [<line key="mid" x1={0} y1={cy} x2={W} y2={cy} stroke="#14233C" strokeWidth={1} />];
  [W / 3, (2 * W) / 3].forEach((x, i) => E.push(<line key={`g${i}`} x1={x} y1={14} x2={x} y2={H - 22} stroke="#0C1526" strokeWidth={1} />));
  series.forEach((s, si) => {
    let up = "", dn = "";
    for (let x = 0; x <= W; x += 8) {
      const a = env(x) * s.amp;
      up += (x ? " L" : "M") + x + " " + (cy - a).toFixed(1);
      dn += (x ? " L" : "M") + x + " " + (cy + a).toFixed(1);
    }
    E.push(<path key={`u${si}`} d={up} pathLength={1} className="sv-draw-path" style={{ animationDelay: `${si * 0.1}s` }} fill="none" stroke={s.c} strokeWidth={s.w} opacity={0.9} />);
    E.push(<path key={`d${si}`} d={dn} pathLength={1} className="sv-draw-path" style={{ animationDelay: `${si * 0.1 + 0.05}s` }} fill="none" stroke={s.c} strokeWidth={s.w} opacity={0.55} />);
  });
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  months.forEach((m, i) => E.push(<text key={m} x={46 + (i * (W - 80)) / 11} y={H - 6} fill={tokens.pending} fontSize={10} textAnchor="middle">{m}</text>));
  return <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto", display: "block" }}>{E}</svg>;
}

function SonicSVG() {
  const W = 540, H = 170, x0 = 34, x1 = W - 10, yT = 16, yB = 138;
  const yOf = (v) => yB - (v / 20) * (yB - yT);
  const f = (x, a1, f1, p1, a2, f2, p2, base) => base + a1 * Math.sin(x / f1 + p1) + a2 * Math.sin(x / f2 + p2) + 2 * Math.sin(x / 7 + p1 * 2);
  const mk = (a1, f1, p1, a2, f2, p2, base) => {
    let d = "";
    for (let x = x0; x <= x1; x += 4) {
      const v = Math.max(0.5, Math.min(19.5, f(x, a1, f1, p1, a2, f2, p2, base)));
      d += (d ? " L" : "M") + x + " " + yOf(v).toFixed(1);
    }
    return d;
  };
  const E = [];
  [0, 10, 20].forEach((v) => {
    E.push(<line key={`g${v}`} x1={x0} y1={yOf(v)} x2={x1} y2={yOf(v)} stroke="#14233C" strokeWidth={1} />);
    E.push(<text key={`gl${v}`} x={x0 - 8} y={yOf(v) + 3.5} fill={tokens.pending} fontSize={10} textAnchor="end">{v}</text>);
  });
  E.push(<path key="l1" d={mk(6.2, 26, 0.8, 3.4, 11, 2.1, 10)} pathLength={1} className="sv-draw-path" style={{ animationDelay: "0s" }} fill="none" stroke={tokens.accentCyan} strokeWidth={1.8} strokeLinecap="round" opacity={0.85} />);
  E.push(<path key="l2" d={mk(5.0, 34, 3.6, 2.8, 15, 0.4, 11)} pathLength={1} className="sv-draw-path" style={{ animationDelay: "0.12s" }} fill="none" stroke={tokens.accentBlue} strokeWidth={1.8} strokeLinecap="round" />);
  E.push(<path key="l3" d={mk(4.2, 21, 5.2, 2.4, 9, 4.0, 9)} pathLength={1} className="sv-draw-path" style={{ animationDelay: "0.24s" }} fill="none" stroke={tokens.purple} strokeWidth={1.6} strokeLinecap="round" opacity={0.9} />);
  ["Mon", "Tue", "Wed"].forEach((m, i) => E.push(<text key={m} x={x0 + (i * (x1 - x0)) / 2} y={H - 12} fill={tokens.pending} fontSize={10.5} textAnchor={i === 0 ? "start" : i === 2 ? "end" : "middle"}>{m}</text>));
  return <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto", display: "block" }}>{E}</svg>;
}

function DvmSVG() {
  const W = 540, H = 150, x0 = 34, x1 = W - 12, yT = 14, yB = H - 26;
  const Y = (v) => yB - (v / 100) * (yB - yT);
  const f = (h) => {
    const dusk = 88 * Math.exp(-Math.pow((h - 18.5) / 1.9, 2));
    const dawn = 58 * Math.exp(-Math.pow((h - 5.5) / 1.7, 2));
    const night = 20 * (h < 6 || h > 20 ? 1 : 0.3);
    const noise = 4 * Math.sin(h * 3.1) + 3 * Math.sin(h * 7.3 + 1);
    return Math.max(2, Math.min(98, dusk + dawn + night * 0.4 + 8 + noise));
  };
  let line = "", area = "";
  for (let h = 0; h <= 24; h += 0.25) {
    const x = x0 + (h / 24) * (x1 - x0), y = Y(f(h)).toFixed(1);
    line += (line ? " L" : "M") + x.toFixed(1) + " " + y;
    area += (area ? " L" : `M${x0} ${yB} L`) + x.toFixed(1) + " " + y;
  }
  area += ` L${x1} ${yB} Z`;
  const E = [];
  [0, 50, 100].forEach((v) => {
    E.push(<line key={`g${v}`} x1={x0} y1={Y(v)} x2={x1} y2={Y(v)} stroke="#14233C" strokeWidth={1} />);
    E.push(<text key={`gl${v}`} x={x0 - 7} y={Y(v) + 3.5} fill={tokens.pending} fontSize={9.5} textAnchor="end">{v}</text>);
  });
  E.push(<path key="a" d={area} className="sv-fade-in-late" fill="rgba(95,217,169,0.10)" stroke="none" />);
  E.push(<path key="l" d={line} pathLength={1} className="sv-draw-path" fill="none" stroke={tokens.success} strokeWidth={1.8} strokeLinejoin="round" />);
  const mark = (h, label) => {
    const x = x0 + (h / 24) * (x1 - x0);
    E.push(<circle key={`p${h}`} cx={x} cy={Y(f(h))} r={2.6} className="sv-fade-in-late" fill={tokens.accentCyan} />);
    E.push(<text key={`pt${h}`} x={x} y={Y(f(h)) - 7} className="sv-fade-in-late" fill={tokens.accentCyan} fontSize={8.5} textAnchor="middle">{label}</text>);
  };
  mark(5.5, "dawn ascent");
  mark(18.5, "dusk ascent · DVM peak");
  ["00:00", "06:00", "12:00", "18:00", "24:00"].forEach((t, i) => E.push(<text key={t} x={x0 + (i * (x1 - x0)) / 4} y={H - 8} fill={tokens.pending} fontSize={10} textAnchor="middle">{t}</text>));
  return <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto", display: "block" }}>{E}</svg>;
}

function buildNetwork() {
  const nodes = [];
  for (let i = 0; i < 140; i++) nodes.push({ x: rnd(i), y: rnd(i + 200), ab: Math.pow(rnd(i + 400), 2.2) * 100, c: NET_COLORS[Math.floor(rnd(i + 600) * 4)] });
  const edges = [];
  for (let i = 0; i < 140; i++) {
    for (let j = i + 1; j < 140; j++) {
      const d = Math.hypot(nodes[i].x - nodes[j].x, nodes[i].y - nodes[j].y);
      if (d < 0.09 && rnd(i * 7 + j) > 0.45) edges.push([i, j, rnd(i + j * 3) > 0.24]);
    }
  }
  return { nodes, edges };
}

// Seconds per ripple cycle -- matches the pacing of the other radiating-ring
// treatment on the Legislative map's current-flow markers, kept here as a
// plain per-frame canvas draw (no CSS animations possible on canvas pixels).
const RIPPLE_PERIOD = 2.8;

// Entrance sweep: nodes pop in left-to-right rather than all appearing at
// once, since canvas content can't use the CSS panel-reveal/draw-path
// treatment the SVG charts use elsewhere on this page. REVEAL_SWEEP is how
// long the sweep takes to cross the whole width (by normalized x); each
// individual node then takes REVEAL_POP seconds to grow in once reached.
const REVEAL_SWEEP = 0.9;
const REVEAL_POP = 0.35;
function revealFor(x, elapsed) {
  return Math.max(0, Math.min(1, (elapsed - x * REVEAL_SWEEP) / REVEAL_POP));
}

function drawNetwork(canvas, nodes, edges, threshold, time = 0, revealElapsed = Infinity) {
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const W = canvas.clientWidth || 800, H = 340;
  canvas.width = W * dpr;
  canvas.height = H * dpr;
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, W, H);
  ctx.strokeStyle = "rgba(20,35,60,0.55)";
  ctx.lineWidth = 1;
  for (let x = 40; x < W; x += 40) { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke(); }
  for (let y = 40; y < H; y += 40) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke(); }
  const vis = nodes.map((n) => n.ab >= threshold);
  const px = (n) => [20 + n.x * (W - 40), 18 + n.y * (H - 36)];
  edges.forEach(([i, j, pos]) => {
    if (!vis[i] || !vis[j]) return;
    const revEdge = Math.min(revealFor(nodes[i].x, revealElapsed), revealFor(nodes[j].x, revealElapsed));
    if (revEdge <= 0) return;
    const [x1, y1] = px(nodes[i]);
    const [x2, y2] = px(nodes[j]);
    ctx.beginPath();
    ctx.moveTo(x1, y1);
    ctx.lineTo(x2, y2);
    if (pos) { ctx.setLineDash([]); ctx.strokeStyle = "rgba(59,158,255,0.30)"; }
    else { ctx.setLineDash([4, 4]); ctx.strokeStyle = "rgba(255,123,123,0.38)"; }
    ctx.lineWidth = 1;
    ctx.globalAlpha = revEdge;
    ctx.stroke();
    ctx.globalAlpha = 1;
  });
  ctx.setLineDash([]);
  nodes.forEach((n, i) => {
    if (!vis[i]) return;
    const revNode = revealFor(n.x, revealElapsed);
    if (revNode <= 0) return;
    const [x, y] = px(n);
    const r = (1.6 + Math.sqrt(n.ab) * 0.5) * revNode;
    // Radar/water-ripple ring radiating outward from the node and fading,
    // like the origin/destination markers on the Legislative currents map --
    // phase-offset per node (deterministic, not Math.random) so the whole
    // network doesn't flash in unison.
    const cycle = ((time / RIPPLE_PERIOD + rnd(i + 900)) % 1 + 1) % 1;
    ctx.beginPath();
    ctx.arc(x, y, r + cycle * r * 4.5, 0, Math.PI * 2);
    ctx.strokeStyle = n.c;
    ctx.lineWidth = 1;
    ctx.globalAlpha = 0.45 * (1 - cycle) * revNode;
    ctx.stroke();
    ctx.globalAlpha = revNode;
    ctx.shadowColor = n.c;
    ctx.shadowBlur = 7;
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.strokeStyle = n.c;
    ctx.lineWidth = 1.1;
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(x, y, Math.max(0.8, r * 0.32), 0, Math.PI * 2);
    ctx.fillStyle = n.c;
    ctx.fill();
    ctx.shadowBlur = 0;
    ctx.globalAlpha = 1;
  });
  return vis.filter(Boolean).length;
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

export default function Academia() {
  const [searchParams] = useSearchParams();
  const requestedId = searchParams.get("analysis_id");

  const [analysisId, setAnalysisId] = useState(requestedId);
  const [report, setReport] = useState(null);
  const [error, setError] = useState("");

  const [netThr, setNetThr] = useState(12);
  const [visCount, setVisCount] = useState(null);
  const [copied, setCopied] = useState(false);
  const [downloadingFormat, setDownloadingFormat] = useState(null);

  const canvasRef = useRef(null);
  const netRef = useRef(null);
  const netMountRef = useRef(null);

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

  useEffect(() => {
    if (!netRef.current) netRef.current = buildNetwork();
    setVisCount(netRef.current.nodes.filter((n) => n.ab >= netThr).length);
  }, [netThr]);

  useEffect(() => {
    if (!netRef.current) netRef.current = buildNetwork();
    // Recorded once on true mount, not per-effect-run, so dragging the
    // abundance-threshold slider (which reruns this effect) doesn't replay
    // the entrance sweep -- it should only ever play once, when the page
    // first opens.
    if (netMountRef.current === null) netMountRef.current = performance.now();
    let raf;
    const loop = (t) => {
      const canvas = canvasRef.current;
      const revealElapsed = (performance.now() - netMountRef.current) / 1000;
      // Runs every frame (not just on resize) so the node-radius ripple
      // animates continuously; this also naturally picks up size changes
      // without a separate resize listener, since drawNetwork re-reads
      // canvas.clientWidth each call.
      if (canvas) drawNetwork(canvas, netRef.current.nodes, netRef.current.edges, netThr, t / 1000, revealElapsed);
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [netThr]);

  const handleExport = async (format) => {
    setDownloadingFormat(format);
    try {
      const resp = format === "csv" ? await exportReportCsv(analysisId) : await exportReportJson(analysisId);
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `synthveda_report_${analysisId}.${format}`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      alert("Export failed: " + e.message);
    } finally {
      setDownloadingFormat(null);
    }
  };

  const citation = report
    ? `SynthVeda eDNA Analysis Platform ${report.metadata.model_version_set || "(model version not recorded)"} (${new Date(report.generated_at).getFullYear()}). Taxonomic assignments generated by DNABERT2-based classification (reference database: pending configuration for this deployment). Run ${report.metadata.analysis_id}; parameters: novelty threshold ≥ 0.45, contamination gate ≥ 0.50.`
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
            {upload.location_label || "Location not recorded"} · eDNA-derived biology paired with environmental telemetry
          </p>
        </div>

        <div style={{ display: "flex", gap: s(12), alignItems: "center", padding: `${s(10)}px ${s(16)}px`, borderRadius: s(6), border: "1px solid rgba(217,150,60,0.28)", background: "rgba(217,150,60,0.05)" }}>
          <WarningTriangleIcon size={s(15)} color={tokens.warning} />
          <span style={{ fontSize: s(12), lineHeight: 1.5, color: "#C8B79A" }}>
            Preliminary eDNA-derived results from SynthVeda&rsquo;s DNABERT2-based classification pipeline. Panels marked <MockTag label="MOCK" /> illustrate a designed capability this deployment doesn&rsquo;t have sensors or pipelines for yet — everything else reflects this run&rsquo;s real data.
          </span>
        </div>

        {/* Row 1: sampling station hero · oxygen gauge (mock) · toxicity index (mock) */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", gap: s(14), alignItems: "stretch" }}>
          <div style={{ ...cardBase, position: "relative", justifyContent: "space-between", background: "linear-gradient(180deg, rgba(20,110,255,0.10) 0%, rgba(6,10,20,0.75) 100%)", overflow: "hidden" }}>
            {/* Sits behind the card's copy, anchored to the right edge and
                bleeding past the top and bottom so it reads as an animal
                drifting behind the panel rather than a pasted-in sticker (the
                card's overflow:hidden does the cropping). pointerEvents:none
                keeps it from swallowing clicks meant for the stats. */}
            <img
              src={jellyfishArt}
              alt=""
              aria-hidden="true"
              className="sv-jelly"
              style={{
                position: "absolute",
                // Kept just inside the right edge so the bell reads whole;
                // only the trailing tentacle tips run past the card's bottom,
                // which is the one crop that looks deliberate.
                right: s(6),
                top: s(-2),
                width: s(234),
                pointerEvents: "none",
                userSelect: "none",
                // Held well back so the station name and stat figures keep
                // their contrast -- at full strength the bell's bright mesh
                // competes directly with the white type in front of it.
                opacity: 0.5,
              }}
            />
            <div style={{ position: "relative", display: "flex", flexDirection: "column", gap: s(5) }}>
              <span style={{ fontSize: s(11), letterSpacing: "0.08em", color: tokens.labelText }}>SAMPLING STATION</span>
              <span style={{ fontSize: s(20), fontWeight: 600, letterSpacing: "-0.01em" }}>{upload.location_label || "Location not recorded"}</span>
              <span style={{ fontSize: s(12), color: tokens.sectionSubtext }}>
                {upload.depth_meters != null ? `${upload.depth_meters.toLocaleString()} m` : "Depth not recorded"} · uploaded {new Date(upload.created_at).toLocaleDateString()}
              </span>
            </div>
            <div style={{ position: "relative", display: "flex", gap: s(18), flexWrap: "wrap" }}>
              <div style={{ display: "flex", flexDirection: "column" }}><span style={{ fontSize: s(10), letterSpacing: "0.07em", color: tokens.pending }}>TAXA DETECTED</span><span style={{ fontSize: s(16), fontWeight: 600, color: tokens.accentCyan }}>{bio.predicted_taxon_richness}</span></div>
              <div style={{ display: "flex", flexDirection: "column" }}><span style={{ fontSize: s(10), letterSpacing: "0.07em", color: tokens.pending }}>SEQUENCES</span><span style={{ fontSize: s(16), fontWeight: 600 }}>{report.qc_summary.total_sequences.toLocaleString()}</span></div>
              <div style={{ display: "flex", flexDirection: "column" }}><span style={{ fontSize: s(10), letterSpacing: "0.07em", color: tokens.pending }}>RUN</span><span style={{ fontSize: s(16), fontWeight: 600, fontFamily: "ui-monospace,monospace", color: tokens.wordmark }}>{report.metadata.analysis_id.replace("ana_", "")}</span></div>
            </div>
          </div>

          <div style={{ ...cardBase, ...revealStyle(0), alignItems: "center" }}>
            <span style={{ ...panelLabelStyle, alignSelf: "flex-start", display: "flex", gap: 6 }}>DISSOLVED OXYGEN <MockTag /></span>
            <OxygenGauge pct={78} />
            <span style={{ fontSize: s(10.5), color: tokens.pending }}>6.4 mg/L · saturation vs surface baseline</span>
          </div>

          <div style={{ ...cardBase, background: "radial-gradient(120% 130% at 15% 0%, rgba(84,60,180,0.22) 0%, rgba(20,110,255,0.08) 45%, rgba(6,10,20,0.75) 100%)" }}>
            <span style={{ ...panelLabelStyle, display: "flex", gap: 6 }}>TOXICITY INDEX <MockTag /></span>
            <span style={{ fontSize: s(44), fontWeight: 600, letterSpacing: "-0.02em", lineHeight: 1 }}>2.1<span style={{ fontSize: s(15), color: tokens.pending }}> / 10</span></span>
            <span style={{ fontSize: s(12.5), fontWeight: 600, color: tokens.success }}>Low</span>
            <span style={{ fontSize: s(11.5), lineHeight: 1.6, color: tokens.sectionSubtext }}>Illustrative only — this deployment has no toxicology sensor or lab-panel integration yet.</span>
          </div>
        </div>

        {/* Row 2: temperature (real) · pH (mock) · salinity (real, replacing the redundant pollutant-levels card) */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", gap: s(14), alignItems: "stretch" }}>
          <div style={{ ...cardBase, justifyContent: "space-between", background: "radial-gradient(130% 140% at 80% 100%, rgba(20,110,255,0.20) 0%, rgba(6,10,20,0.75) 60%)" }}>
            <span style={{ ...panelLabelStyle, display: "flex", gap: 6 }}>TEMPERATURE · AT DEPTH <MockTag /></span>
            {/* Illustrative depth-profile capability -- a single collection-time
                reading doesn't tell you the surface/midwater/seabed split, and
                this deployment has no multi-depth probe to back it yet. Same
                "designed capability, not this run's data" treatment as the
                Oxygen and Toxicity cards above. */}
            <div style={{ display: "flex", flexDirection: "column", gap: s(1) }}>
              {["Surface", "Midwater", "Seabed · reading"].map((label, i) => {
                const active = i === 2;
                return (
                  <div key={label} style={{ display: "flex", alignItems: "center", gap: s(9) }}>
                    <WaveIcon active={active} />
                    <span style={{ fontSize: s(10.5), letterSpacing: "0.05em", fontWeight: active ? 600 : 400, color: active ? tokens.accentCyan : tokens.pending }}>
                      {label.toUpperCase()}
                    </span>
                  </div>
                );
              })}
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: s(10) }}>
              <ThermoIcon />
              <div style={{ display: "flex", alignItems: "baseline", gap: s(8) }}>
                <span style={{ fontSize: s(46), fontWeight: 600, letterSpacing: "-0.02em", lineHeight: 1 }}>4.2°</span>
                <span style={{ fontSize: s(12), color: tokens.sectionSubtext }}>C · {(upload.depth_meters ?? 1840).toLocaleString()} m</span>
              </div>
            </div>
          </div>
          <div style={{ ...cardBase, ...revealStyle(1) }}>
            <span style={{ ...panelLabelStyle, display: "flex", gap: 6 }}>pH LEVEL <MockTag /></span>
            <RangeGauge value={7.9} min={0} max={14} unit="" />
            <span style={{ fontSize: s(10.5), color: tokens.pending, textAlign: "center" }}>within expected range · ocean baseline 8.1</span>
          </div>
          <div style={{ ...cardBase, ...revealStyle(2) }}>
            <span style={{ ...panelLabelStyle, display: "flex", gap: 6 }}>SALINITY {upload.salinity_ppt == null && <MockTag label="NOT RECORDED" />}</span>
            <RangeGauge value={upload.salinity_ppt} min={30} max={40} unit="" />
            <span style={{ fontSize: s(10.5), color: tokens.pending, textAlign: "center" }}>
              {upload.salinity_ppt != null ? "PSU · typical open-ocean range 30–40" : "No salinity reading was captured for this upload."}
            </span>
          </div>
        </div>

        {/* Wind / current -- mock */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: s(14) }}>
          <div style={{ ...cardBase, ...revealStyle(3), background: "radial-gradient(120% 160% at 70% 100%, rgba(46,160,130,0.14) 0%, rgba(6,10,20,0.75) 60%)" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
              <span style={{ ...panelLabelStyle, display: "flex", gap: 6 }}>WIND SPEED BY DAY <MockTag /></span>
              <span style={{ fontSize: s(13), fontWeight: 600, color: tokens.accentCyan }}>14 <span style={{ fontSize: s(10), fontWeight: 400, color: tokens.pending }}>kn · NNE</span></span>
            </div>
            <TrendSVG vals={[19, 18.5, 18, 15, 14.5, 14, 8]} labels={["Tue", "Fri", "Sat", "Wed", "Thu", "Sun", "Mon"]} lo={0} hi={20} />
          </div>
          <div style={{ ...cardBase, ...revealStyle(4), background: "radial-gradient(120% 160% at 30% 100%, rgba(20,110,255,0.14) 0%, rgba(6,10,20,0.75) 60%)" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
              <span style={{ ...panelLabelStyle, display: "flex", gap: 6 }}>CURRENT SPEED BY DAY <MockTag /></span>
              <span style={{ fontSize: s(13), fontWeight: 600, color: tokens.accentCyan }}>1.8 <span style={{ fontSize: s(10), fontWeight: 400, color: tokens.pending }}>kn · SW drift</span></span>
            </div>
            <TrendSVG vals={[2.6, 2.4, 2.3, 2.2, 1.9, 1.8, 1.1]} labels={["Tue", "Fri", "Sat", "Wed", "Thu", "Sun", "Mon"]} lo={0} hi={3} />
          </div>
        </div>

        {/* Multi-omics overlay -- mock */}
        <div style={{ ...cardBase, ...revealStyle(5) }}>
          <span style={{ ...panelLabelStyle, display: "flex", gap: 6 }}>MULTI-OMICS &amp; ENVIRONMENTAL OVERLAY <MockTag /></span>
          <div style={{ display: "flex", gap: s(14), flexWrap: "wrap", fontSize: s(10.5), color: tokens.sectionSubtext }}>
            <span style={{ display: "flex", alignItems: "center", gap: 6 }}><span style={{ width: 16, height: 2, background: tokens.accentCyan, display: "inline-block" }} />DNA reads</span>
            <span style={{ display: "flex", alignItems: "center", gap: 6 }}><span style={{ width: 16, height: 2, background: tokens.accentBlue, display: "inline-block" }} />Temp</span>
            <span style={{ display: "flex", alignItems: "center", gap: 6 }}><span style={{ width: 16, height: 2, background: "#146EFF", display: "inline-block" }} />pH</span>
            <span style={{ display: "flex", alignItems: "center", gap: 6 }}><span style={{ width: 16, height: 2, background: tokens.purple, display: "inline-block" }} />Salinity</span>
          </div>
          <span style={{ fontSize: s(10.5), color: tokens.pending }}>This deployment only stores a single point-in-time reading per upload, not a time series — this chart uses sample data. Correlative view, no causal claim implied.</span>
          <WavesSVG />
        </div>

        {/* Sonic + activity rhythms -- mock */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: s(14) }}>
          <div style={{ ...cardBase, ...revealStyle(6) }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
              <span style={{ ...panelLabelStyle, display: "flex", gap: 6 }}>SONIC ACTIVITY · AMBIENT NOISE <MockTag /></span>
              <span style={{ fontSize: s(13), fontWeight: 600, color: tokens.accentCyan }}>94 dB <span style={{ fontSize: s(10), fontWeight: 400, color: tokens.pending }}>re 1 µPa</span></span>
            </div>
            <SonicSVG />
            <div style={{ display: "flex", gap: s(14), flexWrap: "wrap", fontSize: s(10.5), color: tokens.sectionSubtext }}>
              <span style={{ display: "flex", alignItems: "center", gap: 6 }}><span style={{ width: 16, height: 2, background: tokens.accentCyan, display: "inline-block" }} />Broadband ambient</span>
              <span style={{ display: "flex", alignItems: "center", gap: 6 }}><span style={{ width: 16, height: 2, background: tokens.accentBlue, display: "inline-block" }} />Vessel traffic</span>
              <span style={{ display: "flex", alignItems: "center", gap: 6 }}><span style={{ width: 16, height: 2, background: tokens.purple, display: "inline-block" }} />Biologic band</span>
            </div>
            <span style={{ fontSize: s(10.5), color: tokens.pending }}>No hydrophone is wired up for this deployment yet.</span>
          </div>
          <div style={{ ...cardBase, ...revealStyle(7) }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
              <span style={{ ...panelLabelStyle, display: "flex", gap: 6 }}>ACTIVITY RHYTHMS · VERTICAL MIGRATION <MockTag /></span>
              <span style={{ fontSize: s(13), fontWeight: 600, color: tokens.success }}>DVM peak 18:30 <span style={{ fontSize: s(10), fontWeight: 400, color: tokens.pending }}>· detections/hr</span></span>
            </div>
            <DvmSVG />
            <span style={{ fontSize: s(10.5), color: tokens.pending }}>No acoustic backscatter pipeline exists for this deployment yet.</span>
          </div>
        </div>

        {/* Co-occurrence network */}
        <div style={{ ...cardBase, ...revealStyle(8) }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: s(14), flexWrap: "wrap" }}>
            <span style={{ ...panelLabelStyle, display: "flex", gap: 6 }}>SPECIES CO-OCCURRENCE NETWORK <MockTag /></span>
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <span style={{ fontSize: s(9.5), letterSpacing: "0.07em", color: tokens.sectionSubtext }}>ABUNDANCE THRESHOLD · {netThr}%</span>
              <input type="range" min={0} max={60} value={netThr} onChange={(e) => setNetThr(+e.target.value)} className="sv-novelty-slider" style={{ width: s(170) }} />
            </div>
          </div>
          <div style={{ display: "flex", gap: s(16), flexWrap: "wrap", fontSize: s(10.5), color: tokens.sectionSubtext }}>
            <span style={{ display: "flex", alignItems: "center", gap: 6 }}><span style={{ width: 18, height: 2, background: tokens.accentBlue, display: "inline-block" }} />Positive statistical co-occurrence (Spearman ρ &gt; 0.6)</span>
            <span style={{ display: "flex", alignItems: "center", gap: 6 }}><span style={{ width: 18, height: 0, borderTop: `2px dashed ${tokens.danger}`, display: "inline-block" }} />Negative statistical co-occurrence (ρ &lt; −0.6)</span>
            <span style={{ color: tokens.pending }}>Node radius ∝ relative DNA abundance · correlation ≠ biological interaction</span>
          </div>
          <canvas ref={canvasRef} style={{ width: "100%", height: s(340), borderRadius: 6, border: "1px solid #101D33", background: "#04070E" }} />
          <span style={{ fontSize: s(11), color: tokens.sectionSubtext }}>Showing nodes with relative abundance ≥ {netThr}% of max · {visCount ?? "—"} of 140 nodes visible</span>
        </div>

        {/* Export engine */}
        <div style={cardBase}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: s(12), flexWrap: "wrap" }}>
            <span style={panelLabelStyle}>PUBLISH-READY EXPORT</span>
            <div style={{ display: "flex", gap: s(8) }}>
              <button
                onClick={() => handleExport("json")}
                disabled={downloadingFormat !== null}
                style={{ padding: `${s(8)}px ${s(18)}px`, border: "1px solid rgba(160,205,255,0.55)", borderRadius: s(12), background: "linear-gradient(180deg, #459AF5 0%, #1A71F0 48%, #0D57D1 100%)", boxShadow: "inset 0 1.5px 0 rgba(255,255,255,0.55), inset 0 -3px 8px rgba(8,50,140,0.45), 0 10px 30px rgba(30,123,255,0.38)", fontFamily: "inherit", fontSize: s(12), fontWeight: 600, color: "#FFFFFF", textShadow: "0 1px 2px rgba(8,50,140,0.4)", cursor: downloadingFormat ? "default" : "pointer", opacity: downloadingFormat && downloadingFormat !== "json" ? 0.5 : 1 }}
              >
                {downloadingFormat === "json" ? "Exporting..." : "⬇ Download JSON"}
              </button>
              <button
                onClick={() => handleExport("csv")}
                disabled={downloadingFormat !== null}
                style={{ padding: `${s(8)}px ${s(18)}px`, border: "1px solid rgba(160,205,255,0.55)", borderRadius: s(12), background: "linear-gradient(180deg, #459AF5 0%, #1A71F0 48%, #0D57D1 100%)", boxShadow: "inset 0 1.5px 0 rgba(255,255,255,0.55), inset 0 -3px 8px rgba(8,50,140,0.45), 0 10px 30px rgba(30,123,255,0.38)", fontFamily: "inherit", fontSize: s(12), fontWeight: 600, color: "#FFFFFF", textShadow: "0 1px 2px rgba(8,50,140,0.4)", cursor: downloadingFormat ? "default" : "pointer", opacity: downloadingFormat && downloadingFormat !== "csv" ? 0.5 : 1 }}
              >
                {downloadingFormat === "csv" ? "Exporting..." : "⬇ Download CSV"}
              </button>
            </div>
          </div>
          <span style={{ fontSize: s(11), color: tokens.pending, display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
            A single FAIR-structured ZIP (raw FASTA + curated tables + metadata) isn&rsquo;t available yet — the buttons above download the real report as JSON or CSV instead. <MockTag label="MOCK — ZIP BUNDLE NOT BUILT YET" />
          </span>
          <div style={{ display: "flex", flexDirection: "column", gap: s(7) }}>
            <span style={{ fontSize: s(11), letterSpacing: "0.08em", color: tokens.sectionSubtext }}>AUTO-CITATION GENERATOR</span>
            <textarea
              readOnly
              rows={3}
              value={citation}
              style={{ width: "100%", boxSizing: "border-box", padding: `${s(12)}px ${s(14)}px`, border: `1px solid ${tokens.sectionBorder}`, borderRadius: s(3), background: "#04070E", color: tokens.accentCyan, fontFamily: "ui-monospace,monospace", fontSize: s(11.5), lineHeight: 1.7, resize: "vertical", outline: "none" }}
            />
            <button
              onClick={copyCitation}
              style={{ alignSelf: "flex-start", padding: `${s(6)}px ${s(14)}px`, border: `1px solid ${tokens.sectionBorder}`, borderRadius: s(10), background: "#080F1C", fontFamily: "inherit", fontSize: s(11.5), fontWeight: 500, color: tokens.wordmark, cursor: "pointer" }}
            >
              {copied ? "Copied ✓" : "Copy citation"}
            </button>
          </div>
          <span style={{ fontSize: s(10), color: tokens.pending, fontFamily: "ui-monospace,monospace" }}>
            Novelty threshold ≥ 0.45 · Contamination gate ≥ 0.50 · Models: {report.model_versions_used.map((m) => m.model_version_used).join(", ") || "none recorded"}
          </span>
        </div>

        <div style={{ display: "flex", justifyContent: "center", padding: `${s(8)}px 0 ${s(2)}px`, borderTop: `1px solid ${tokens.sectionBorder}` }}>
          <span style={{ fontSize: s(11), color: tokens.pending, textAlign: "center" }}>
            Run {report.metadata.analysis_id} · Pipeline: {report.metadata.model_version_set || "not recorded"} · Reference DB: pending configuration · Generated {new Date(report.generated_at).toLocaleString()}
          </span>
        </div>
      </div>
    </div>
  );
}
