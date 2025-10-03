// ResearcherDashboard.jsx
import React, { useEffect, useState } from "react";
import * as THREE from "three";
import { Chart as ChartJS, BarElement, CategoryScale, LinearScale, PointElement, LineElement, Tooltip, Legend } from "chart.js";
import { Bar } from "react-chartjs-2";
ChartJS.register(BarElement, CategoryScale, LinearScale, PointElement, LineElement, Tooltip, Legend);

export default function ResearcherDashboard() {
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  // sample data for DNA matches and novel species (placeholders)
  const sampleMatches = [
    { sample: "A21", match: "Species X", score: 0.98 },
    { sample: "B13", match: "Species Y", score: 0.85 },
    { sample: "C07", match: "Unknown", score: 0.42 },
  ];

  const sampleNovels = [
    { id: "NV-001", name: "Candidate sp. 1", location: "Site A" },
    { id: "NV-002", name: "Candidate sp. 2", location: "Site C" },
  ];

  /* ---------------- Histogram (bars) with Line overlay ---------------- */
  const labels = ["Species Richness", "Evenness", "Coverage", "Novelty Index", "Genetic Diversity"];
  const barValues = [72, 58, 81, 46, 69];
  const lineValues = [68, 60, 79, 50, 71];

  const comboData = {
    labels,
    datasets: [
      {
        type: "bar",
        label: "Metric (histogram)",
        data: barValues,
        backgroundColor: ["#0066ff", "#00d4ff", "#00ffaa", "#00ffaa", "#0066ff"],
        borderColor: "rgba(255,255,255,0.06)",
        borderWidth: 1,
        barPercentage: 0.64,
        categoryPercentage: 0.66,
        order: 1,
      },
      {
        type: "line",
        label: "Trend",
        data: lineValues,
        borderColor: "#00d4ff",
        backgroundColor: "transparent",
        borderWidth: 2.6,
        tension: 0.22,
        pointBackgroundColor: "#00d4ff",
        pointBorderColor: "#ffffff",
        pointRadius: 6,
        pointBorderWidth: 2,
        pointHoverRadius: 7,
        order: 3,
      },
    ],
  };

  const comboOptions = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { display: false },
      tooltip: {
        titleColor: "#ffffff",
        bodyColor: "#ffffff",
        backgroundColor: "rgba(0,0,0,0.72)",
      },
    },
    scales: {
      x: {
        ticks: {
          color: "#ffffff",
          maxRotation: 0,
          minRotation: 0,
          autoSkip: false,
        },
        grid: { display: false },
      },
      y: {
        ticks: { color: "#ffffff", beginAtZero: true, stepSize: 20 },
        grid: { color: "rgba(255,255,255,0.06)" },
      },
    },
    elements: {
      point: {
        hoverBorderWidth: 2,
      },
    },
  };
  /* ------------------------------------------------------------------- */

  return (
    <>
      <style>{`
:root{
  --primary-blue:#0066ff;
  --secondary-cyan:#00d4ff;
  --marine-green:#00ffaa;
  --deep-ocean:#001133;
  --dark-blue:#002266;
  --glass-border:rgba(0,150,255,0.14);
  --text-primary:#f4fdff;
  --text-muted:#9acfff;
  --gradient-primary:linear-gradient(135deg,var(--primary-blue) 0%,var(--secondary-cyan) 100%);
  --gradient-bg:radial-gradient(ellipse at center,var(--dark-blue) 0%,var(--deep-ocean) 100%);
}

/* Remove horizontal page scroll and style the page scrollbar (Chromium/Opera) */
html, body, #root {
  height: 100%;
  width: 100%;
  margin: 0;
  padding: 0;
  overflow-y: auto;    /* vertical allowed */
  overflow-x: hidden;  /* remove horizontal scroll */
  background: var(--gradient-bg);
  color: var(--text-primary);
  font-family: Inter, system-ui, Roboto, "Helvetica Neue", Arial;
  -webkit-font-smoothing:antialiased;
}

/* Page-level scrollbar styling (Chromium/WebKit) */
body::-webkit-scrollbar {
  width: 14px;
  height: 14px;
  background: transparent;
}
body::-webkit-scrollbar-track {
  background: transparent;
  margin: 6px 0;
}
body::-webkit-scrollbar-corner {
  background: transparent;
}
body::-webkit-scrollbar-thumb {
  background: linear-gradient(180deg,#00d4ff 0%, #00f4ff 48%, #00bfff 100%);
  border-radius: 999px;
  min-height: 44px;
  box-shadow: 0 0 22px rgba(0,212,255,0.45);
  border: 3px solid rgba(0,0,0,0);
}
body::-webkit-scrollbar-thumb:hover {
  filter: brightness(1.06);
}

/* Firefox fallback */
body {
  scrollbar-width: thin;
  scrollbar-color: rgba(0,212,255,0.95) transparent;
}

/* page UI */
.page-root{
  min-height:100vh;
  width:100%;
  padding:28px;
  box-sizing:border-box;
  background: transparent;
  color:var(--text-primary);
  position:relative;
  z-index: 30;
}

/* canvases inserted into body */
.bg-canvas { position: fixed; inset: 0; z-index: 20; pointer-events: none; width:100%; height:100%; }

/* layout */
.page-inner { max-width: 1300px; margin: 0 auto; }
.header { text-align:center; margin-bottom:20px; }
.header .logo { font-size: clamp(1.8rem, 3.2vw, 2.6rem); font-weight:800; background:var(--gradient-primary); -webkit-background-clip:text; -webkit-text-fill-color:transparent; }
.header .subtitle { color:var(--text-muted); margin-top:6px; }

.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; align-items: stretch; grid-auto-rows: auto; }
@media (max-width: 980px) { .grid { grid-template-columns: 1fr; } }

.card {
  position: relative; z-index: 50;
  background: linear-gradient(180deg, rgba(0,40,100,0.40), rgba(0,20,60,0.32));
  border-radius: 14px; padding: 18px; border: 1px solid var(--glass-border);
  box-shadow: 0 18px 60px rgba(0,8,28,0.6);
  backdrop-filter: blur(20px) saturate(130%); -webkit-backdrop-filter: blur(20px) saturate(130%);
  color: var(--text-primary); display:flex; flex-direction:column; gap:12px; min-height: 320px;
}

.full-span { grid-column: 1 / -1; min-height: 360px; }

/* tables & lists */
.matchTable { width:100%; border-collapse:collapse; font-size:0.95rem; margin-top:6px; color:var(--text-primary); }
.matchTable th, .matchTable td { padding:10px 8px; border-bottom:1px solid rgba(255,255,255,0.04); text-align:left; }
.matchTable thead th { color:var(--text-primary); font-weight:700; background: linear-gradient(90deg, rgba(0,102,255,0.06), rgba(0,212,255,0.03)); }

.novelItem { padding:12px; border-radius:10px; background: linear-gradient(180deg, rgba(255,255,255,0.01), rgba(255,255,255,0.005)); border:1px solid rgba(255,255,255,0.03); color:var(--text-primary); }
.kpiRow { display:flex; gap:12px; flex-wrap:wrap; }
.kpi { flex:1; min-width:110px; text-align:center; padding:12px; border-radius:10px; background: rgba(255,255,255,0.02); border:1px solid rgba(255,255,255,0.03); }
.kpi .value { font-size:1.4rem; font-weight:900; color:var(--marine-green); }
.kpi .label { color:var(--text-muted); font-size:0.9rem; margin-top:6px; }

.controls { display:flex; gap:8px; align-items:center; }
.btn { padding:8px 12px; border-radius:8px; border:none; font-weight:700; cursor:pointer; }
.btn.primary { background:var(--gradient-primary); color:#fff; box-shadow: 0 10px 30px rgba(0,102,255,0.12); }
.btn.ghost { background:transparent; color:var(--text-muted); border:1px solid rgba(255,255,255,0.04); }

/* Keep internal overflow-x on tables but let that scrollbar use inner styling (unchanged) */
.table-wrapper { overflow-x: auto; }
.table-wrapper::-webkit-scrollbar { height: 10px; }
.table-wrapper::-webkit-scrollbar-thumb { background: linear-gradient(180deg,#0066ff,#00d4ff); border-radius:8px; }
      `}</style>

      {/* Three.js backgrounds */}
      <FloatingBackgroundCanvas />
      <BackgroundOrbitalCanvas />

      <div className="page-root">
        <div className="page-inner">
          <header className="header" aria-hidden>
            <div className="logo">eDNA Biodiversity Analyzer</div>
            <div className="subtitle">Researcher • DNA & biodiversity analysis</div>
          </header>

          <div className="grid" role="main" aria-label="Researcher dashboard grid">
            {/* Top-left: DNA Match Results */}
            <section className="card" aria-labelledby="dna-match-title">
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <div>
                  <h3 id="dna-match-title">DNA Match Results</h3>
                  <div className="sub">Recent sequencing sample matches</div>
                </div>
                <div style={{ color: "var(--text-muted)", fontSize: 13 }}>live</div>
              </div>

              <div style={{ display: "grid", gap: 12 }}>
                <div className="kpiRow">
                  <div className="kpi"><div className="value">124</div><div className="label">Active Samples</div></div>
                  <div className="kpi"><div className="value">8</div><div className="label">Novel Candidates</div></div>
                  <div className="kpi"><div className="value">98%</div><div className="label">Avg Match Confidence</div></div>
                </div>

                <div className="table-wrapper" style={{ marginTop: 6 }}>
                  <table className="matchTable" role="table" aria-label="DNA match table">
                    <thead>
                      <tr><th>Sample</th><th>Match</th><th>Score</th></tr>
                    </thead>
                    <tbody>
                      {sampleMatches.map((r, i) => (
                        <tr key={i}>
                          <td>{r.sample}</td>
                          <td style={{ textTransform: "capitalize" }}>{r.match}</td>
                          <td style={{ color: "var(--marine-green)", fontWeight: 800 }}>{(r.score*100).toFixed(0)}%</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </section>

            {/* Top-right: Novel Species */}
            <section className="card" aria-labelledby="novel-title">
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <div>
                  <h3 id="novel-title">Novel Species</h3>
                  <div className="sub">Candidate novel sequences</div>
                </div>
                <div style={{ color: "var(--text-muted)", fontSize: 13 }}>review</div>
              </div>

              <div style={{ display: "grid", gap: 12 }}>
                {sampleNovels.map((n) => (
                  <div key={n.id} className="novelItem">
                    <div style={{ fontWeight: 800 }}>{n.name} <span style={{ color: "var(--text-muted)", fontWeight: 600, fontSize: 12 }}> — {n.id}</span></div>
                    <div style={{ color: "var(--text-muted)", marginTop: 6 }}>{n.location}</div>
                  </div>
                ))}

                {sampleNovels.length === 0 && <div style={{ color: "var(--text-muted)" }}>No candidates</div>}
              </div>
            </section>

            {/* Bottom: Biodiversity Metrics */}
            <section className="card full-span" aria-labelledby="biodiv-title">
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <div>
                  <h3 id="biodiv-title">Biodiversity Metrics</h3>
                  <div className="sub">Summary metrics & trends</div>
                </div>

                <div className="controls">
                  <button className="btn primary">Export CSV</button>
                  <button className="btn ghost">Refresh</button>
                </div>
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "1fr 360px", gap: 12, marginTop: 8 }}>
                <div style={{ padding: 8 }}>
                  {mounted ? <div style={{ height: 260 }}><Bar data={comboData} options={comboOptions} /></div> : <div className="sub">Loading chart…</div>}
                </div>

                <div style={{ padding: 12 }}>
                  <div style={{ fontWeight: 800, marginBottom: 6 }}>Quick Insights</div>
                  <div style={{ color: "var(--text-muted)", marginBottom: 10 }}>Species Coverage is high; Novelty index suggests promising targets for follow-up sampling.</div>

                  <div style={{ marginTop: 12 }}>
                    <div style={{ fontWeight: 800 }}>Top Species</div>
                    <ul style={{ marginTop: 8 }}>
                      <li style={{ color: "var(--text-muted)" }}>Species A — dominant in Tidepool samples</li>
                      <li style={{ color: "var(--text-muted)" }}>Species B — localized to wetland sites</li>
                      <li style={{ color: "var(--text-muted)" }}>Candidate sp. 1 — requires phylogenetic check</li>
                    </ul>
                  </div>
                </div>
              </div>
            </section>
          </div>
        </div>
      </div>
    </>
  );
}

