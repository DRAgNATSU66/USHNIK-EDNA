import { useState, Fragment } from "react";
import { MapContainer, TileLayer, Circle, CircleMarker, Tooltip, Popup, Polyline } from "react-leaflet";
import "leaflet/dist/leaflet.css";
import SidebarMenu from "../../components/sidebar/SidebarMenu";
import { tokens } from "../../components/shared/tokens";
import MockTag from "../../components/shared/MockTag";
import { liquidGlass } from "../../styles/liquidGlass";
import { revealStyle } from "../../styles/reveal";

// Same per-page scale convention as Academia.jsx -- keeps card padding, radii
// and type sizes on the same ratio across every Partner Report screen.
const SCALE = 1.18;
const s = (n) => Math.round(n * SCALE * 10) / 10;

const SEVERITY = {
  Critical: tokens.danger,
  High: tokens.warningAlt,
  Medium: tokens.success,
  Low: tokens.accentBlue,
};

const ALERTS = [
  {
    id: 1,
    title: "Protected Species — Sector 3",
    sev: "Critical",
    desc: "IUCN Red List species DNA detected within active construction zone.",
    action: "Temporary halt of dredging in Sector 3 pending field survey and secondary sampling.",
    boundary: false,
  },
  {
    id: 2,
    title: "Invasive Species — Sector 7",
    sev: "High",
    desc: "Invasive bivalve DNA signature rising across two consecutive samples.",
    action: "Field survey and sample removal; increase monitoring frequency to weekly.",
    boundary: true,
  },
  {
    id: 3,
    title: "Coastal Stabilization Risk — Estuary N",
    sev: "Medium",
    desc: "Inferred from mangrove/seagrass indicator taxa decline (not a direct physical measurement).",
    action: "Commission indicator-taxa resampling before permitting review.",
    boundary: false,
  },
  {
    id: 4,
    title: "Invasive Species — Outer Shelf",
    sev: "Low",
    desc: "Trace invasive copepod DNA at detection threshold; single sample only.",
    action: "No action required; retest at next scheduled collection.",
    boundary: false,
  },
];

const ECON = [
  { k: "PROJECT DELAY EXPOSURE", v: "₹4.2 Cr", basis: "Modeled estimate — biodiversity baseline + regional precedent" },
  { k: "COMPLIANCE FINE EXPOSURE", v: "₹1.8 Cr", basis: "Modeled from regional regulatory schedule" },
  { k: "MITIGATION COST RANGE", v: "₹0.3–0.6 Cr", basis: "Modeled estimate — contractor rate card, ±40%" },
];

// Illustrative coordinates in the Bay of Bengal / Andaman Sea -- these plot
// on a real basemap (so panning/zooming lands somewhere geographically
// coherent) but, like the rest of this page, are not real detection sites.
const HOTSPOTS = [
  { name: "Sector 3", sev: "Critical", lat: 15.6, lng: 82.3, desc: "IUCN Red List species DNA detected within an active construction zone." },
  { name: "Sector 7", sev: "High", lat: 18.4, lng: 89.7, desc: "Invasive bivalve DNA signature rising across two consecutive samples." },
  { name: "Estuary N", sev: "Medium", lat: 21.6, lng: 88.2, desc: "Mangrove/seagrass indicator taxa in decline." },
  { name: "Outer Shelf", sev: "Low", lat: 12.4, lng: 93.6, desc: "Trace invasive copepod DNA at detection threshold." },
];

// Illustrative current-flow paths (not measured oceanographic data -- there's
// no live current feed behind this deployment any more than there's a real
// hotspot feed) -- but the *shape* follows the real winter (northeast
// monsoon, Dec-Feb) Indian Ocean circulation, not an arbitrary curve. The
// map's default view centers on the Bay of Bengal (this report's hotspots),
// but it's the same zoomable/pannable map, so the full basin -- Arabian Sea
// through the Bay of Bengal -- is drawn; zooming out (minZoom=3) or panning
// west reveals the rest. Each path is ordered start-to-end in its real flow
// direction, which is what the dash animation's direction is keyed to.
// The basin gyres are drawn as coastal boundary currents above, but a real
// gyre is also a closed circulating loop in the open basin interior (the
// circular-arrow schematic in oceanographic diagrams) -- distinct from any
// one coastal current. This traces that interior loop as an ellipse, swept
// just short of a full 360deg so it still reads as a directed path with a
// start and end rather than a closed shape.
function gyreLoop(centerLat, centerLng, latRadius, lngRadius, steps = 16, sweepDeg = 330) {
  const points = [];
  for (let i = 0; i <= steps; i++) {
    const rad = ((sweepDeg * i) / steps) * (Math.PI / 180);
    points.push([centerLat + latRadius * Math.cos(rad), centerLng + lngRadius * Math.sin(rad)]);
  }
  return points;
}

