import { useState, useEffect } from "react";
import SidebarMenu from "../../components/sidebar/SidebarMenu";
import { tokens } from "../../components/shared/tokens";
import MockTag from "../../components/shared/MockTag";
import { liquidGlass } from "../../styles/liquidGlass";
import { revealStyle } from "../../styles/reveal";

// Same per-page scale convention as Academia.jsx / Legislative.jsx -- keeps
// card padding, radii and type sizes on the same ratio across every Partner
// Report screen.
const SCALE = 1.18;
const s = (n) => Math.round(n * SCALE * 10) / 10;

const INCIDENTS = [
  {
    id: 1,
    title: "Protected species near active dredging — Sector 3",
    detail: "IUCN Red List species DNA detected within permit zone during active operations.",
    src: "stn14_bay-of-bengal_0812.fasta",
    batch: "#A21",
  },
  {
    id: 2,
    title: "Invasive bivalve above intake threshold — Berth 2",
    detail: "Biofouling-linked DNA exceeded internal alert threshold across two samples.",
    src: "berth2_intake_0808.fasta",
    batch: "#A19",
  },
  {
    id: 3,
    title: "Indicator taxa decline — Outfall S",
    detail: "Seagrass indicator DNA down 3 consecutive samples near discharge outfall.",
    src: "outfall-s_0801.fasta",
    batch: "#A17",
  },
];

const TASK_DEFS = [
  { id: 1, label: "Check chain-of-custody logs for sample batch #A21" },
  { id: 2, label: "Confirm mitigation budget allocation" },
  { id: 3, label: "Schedule stakeholder briefing — add to calendar" },
];

const RADAR_AXES = ["Regulatory Fines", "Permit Delays", "Biodiversity Loss", "Biofouling Risk", "Supply Disruption"];
const RADAR_VALS = [0.62, 0.74, 0.48, 0.66, 0.35];

// Hover-reactive: the outer name+percentage label doubles as the hover
// target (a generous invisible hit circle, not just the small 3px dot --
// that'd be an unreasonably small target), and hovering it highlights the
// label, its spoke, and its vertex dot together as one unit. Percentages
// are always visible (dim) rather than hover-only, per "label the edges" --
// hover only makes the hovered one pop.
function RiskRadar() {
  const [hovered, setHovered] = useState(null);
  const cx = 210, cy = 130, R = 92;
  const pt = (i, r) => {
    const a = -Math.PI / 2 + (i * 2 * Math.PI) / 5;
    return [cx + Math.cos(a) * r, cy + Math.sin(a) * r];
  };
  const ring = (f) => "M" + RADAR_AXES.map((_, i) => pt(i, R * f).join(" ")).join(" L") + " Z";
  const poly = "M" + RADAR_VALS.map((v, i) => pt(i, R * v).join(" ")).join(" L") + " Z";
  const enter = (i) => () => setHovered(i);
  const leave = () => setHovered(null);
  return (
    <svg viewBox="0 0 420 265" style={{ width: "100%", height: "auto", display: "block" }}>
      {[0.33, 0.66, 1].map((f) => (
        <path key={f} d={ring(f)} fill="none" stroke="#14233C" strokeWidth={1} />
      ))}
      {RADAR_AXES.map((_, i) => {
        const [x, y] = pt(i, R);
        const active = hovered === i;
        return (
          <line
            key={`ax${i}`}
            x1={cx} y1={cy} x2={x} y2={y}
            pathLength={1}
            className="sv-draw-path"
            style={{ animationDelay: `${i * 0.06}s`, transition: "stroke .12s ease" }}
            stroke={active ? tokens.accentCyan : "#14233C"}
            strokeWidth={active ? 1.5 : 1}
          />
        );
      })}
      <path d={poly} className="sv-scale-in" style={{ animationDelay: "0.35s" }} fill="rgba(59,158,255,0.18)" stroke={tokens.accentBlue} strokeWidth={2} strokeLinejoin="round" />
      {RADAR_VALS.map((v, i) => {
        const [x, y] = pt(i, R * v);
        const active = hovered === i;
        return (
          <circle
            key={`v${i}`}
            cx={x}
            cy={y}
            r={active ? 5 : 3}
            className="sv-fade-in-late"
            style={{ "--sv-fade-to": 1, animationDelay: "0.7s", cursor: "pointer", transition: "r .12s ease" }}
            fill={tokens.accentCyan}
            onMouseEnter={enter(i)}
            onMouseLeave={leave}
          />
        );
      })}
      {RADAR_AXES.map((name, i) => {
        const [x, y] = pt(i, R + 26);
        const active = hovered === i;
        const pct = Math.round(RADAR_VALS[i] * 100);
        return (
          <g key={name} className="sv-fade-in-late" style={{ animationDelay: "0.75s", cursor: "pointer" }} onMouseEnter={enter(i)} onMouseLeave={leave}>
            <circle cx={x} cy={y} r={28} fill="transparent" />
            <text x={x} y={y - 2} fill={active ? tokens.textPrimary : tokens.sectionSubtext} fontSize={10} fontWeight={active ? 600 : 400} textAnchor="middle" style={{ transition: "fill .12s ease" }}>
              {name}
            </text>
            <text x={x} y={y + 13} fill={active ? tokens.accentCyan : tokens.pending} fontSize={active ? 12 : 10} fontWeight={700} textAnchor="middle" style={{ transition: "fill .12s ease, font-size .12s ease" }}>
              {pct}%
            </text>
          </g>
        );
      })}
    </svg>
  );
}