/* ------------------- Floating Background Canvas (Three.js) --------------- */
function FloatingBackgroundCanvas() {
  useEffect(() => {
    const canvas = document.createElement("canvas");
    canvas.style.width = "100%";
    canvas.style.height = "100%";
    canvas.style.position = "fixed";
    canvas.style.inset = "0";
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

    const COUNT = 750;
    const positions = new Float32Array(COUNT * 3);
    const velocities = new Float32Array(COUNT * 3);
    const spreadX = 160, spreadY = 90, spreadZ = 80;
    for (let i = 0; i < COUNT; i++) {
      positions[i * 3 + 0] = (Math.random() - 0.5) * spreadX;
      positions[i * 3 + 1] = (Math.random() - 0.5) * spreadY;
      positions[i * 3 + 2] = (Math.random() - 0.5) * spreadZ;

      velocities[i * 3 + 0] = (Math.random() - 0.5) * 0.02;
      velocities[i * 3 + 1] = (Math.random() - 0.5) * 0.01;
      velocities[i * 3 + 2] = (Math.random() - 0.5) * 0.02;
    }

    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(positions, 3));

    const mat = new THREE.PointsMaterial({
      size: 1.4,
      color: 0x00ffaa,
      transparent: true,
      opacity: 0.045,
      depthTest: false,
      blending: THREE.AdditiveBlending,
    });

    const pts = new THREE.Points(geo, mat);
    scene.add(pts);

    let rafId;
    const start = performance.now();
    const loop = (now) => {
      const t = (now - start) / 1000;
      const posArr = geo.attributes.position.array;
      for (let i = 0; i < COUNT; i++) {
        const idx = i * 3;
        posArr[idx] += velocities[idx] * (1 + 0.4 * Math.sin(t * 0.15 + i));
        posArr[idx + 1] += velocities[idx + 1] * (1 + 0.3 * Math.cos(t * 0.12 + i * 0.2));
        if (posArr[idx] > spreadX / 2) posArr[idx] = -spreadX / 2;
        if (posArr[idx] < -spreadX / 2) posArr[idx] = spreadX / 2;
        if (posArr[idx + 1] > spreadY / 2) posArr[idx + 1] = -spreadY / 2;
        if (posArr[idx + 1] < -spreadY / 2) posArr[idx + 1] = spreadY / 2;
      }
      geo.attributes.position.needsUpdate = true;

      pts.rotation.y = Math.sin(t * 0.04) * 0.04;
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
      try { geo.dispose(); mat.dispose(); renderer.dispose(); } catch (e) {}
      if (canvas && canvas.parentNode) canvas.parentNode.removeChild(canvas);
    };
  }, []);
  return null;
}