const CURRENT_PATHS = [
  // -- Bay of Bengal Gyre (clockwise) --
  // East India Coastal Current -- southward along the Indian coast, then a
  // smooth arc (many small angular steps, not a 2-point dip-and-reverse)
  // around Sri Lanka's east coast (island's east side runs up to ~81.9E)
  // down past Dondra Head (the southern tip, ~5.92N/80.6E)
  [[20.5, 87.2], [19, 86.3], [17.7, 84.9], [15.9, 83.5], [13.9, 81.8], [12, 81.1], [10.1, 80.9], [9.8, 82.05], [9, 82.89], [7.9, 83.2], [6.8, 82.89], [6, 82.05], [5.7, 80.9]],
  // Winter Monsoon Current -- westward across the base of the bay, staying
  // well south of Sri Lanka's southern tip the whole way, not just at the end
  [[7.5, 93.5], [7.2, 89], [6.6, 85], [6.1, 82.5], [5.7, 80.9]],
  // Return branch -- northward up the Andaman Sea, kept a full degree or
  // more offshore of the Ayeyarwady delta bulge (Cape Negrais juts out to
  // ~94.2E at 16N) rather than tracking close along the coastline
  [[7.5, 93.8], [9.5, 93.9], [11.8, 94], [14, 93.6], [15.8, 92.7], [17.3, 91.6], [18.8, 90.6], [20, 89.5], [20.4, 87.6]],
  // Interior basin circulation -- clockwise (winter), kept clear of the
  // Indian coast to the west and the Andaman chain to the east
  gyreLoop(11.5, 89.5, 3.6, 3),
  // -- Arabian Sea Gyre (clockwise) --
  // West India Coastal Current -- northward along the Indian coast, kept
  // offshore of Kerala/Konkan/Gujarat
  [[8.3, 76], [10.5, 75.3], [13, 74], [15.5, 73], [17.8, 72.3], [19.5, 71.7], [21, 69.8], [21.7, 68]],
  // North branch -- westward across the Arabian Sea, bowed south to stay
  // well clear of the Yemen coast (Al Mahrah reaches ~54E) before
  // approaching the Horn of Africa from due east of Cape Guardafui
  [[21.7, 68], [19, 63], [17, 59], [15, 56], [13, 53.5], [11.5, 51.8]],
  // Somali Current -- southward along the Somali coast, offset consistently
  // offshore of the real coastline (Cape Guardafui 11.8N/51.3E, Eyl
  // 7.98N/49.8E, Hobyo 5.35N/48.5E, Mogadishu 2.04N/45.3E, Kismayo
  // -0.36N/42.6E) rather than drifting inland between waypoints
  [[11.5, 51.8], [10, 50.9], [8, 50.1], [6, 49], [4.5, 47.7], [3, 46.4], [1.5, 45]],
  // Interior basin circulation -- clockwise (winter), centered in open
  // water clear of both the Indian and Arabian coastlines
  gyreLoop(14, 62, 3.5, 3.5),
  // -- Basin-scale equatorial band --
  // North Equatorial Current -- westward, south of Sri Lanka, ending
  // offshore near the Somali coast (not run all the way inland to it)
  [[6, 80], [6, 73], [6, 67], [6, 61], [5.8, 55], [5.5, 50.2]],
  // South Equatorial Current -- westward, Sumatra to Madagascar
  [[-8, 96], [-8.2, 90], [-8.5, 84], [-9, 78], [-9.3, 72], [-9.6, 66], [-10, 60], [-10, 55], [-11.5, 51.5]],
  // East Madagascar Current -- southward along the *outer* east coast
  // (Sambava 14.27S/50.2E, Toamasina 18.15S/49.4E, Manakara 22.13S/48E,
  // Tolagnaro 25.03S/47E), offset east of each so it runs offshore rather
  // than along the coastline itself
  [[-12, 51.3], [-14.3, 51], [-18.15, 50.2], [-22.13, 48.8], [-25, 47.8], [-26.3, 46.8]],
];

