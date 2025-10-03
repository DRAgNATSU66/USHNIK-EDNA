// PolicymakerDashboard.jsx
import React, { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { Line, Bar } from "react-chartjs-2";
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
  --marine-green:#00ffaa; /* marine green accent */
  --accent-green:#00ff88;
  --deep-ocean:#001133;   /* matches your earlier theme */
  --dark-blue:#002266;    /* matches earlier theme */
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
  overflow-x: hidden; /* remove horizontal scroll */
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
  background:transparent; /* gradient is on body */
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
.mapPlaceholder { height:420px; border-radius:10px; border: 1px dashed rgba(255,255,255,0.03); display:flex; align-items:center; justify-content:center; color:var(--text-muted); }
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
                <div style={{ textAlign: "center" }}>
                  <div style={{ fontWeight: 800, marginBottom: 6 }}>Map Placeholder</div>
                  <div style={{ color: "var(--text-muted)" }}>Integrate Mapbox / Leaflet here</div>
                </div>
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
                  <button className="btn primary" onClick={() => setMapOpen(false)}>Close</button>
                </div>
              </div>

              <div style={{ height: "60vh", borderRadius: 10, border: "1px dashed rgba(255,255,255,0.03)", display: "flex", alignItems: "center", justifyContent: "center", color: "var(--text-muted)" }}>
                Replace with full map integration (Mapbox / Leaflet)
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
