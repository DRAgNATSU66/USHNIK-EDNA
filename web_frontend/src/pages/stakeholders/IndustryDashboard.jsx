// IndustryDashboard.jsx
import React, { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import Chart from "chart.js/auto";
import { Pie, Radar } from "react-chartjs-2";

export default function IndustryDashboard() {
  const [viewerOpen, setViewerOpen] = useState(false);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  const sampleCSVRows = [
    ["metric", "value"],
    ["compliance_incidents", "3"],
    ["avg_impact_score", "7.2"],
    ["last_audit", "2025-08-20"],
  ];

  const downloadCSV = (rows, filename = "industry_export.csv") => {
    const csv = rows
      .map((r) => r.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(","))
      .join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  };

  /* --- Chart data (sample) --- */
  const pieData = {
    labels: ["Efficiency Gain", "Emission Reduction", "Other Impact"],
    datasets: [
      {
        data: [18, 12, 70],
        backgroundColor: ["#00ffaa", "#00d4ff", "#0066ff"],
        borderColor: "rgba(255,255,255,0.02)",
        borderWidth: 1,
      },
    ],
  };
  const pieOptions = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { position: "bottom" },
    },
  };

  /* ---------- UPDATED RADAR: white lines & text for visibility ---------- */
  const radarData = {
    labels: [
      "Operational Costs",
      "Regulatory Fines",
      "Biodiversity Value",
      "Market Volatility",
      "Supply Disruption",
    ],
    datasets: [
      {
        label: "Risk Sensitivity",
        data: [65, 55, 70, 50, 45],
        fill: true,
        backgroundColor: "rgba(0,170,140,0.12)", // keep faint fill
        borderColor: "#ffffff",                    // white outline for clarity
        borderWidth: 2.5,                          // slightly thicker line
        pointBackgroundColor: "#00ffaa",
        pointBorderColor: "#ffffff",
        pointRadius: 4,
        pointHoverRadius: 6,
      },
    ],
  };

  const radarOptions = {
    responsive: true,
    maintainAspectRatio: false,
    scales: {
      r: {
        suggestedMin: 0,
        suggestedMax: 100,
        // grid and angle lines subtle but white-tinged
        grid: { color: "rgba(255,255,255,0.06)" },
        angleLines: { color: "rgba(255,255,255,0.06)" },
        // axis labels around the radar (the category names)
        pointLabels: {
          color: "#ffffff",
          font: { family: "'Inter', system-ui, Roboto, Arial", size: 12, weight: "600" },
        },
        // tick labels (radial values)
        ticks: {
          color: "#ffffff",
          backdropColor: "transparent",
          showLabelBackdrop: false,
          stepSize: 20,
          z: 2,
        },
      },
    },
    plugins: {
      legend: { display: false },
      tooltip: {
        titleColor: "#ffffff",
        bodyColor: "#ffffff",
        backgroundColor: "rgba(0,0,0,0.7)",
      },
    },
    elements: {
      line: {
        tension: 0.1,
      },
    },
  };
  /* --------------------------------------------------------------------- */

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
  --glass-border:rgba(0,150,255,0.14);
  --text-primary:#f4fdff;
  --text-muted:#9acfff;
  --gradient-primary:linear-gradient(135deg,var(--primary-blue) 0%,var(--secondary-cyan) 100%);
  --gradient-bg:radial-gradient(ellipse at center,var(--dark-blue) 0%,var(--deep-ocean) 100%);
}

/* Put the page background on the document root so canvases can sit above it */
html, body {
  height: 100%;
  margin: 0;
  background: var(--gradient-bg);
}

/* Page root should be transparent so canvases (which are in body) can show */
.page-root{
  min-height:100vh;
  width:100%;
  padding:28px;
  box-sizing:border-box;
  background: transparent; /* transparent so canvases are visible */
  color:var(--text-primary);
  font-family: Inter, system-ui, Roboto, "Helvetica Neue", Arial;
  position:relative;
  overflow:auto;
  z-index: 30; /* UI stack above canvases */
}

/* Background canvases (sit between page background and UI) */
.bg-canvas { position: fixed; inset: 0; z-index: 20; pointer-events: none; }