// Centered alone at the top of its card now (not squeezed beside text), so
// there's room for real leader-line percentage labels around the ring --
// each one radiates outward from its segment's own midpoint angle, in that
// segment's color, terminating in a short text anchored left/right/center
// depending which side of the circle it lands on (so the label reads away
// from the ring rather than doubling back over it). Hover still swaps the
// center readout to the segment's full name, since the leader labels alone
// don't have room to spell that out.
function ImpactDonut() {
  const [hovered, setHovered] = useState(null);
  // Leader-line labels show briefly on mount, then hide themselves after
  // 2s and only reappear on hover -- driven by plain React state (not a
  // CSS animation + fill-mode "backwards") since that approach relied on
  // the browser correctly releasing the animation's effect back to each
  // leader's own hover-driven opacity once the fade finished, which didn't
  // hold reliably: the labels would show once and then never respond to
  // hover again. This way opacity is always computed live from
  // `introShown`/`hovered` on every render, so hover keeps working no
  // matter what phase the intro is in.
  const [introShown, setIntroShown] = useState(false);
  useEffect(() => {
    const showAt = setTimeout(() => setIntroShown(true), 100);
    const hideAt = setTimeout(() => setIntroShown(false), 2000);
    return () => { clearTimeout(showAt); clearTimeout(hideAt); };
  }, []);
  const segs = [
    [62, tokens.success, "Mitigation success"],
    [14, tokens.danger, "Biofouling load"],
    [24, tokens.accentBlue, "Indicator stability"],
  ];
  const cx = 120, cy = 120, r = 64, W = 20;
  const rOuter = r + W / 2;
  const rLine = rOuter + 14;
  const rText = rLine + 6;
  let a0 = -Math.PI / 2;
  const arcs = [];
  const leaders = [];
  segs.forEach(([v, c], i) => {
    const a1 = a0 + (v / 100) * 2 * Math.PI;
    const large = a1 - a0 > Math.PI ? 1 : 0;
    const d = `M${cx + Math.cos(a0) * r} ${cy + Math.sin(a0) * r} A${r} ${r} 0 ${large} 1 ${cx + Math.cos(a1) * r} ${cy + Math.sin(a1) * r}`;
    const active = hovered === i;
    arcs.push(
      <path
        key={i}
        d={d}
        pathLength={1}
        className="sv-draw-path"
        fill="none"
        stroke={c}
        strokeWidth={active ? W + 4 : W}
        strokeLinecap="butt"
        opacity={active ? 1 : 0.85}
        onMouseEnter={() => setHovered(i)}
        onMouseLeave={() => setHovered(null)}
        style={{ animationDelay: `${i * 0.15}s`, cursor: "pointer", transition: "stroke-width .12s ease, opacity .12s ease" }}
      />
    );

    const am = (a0 + a1) / 2;
    const cos = Math.cos(am), sin = Math.sin(am);
    const lx1 = cx + cos * rOuter, ly1 = cy + sin * rOuter;
    const lx2 = cx + cos * rLine, ly2 = cy + sin * rLine;
    const tx = cx + cos * rText, ty = cy + sin * rText;
    const anchor = cos > 0.2 ? "start" : cos < -0.2 ? "end" : "middle";
    leaders.push(
      <g
        key={`l${i}`}
        opacity={active ? 1 : introShown ? 0.75 : 0}
        style={{ transition: "opacity .4s ease" }}
      >
        <line x1={lx1} y1={ly1} x2={lx2} y2={ly2} stroke={c} strokeWidth={1.4} />
        <circle cx={lx1} cy={ly1} r={1.6} fill={c} />
        <text x={tx} y={ty + 4} fill={c} fontSize={13} fontWeight={700} textAnchor={anchor}>{v}%</text>
      </g>
    );
    a0 = a1;
  });
  const active = hovered != null ? segs[hovered] : null;
  return (
    <svg viewBox="0 36 240 164" style={{ width: 480, flexShrink: 0, display: "block" }}>
      {leaders}
      {arcs}
      {active ? (
        <>
          <text x={cx} y={cy - 5} fill={active[1]} fontSize={24} fontWeight={700} textAnchor="middle">{active[0]}%</text>
          <text x={cx} y={cy + 15} fill={tokens.wordmark} fontSize={9} textAnchor="middle">{active[2]}</text>
        </>
      ) : (
        <>
          <text x={cx} y={cy - 3} fill={tokens.textPrimary} fontSize={19} fontWeight={600} textAnchor="middle">100%</text>
          <text x={cx} y={cy + 16} fill={tokens.pending} fontSize={10} textAnchor="middle">DNA-derived</text>
        </>
      )}
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

// Button uses the app's shared liquid-glass material rather than the flat
// gradient the original design mockup specified -- same recipe as
// Legislative.jsx, so every raised control across Partner Report reads as
// one system.
const primaryBtnStyle = {
  alignSelf: "flex-start",
  padding: `${s(8)}px ${s(18)}px`,
  borderRadius: 999,
  fontFamily: "inherit",
  fontSize: s(12),
  fontWeight: 600,
  color: "#FFFFFF",
  textShadow: "0 1px 2px rgba(8,50,140,0.4)",
  cursor: "pointer",
  ...liquidGlass({
    top: "rgba(120,185,255,0.95)",
    bottom: "rgba(20,110,255,0.88)",
    border: "rgba(255,255,255,0.40)",
    highlight: "rgba(255,255,255,0.55)",
    innerShadow: "rgba(10,60,170,0.35)",
    outerShadow: "0 10px 26px rgba(20,110,255,0.42)",
    blur: 16,
  }),
};

// Anchors this deployment has no real destination for yet (document store,
// remediation tracker) -- rendered as plain dimmed text with a tooltip
// rather than a normal link, so it never looks clickable when it isn't.
const inertLinkStyle = { fontSize: s(12), color: tokens.pending, cursor: "default" };

function DocIcon() {
  return (
    <svg width={12} height={12} viewBox="0 0 14 14" fill="none">
      <path d="M7 1v8M4 6l3 3 3-3M2 12h10" stroke="currentColor" strokeWidth={1.4} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function CheckCircleIcon({ size = 12, color = "currentColor" }) {
  return (
    <svg width={size} height={size} viewBox="0 0 14 14" fill="none">
      <circle cx={7} cy={7} r={5.5} stroke={color} strokeWidth={1.3} />
      <path d="M4.5 7l1.8 1.8L9.5 5.5" stroke={color} strokeWidth={1.3} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export default function Industrial() {
  const [incOpen, setIncOpen] = useState(false);
  const [done, setDone] = useState({ 1: false, 2: true, 3: false });
  const [scheduled, setScheduled] = useState(false);

  const toggleTask = (id) => setDone((d) => ({ ...d, [id]: !d[id] }));

  // Honest middle ground between "fully wired" and "silently does nothing":
  // there's no real audit-scheduling backend, but flipping a local
  // acknowledgement state (same pattern as Academia's citation-copy
  // feedback) is a real, truthful response to the click rather than either
  // extreme.
  const scheduleAudit = () => {
    setScheduled(true);
    setTimeout(() => setScheduled(false), 1600);
  };

  return (
    <div style={pageStyle}>
      <div style={ambientGlow} />
      <SidebarMenu />
      <div style={{ position: "relative", maxWidth: s(1560), margin: "0 auto", padding: `${s(32)}px ${s(44)}px ${s(44)}px`, display: "flex", flexDirection: "column", gap: s(18) }}>
        {/* Header */}
        <div style={{ display: "flex", flexDirection: "column", gap: s(6), alignItems: "center", textAlign: "center" }}>
          <div style={{ fontSize: s(12), letterSpacing: "0.08em", color: tokens.labelText }}>PARTNER REPORT › INDUSTRIAL</div>
          <h1 style={{ margin: 0, fontSize: s(27), fontWeight: 600, letterSpacing: "-0.01em" }}>Enterprise Compliance Dashboard</h1>
          <p style={{ margin: 0, fontSize: s(14), color: tokens.sectionSubtext }}>Corporate environmental risk, audit readiness &amp; biological compliance</p>
        </div>

        {/* KPIs -- all three cards share the same neutral cardBase shell now;
            the only red/yellow/etc. left is on the specific number or
            button that carries real meaning, not the whole card, so the
            row reads as one consistent set instead of three different
            colored tiles. */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: s(14) }}>
          <div style={cardBase}>
            <span style={{ ...panelLabelStyle, display: "flex", gap: 6 }}>ACTIVE INCIDENTS <MockTag /></span>
            <span style={{ fontSize: s(28), fontWeight: 600, color: tokens.danger }}>3</span>
            <button
              onClick={() => setIncOpen(true)}
              style={{ alignSelf: "flex-start", padding: `${s(5)}px ${s(13)}px`, border: "1px solid rgba(255,123,123,0.35)", borderRadius: s(10), background: "rgba(255,123,123,0.08)", fontFamily: "inherit", fontSize: s(11.5), fontWeight: 600, color: "#FF9B9B", cursor: "pointer" }}
            >
              View source detections →
            </button>
          </div>
          <div style={cardBase}>
            <span style={{ ...panelLabelStyle, display: "flex", gap: 6 }}>AVERAGE IMPACT SCORE <MockTag /></span>
            <span style={{ fontSize: s(28), fontWeight: 600, color: tokens.warningAlt }}>5.8<span style={{ fontSize: s(14), color: tokens.pending }}> / 10</span></span>
            <span style={{ fontSize: s(11), color: tokens.pending }}>weighted across 4 active projects</span>
          </div>
          <div style={cardBase}>
            <span style={{ ...panelLabelStyle, display: "flex", gap: 6 }}>PENDING AUDITS <MockTag /></span>
            <span style={{ fontSize: s(28), fontWeight: 600 }}>2</span>
            <span style={{ fontSize: s(11), color: tokens.pending }}>next EIA due 04 Sep 2026</span>
          </div>
        </div>

        {/* Radar + biological impact -- alignItems left at grid's default
            "stretch" (not "start") so both cards match height instead of
            each sizing to its own content, which is what made this row
            look lopsided. */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: s(18) }}>
          <div style={{ ...cardBase, ...revealStyle(0) }}>
            <span style={{ ...panelLabelStyle, display: "flex", gap: 6 }}>ENVIRONMENTAL RISK RADAR <MockTag /></span>
            <RiskRadar />
            <div style={{ display: "flex", flexDirection: "column", gap: s(4), alignItems: "center", textAlign: "center" }}>
              <span style={{ fontSize: s(13), fontWeight: 600, color: tokens.warningAlt }}>Medium Overall Risk</span>
              <span style={{ fontSize: s(11.5), color: tokens.sectionSubtext }}>Key drivers: permit delays, regulatory fines, biofouling load</span>
            </div>
          </div>
          {/* Donut centered on top, the three metric blocks stacked full-
              width below it -- was donut-left/labels-right; turning that
              90° puts the chart up top and its breakdown underneath. */}
          <div style={{ ...cardBase, ...revealStyle(1) }}>
            <span style={{ ...panelLabelStyle, display: "flex", gap: 6 }}>BIOLOGICAL IMPACT METRICS <MockTag /></span>
            <div style={{ display: "flex", justifyContent: "center" }}>
              <ImpactDonut />
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: s(8) }}>
              <div style={{ display: "flex", flexDirection: "column", gap: s(2), padding: `${s(9)}px ${s(13)}px`, borderRadius: s(6), border: "1px solid #101D33", borderLeft: `3px solid ${tokens.success}`, background: "rgba(8,14,26,0.5)" }}>
                <span style={{ fontSize: s(10), letterSpacing: "0.07em", color: tokens.sectionSubtext }}>MITIGATION SUCCESS</span>
                <span style={{ fontSize: s(16), fontWeight: 600, color: tokens.success }}>62%</span>
                <span style={{ fontSize: s(9.5), color: tokens.pending }}>native/target species DNA returning post-restoration</span>
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: s(2), padding: `${s(9)}px ${s(13)}px`, borderRadius: s(6), border: "1px solid #101D33", borderLeft: `3px solid ${tokens.danger}`, background: "rgba(8,14,26,0.5)" }}>
                <span style={{ fontSize: s(10), letterSpacing: "0.07em", color: tokens.sectionSubtext }}>BIOFOULING / INVASIVE LOAD</span>
                <span style={{ fontSize: s(16), fontWeight: 600, color: tokens.danger }}>14%</span>
                <span style={{ fontSize: s(9.5), color: tokens.pending }}>DNA linked to infrastructure-damaging organisms</span>
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: s(2), padding: `${s(9)}px ${s(13)}px`, borderRadius: s(6), border: "1px solid #101D33", borderLeft: `3px solid ${tokens.accentBlue}`, background: "rgba(8,14,26,0.5)" }}>
                <span style={{ fontSize: s(10), letterSpacing: "0.07em", color: tokens.sectionSubtext }}>INDICATOR SPECIES STABILITY</span>
                <span style={{ fontSize: s(16), fontWeight: 600, color: tokens.accentBlue }}>24%</span>
                <span style={{ fontSize: s(9.5), color: tokens.pending }}>baseline biodiversity stable despite operations</span>
              </div>
            </div>
          </div>
        </div>

        {/* Operational & audit -- same fix: default stretch instead of
            "start", so Document Hub (short) no longer sits visibly shorter
            than Quick Notes & Tasks (long) in the same row. */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: s(14) }}>
          <div style={cardBase}>
            <span style={{ ...panelLabelStyle, display: "flex", gap: 6 }}>AUDIT TRAIL <MockTag /></span>
            <span style={{ fontSize: s(12), lineHeight: 1.55, color: tokens.sectionSubtext }}>
              Last audit: <span style={{ color: tokens.wordmark }}>2025-08-20</span> — minor non-compliance resolved
            </span>
            <button onClick={scheduleAudit} style={primaryBtnStyle}>{scheduled ? "Requested ✓" : "Schedule Audit"}</button>
          </div>
          <div style={cardBase}>
            <span style={{ ...panelLabelStyle, display: "flex", gap: 6 }}>REMEDIATION PLAN <MockTag /></span>
            <div style={{ display: "flex", flexDirection: "column", gap: s(4), fontSize: s(12), color: tokens.sectionSubtext }}>
              <span>Action: <span style={{ color: tokens.wordmark }}>Submit remediation plan</span></span>
              <span>Owner: <span style={{ color: tokens.wordmark }}>Environmental Team</span></span>
              <span>Deadline: <span style={{ color: tokens.warningAlt }}>28 Aug 2026</span></span>
            </div>
            <span style={inertLinkStyle} title="No live remediation tracker connected yet">Open remediation plan →</span>
          </div>
          <div style={cardBase}>
            <span style={{ ...panelLabelStyle, display: "flex", gap: 6 }}>DOCUMENT HUB <MockTag /></span>
            <div style={{ display: "flex", flexDirection: "column", gap: s(7), fontSize: s(12) }}>
              {["audit-2025-08.pdf", "eia-baseline-2026-02.pdf", "mitigation-q2-2026.pdf"].map((f) => (
                <span key={f} style={{ ...inertLinkStyle, display: "flex", alignItems: "center", gap: s(7) }} title="No live document store connected yet">
                  <DocIcon />
                  {f}
                </span>
              ))}
            </div>
          </div>
          <div style={cardBase}>
            <span style={{ ...panelLabelStyle, display: "flex", gap: 6 }}>QUICK NOTES &amp; TASKS <MockTag /></span>
            <div style={{ display: "flex", flexDirection: "column", gap: s(8) }}>
              {TASK_DEFS.map((t) => {
                const isDone = done[t.id];
                return (
                  <div key={t.id} onClick={() => toggleTask(t.id)} style={{ display: "flex", alignItems: "flex-start", gap: s(9), cursor: "pointer" }}>
                    <span
                      style={{
                        width: s(16),
                        height: s(16),
                        borderRadius: s(4),
                        flexShrink: 0,
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        fontSize: s(10),
                        fontWeight: 700,
                        border: `1.5px solid ${isDone ? tokens.accentBlue : "#2A3B58"}`,
                        background: isDone ? "rgba(59,158,255,0.25)" : "rgba(8,14,26,0.6)",
                        color: tokens.accentCyan,
                        marginTop: 1,
                      }}
                    >
                      {isDone ? "✓" : ""}
                    </span>
                    <span style={{ fontSize: s(11.5), lineHeight: 1.45, color: isDone ? tokens.pending : tokens.wordmark, textDecoration: isDone ? "line-through" : "none" }}>{t.label}</span>
                  </div>
                );
              })}
            </div>
            <span style={{ fontSize: s(9.5), color: tokens.pending }}>Batch IDs reference chain-of-custody metadata captured at Upload Analysis</span>
          </div>
        </div>

        {/* Predictive -- Predictive Threshold now shares the same neutral
            cardBase shell as its neighbor instead of a full yellow wash;
            the "~45 days" figure and header label stay warning-colored,
            which is enough to flag it as a caution callout on its own. */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: s(18) }}>
          <div style={cardBase}>
            <span style={{ fontSize: s(12.5), fontWeight: 600, letterSpacing: "0.08em", color: tokens.warningAlt, display: "flex", gap: 6 }}>PREDICTIVE THRESHOLD · BIOFOULING <MockTag /></span>
            <span style={{ fontSize: s(15), lineHeight: 1.55, color: tokens.textPrimary }}>
              Current trajectory indicates biofouling load will exceed regulatory limits in <span style={{ fontWeight: 600, color: tokens.warningAlt }}>~45 days</span> — early mitigation recommended.
            </span>
            <span style={{ fontSize: s(10.5), color: tokens.sectionSubtext, alignSelf: "flex-start" }}>Modeled from trend across last 6 samples · ±12 days</span>
          </div>
          <div style={cardBase}>
            <span style={{ ...panelLabelStyle, display: "flex", gap: 6 }}>REMEDIATION ROI · COST DELTA <MockTag /></span>
            <div style={{ display: "flex", alignItems: "baseline", gap: s(14), flexWrap: "wrap" }}>
              <span style={{ fontSize: s(20), fontWeight: 600, color: tokens.success }}>$12,000</span>
              <span style={{ fontSize: s(12), color: tokens.pending }}>est. mitigation</span>
              <span style={{ fontSize: s(13), color: tokens.pending }}>vs</span>
              <span style={{ fontSize: s(20), fontWeight: 600, color: tokens.danger }}>$85,000</span>
              <span style={{ fontSize: s(12), color: tokens.pending }}>projected fine</span>
            </div>
            <span style={{ fontSize: s(10.5), color: tokens.sectionSubtext, alignSelf: "flex-start" }}>Cost: external contractor rate card · Fine exposure: regional regulatory schedule</span>
          </div>
        </div>

        <div style={{ display: "flex", justifyContent: "center", padding: `${s(8)}px 0 2px`, borderTop: "1px solid #0C1526" }}>
          <span style={{ fontSize: s(11), color: tokens.pending }}>Reference DB: MarineGenomeDB v4.2 · SILVA 16S v138.2 · Pipeline: v2.8.1 · Matched 15 Aug 2026, 09:41 UTC</span>
        </div>
      </div>

      {/* Incidents modal */}
      {incOpen && (
        <>
          <div onClick={() => setIncOpen(false)} style={{ position: "fixed", inset: 0, background: "rgba(2,4,9,0.7)", backdropFilter: "blur(4px)", zIndex: 40 }} />
          <div style={{ position: "fixed", top: "50%", left: "50%", transform: "translate(-50%,-50%)", width: s(600), maxWidth: "92vw", zIndex: 41, display: "flex", flexDirection: "column", gap: s(14), padding: `${s(24)}px ${s(28)}px`, borderRadius: s(12), border: "1px solid #1C2E4C", background: "#050912", boxShadow: "0 40px 120px rgba(0,0,0,0.7)" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span style={{ fontSize: s(15), fontWeight: 600 }}>Active incidents — source detections</span>
              <button onClick={() => setIncOpen(false)} style={{ width: s(30), height: s(30), borderRadius: s(8), border: "1px solid #17253D", background: "#080F1C", color: tokens.wordmark, fontSize: s(14), cursor: "pointer" }}>✕</button>
            </div>
            {INCIDENTS.map((i) => (
              <div key={i.id} style={{ display: "flex", flexDirection: "column", gap: s(5), padding: `${s(13)}px ${s(15)}px`, borderRadius: s(6), border: "1px solid #101D33", borderLeft: `3px solid ${tokens.danger}`, background: "rgba(8,14,26,0.55)" }}>
                <span style={{ fontSize: s(13), fontWeight: 600 }}>{i.title}</span>
                <span style={{ fontSize: s(11.5), color: tokens.sectionSubtext }}>{i.detail}</span>
                <span style={{ fontSize: s(10.5), fontFamily: "ui-monospace,monospace", color: tokens.pending, display: "flex", alignItems: "center", gap: s(6) }}>
                  source: {i.src} · batch {i.batch} · <CheckCircleIcon size={s(11)} color={tokens.success} /> sha-256 verified
                </span>
              </div>
            ))}
            <span style={{ fontSize: s(10.5), color: tokens.pending }}>Each incident traces to its source detection event and chain-of-custody record — auditable for legal defense documentation.</span>
          </div>
        </>
      )}
    </div>
  );
}