// Named water bodies -- geographic labels, not illustrative/mock data, so
// they don't need the same "not measured" caveat as the hotspots/currents.
// The CARTO basemap already renders its own native label for the Andaman
// Sea at this zoom (visible without any overlay), so it's deliberately
// left out here to avoid a duplicate label in a mismatched style; Bay of
// Bengal and Indian Ocean aren't in the tileset's default label set at
// this zoom, so those two are added, styled to match the basemap's own
// sea-label typography (see .sv-map-waterlabel).
const WATER_BODIES = [
  { name: "Bay of Bengal", lat: 14.8, lng: 87.3 },
  { name: "Indian Ocean", lat: 5.6, lng: 84.5 },
];

// Meters, not pixels (Leaflet's Circle, not CircleMarker) -- a radius of
// approximation is a real geographic extent, so it has to grow and shrink
// on screen the way any map annotation does when you zoom, or it reads as
// inconsistent (the ring visibly "shrinking" as you zoom in and the
// basemap's real features grow around it). The center-dot epicenter below
// is the opposite case: a point has no extent to represent, so it stays a
// fixed small size in pixels at every zoom level instead.
const HOTSPOT_RADIUS_M = { Critical: 22000, High: 16000, Medium: 11000, Low: 7000 };

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
      <span style={{ fontWeight: 600, marginBottom: 2 }}>Hotspot key</span>
      {Object.entries(SEVERITY).map(([label, color]) => (
        <span key={label} style={{ display: "flex", alignItems: "center", gap: 7 }}>
          <span style={{ width: 9, height: 9, borderRadius: 2, background: color }} /> {label}
        </span>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Real interactive Bay of Bengal map (Leaflet, CartoDB dark basemap) -- pan
// and zoom against actual geography rather than a static illustration.
// isolation:"isolate" on the wrapper is load-bearing: Leaflet's own panes and
// controls carry z-index up to 1000, and without a wrapper that establishes
// its own stacking context, that would fight the MapLegend overlay (and
// potentially the app's own fixed-position sidebar/modals) instead of
// staying contained to the map. Rendered fresh in both the inline card and
// the fullscreen modal rather than moved between them, which sidesteps
// Leaflet's stale-container-size problem (map.invalidateSize()) entirely --
// each instance measures its own final container on mount.
// ---------------------------------------------------------------------------
function HotspotMap({ height = 340 }) {
  return (
    <div style={{ position: "relative", width: "100%", height, isolation: "isolate" }}>
      {/* attributionControl={false}: drops the "Leaflet | OpenStreetMap
          contributors | CARTO" badge from both the inline card and the
          fullscreen modal (one shared component, so this fixes both at
          once). Per explicit request -- worth knowing CARTO's free
          no-API-key basemap and OSM's data normally expect attribution to
          stay visible as a condition of free use, so this is a call worth
          revisiting before this ever ships somewhere public. */}
      <MapContainer className="sv-legis-map" center={[16, 88]} zoom={5} minZoom={3} maxZoom={10} scrollWheelZoom attributionControl={false} style={{ width: "100%", height: "100%", background: "#0A1526" }}>
        <TileLayer
          url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
          subdomains="abcd"
          maxZoom={19}
        />
        {WATER_BODIES.map((w) => (
          <CircleMarker key={w.name} center={[w.lat, w.lng]} radius={0} interactive={false} pathOptions={{ stroke: false, fill: false }}>
            <Tooltip className="sv-map-waterlabel" direction="center" permanent>
              {w.name}
            </Tooltip>
          </CircleMarker>
        ))}
        {/* Current flow -- rendered before the hotspots so it paints behind
            them in the shared overlay pane. A steadily flowing dashed line
            marks each path; the origin and destination each get a static
            glow halo plus two staggered water-ripple rings expanding
            outward and fading, like a pebble dropped in water. */}
        {CURRENT_PATHS.map((path, i) => {
          const origin = path[0];
          const dest = path[path.length - 1];
          return (
            <Fragment key={`flow${i}`}>
              <Polyline positions={path} pathOptions={{ className: "sv-current-flow", color: tokens.accentCyan, weight: 1.6, opacity: 0.8 }} />
              {[origin, dest].map((pt, j) => (
                <Fragment key={j}>
                  <CircleMarker center={pt} radius={4} interactive={false} pathOptions={{ className: "sv-current-node-ripple", color: tokens.accentCyan, weight: 0.75, fill: false }} />
                  <CircleMarker center={pt} radius={4} interactive={false} pathOptions={{ className: "sv-current-node-ripple sv-current-node-ripple--b", color: tokens.accentCyan, weight: 0.75, fill: false }} />
                </Fragment>
              ))}
            </Fragment>
          );
        })}
        {HOTSPOTS.map((z, i) => (
          <Fragment key={z.name}>
            {/* Outer ring: radius of approximation, in real meters -- hollow
                (no fill), so it reads as an uncertainty zone rather than a
                filled area, and it genuinely grows/shrinks with zoom like
                any other map geometry. Carries the tooltip/popup; the
                center dot below is purely decorative and non-interactive
                so clicks never double-fire. `sv-scale-in-N` staggers each
                hotspot's entrance (react-leaflet's pathOptions only maps to
                Leaflet's own style properties, not arbitrary CSS like
                animation-delay, so the stagger has to come from a per-index
                class rather than an inline style). */}
            <Circle
              center={[z.lat, z.lng]}
              radius={HOTSPOT_RADIUS_M[z.sev]}
              pathOptions={{ color: SEVERITY[z.sev], weight: 2, fillOpacity: 0, className: `sv-scale-in sv-scale-in-${i}` }}
            >
              <Tooltip className="sv-map-tooltip" direction="top" offset={[0, -14]} opacity={1} permanent>
                {z.name}
              </Tooltip>
              <Popup className="sv-map-popup">
                <strong>{z.name}</strong> · {z.sev}
                <br />
                {z.desc}
              </Popup>
            </Circle>
            {/* Center dot: the epicenter -- the actual detection point the
                ring's approximation radius is drawn around. */}
            <CircleMarker
              center={[z.lat, z.lng]}
              radius={3}
              interactive={false}
              pathOptions={{ color: SEVERITY[z.sev], weight: 0, fillColor: SEVERITY[z.sev], fillOpacity: 1, className: `sv-scale-in sv-scale-in-${i}` }}
            />
          </Fragment>
        ))}
      </MapContainer>
      <MapLegend />
    </div>
  );
}

function IndicatorTrendSVG() {
  const vals = [30, 34, 31, 38, 42, 40, 46, 44, 50, 53, 51, 56];
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const X = (i) => 34 + i * 46;
  const Y = (v) => 130 - v * 1.7;
  const d = vals.map((v, i) => (i ? "L" : "M") + X(i) + " " + Y(v)).join(" ");
  const area = `${d} L${X(11)} 140 L${X(0)} 140 Z`;
  const gridValues = [0, 10, 20, 30, 40, 50, 60];
  const gridX = [X(0) - 23, ...months.map((_, i) => X(i)), X(11) + 23].flatMap((x, i, arr) =>
    i < arr.length - 1 ? [x, (x + arr[i + 1]) / 2] : [x]
  );
  return (
    <svg viewBox="0 0 570 150" style={{ width: "100%", height: "auto", display: "block" }}>
      {gridValues.map((v) => (
        <line key={v} x1={20} y1={Y(v)} x2={556} y2={Y(v)} stroke="#3D4F6E" strokeWidth={1} strokeOpacity={0.9} />
      ))}
      {gridX.map((x, i) => (
        <line key={i} x1={x} y1={Y(0)} x2={x} y2={Y(60)} stroke="#3D4F6E" strokeWidth={1} strokeOpacity={i % 2 ? 0.35 : 0.55} />
      ))}
      <path d={area} className="sv-fade-in-late" fill="rgba(59,158,255,0.10)" />
      <path d={d} pathLength={1} className="sv-draw-path" fill="none" stroke={tokens.accentBlue} strokeWidth={2} strokeLinecap="round" />
      {vals.map((v, i) => <circle key={i} cx={X(i)} cy={Y(v)} r={2.6} className="sv-fade-in-late" fill={tokens.accentCyan} />)}
      {months.map((m, i) => <text key={m} x={X(i)} y={148} fill={tokens.pending} fontSize={9} textAnchor="middle">{m}</text>)}
    </svg>
  );
}

function TaxaDeclineSVG() {
  const data = [
    ["Coral", 18, tokens.danger],
    ["Seagrass", 12, tokens.warningAlt],
    ["Mangrove", 9, tokens.success],
    ["Kelp", 4, tokens.accentBlue],
  ];
  return (
    <svg viewBox="0 0 570 150" style={{ width: "100%", height: "auto", display: "block" }}>
      {data.map(([n, v, c], i) => {
        const y = 14 + i * 33;
        return (
          <g key={n}>
            <text x={0} y={y + 12} fill={tokens.wordmark} fontSize={11}>{n}</text>
            <rect x={80} y={y} width={440} height={16} rx={3} fill="#0A1526" />
            <rect x={80} y={y} width={(440 * v) / 20} height={16} rx={3} className="sv-grow-x" style={{ animationDelay: `${i * 0.1}s` }} fill={c} opacity={0.75} />
            <text x={530} y={y + 12} className="sv-fade-in-late" style={{ animationDelay: `${i * 0.1 + 0.5}s` }} fill={tokens.sectionSubtext} fontSize={10.5}>−{v}%</text>
          </g>
        );
      })}
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

// The map's own accent frame -- the "electric blue" glow language already
// used for focus rings and glowing chrome elsewhere in the app (OxygenGauge's
// drop-shadow, .sv-upload-field:focus's ring) rather than the plain dark
// #101D33 border every other panel uses, so the map itself reads as part of
// this tool rather than a generic embedded widget.
const mapFrameStyle = {
  border: "1px solid rgba(59,158,255,0.45)",
  boxShadow: "0 0 0 1px rgba(59,158,255,0.12), 0 0 32px rgba(59,158,255,0.22)",
};

// Buttons use the app's shared liquid-glass material (styles/liquidGlass.js)
// rather than the flat gradient the original design mockup specified --
// keeps every raised control across the app reading as one system.
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

// Same material, disabled semantics: these correspond to exports this
// deployment has no file to generate (no live regional feed behind the
// map/alerts/economics), so they're visually inert rather than faking a
// download that doesn't exist.
const inertBtnStyle = { ...ghostBtnStyle, opacity: 0.5, cursor: "default" };

const primaryBtnStyle = {
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

export default function Legislative() {
  const [mapOpen, setMapOpen] = useState(false);
  const [alertId, setAlertId] = useState(null);
  const [feas, setFeas] = useState("idle"); // idle | running | done

  const runFeasibility = () => {
    setFeas("running");
    setTimeout(() => setFeas("done"), 1400);
  };

  const activeAlert = ALERTS.find((a) => a.id === alertId);

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
        </div>

        {/* Map + alerts */}
        <div style={{ display: "grid", gridTemplateColumns: "1.5fr 1fr", gap: s(18), alignItems: "start" }}>
          <div style={{ ...cardBase, ...revealStyle(0) }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: s(12), flexWrap: "wrap" }}>
              <span style={{ ...panelLabelStyle, display: "flex", gap: 6 }}>BIODIVERSITY HOTSPOT MAP · BAY OF BENGAL <MockTag /></span>
              <div style={{ display: "flex", gap: s(8) }}>
                <button onClick={() => setMapOpen(true)} style={ghostBtnStyle}>Open Map</button>
                <button style={inertBtnStyle} title="No live regional feed connected yet">Export Region CSV</button>
              </div>
            </div>
            <div style={{ position: "relative", borderRadius: s(6), overflow: "hidden", ...mapFrameStyle }}>
              <HotspotMap height={s(340)} />
            </div>
            <span style={{ fontSize: s(11), color: tokens.pending }}>Zones show drift-diffused detection areas, not exact positions. Flow lines illustrate current direction, not measured data. Pan and zoom the map, or click a marker for detail.</span>
          </div>

          <div style={cardBase}>
            <span style={{ ...panelLabelStyle, display: "flex", gap: 6 }}>ACTIVE ALERTS <MockTag /></span>
            {ALERTS.map((a) => (
              <div
                key={a.id}
                onClick={() => setAlertId(a.id)}
                style={{ display: "flex", flexDirection: "column", gap: s(5), padding: `${s(12)}px ${s(14)}px`, borderRadius: s(6), cursor: "pointer", border: "1px solid #101D33", borderLeft: `3px solid ${SEVERITY[a.sev]}`, background: "rgba(8,14,26,0.55)" }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: s(8) }}>
                  <span style={{ display: "flex", alignItems: "center", gap: s(8), fontSize: s(13), fontWeight: 600 }}>
                    <span style={{ width: s(8), height: s(8), borderRadius: "50%", background: SEVERITY[a.sev], boxShadow: `0 0 8px ${SEVERITY[a.sev]}88` }} />
                    {a.title}
                  </span>
                  <span style={{ fontSize: s(10.5), fontWeight: 600, color: SEVERITY[a.sev] }}>{a.sev}</span>
                </div>
                <span style={{ fontSize: s(12), lineHeight: 1.5, color: tokens.sectionSubtext }}>{a.desc}</span>
                <span style={{ fontSize: s(10.5), color: tokens.pending }}>Detected — genetic trace consistent with presence within the last ~7–14 days</span>
                {a.boundary && (
                  <span style={{ fontSize: s(10.5), color: tokens.warning }}>⚠ Near maritime boundary — origin uncertain due to current drift (spatial uncertainty only)</span>
                )}
              </div>
            ))}
          </div>
        </div>

        {/* Trends */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: s(18) }}>
          <div style={{ ...cardBase, ...revealStyle(1) }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
              <span style={{ ...panelLabelStyle, display: "flex", gap: 6 }}>INDICATOR SPECIES TREND <MockTag /></span>
              <span style={{ fontSize: s(12), fontWeight: 600, color: tokens.success }}>+8% YTD</span>
            </div>
            <span style={{ fontSize: s(10.5), color: tokens.pending }}>Target species DNA presence · as of 15 Aug 2026</span>
            <IndicatorTrendSVG />
          </div>
          <div style={{ ...cardBase, ...revealStyle(2) }}>
            <span style={{ ...panelLabelStyle, display: "flex", gap: 6 }}>HABITAT-ASSOCIATED TAXA DECLINE <MockTag /></span>
            <span style={{ fontSize: s(10.5), color: tokens.pending, lineHeight: 1.5 }}>Decline in DNA signatures associated with vulnerable ecosystems — an early-warning proxy, not a direct habitat measurement · as of 15 Aug 2026</span>
            <TaxaDeclineSVG />
          </div>
        </div>

        {/* Economic risk */}
        <div style={cardBase}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: s(12), flexWrap: "wrap" }}>
            <span style={{ ...panelLabelStyle, display: "flex", gap: 6 }}>ECONOMIC RISK &amp; COMPLIANCE EXPOSURE <MockTag /></span>
            <div style={{ display: "flex", gap: s(8) }}>
              <button onClick={runFeasibility} style={primaryBtnStyle}>
                {feas === "running" ? "Running…" : feas === "done" ? "Feasibility ✓ Re-run" : "Run Feasibility"}
              </button>
              <button style={inertBtnStyle} title="No live regional feed connected yet">Export Report</button>
              <button style={inertBtnStyle} title="No live regional feed connected yet">Export CSV</button>
            </div>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: s(14) }}>
            {ECON.map((e) => (
              <div key={e.k} style={{ display: "flex", flexDirection: "column", gap: s(6), padding: `${s(15)}px ${s(17)}px`, borderRadius: s(6), border: "1px solid #101D33", background: "rgba(8,14,26,0.5)" }}>
                <span style={{ fontSize: s(10.5), letterSpacing: "0.07em", color: tokens.sectionSubtext }}>{e.k}</span>
                <span style={{ fontSize: s(21), fontWeight: 600, letterSpacing: "-0.01em" }}>{e.v}</span>
                <span style={{ fontSize: s(10.5), color: tokens.sectionSubtext, alignSelf: "flex-start" }}>{e.basis}</span>
              </div>
            ))}
          </div>
        </div>

        <div style={{ display: "flex", justifyContent: "center", padding: `${s(8)}px 0 2px`, borderTop: "1px solid #0C1526" }}>
          <span style={{ fontSize: s(11), color: tokens.pending }}>Reference DB: MarineGenomeDB v4.2 · SILVA 16S v138.2 · Pipeline: v2.8.1 · Matched 15 Aug 2026, 09:41 UTC</span>
        </div>
      </div>

      {/* Fullscreen map modal */}
      {mapOpen && (
        <>
          <div onClick={() => setMapOpen(false)} style={{ position: "fixed", inset: 0, background: "rgba(2,4,9,0.75)", backdropFilter: "blur(4px)", zIndex: 40 }} />
          <div style={{ position: "fixed", inset: "5%", zIndex: 41, display: "flex", flexDirection: "column", gap: s(14), padding: `${s(22)}px ${s(26)}px`, borderRadius: s(12), border: "1px solid #1C2E4C", background: "#050912", boxShadow: "0 40px 120px rgba(0,0,0,0.7)" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span style={{ fontSize: s(13), fontWeight: 600, letterSpacing: "0.08em", color: tokens.wordmark }}>BIODIVERSITY HOTSPOT MAP · FULLSCREEN</span>
              <div style={{ display: "flex", gap: s(8) }}>
                <button style={inertBtnStyle} title="No live regional feed connected yet">Export PNG</button>
                <button onClick={() => setMapOpen(false)} style={ghostBtnStyle}>Close ✕</button>
              </div>
            </div>
            <div style={{ flex: 1, minHeight: 0, borderRadius: s(6), overflow: "hidden", ...mapFrameStyle, display: "flex" }}>
              <HotspotMap height="100%" />
            </div>
          </div>
        </>
      )}

      {/* Alert detail modal */}
      {activeAlert && (
        <>
          <div onClick={() => setAlertId(null)} style={{ position: "fixed", inset: 0, background: "rgba(2,4,9,0.7)", backdropFilter: "blur(4px)", zIndex: 40 }} />
          <div style={{ position: "fixed", top: "50%", left: "50%", transform: "translate(-50%,-50%)", width: s(560), maxWidth: "92vw", zIndex: 41, display: "flex", flexDirection: "column", gap: s(16), padding: `${s(24)}px ${s(28)}px`, borderRadius: s(12), border: "1px solid #1C2E4C", background: "#050912", boxShadow: "0 40px 120px rgba(0,0,0,0.7)" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span style={{ display: "flex", alignItems: "center", gap: s(10), fontSize: s(16), fontWeight: 600 }}>
                <span style={{ width: s(10), height: s(10), borderRadius: "50%", background: SEVERITY[activeAlert.sev], boxShadow: `0 0 10px ${SEVERITY[activeAlert.sev]}88` }} />
                {activeAlert.title}
              </span>
              <button onClick={() => setAlertId(null)} style={{ width: s(30), height: s(30), borderRadius: s(8), border: "1px solid #17253D", background: "#080F1C", color: tokens.wordmark, fontSize: s(14), cursor: "pointer" }}>✕</button>
            </div>
            <p style={{ margin: 0, fontSize: s(13), lineHeight: 1.65, color: tokens.wordmark }}>
              {activeAlert.desc} {activeAlert.boundary && "Hotspot sits near a maritime boundary; origin is spatially uncertain due to current drift — this is not a jurisdictional determination."}
            </p>
            <span style={{ fontSize: s(11), color: tokens.pending }}>Detected — genetic trace consistent with presence within the last ~7–14 days.</span>
            <div style={{ padding: `${s(12)}px ${s(15)}px`, borderRadius: s(6), border: "1px solid rgba(59,158,255,0.25)", background: "rgba(20,110,255,0.07)", fontSize: s(12.5), color: "#9FC6F5" }}>
              <span style={{ fontWeight: 600, color: "#6FBAFF" }}>Suggested action:</span> {activeAlert.action}
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: s(8), padding: `${s(14)}px ${s(16)}px`, borderRadius: s(6), border: "1px solid #101D33", background: "rgba(8,14,26,0.5)" }}>
              <span style={{ ...panelLabelStyle, fontSize: s(10.5), display: "flex", gap: 6 }}>CRYPTOGRAPHIC CHAIN OF CUSTODY <MockTag /></span>
              <div style={{ display: "flex", flexDirection: "column", gap: s(5), fontSize: s(11.5), fontFamily: "ui-monospace,monospace", color: tokens.wordmark }}>
                <span>source: stn14_bay-of-bengal_0812.fasta</span>
                <span>uploaded by: M. Fernandes · 2026-08-12 10:02 UTC</span>
                <span style={{ wordBreak: "break-all" }}>sha-256: 9f3a…c41e77b2</span>
                <span style={{ display: "flex", alignItems: "center", gap: s(7), color: tokens.success }}>
                  <CheckCircleIcon size={s(12)} color={tokens.success} /> Hash verified — file unaltered since upload
                </span>
              </div>
            </div>
            <button style={{ ...inertBtnStyle, alignSelf: "flex-start" }} title="No live regional feed connected yet">Generate Alert PDF</button>
          </div>
        </>
      )}
    </div>
  );
}