/* header */
.header {
  max-width:1300px;
  margin: 0 auto 18px;
  text-align:center;
  position:relative;
  z-index: 70;
}
.brand .logo {
  font-size:clamp(1.6rem,4vw,2.6rem);
  font-weight:800;
  background:var(--gradient-primary);
  -webkit-background-clip:text;
  -webkit-text-fill-color:transparent;
}
.brand .subtitle { color:var(--text-muted); margin-top:6px; font-size:0.95rem; }

/* layout grid - symmetric two-column with consistent rows */
.container {
  max-width:1300px;
  margin: 0 auto;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap:20px;
  z-index: 70; /* above canvases */
  align-items: start;
  grid-auto-rows: minmax(260px, auto);
  position: relative;
}

/* bluish glass card — stronger blur, more opaque but still hazy */
.card {
  position: relative;
  z-index: 80; /* ensure cards always above background canvases */
  background: linear-gradient(180deg, rgba(0,40,100,0.38), rgba(0,20,60,0.30)); /* bluish haze */
  border-radius:14px;
  padding:18px;
  border: 1px solid var(--glass-border);
  box-shadow: 0 18px 60px rgba(0,8,28,0.6);
  backdrop-filter: blur(20px) saturate(130%);
  -webkit-backdrop-filter: blur(20px) saturate(130%);
  display:flex;
  flex-direction:column;
  justify-content:space-between;
  color: var(--text-primary);
  -webkit-font-smoothing:antialiased;
  -moz-osx-font-smoothing:grayscale;
}

/* stronger card - used for larger panels */
.card.strong {
  padding:22px;
  border-radius:16px;
  border: 1px solid rgba(0,150,255,0.18);
  box-shadow: 0 26px 100px rgba(0,10,30,0.65);
  min-height: 420px;
}

/* non-strong cards baseline min-height */
.card:not(.strong) {
  min-height: 260px;
}