/* ---------------------- Background Orbital (Three.js) ------------------- */
function BackgroundOrbitalCanvas() {
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

    const root = new THREE.Group();
    scene.add(root);

    const centralCount = 600;
    const centralPos = new Float32Array(centralCount * 3);
    const radius = 1.7;
    for (let i = 0; i < centralCount; i++) {
      const phi = Math.acos(1 - 2 * (i + 0.5) / centralCount);
      const theta = Math.PI * (1 + Math.sqrt(5)) * (i + 0.5);
      centralPos[i * 3 + 0] = Math.sin(phi) * Math.cos(theta) * radius;
      centralPos[i * 3 + 1] = Math.sin(phi) * Math.sin(theta) * radius;
      centralPos[i * 3 + 2] = Math.cos(phi) * radius;
    }
    const centralGeo = new THREE.BufferGeometry();
    centralGeo.setAttribute("position", new THREE.BufferAttribute(centralPos, 3));
    const centralMat = new THREE.PointsMaterial({
      size: 0.055,
      color: 0x00ffaa,
      transparent: true,
      opacity: 0.22,
      depthTest: false,
      blending: THREE.AdditiveBlending,
      sizeAttenuation: true,
    });
    const centralPoints = new THREE.Points(centralGeo, centralMat);
    root.add(centralPoints);

    const makeOrbitDots = (num = 120, r = 2.8, rot = 0) => {
      const p = new Float32Array(num * 3);
      for (let i = 0; i < num; i++) {
        const t = (i / num) * Math.PI * 2;
        p[i * 3] = Math.cos(t) * r;
        p[i * 3 + 1] = Math.sin(t) * r;
        p[i * 3 + 2] = 0;
      }
      const g = new THREE.BufferGeometry();
      g.setAttribute("position", new THREE.BufferAttribute(p, 3));
      const m = new THREE.PointsMaterial({ size: 0.04, color: 0x00ffaa, transparent: true, opacity: 0.14, blending: THREE.AdditiveBlending, sizeAttenuation: true });
      const mesh = new THREE.Points(g, m);
      mesh.rotation.z = rot;
      return { mesh, g, m };
    };

    const orbit1 = makeOrbitDots(160, 3.1, 0.12);
    const orbit2 = makeOrbitDots(120, 2.6, -0.3);
    root.add(orbit1.mesh, orbit2.mesh);

    let rafId = null;
    const start = performance.now();
    const animate = (now) => {
      const t = (now - start) / 1000;
      root.rotation.y = Math.sin(t * 0.06) * 0.04;
      orbit1.mesh.rotation.y += 0.0048;
      orbit2.mesh.rotation.z -= 0.0052;

      const pos = centralGeo.attributes.position.array;
      for (let i = 0; i < centralCount; i++) {
        const idx = i * 3;
        const m = 1 + 0.004 * Math.sin(t * 2.6 + i * 0.07);
        pos[idx] = pos[idx] * m;
        pos[idx + 1] = pos[idx + 1] * m;
        pos[idx + 2] = pos[idx + 2] * m;
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
        centralGeo.dispose(); centralMat.dispose();
        orbit1.g.dispose(); orbit1.m.dispose();
        orbit2.g.dispose(); orbit2.m.dispose();
        renderer.dispose();
      } catch (e) {}
      if (canvas && canvas.parentNode) canvas.parentNode.removeChild(canvas);
    };
  }, []);
  return null;
}
