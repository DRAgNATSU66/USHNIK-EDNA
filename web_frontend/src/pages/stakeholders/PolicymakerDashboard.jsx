// PolicymakerDashboard.jsx
// Requires: npm install leaflet
// Optional (for map export): npm install dom-to-image-more

import React, { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { Line, Bar } from "react-chartjs-2";
import L from "leaflet";
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  BarElement,
  Title,
  Tooltip,
  Legend,
} from "chart.js";

ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  BarElement,
  Title,
  Tooltip,
  Legend
);

export default function PolicymakerDashboard() {
  const [mapOpen, setMapOpen] = useState(false);
  const [alertsOpen, setAlertsOpen] = useState(false);
  const [feasibilityRunning, setFeasibilityRunning] = useState(false);
  const [feasibilityResult, setFeasibilityResult] = useState(null);

  const sampleCSVRows = [
    ["region", "species_count", "risk_level"],
    ["Sector 1", "54", "Low"],
    ["Sector 2", "12", "High"],
    ["Sector 7", "7", "Critical"],
  ];

  const downloadCSV = (rows, filename = "region_export.csv") => {
    const csv = rows
      .map((r) =>
        r.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(",")
      )
      .join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  };

  // Run a dummy economic feasibility simulation (async fake)
  const runFeasibility = async () => {
    setFeasibilityRunning(true);
    setFeasibilityResult(null);
    await new Promise((r) => setTimeout(r, 1000 + Math.random() * 1200));
    const result = {
      roiPercent: (5 + Math.random() * 18).toFixed(1), // 5 - 23%
      npv: (100000 + Math.random() * 350000).toFixed(0),
      paybackYears: (2 + Math.random() * 6).toFixed(1),
      notes: "Model uses historical biodiversity-economic correlation and conservative ecosystem valuation.",
      timestamp: new Date().toISOString(),
    };
    setFeasibilityResult(result);
    setFeasibilityRunning(false);
  };

  const exportFeasibilityReport = (res) => {
    if (!res) return;
    const blob = new Blob([JSON.stringify(res, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `feasibility_${new Date().toISOString().slice(0,19)}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <>
      <style>{`
:root{
  --primary-blue:#0066ff;
  --secondary-cyan:#00d4ff;
  --marine-green:#00ffaa;
  --accent-green:#00ff88;
  --deep-ocean:#001133;
  --dark-blue:#002266;
  --glass-border:rgba(255,255,255,0.06);
  --text-primary:#eaf6ff;
  --text-muted:#9acfff;
  --gradient-primary:linear-gradient(135deg,var(--primary-blue) 0%,var(--secondary-cyan) 100%);
  --gradient-bg:radial-gradient(ellipse at center,var(--dark-blue) 0%,var(--deep-ocean) 100%);
}

/* Ensure no horizontal scroll and style the global scrollbar */
html, body, #root {
  height: 100%;
  width: 100%;
  margin: 0;
  padding: 0;
  background: var(--gradient-bg);
  color: var(--text-primary);
  font-family: Inter, system-ui, Roboto, "Helvetica Neue", Arial;
  -webkit-font-smoothing: antialiased;
  overflow-x: hidden;
  overflow-y: auto;
}

/* WebKit scrollbar (Chrome/Edge/Opera) */
body::-webkit-scrollbar {
  width: 12px;
  height: 12px;
}
body::-webkit-scrollbar-track {
  background: transparent;
}
body::-webkit-scrollbar-thumb {
  background: linear-gradient(180deg,#00d4ff 0%, #00bfff 100%);
  border-radius: 999px;
  min-height: 44px;
  border: 3px solid rgba(0,0,0,0);
  box-shadow: 0 8px 20px rgba(0,212,255,0.18);
}
body::-webkit-scrollbar-thumb:hover {
  filter: brightness(1.06);
}

/* Firefox scrollbar */
* {
  scrollbar-width: thin;
  scrollbar-color: #00bfff transparent;
}

/* Page root / layout */
.page-root{
  min-height:100vh;
  width:100%;
  padding:28px;
  box-sizing:border-box;
  background:transparent;
  color:var(--text-primary);
  position:relative;
  overflow: visible;
}

/* background canvases */
.bg-canvas {
  position: fixed;
  inset: 0;
  z-index: 0;
  pointer-events: none;
}

/* header + branding */
.header {
  max-width:1300px;
  margin: 0 auto 22px;
  text-align:center;
  position:relative;
  z-index: 6;
}
.brand .logo {
  font-size:clamp(1.6rem,4vw,2.6rem);
  font-weight:800;
  background:var(--gradient-primary);
  -webkit-background-clip:text;
  -webkit-text-fill-color:transparent;
}
.brand .subtitle { color:var(--text-muted); margin-top:6px; font-size:0.95rem; }

/* main grid layout */
.container {
  max-width:1300px;
  margin: 0 auto;
  display:grid;
  grid-template-columns: 1fr 1fr;
  gap:20px;
  z-index: 6;
  align-items:start;
}

/* Trend full width */
.trendFull {
  grid-column: 1 / -1;
}

/* card styles */
.card {
  background: linear-gradient(180deg, rgba(255,255,255,0.02), rgba(255,255,255,0.01));
  border-radius:14px;
  padding:18px;
  border: 1px solid var(--glass-border);
  box-shadow: 0 18px 60px rgba(0,10,30,0.45);
  backdrop-filter: blur(12px) saturate(120%);
}
.card.strong {
  padding:22px;
  border-radius:16px;
  border: 1px solid rgba(255,255,255,0.05);
  box-shadow: 0 26px 90px rgba(0,12,40,0.6);
}

/* sections and helpers */
.sectionTitle { display:flex; align-items:center; justify-content:space-between; margin-bottom:12px; }
.sectionTitle .left { display:flex; gap:12px; align-items:center; }
.sectionTitle h3 { margin:0; font-size:1.05rem; font-weight:700; }
.sectionTitle .sub { color:var(--text-muted); font-size:0.9rem; }

/* placeholders and charts layout */
.mapPlaceholder { height:420px; border-radius:10px; border: 1px dashed rgba(255,255,255,0.03); display:flex; align-items:center; justify-content:center; color:var(--text-muted); position:relative; overflow:hidden; }
.trendGrid { display:flex; gap:12px; align-items:flex-start; margin-bottom:12px; }
.statTile { flex: 0 0 48%; background: rgba(0,0,0,0.04); padding:12px; border-radius:10px; border:1px solid rgba(255,255,255,0.02); }
.stat { font-weight:800; font-size:1.4rem; background: var(--gradient-primary); -webkit-background-clip:text; -webkit-text-fill-color:transparent; }
.statLabel { color:var(--text-muted); font-size:0.92rem; margin-top:6px; }

.trendCharts { display:flex; gap:14px; width:100%; margin-top:10px; }
.trendCharts .chartCard { flex:1; background: rgba(0,0,0,0.03); border-radius:10px; padding:12px; min-height:220px; }

.feasibilityKpis { display:flex; gap:12px; }
.kpi { flex:1; padding:12px; border-radius:10px; background:rgba(0,0,0,0.03); border:1px solid rgba(255,255,255,0.02); text-align:center; }
.kpi .big { font-weight:900; font-size:1.4rem; color:var(--marine-green); }

.controls { display:flex; gap:10px; justify-content:flex-end; margin-top:12px; }
.btn { padding:10px 14px; border-radius:10px; border:none; cursor:pointer; font-weight:700; }
.btn.primary { background:var(--gradient-primary); color:white; box-shadow:0 12px 40px rgba(0,102,255,0.16); }
.btn.ghost { background:transparent; color:var(--text-muted); border:1px solid rgba(255,255,255,0.03); }

.modal-backdrop { position:fixed; inset:0; background:rgba(2,8,18,0.6); display:flex; align-items:center; justify-content:center; z-index:40; }
.modal { width:calc(100% - 64px); max-width:1000px; background:linear-gradient(180deg, rgba(255,255,255,0.03), rgba(255,255,255,0.02)); border-radius:12px; padding:20px; border:1px solid var(--glass-border); box-shadow:0 30px 80px rgba(0,10,30,0.6); max-height:90vh; overflow:auto; }

/* Leaflet container styling (keeps theme) */
.leaflet-container {
  width: 100%;
  height: 100%;
  border-radius: 10px;
  filter: drop-shadow(0 6px 18px rgba(0,102,255,0.06));
}
/* small map inside card */
.map-small { height: 420px; width: 100%; border-radius: 10px; }
/* large map in modal */
.map-large { height: 60vh; width: 100%; border-radius: 10px; }

/* DARK tiles should match the UI — no hue-rotate here (we use dark tiles) */

/* hollow marker style is stroke-only (circleMarker uses stroke color) */
/* tooltip and popup readability — styled to match site card theme */
.leaflet-tooltip.map-tooltip {
  background: linear-gradient(135deg, rgba(0,48,90,0.95), rgba(0,64,130,0.95)) !important;
  color: #ffffff !important;
  border-radius: 10px !important;
  box-shadow: 0 18px 60px rgba(0,10,30,0.6) !important;
  padding: 10px 12px !important;
  font-weight: 800 !important;
  font-size: 13px !important;
  opacity: 0.99 !important;
  line-height: 1.2 !important;
  border: 1px solid rgba(0,212,255,0.12) !important;
}
.leaflet-popup-content-wrapper.map-popup {
  background: linear-gradient(135deg, rgba(0,102,255,0.95), rgba(0,212,255,0.95)) !important;
  color: #ffffff !important;
  border-radius: 10px !important;
  padding: 12px !important;
  box-shadow: 0 22px 80px rgba(0,12,40,0.66) !important;
  border: 1px solid rgba(255,255,255,0.06) !important;
}
.leaflet-popup-content {
  color: #ffffff !important;
  font-weight: 800;
  font-size: 13px;
}

/* 'Indian Ocean' label styling */
.ocean-label {
  font-weight: 800;
  font-size: 18px;
  color: rgba(234,246,255,0.18);
  text-shadow: 0 3px 10px rgba(0,0,0,0.55);
  pointer-events: none;
  transform: translate(-50%, -50%);
}

/* map legend */
.map-legend {
  background: rgba(0,5,18,0.55);
  padding: 8px 10px;
  border-radius: 8px;
  color: var(--text-primary);
  font-size: 13px;
  border: 1px solid rgba(255,255,255,0.03);
}
.map-legend .row { display:flex; align-items:center; gap:8px; margin-bottom:6px; }
.map-legend .swatch { width:12px; height:12px; border-radius:3px; box-shadow: 0 6px 18px rgba(0,102,255,0.06); border:1px solid rgba(255,255,255,0.06); }

@media (max-width: 1100px) {
  .trendCharts { flex-direction:column; }
}
@media (max-width: 980px) {
  .container { grid-template-columns: 1fr; }
  .mapPlaceholder { height:300px; }
}
      `}</style>

      <div className="page-root">
        {/* Background components (particles + orbital) */}
        <FloatingBackgroundCanvas />
        <BackgroundOrbitalCanvas />

        <header className="header">
          <div className="brand" aria-hidden>
            <div className="logo">eDNA Biodiversity Analyzer</div>
            <div className="subtitle">Policymaker • Regional biodiversity & policy</div>
          </div>
        </header>

        <main className="container" role="main">
          {/* LEFT column -> Top: Map card */}
          <div>
            {/* Map card */}
            <section className="card strong" aria-labelledby="map-title">
              <div className="sectionTitle">
                <div className="left">
                  <h3 id="map-title">Biodiversity Hotspot Map</h3>
                  <div className="sub">interactive map & regional overlays</div>
                </div>
                <div style={{ display: "flex", gap: 8 }}>
                  <button className="btn primary" onClick={() => setMapOpen(true)}>Open Map</button>
                  <button className="btn ghost" onClick={() => downloadCSV(sampleCSVRows, "regions.csv")}>Export Region CSV</button>
                </div>
              </div>

              <div className="mapPlaceholder">
                {/* Small embedded map */}
                <MapComponent smallKey="card-map" small={true} />
              </div>
            </section>
          </div>

          {/* RIGHT column -> Top: Economic Feasibility (replaces orbital card) ; Below: Threat & Alert Panel */}
          <div>
            {/* Economic Feasibility card */}
            <section className="card strong" aria-labelledby="econ-title">
              <div className="sectionTitle">
                <div className="left">
                  <h3 id="econ-title">Economic Feasibility</h3>
                  <div className="sub">Assess project viability & ecosystem valuations</div>
                </div>
                <div style={{ color: "var(--text-muted)" }}>model preview</div>
              </div>

              <div style={{ display: "grid", gap: 12 }}>
                <div className="feasibilityKpis">
                  <div className="kpi">
                    <div style={{ color: "var(--text-muted)", fontSize: 12 }}>Estimated ROI</div>
                    <div className="big">{feasibilityResult ? `${feasibilityResult.roiPercent}%` : "—"}</div>
                  </div>
                  <div className="kpi">
                    <div style={{ color: "var(--text-muted)", fontSize: 12 }}>NPV (USD)</div>
                    <div className="big">{feasibilityResult ? `$${Number(feasibilityResult.npv).toLocaleString()}` : "—"}</div>
                  </div>
                </div>

                <div style={{ display: "flex", gap: 12 }}>
                  <button
                    className="btn primary"
                    onClick={runFeasibility}
                    disabled={feasibilityRunning}
                    aria-busy={feasibilityRunning}
                    title="Run a feasibility estimate"
                  >
                    {feasibilityRunning ? "Running..." : "Run Feasibility"}
                  </button>

                  <button
                    className="btn ghost"
                    onClick={() => exportFeasibilityReport(feasibilityResult)}
                    disabled={!feasibilityResult}
                  >
                    Export Report
                  </button>

                  <button
                    className="btn ghost"
                    onClick={() => {
                      const rows = [
                        ["metric", "value"],
                        ["estimated_roi_percent", feasibilityResult?.roiPercent ?? "n/a"],
                        ["npv_usd", feasibilityResult?.npv ?? "n/a"],
                        ["payback_years", feasibilityResult?.paybackYears ?? "n/a"],
                      ];
                      downloadCSV(rows, "feasibility_summary.csv");
                    }}
                  >
                    Export CSV
                  </button>
                </div>

                <div style={{ marginTop: 8, color: "var(--text-muted)", fontSize: 13 }}>
                  {feasibilityResult ? (
                    <>
                      <div style={{ marginBottom: 6 }}>
                        <strong>Notes:</strong> {feasibilityResult.notes}
                      </div>
                      <div style={{ fontSize: 12 }}>Last run: {new Date(feasibilityResult.timestamp).toLocaleString()}</div>
                    </>
                  ) : (
                    <div>Click <em>Run Feasibility</em> to compute an estimate based on current assumptions.</div>
                  )}
                </div>
              </div>
            </section>

            {/* Threats & Alerts card below */}
            <section className="card strong" style={{ marginTop: 18 }} aria-labelledby="alerts-title">
              <div className="sectionTitle">
                <div className="left">
                  <h3 id="alerts-title">Threat & Alert Panel</h3>
                  <div className="sub">Active incidents, severity & recommended actions</div>
                </div>

                <div>
                  <button className="btn primary" onClick={() => setAlertsOpen(true)}>Open Alerts</button>
                </div>
              </div>

              <div style={{ display: "grid", gap: 10 }}>
                <AlertRow title="Coastal Erosion" desc="High risk near Sector 7" severity="HIGH" color="#ffcf33" />
                <AlertRow title="Invasive Species" desc="Monitoring required" severity="MED" color="#00ff88" />
                <AlertRow title="Pollution Spike" desc="Recent high readings" severity="LOW" color="#66d2ff" />
              </div>
            </section>
          </div>

          {/* FULL-WIDTH Trend Graphs */}
          <section className="card trendFull" aria-labelledby="trends-title" style={{ marginTop: 18 }}>
            <div className="sectionTitle">
              <div className="left">
                <h3 id="trends-title">Trend Graphs</h3>
                <div className="sub">Species & habitat trends — time series</div>
              </div>
              <div style={{ color: "var(--text-muted)" }}>live sample</div>
            </div>

            <div className="trendGrid">
              <div className="statTile">
                <div className="stat">+8%</div>
                <div className="statLabel">Species Increase (year)</div>
              </div>
              <div className="statTile">
                <div className="stat">-12%</div>
                <div className="statLabel">Habitat Loss (year)</div>
              </div>
            </div>

            <div className="trendCharts" style={{ marginTop: 6 }}>
              <div className="chartCard">
                <div style={{ height: 260 }}>
                  <LineChart />
                </div>
              </div>
              <div className="chartCard">
                <div style={{ height: 260 }}>
                  <BarChart />
                </div>
              </div>
            </div>
          </section>
        </main>

        {/* Map modal */}
        {mapOpen && (
          <div className="modal-backdrop" role="dialog" aria-modal="true">
            <div className="modal">
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
                <h3 style={{ margin: 0 }}>Map Viewer</h3>
                <div style={{ display: "flex", gap: 8 }}>
                  <button className="btn ghost" onClick={() => downloadCSV(sampleCSVRows, "map-region.csv")}>Export CSV</button>
                  {/* Export PNG using dynamic import of dom-to-image-more */}
                  <MapExportButton />
                  <button className="btn primary" onClick={() => setMapOpen(false)}>Close</button>
                </div>
              </div>

              <div style={{ height: "60vh", borderRadius: 10, border: "1px dashed rgba(255,255,255,0.03)", display: "flex", alignItems: "center", justifyContent: "center", color: "var(--text-muted)" }}>
                <MapComponent smallKey="modal-map" small={false} />
              </div>
            </div>
          </div>
        )}

        {/* Alerts modal */}
        {alertsOpen && (
          <div className="modal-backdrop" role="dialog" aria-modal="true">
            <div className="modal">
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
                <h3 style={{ margin: 0 }}>Active Alerts</h3>
                <button className="btn primary" onClick={() => setAlertsOpen(false)}>Close</button>
              </div>

              <div style={{ display: "grid", gap: 12 }}>
                <div style={{ padding: 12, borderRadius: 10, background: "rgba(0,0,0,0.04)" }}>
                  <strong>Coastal Erosion — Sector 7</strong>
                  <div style={{ color: "var(--text-muted)" }}>Suggested action: temporary barrier + habitat restoration</div>
                </div>

                <div style={{ padding: 12, borderRadius: 10, background: "rgba(0,0,0,0.03)" }}>
                  <strong>Invasive Species — Sector 3</strong>
                  <div style={{ color: "var(--text-muted)" }}>Suggested action: field survey and sample removal</div>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </>
  );

  // Small inline components ------------------------------------------------
  function AlertRow({ title, desc, severity, color }) {
    return (
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10 }}>
        <div>
          <div style={{ fontWeight: 800 }}>{title}</div>
          <div style={{ color: "var(--text-muted)" }}>{desc}</div>
        </div>
        <div style={{ textAlign: "right" }}>
          <div style={{ fontWeight: 800, color }}>{severity}</div>
          <div style={{ color: "var(--text-muted)" }}>priority</div>
        </div>
      </div>
    );
  }
}

/* ---------------------------- Charts ------------------------------------ */

function LineChart() {
  const cyan = "#00d4ff";
  const data = {
    labels: ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul"],
    datasets: [
      {
        label: "Species Observed",
        data: [22, 25, 28, 30, 34, 38, 42],
        fill: false,
        tension: 0.35,
        borderWidth: 2.6,
        borderColor: cyan,
        pointBackgroundColor: "#001f33",
        pointBorderColor: cyan,
        pointBorderWidth: 2,
        pointRadius: 5,
        pointHoverRadius: 7,
        backgroundColor: "rgba(0,212,255,0.06)",
      },
    ],
  };

  const options = {
    responsive: true,
    plugins: {
      legend: { display: false },
      tooltip: { mode: "index", intersect: false },
    },
    scales: {
      x: {
        grid: { display: false, color: "rgba(255,255,255,0.02)" },
        ticks: { color: "#9acfff", font: { size: 12 } },
      },
      y: {
        grid: { color: "rgba(255,255,255,0.04)" },
        ticks: { color: "#9acfff", font: { size: 12 }, beginAtZero: false },
      },
    },
    elements: {
      line: { capBezierPoints: true },
    },
  };

  return <Line data={data} options={options} />;
}

function BarChart() {
  const data = {
    labels: ["Coral", "Seagrass", "Mangrove", "Kelp"],
    datasets: [
      {
        label: "Habitat Cover (%)",
        data: [32, 18, 14, 10],
        backgroundColor: [
          "rgba(0,255,170,0.95)",
          "rgba(0,200,170,0.85)",
          "rgba(0,160,200,0.78)",
          "rgba(0,120,200,0.6)",
        ],
        borderWidth: 0,
      },
    ],
  };

  const options = {
    responsive: true,
    plugins: { legend: { display: false } },
    scales: {
      x: { ticks: { color: "#9acfff" }, grid: { display: false } },
      y: { ticks: { color: "#9acfff" }, grid: { color: "rgba(255,255,255,0.03)" } },
    },
  };

  return <Bar data={data} options={options} />;
}

/* ------------------- Floating Background Canvas (Three.js) --------------- */
function FloatingBackgroundCanvas(props) {
  const ref = useRef();

  useEffect(() => {
    const canvas = document.createElement("canvas");
    canvas.style.width = "100%";
    canvas.style.height = "100%";
    canvas.style.position = "fixed";
    canvas.style.inset = "0";
    canvas.style.zIndex = 0;
    canvas.style.pointerEvents = "none";
    if (ref.current) ref.current.appendChild(canvas);

    const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.setClearColor(0x000000, 0);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(50, window.innerWidth / window.innerHeight, 0.1, 1000);
    camera.position.z = 50;

    const COUNT = 900;
    const positions = new Float32Array(COUNT * 3);
    const velocities = new Float32Array(COUNT * 3);
    const spreadX = 160;
    const spreadY = 90;
    const spreadZ = 80;

    for (let i = 0; i < COUNT; i++) {
      positions[i * 3 + 0] = (Math.random() - 0.5) * spreadX;
      positions[i * 3 + 1] = (Math.random() - 0.5) * spreadY;
      positions[i * 3 + 2] = (Math.random() - 0.5) * spreadZ;

      velocities[i * 3 + 0] = (Math.random() - 0.5) * 0.02;
      velocities[i * 3 + 1] = (Math.random() - 0.5) * 0.01;
      velocities[i * 3 + 2] = (Math.random() - 0.5) * 0.02;
    }

    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));

    const material = new THREE.PointsMaterial({
      size: 1.1,
      color: 0x00ffaa,
      transparent: true,
      opacity: 0.07,
      depthTest: false,
      blending: THREE.AdditiveBlending,
    });

    const pts = new THREE.Points(geometry, material);
    scene.add(pts);

    let rafId;
    const start = performance.now();
    const loop = (now) => {
      const t = (now - start) / 1000;

      const posArr = geometry.attributes.position.array;
      for (let i = 0; i < COUNT; i++) {
        const idx = i * 3;
        posArr[idx] += velocities[idx] * (1 + 0.5 * Math.sin(t * 0.2 + i));
        posArr[idx + 1] += velocities[idx + 1] * (1 + 0.4 * Math.cos(t * 0.15 + i * 0.3));
        posArr[idx + 2] += velocities[idx + 2] * (1 + 0.6 * Math.sin(t * 0.18 + i * 0.7));

        if (posArr[idx] > spreadX / 2) posArr[idx] = -spreadX / 2;
        if (posArr[idx] < -spreadX / 2) posArr[idx] = spreadX / 2;
        if (posArr[idx + 1] > spreadY / 2) posArr[idx + 1] = -spreadY / 2;
        if (posArr[idx + 1] < -spreadY / 2) posArr[idx + 1] = spreadY / 2;
        if (posArr[idx + 2] > spreadZ / 2) posArr[idx + 2] = -spreadZ / 2;
        if (posArr[idx + 2] < -spreadZ / 2) posArr[idx + 2] = spreadZ / 2;
      }
      geometry.attributes.position.needsUpdate = true;

      pts.rotation.y = Math.sin(t * 0.06) * 0.08;
      pts.rotation.x = Math.cos(t * 0.03) * 0.03;

      renderer.render(scene, camera);
      rafId = requestAnimationFrame(loop);
    };
    rafId = requestAnimationFrame(loop);

    const onResize = () => {
      renderer.setSize(window.innerWidth, window.innerHeight);
      camera.aspect = window.innerWidth / window.innerHeight;
      camera.updateProjectionMatrix();
    };
    window.addEventListener("resize", onResize);

    return () => {
      window.removeEventListener("resize", onResize);
      cancelAnimationFrame(rafId);
      try {
        geometry.dispose();
        material.dispose();
        renderer.dispose();
      } catch (e) {}
      if (ref.current) ref.current.removeChild(canvas);
    };
  }, []);

  return <div ref={ref} className="bg-canvas" {...props} />;
}

/* ---------------------- Background Orbital (Three.js) ------------------- */
function BackgroundOrbitalCanvas(props) {
  const ref = useRef();

  useEffect(() => {
    const canvas = document.createElement("canvas");
    canvas.style.width = "100%";
    canvas.style.height = "100%";
    canvas.style.position = "fixed";
    canvas.style.inset = "0";
    canvas.style.zIndex = 0;
    canvas.style.pointerEvents = "none";
    if (ref.current) ref.current.appendChild(canvas);

    const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.setClearColor(0x000000, 0);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(50, window.innerWidth / window.innerHeight, 0.1, 2000);
    camera.position.set(0, 0, 8);

    const amb = new THREE.AmbientLight(0xffffff, 0.25);
    const dir = new THREE.DirectionalLight(0xffffff, 0.2);
    dir.position.set(5, 10, 7);
    scene.add(amb, dir);

    const root = new THREE.Group();
    scene.add(root);

    // central dotted sphere
    const centralCount = 700;
    const centralPos = new Float32Array(centralCount * 3);
    const radius = 1.6;
    for (let i = 0; i < centralCount; i++) {
      const phi = Math.acos(1 - 2 * (i + 0.5) / centralCount);
      const theta = Math.PI * (1 + Math.sqrt(5)) * (i + 0.5);
      const x = Math.sin(phi) * Math.cos(theta);
      const y = Math.sin(phi) * Math.sin(theta);
      const z = Math.cos(phi);
      centralPos[i * 3 + 0] = x * radius;
      centralPos[i * 3 + 1] = y * radius;
      centralPos[i * 3 + 2] = z * radius;
    }
    const centralGeo = new THREE.BufferGeometry();
    centralGeo.setAttribute("position", new THREE.BufferAttribute(centralPos, 3));
    const centralMat = new THREE.PointsMaterial({
      size: 0.04,
      color: 0x00ffaa,
      transparent: true,
      opacity: 0.6,
      depthTest: false,
      blending: THREE.AdditiveBlending,
      sizeAttenuation: true,
    });
    const centralPoints = new THREE.Points(centralGeo, centralMat);
    root.add(centralPoints);

    // orbit helper creation
    const makeOrbitDots = (numDots = 120, r = 2.6, axis = "y", tilt = 0) => {
      const pos = new Float32Array(numDots * 3);
      for (let i = 0; i < numDots; i++) {
        const t = (i / numDots) * Math.PI * 2;
        const x = Math.cos(t) * r;
        const y = Math.sin(t) * r;
        const z = 0;
        pos[i * 3 + 0] = x;
        pos[i * 3 + 1] = y;
        pos[i * 3 + 2] = z;
      }
      const geo = new THREE.BufferGeometry();
      geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
      const mat = new THREE.PointsMaterial({
        size: 0.03,
        color: 0x00ffaa,
        transparent: true,
        opacity: 0.65,
        depthTest: false,
        blending: THREE.AdditiveBlending,
        sizeAttenuation: true,
      });
      const mesh = new THREE.Points(geo, mat);
      if (axis === "x") mesh.rotation.z = Math.PI / 2;
      if (axis === "diag1") mesh.rotation.set(0.38, 0.32, 0);
      if (axis === "diag2") mesh.rotation.set(-0.38, 0.32, 0);
      if (tilt) mesh.rotation.x = tilt;
      return { mesh, geo, mat };
    };

    const orbitH = makeOrbitDots(160, 3.1, "y");
    const orbitV = makeOrbitDots(120, 2.6, "x");
    const orbitD1 = makeOrbitDots(120, 3.0, "diag1");
    const orbitD2 = makeOrbitDots(120, 2.8, "diag2");

    root.add(orbitH.mesh, orbitV.mesh, orbitD1.mesh, orbitD2.mesh);

    // subtle animation and twinkle
    let rafId = null;
    const start = performance.now();
    const animate = (now) => {
      const t = (now - start) / 1000;

      root.rotation.y = Math.sin(t * 0.08) * 0.06;
      root.rotation.x = Math.cos(t * 0.03) * 0.02;

      orbitH.mesh.rotation.y += 0.0055;
      orbitV.mesh.rotation.x += 0.0062;
      orbitD1.mesh.rotation.z += 0.0048;
      orbitD2.mesh.rotation.z -= 0.0053;

      // twinkle central (subtle)
      const positions = centralGeo.attributes.position.array;
      for (let i = 0; i < centralCount; i++) {
        const idx = i * 3;
        const px = positions[idx];
        const py = positions[idx + 1];
        const pz = positions[idx + 2];
        const m = 1 + 0.01 * Math.sin(t * 2.6 + i * 0.07);
        positions[idx] = px * m;
        positions[idx + 1] = py * m;
        positions[idx + 2] = pz * m;
      }
      centralGeo.attributes.position.needsUpdate = true;

      renderer.render(scene, camera);
      rafId = requestAnimationFrame(animate);
    };
    rafId = requestAnimationFrame(animate);

    const onResize = () => {
      renderer.setSize(window.innerWidth, window.innerHeight);
      camera.aspect = window.innerWidth / window.innerHeight;
      camera.updateProjectionMatrix();
    };
    window.addEventListener("resize", onResize);

    return () => {
      cancelAnimationFrame(rafId);
      window.removeEventListener("resize", onResize);
      try {
        centralGeo.dispose();
        centralMat.dispose();
        orbitH.geo.dispose();
        orbitH.mat.dispose();
        orbitV.geo.dispose();
        orbitV.mat.dispose();
        orbitD1.geo.dispose();
        orbitD1.mat.dispose();
        orbitD2.geo.dispose();
        orbitD2.mat.dispose();
        renderer.dispose();
      } catch (e) {}
      if (ref.current) ref.current.removeChild(canvas);
    };
  }, []);

  return <div ref={ref} className="bg-canvas" {...props} />;
}

/* ---------------------------- Map Component ----------------------------- */
/*
  - smallKey: unique id for container DOM element
  - small: boolean -> renders smaller interactive map (for card) or larger (for modal)
*/
function MapComponent({ smallKey = "map", small = true }) {
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const legendControlRef = useRef(null);

  // hotspots sample for Indian Ocean region (lat, lng ~ [lat, lon])
  const hotspots = [
    {
      id: "sri-lanka",
      name: "Sri Lanka Coastal Shelf",
      coords: [6.9, 79.9],
      species_count: 54,
      risk: "High",
      info: "Multiple coral and seagrass hotspots; local pollution pressures.",
    },
    {
      id: "andaman",
      name: "Andaman & Nicobar",
      coords: [10.5, 92.7],
      species_count: 72,
      risk: "Critical",
      info: "High biodiversity; invasive species monitoring needed.",
    },
    {
      id: "maldives",
      name: "Maldives Atolls",
      coords: [3.2, 73.2],
      species_count: 38,
      risk: "Medium",
      info: "Coral bleaching susceptibility; active restoration sites.",
    },
    {
      id: "lakshadweep",
      name: "Lakshadweep",
      coords: [10.5, 72.6],
      species_count: 28,
      risk: "Low",
      info: "Protected zones present; monitoring ongoing.",
    },
    {
      id: "bay-of-bengal",
      name: "Bay of Bengal Offshore",
      coords: [10.0, 85.0],
      species_count: 19,
      risk: "High",
      info: "Shipping/pollution corridor; watch-listed species present.",
    },
  ];

  // risk color map (uses same palette present in page)
  const riskColor = {
    Critical: "#ff6b6b", // neon red-ish
    High: "#ffcf33",
    Medium: "var(--accent-green)",
    MediumAlt: "#00ff88",
    Low: "#66d2ff",
  };

  // ensure leaflet CSS exists (inject if not)
  useEffect(() => {
    const checkAndInject = () => {
      const href = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";
      const exists = Array.from(document.styleSheets).some((s) => (s.href || "").includes("leaflet"));
      if (!exists) {
        const link = document.createElement("link");
        link.rel = "stylesheet";
        link.href = href;
        link.crossOrigin = "";
        document.head.appendChild(link);
      }
    };
    checkAndInject();
  }, []);

  useEffect(() => {
    // create map if not present
    const el = containerRef.current;
    if (!el) return;
    // avoid re-init
    if (mapRef.current) {
      setTimeout(() => mapRef.current.invalidateSize(), 200);
      return;
    }

    // center over Indian Ocean / Indian subcontinent region
    const center = [7.5, 82.5];
    const initialZoom = small ? 4.4 : 5.2;

    const map = L.map(el, {
      center,
      zoom: initialZoom,
      minZoom: 3,
      maxZoom: 13,
      zoomControl: true,
      attributionControl: false,
      preferCanvas: true,
    });
    mapRef.current = map;

    // DARK themed tile layer (Carto dark_all)
    const tileUrl = "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png";
    const tileLayer = L.tileLayer(tileUrl, {
      maxZoom: 19,
    }).addTo(map);

    // Add 'Indian Ocean' label as non-interactive DivIcon (position approximated)
    // coordinates chosen to appear roughly center-south of India
    const oceanLabel = L.marker([6.5, 80.5], {
      interactive: false,
      icon: L.divIcon({
        className: "ocean-label",
        html: "Indian Ocean",
        iconSize: [160, 30],
      }),
    }).addTo(map);

    // Add hollow circle markers (stroke only). radius scaled by species_count.
    hotspots.forEach((h) => {
      const cs = getComputedStyle(document.documentElement);
      const accentGreen = cs.getPropertyValue("--accent-green").trim() || "#00ff88";

      const color =
        h.risk === "Critical" ? riskColor.Critical :
        h.risk === "High" ? riskColor.High :
        h.risk === "Medium" ? (accentGreen || riskColor.MediumAlt) :
        riskColor.Low;

      const radius = Math.max(6, Math.min(20, Math.round(4 + Math.log(h.species_count + 1) * 4)));

      // hollow: stroke-only circleMarker
      const circle = L.circleMarker(h.coords, {
        radius,
        color: color,         // stroke color
        weight: 2.8,
        fill: false,          // <-- no fill to create hollow marker
        fillOpacity: 0,
        opacity: 0.96,
      }).addTo(map);

      // hover interaction: thicker stroke on mouseover for emphasis
      circle.on("mouseover", function () {
        this.setStyle({ weight: 4.6 });
        this.openTooltip();
      });
      circle.on("mouseout", function () {
        this.setStyle({ weight: 2.8 });
        this.closeTooltip();
      });

      // styled tooltip / popup (one-liner on hover)
      const html = `
        <div style="font-weight:800;color:#ffffff;margin-bottom:6px;">${h.name}</div>
        <div style="color:rgba(234,246,255,0.85);font-size:13px;">Species: ${h.species_count} • Risk: ${h.risk}</div>
        <div style="color:rgba(234,246,255,0.82);font-size:12px;margin-top:6px;">${h.info}</div>
      `;
      circle.bindTooltip(html, {
        direction: "top",
        offset: [0, -8],
        opacity: 0.99,
        permanent: false,
        className: "map-tooltip",
      });

      // popup on click with themed class
      circle.on("click", () => {
        L.popup({ closeButton: true, autoClose: true, className: "map-popup" })
          .setLatLng(h.coords)
          .setContent(`<div style="font-weight:900">${h.name}</div><div style="color:rgba(234,246,255,0.92);font-size:13px;margin-top:6px;">Species: ${h.species_count} • Risk: ${h.risk}</div><div style="color:rgba(234,246,255,0.9);font-size:12px;margin-top:8px;">${h.info}</div>`)
          .openOn(map);
      });
    });

    // custom legend control
    const legend = L.control({ position: small ? "bottomleft" : "bottomright" });
    legend.onAdd = function () {
      const div = L.DomUtil.create("div", "map-legend");
      div.innerHTML = `
        <div style="font-weight:800;margin-bottom:6px;">Hotspot key</div>
        <div class="row"><div class="swatch" style="background:${riskColor.Critical}"></div><div style="color:var(--text-muted);font-size:13px;">Critical</div></div>
        <div class="row"><div class="swatch" style="background:${riskColor.High}"></div><div style="color:var(--text-muted);font-size:13px;">High</div></div>
        <div class="row"><div class="swatch" style="background:var(--accent-green)"></div><div style="color:var(--text-muted);font-size:13px;">Medium</div></div>
        <div class="row"><div class="swatch" style="background:${riskColor.Low}"></div><div style="color:var(--text-muted);font-size:13px;">Low</div></div>
      `;
      return div;
    };
    legend.addTo(map);
    legendControlRef.current = legend;

    // ensure size invalidation responsiveness
    const onResize = () => {
      try { map.invalidateSize(); } catch (e) {}
    };
    window.addEventListener("resize", onResize);

    // fit to markers nicely at mount
    const markerLatLngs = hotspots.map((h) => h.coords);
    if (markerLatLngs.length) {
      const bounds = L.latLngBounds(markerLatLngs);
      map.fitBounds(bounds.pad(0.6), { maxZoom: small ? 7 : 9, animate: true });
    }

    return () => {
      window.removeEventListener("resize", onResize);
      try {
        if (legend) map.removeControl(legend);
        tileLayer.remove();
        oceanLabel.remove();
        map.off();
        map.remove();
        mapRef.current = null;
      } catch (e) {}
    };
  }, [small]);

  // ensure map redraw if container size changes (e.g. modal open)
  useEffect(() => {
    const t = setTimeout(() => {
      if (mapRef.current) mapRef.current.invalidateSize();
    }, 300);
    return () => clearTimeout(t);
  }, [smallKey]);

  return (
    <div
      id={smallKey}
      ref={containerRef}
      className={small ? "map-small leaflet-container" : "map-large leaflet-container"}
      aria-label="Indian Ocean biodiversity hotspot map"
    />
  );
}

/* -------------------- Map Export Button (dynamic) ----------------------- */
function MapExportButton() {
  const handleExport = async () => {
    // find the modal map container if present, else card map
    const el = document.querySelector(".map-large") || document.querySelector(".map-small");
    if (!el) {
      alert("Map element not found for export.");
      return;
    }

    try {
      // dynamic import to avoid hard dependency if not installed
      const domtoimage = await import("dom-to-image-more");
      const dataUrl = await domtoimage.toPng(el, {
        bgcolor: "#001426",
        style: {
          transform: "scale(1)",
          transformOrigin: "top left",
        },
      });
      const a = document.createElement("a");
      a.href = dataUrl;
      a.download = `hotspot_map_${new Date().toISOString().slice(0,19)}.png`;
      a.click();
    } catch (err) {
      console.warn("Export failed (dom-to-image-more missing?)", err);
      alert("Map export requires 'dom-to-image-more'. Install it: npm install dom-to-image-more\nOr open / right-click & screenshot as a fallback.");
    }
  };

  return (
    <button className="btn ghost" onClick={handleExport} title="Export map view to PNG">
      Export PNG
    </button>
  );
}