/* small header row for sections */
.sectionTitle { display:flex; align-items:center; justify-content:space-between; margin-bottom:12px; }
.sectionTitle .left { display:flex; gap:12px; align-items:center; }
.sectionTitle h3 { margin:0; font-size:1.05rem; font-weight:800; color: #ffffff; }
.sectionTitle .sub { color:var(--text-muted); font-size:0.9rem; }

/* KPI row / tiles */
.kpiRow { display:flex; gap:12px; margin-bottom:12px; flex-wrap:wrap; }
.kpi { flex:1; padding:12px; border-radius:10px; background: rgba(0,0,0,0.06); border:1px solid rgba(255,255,255,0.03); text-align:center; min-width:130px; }
.kpi .value { font-weight:900; font-size:1.4rem; color:var(--marine-green); }
.kpi .label { color:var(--text-muted); font-size:0.9rem; margin-top:6px; }

/* placeholders */
.placeholder {
  height: 220px;
  border-radius: 12px;
  border: 1px dashed rgba(255,255,255,0.03);
  display:flex;
  align-items:center;
  justify-content:center;
  color:var(--text-muted);
  background: linear-gradient(180deg, rgba(0,0,0,0.03), rgba(0,0,0,0.02));
}

/* compliance table */
.complianceTable { width:100%; border-collapse:collapse; font-size:0.95rem; margin-top:10px; color: var(--text-primary); }
.complianceTable th, .complianceTable td { padding:10px 12px; border-bottom:1px solid rgba(255,255,255,0.04); color: var(--text-primary); }
.complianceTable thead th { text-align:left; font-weight:800; background: linear-gradient(90deg, rgba(0,102,255,0.12), rgba(0,212,255,0.06)); color:var(--text-primary); border-bottom:2px solid rgba(0,170,140,0.12); }
.complianceTable tbody tr:hover { background: linear-gradient(90deg, rgba(0,102,255,0.02), rgba(0,212,255,0.01)); }
.complianceLink { color: var(--secondary-cyan); text-decoration: none; font-weight:800; }

/* controls */
.controls { display:flex; gap:10px; margin-top:6px; flex-wrap:wrap; }
.btn { padding:10px 14px; border-radius:10px; border:none; cursor:pointer; font-weight:700; }
.btn.primary { background:var(--gradient-primary); color:white; box-shadow:0 12px 40px rgba(0,102,255,0.16); }
.btn.ghost { background:transparent; color:var(--text-muted); border:1px solid rgba(255,255,255,0.03); }

/* operational notes list */
.opNotes { display:flex; flex-direction:column; gap:8px; }
.opNotes a { color: var(--marine-green); font-weight:700; text-decoration:none; }
.opNoteItem { background: linear-gradient(180deg, rgba(255,255,255,0.02), rgba(255,255,255,0.01)); padding:10px; border-radius:8px; border:1px solid rgba(255,255,255,0.03); color: var(--text-primary); }

/* responsive */
@media (max-width: 980px) {
  .container { grid-template-columns: 1fr; }
  .card.strong { min-height: auto; }
}
      `}</style>

      {/* Background canvases: Floating particles + decorative orbital (both pointer-events:none) */}
      <FloatingBackgroundCanvas className="bg-canvas" />
      <BackgroundOrbitalCanvas className="bg-canvas" />

      <div className="page-root">
        <header className="header" aria-hidden>
          <div className="brand">
            <div className="logo">eDNA Biodiversity Analyzer</div>
            <div className="subtitle">Industry • Compliance & impact monitoring</div>
          </div>
        </header>

        <main className="container" role="main">
          {/* Left column: Compliance Panel (top-left) */}
          <section className="card strong" aria-labelledby="compliance-title">
            <div className="sectionTitle">
              <div className="left">
                <h3 id="compliance-title">Compliance Panel</h3>
                <div className="sub">Regulatory checks & incident log</div>
              </div>

              <div style={{ display: "flex", gap: 8 }}>
                <button className="btn primary" onClick={() => downloadCSV(sampleCSVRows, "compliance.csv")}>Export CSV</button>
                <button className="btn ghost" onClick={() => alert("Open Compliance Viewer (placeholder)")}>Open Viewer</button>
              </div>
            </div>

            <div style={{ display: "grid", gap: 12 }}>
              <div className="kpiRow">
                <div className="kpi">
                  <div className="value">3</div>
                  <div className="label">Active Incidents</div>
                </div>
                <div className="kpi">
                  <div className="value">7.2</div>
                  <div className="label">Avg Impact Score</div>
                </div>
                <div className="kpi">
                  <div className="value">4</div>
                  <div className="label">Pending Audits</div>
                </div>
              </div>

              {/* compliance table rendered with electric-blue theme */}
              <div style={{ overflowX: "auto" }}>
                <table className="complianceTable" role="table" aria-label="Compliance summary">
                  <thead>
                    <tr>
                      <th>Metric</th>
                      <th>Value</th>
                      <th>Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sampleCSVRows.slice(1).map((row, i) => (
                      <tr key={i}>
                        <td style={{ textTransform: "capitalize" }}>{row[0].replace(/_/g, " ")}</td>
                        <td>{row[1]}</td>
                        <td>
                          <a
                            className="complianceLink"
                            href="#"
                            onClick={(e) => {
                              e.preventDefault();
                              alert(`Open details for ${row[0]}`);
                            }}
                          >
                            View
                          </a>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </section>

          {/* Right column: Economic Risk Dashboard (top-right) */}
          <section className="card strong" aria-labelledby="risk-title">
            <div className="sectionTitle">
              <div className="left">
                <h3 id="risk-title">Economic Risk Dashboard</h3>
                <div className="sub">Risk curves & sensitivity</div>
              </div>

              <div>
                <button className="btn ghost" onClick={() => downloadCSV(sampleCSVRows, "risk_report.csv")}>Export Report</button>
              </div>
            </div>

            <div style={{ display: "grid", gap: 12 }}>
              <div style={{ height: 260 }}>
                {mounted ? (
                  <Radar data={radarData} options={radarOptions} />
                ) : (
                  <div className="placeholder">Loading chart…</div>
                )}
              </div>

              <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
                <div style={{ flex: 1 }}>
                  <div style={{ fontWeight: 800, color: "#ffffff" }}>Key Drivers</div>
                  <div style={{ color: "var(--text-muted)" }}>Operational costs, regulatory fines, biodiversity value</div>
                </div>

                <div style={{ width: 160 }}>
                  <div style={{ fontWeight: 700, fontSize: 20, color: "var(--marine-green)" }}>Medium</div>
                  <div style={{ color: "var(--text-muted)", fontSize: 12 }}>Overall Risk</div>
                </div>
              </div>
            </div>
          </section>

          {/* Left column bottom: Resource Impact (bottom-left) */}
          <section className="card" style={{ marginTop: 0 }} aria-labelledby="resources-title">
            <div className="sectionTitle">
              <div className="left">
                <h3 id="resources-title">Resource Impact Metrics</h3>
                <div className="sub">KPI cards & trend snapshots</div>
              </div>
              <div style={{ color: "var(--text-muted)" }}>overview</div>
            </div>

            <div style={{ display: "grid", gap: 12 }}>
              <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
                <div className="kpi">
                  <div className="value">18%</div>
                  <div className="label">Efficiency Gain</div>
                </div>
                <div className="kpi">
                  <div className="value">12%</div>
                  <div className="label">Emission Reduction</div>
                </div>
                <div className="kpi">
                  <div className="value">4</div>
                  <div className="label">Pending Audits</div>
                </div>
              </div>

              {/* Pie chart placed here (uses Chart.js via react-chartjs-2) */}
              <div style={{ height: 260 }}>
                {mounted ? (
                  <Pie data={pieData} options={pieOptions} />
                ) : (
                  <div className="placeholder">Loading chart…</div>
                )}
              </div>
            </div>
          </section>

          {/* Right column bottom: Operational Summary (bottom-right) */}
          <section className="card" style={{ marginTop: 0 }} aria-labelledby="summary-title">
            <div className="sectionTitle">
              <div className="left">
                <h3 id="summary-title">Operational Summary</h3>
                <div className="sub">Short actions & notes</div>
              </div>
              <div style={{ color: "var(--text-muted)" }}>live</div>
            </div>

            <div style={{ display: "grid", gap: 12 }}>
              <div style={{ display: "flex", gap: 12 }}>
                <div style={{ flex: 1 }}>
                  <div style={{ fontWeight: 800, color: "#ffffff" }}>Last Audit</div>
                  <div style={{ color: "var(--text-muted)" }}>2025-08-20 — minor non-compliance resolved</div>
                </div>

                <div style={{ width: 140, textAlign: "center" }}>
                  <button className="btn primary" onClick={() => alert("Schedule Audit (placeholder)")}>Schedule Audit</button>
                </div>
              </div>

              {/* operational notes with links and quick actions */}
              <div className="opNotes">
                <div className="opNoteItem">
                  <div style={{ fontWeight: 800 }}>Action: Submit remediation plan</div>
                  <div style={{ color: "var(--text-muted)", marginTop: 6 }}>Owner: Environmental Team — Due: 2025-10-10</div>
                  <div style={{ marginTop: 8 }}>
                    <a href="#" onClick={(e) => { e.preventDefault(); alert("Open remediation plan (placeholder)"); }}>Open remediation plan</a>
                  </div>
                </div>

                <div className="opNoteItem">
                  <div style={{ fontWeight: 800 }}>Document: Audit report (Aug 2025)</div>
                  <div style={{ color: "var(--text-muted)", marginTop: 6 }}>Link to PDF and internal notes</div>
                  <div style={{ marginTop: 8 }}>
                    <a href="/docs/audit-2025-08.pdf" className="complianceLink">Download audit-2025-08.pdf</a>
                  </div>
                </div>

                <div className="opNoteItem">
                  <div style={{ fontWeight: 800 }}>Quick Notes</div>
                  <ul style={{ marginTop: 8 }}>
                    <li style={{ color: "var(--text-muted)" }}>Check chain-of-custody logs for sample batch #A21</li>
                    <li style={{ color: "var(--text-muted)" }}>Confirm mitigation budget allocation</li>
                    <li style={{ color: "var(--text-muted)" }}>Schedule stakeholder briefing — add to calendar</li>
                  </ul>
                </div>
              </div>
            </div>
          </section>
        </main>

        {/* optional modal skeleton */}
        {viewerOpen && (
          <div className="modal-backdrop" role="dialog" aria-modal="true" style={{ zIndex: 95, background: "rgba(0,6,18,0.75)" }}>
            <div style={{ width: "min(1200px, 96%)", height: "min(880px, 92%)", borderRadius: 12, padding: 12, background: "linear-gradient(180deg, rgba(255,255,255,0.03), rgba(255,255,255,0.02))", border: "1px solid var(--glass-border)" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                <h3 style={{ margin: 0 }}>Full Viewer</h3>
                <div style={{ display: "flex", gap: 8 }}>
                  <button className="btn ghost" onClick={() => setViewerOpen(false)}>Close</button>
                </div>
              </div>

              <div style={{ height: "calc(100% - 44px)", borderRadius: 8, overflow: "hidden", border: "1px dashed rgba(255,255,255,0.03)", display: "flex", alignItems: "center", justifyContent: "center" }}>
                <div style={{ color: "var(--text-muted)" }}>Full viewer placeholder</div>
              </div>
            </div>
          </div>
        )}
      </div>
    </>
  );
}

/* ------------------- Floating Background Canvas (Three.js) --------------- */
/* Marine-green glowing particles with drifting velocities for organic motion */
function FloatingBackgroundCanvas(props) {
  useEffect(() => {
    const canvas = document.createElement("canvas");
    canvas.style.width = "100%";
    canvas.style.height = "100%";
    canvas.style.position = "fixed";
    canvas.style.inset = "0";
    // put background canvases above the page background but under the UI
    canvas.style.zIndex = "20";
    canvas.style.pointerEvents = "none";
    canvas.setAttribute("data-bg", "floating-particles");
    document.body.appendChild(canvas);

    const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.setClearColor(0x000000, 0);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(50, window.innerWidth / window.innerHeight, 0.1, 1000);
    camera.position.z = 50;

    // particle field
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

    // particles slightly more visible
    const material = new THREE.PointsMaterial({
      size: 1.65,
      color: 0x00ffaa,
      transparent: true,
      opacity: 0.0525,
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
      if (canvas && canvas.parentNode) canvas.parentNode.removeChild(canvas);
    };
  }, []);

  return null;
}

/* ---------------------- Background Orbital (Three.js) ------------------- */
function BackgroundOrbitalCanvas(props) {
  useEffect(() => {
    const canvas = document.createElement("canvas");
    canvas.style.width = "100%";
    canvas.style.height = "100%";
    canvas.style.position = "fixed";
    canvas.style.inset = "0";
    canvas.style.zIndex = "20";
    canvas.style.pointerEvents = "none";
    canvas.setAttribute("data-bg", "orbital");
    document.body.appendChild(canvas);

    const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.setClearColor(0x000000, 0);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(50, window.innerWidth / window.innerHeight, 0.1, 2000);
    camera.position.set(0, 0, 8);

    const amb = new THREE.AmbientLight(0xffffff, 0.16);
    const dir = new THREE.DirectionalLight(0xffffff, 0.10);
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
      size: 0.06,
      color: 0x00ffaa,
      transparent: true,
      opacity: 0.27,
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
        pos[i * 3 + 0] = x;
        pos[i * 3 + 1] = y;
        pos[i * 3 + 2] = 0;
      }
      const geo = new THREE.BufferGeometry();
      geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
      const mat = new THREE.PointsMaterial({
        size: 0.045,
        color: 0x00ffaa,
        transparent: true,
        opacity: 0.15,
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

      const positions = centralGeo.attributes.position.array;
      for (let i = 0; i < centralCount; i++) {
        const idx = i * 3;
        const m = 1 + 0.004 * Math.sin(t * 2.6 + i * 0.07);
        positions[idx] = positions[idx] * m;
        positions[idx + 1] = positions[idx + 1] * m;
        positions[idx + 2] = positions[idx + 2] * m;
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
      if (canvas && canvas.parentNode) canvas.parentNode.removeChild(canvas);
    };
  }, []);

  return null;
}
