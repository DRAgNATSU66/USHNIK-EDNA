import React, { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import {
  ChevronRight,
  Download,
  MessageSquare,
  AlertTriangle,
  CheckCircle,
  Copy,
  Zap,
  TrendingUp,
  Database,
  Eye,
} from "lucide-react";

// Mock axios for demo — replace with your real axios
const axios = {
  get: async (url) => ({
    data: {
      id: "analysis_001",
      metrics: { totalSpecies: 45, noveltyCount: 8 },
      species: [
        { id: "sp001", name: "Bacillus subtilis", confidence: 0.95 },
        { id: "sp002", name: "Unknown species A", confidence: 0.25 },
        { id: "sp003", name: "Escherichia coli", confidence: 0.88 },
        { id: "sp004", name: "Unknown species B", confidence: 0.15 },
        { id: "sp005", name: "Streptococcus thermophilus", confidence: 0.92 },
        { id: "sp006", name: "Novel candidate C", confidence: 0.32 },
        { id: "sp007", name: "Mycelia aetheria", confidence: 0.82 },
        { id: "sp008", name: "Pseudomonas aeruginosa", confidence: 0.76 },
        { id: "sp009", name: "Micrococcus luteus", confidence: 0.55 },
        { id: "sp010", name: "Staphylococcus epidermidis", confidence: 0.68 },
        { id: "sp011", name: "Novel candidate D", confidence: 0.18 },
        { id: "sp012", name: "Unknown species E", confidence: 0.39 },
      ],
    },
  }),
  post: async (url, data) => ({ data: { success: true } }),
};

const BASE_URL = "http://127.0.0.1:8000";
const NOVELTY_THRESHOLD = 0.4;

const Admin = () => {
  // Redirect to landing page on reload (ONLY reloads)
  useEffect(() => {
    try {
      const navEntries =
        performance.getEntriesByType && performance.getEntriesByType("navigation");
      const navType =
        navEntries && navEntries.length && navEntries[0].type
          ? navEntries[0].type
          : performance && performance.navigation && performance.navigation.type === 1
          ? "reload"
          : null;

      if (navType === "reload" && window.location.pathname !== "/") {
        window.location.href = "/";
      }
    } catch (e) {
      // fail quietly
    }
  }, []);

  // Try to read analysis and originalJson from navigation state
  const navState = (window.history && window.history.state) || {};
  const initialAnalysis = navState?.usr?.analysis || navState?.analysis || null;
  const initialOriginalJson = navState?.usr?.originalJson || navState?.originalJson || null;

  const [analysis, setAnalysis] = useState(
    initialAnalysis || {
      id: "analysis_001",
      metrics: { totalSpecies: 45, noveltyCount: 8 },
      species: [
        { id: "sp001", name: "Bacillus subtilis", confidence: 0.95 },
        { id: "sp002", name: "Unknown species A", confidence: 0.25 },
        { id: "sp003", name: "Escherichia coli", confidence: 0.88 },
        { id: "sp004", name: "Unknown species B", confidence: 0.15 },
        { id: "sp005", name: "Streptococcus thermophilus", confidence: 0.92 },
        { id: "sp006", name: "Novel candidate C", confidence: 0.32 },
        { id: "sp007", name: "Mycelia aetheria", confidence: 0.82 },
        { id: "sp008", name: "Pseudomonas aeruginosa", confidence: 0.76 },
        { id: "sp009", name: "Micrococcus luteus", confidence: 0.55 },
        { id: "sp010", name: "Staphylococcus epidermidis", confidence: 0.68 },
        { id: "sp011", name: "Novel candidate D", confidence: 0.18 },
        { id: "sp012", name: "Unknown species E", confidence: 0.39 },
      ],
    }
  );
  const [originalJson, setOriginalJson] = useState(initialOriginalJson);
  const [analysisIdInput, setAnalysisIdInput] = useState("");
  const [loadingFetch, setLoadingFetch] = useState(false);
  const [fetchError, setFetchError] = useState("");
  const [commentMeta, setCommentMeta] = useState({ fullName: "", job: "", goal: "" });
  const [commentText, setCommentText] = useState("");
  const [postingComment, setPostingComment] = useState(false);
  const [postCommentMsg, setPostCommentMsg] = useState("");

  const [selectedNovelty, setSelectedNovelty] = useState(null);
  const [proposedSpecies, setProposedSpecies] = useState("");
  const [proposeReason, setProposeReason] = useState("");
  const [proposeBy, setProposeBy] = useState("");
  const [proposing, setProposing] = useState(false);
  const [proposeMsg, setProposeMsg] = useState("");

  // helpers & derived data
  const speciesList = useMemo(() => (analysis && Array.isArray(analysis.species) ? analysis.species : []), [analysis]);
  const belowThreshold = useMemo(() => speciesList.filter((s) => (s.confidence || 0) < NOVELTY_THRESHOLD), [speciesList]);
  const familiarityCount = useMemo(() => speciesList.filter((s) => (s.confidence || 0) >= NOVELTY_THRESHOLD).length, [speciesList]);
  const noveltyCount = useMemo(() => speciesList.filter((s) => (s.confidence || 0) < NOVELTY_THRESHOLD).length, [speciesList]);
  const totalSpeciesCount = useMemo(() => speciesList.length, [speciesList]);
  const familiarityPct = useMemo(() => {
    if (!speciesList.length) return 0;
    const matched = speciesList.filter((s) => (s.confidence || 0) >= NOVELTY_THRESHOLD).length;
    return Math.round((matched / speciesList.length) * 100);
  }, [speciesList]);
  const unfamiliarityPct = useMemo(() => {
    if (!speciesList.length) return 0;
    const unmatched = speciesList.filter((s) => (s.confidence || 0) < NOVELTY_THRESHOLD).length;
    return Math.round((unmatched / speciesList.length) * 100);
  }, [speciesList]);
  const noveltyCandidates = useMemo(() => {
    return speciesList.filter((s) => (s.confidence || 0) < NOVELTY_THRESHOLD).length;
  }, [speciesList]);

  const topNSimilar = (targetId, n = 3) => {
    const target = speciesList.find((s) => (s.id || s.name) === (targetId || targetId));
    if (!target) return [];
    return speciesList
      .filter((s) => (s.id || s.name) !== (target.id || target.name))
      .sort((a, b) => (b.confidence || 0) - (a.confidence || 0))
      .slice(0, n)
      .map((s) => ({ name: s.name, confidence: (s.confidence || 0) }));
  };

  const bottomNDifferent = (targetId, n = 3) => {
    const target = speciesList.find((s) => (s.id || s.name) === (targetId || targetId));
    if (!target) return [];
    return speciesList
      .filter((s) => (s.id || s.name) !== (target.id || target.name))
      .sort((a, b) => (a.confidence || 0) - (b.confidence || 0))
      .slice(0, n)
      .map((s) => ({ name: s.name, confidence: (s.confidence || 0) }));
  };

  const fetchAnalysisById = async (id) => {
    if (!id) {
      setFetchError("Please enter an analysis ID to fetch.");
      return;
    }
    setLoadingFetch(true);
    setFetchError("");
    try {
      const res = await axios.get(`${BASE_URL}/analysis/${encodeURIComponent(id)}`);
      const data = res.data;
      setAnalysis(data);
      if (data.originalJson) setOriginalJson(data.originalJson);
      setPostCommentMsg("");
    } catch (err) {
      console.error("fetchAnalysisById:", err);
      setFetchError("Failed to fetch analysis. Check the ID or backend.");
    } finally {
      setLoadingFetch(false);
    }
  };

  const downloadJson = () => {
    const payload = originalJson || { analysisId: analysis?.id || null, species: speciesList };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    const name = `analysis_${analysis?.id || "export"}.json`;
    a.download = name;
    a.click();
    URL.revokeObjectURL(url);
  };

  const postComment = async () => {
    if (!analysis?.id) {
      setPostCommentMsg("No analysis ID available to attach comment.");
      return;
    }
    setPostingComment(true);
    setPostCommentMsg("");
    try {
      const payload = {
        commentText: commentText || "",
        meta: {
          fullName: commentMeta.fullName || "",
          job: commentMeta.job || "",
          goal: commentMeta.goal || "",
          familiarityPct,
          unfamiliarityPct,
        },
        fileJson: originalJson || null,
      };
      await axios.post(`${BASE_URL}/analysis/${encodeURIComponent(analysis.id)}/comment`, payload);
      setPostCommentMsg("Comment uploaded successfully.");
      setCommentText("");
    } catch (err) {
      console.error("postComment:", err);
      setPostCommentMsg("Failed to upload comment — check backend.");
    } finally {
      setPostingComment(false);
    }
  };

  const postPropose = async () => {
    if (!analysis?.id || !selectedNovelty) {
      setProposeMsg("No selected novelty or analysis ID.");
      return;
    }
    if (!proposedSpecies) {
      setProposeMsg("Please provide a proposed species name.");
      return;
    }
    setProposing(true);
    setProposeMsg("");
    try {
      const payload = {
        fromNovelty: { id: selectedNovelty.id, name: selectedNovelty.name, confidence: selectedNovelty.confidence },
        to: proposedSpecies,
        reason: proposeReason || "",
        by: proposeBy || commentMeta.fullName || "unknown",
      };
      await axios.post(`${BASE_URL}/analysis/${encodeURIComponent(analysis.id)}/propose`, payload);
      setProposeMsg("Proposal sent successfully.");
    } catch (err) {
      console.error("postPropose:", err);
      setProposeMsg("Failed to send proposal — check backend.");
    } finally {
      setProposing(false);
    }
  };

  const clearSelection = () => {
    setSelectedNovelty(null);
    setProposedSpecies("");
    setProposeReason("");
    setProposeMsg("");
  };

  const copyToClipboard = async (text) => {
    try {
      await navigator.clipboard.writeText(text);
    } catch (e) {
      console.log("Clipboard not available");
    }
  };

  //
  // === THREE.JS BACKGROUND CUBE (DOTS) ===
  //
  const canvasRef = useRef(null);
  const three = useRef({
    renderer: null,
    scene: null,
    camera: null,
    group: null,
    points: null,
    raf: null,
    start: performance.now(),
  });

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    // Renderer
    const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.setClearColor(0x000000, 0);

    // Scene & Camera
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(50, window.innerWidth / window.innerHeight, 0.1, 1000);
    camera.position.z = 2.5;

    // Soft ambient light
    const amb = new THREE.AmbientLight(0xffffff, 0.25);
    scene.add(amb);

    // Group to rotate together
    const group = new THREE.Group();
    scene.add(group);

    // Generate cube points
    const cubeSize = 0.8;
    const pointsArray = [];
    const density = 10;
    for (let xi = 0; xi <= density; xi++) {
      for (let yi = 0; yi <= density; yi++) {
        const x = (xi / density - 0.5) * 2 * cubeSize;
        const y = (yi / density - 0.5) * 2 * cubeSize;
        pointsArray.push(new THREE.Vector3(x, y, cubeSize));
        pointsArray.push(new THREE.Vector3(x, y, -cubeSize));
        pointsArray.push(new THREE.Vector3(cubeSize, x, y));
        pointsArray.push(new THREE.Vector3(-cubeSize, x, y));
        pointsArray.push(new THREE.Vector3(x, cubeSize, y));
        pointsArray.push(new THREE.Vector3(x, -cubeSize, y));
      }
    }
    const uniqueMap = new Map();
    pointsArray.forEach((v) => {
      const key = `${v.x.toFixed(4)},${v.y.toFixed(4)},${v.z.toFixed(4)}`;
      if (!uniqueMap.has(key)) uniqueMap.set(key, v);
    });
    const uniquePoints = Array.from(uniqueMap.values());

    // Buffer geometry
    const positions = new Float32Array(uniquePoints.length * 3);
    for (let i = 0; i < uniquePoints.length; i++) {
      positions[i * 3 + 0] = uniquePoints[i].x;
      positions[i * 3 + 1] = uniquePoints[i].y;
      positions[i * 3 + 2] = uniquePoints[i].z;
    }
    const geom = new THREE.BufferGeometry();
    geom.setAttribute("position", new THREE.BufferAttribute(positions, 3));

    // Material (color will be updated each frame)
    const mat = new THREE.PointsMaterial({
      size: 0.028,
      transparent: true,
      opacity: 0.95,
      sizeAttenuation: true,
      depthTest: false,
      blending: THREE.AdditiveBlending,
    });

    const points = new THREE.Points(geom, mat);
    group.add(points);

    // Store refs
    three.current = { renderer, scene, camera, group, points, start: performance.now(), raf: null };

    // color stops for smooth cycling
    const colorStops = [
      new THREE.Color(0x00d4ff), // blue
      new THREE.Color(0xffea00), // yellow
      new THREE.Color(0xff2b4b), // red
      new THREE.Color(0x00ff88), // green
    ];

    const LOOP = 12.0; // 12s full loop
    const animate = () => {
      const now = performance.now();
      const elapsed = (now - three.current.start) / 1000;

      group.rotation.x = elapsed * 0.18;
      group.rotation.y = elapsed * 0.13;
      group.rotation.z = elapsed * 0.07;
      
      // color interpolation
      const t = (elapsed % LOOP) / LOOP; // 0..1
      const seg = t * colorStops.length;
      const idx = Math.floor(seg) % colorStops.length;
      const next = (idx + 1) % colorStops.length;
      const frac = seg - Math.floor(seg);
      const c = colorStops[idx].clone().lerp(colorStops[next], frac);

      mat.color.copy(c);

      renderer.render(scene, camera);
      three.current.raf = requestAnimationFrame(animate);
    };

    // start animation
    animate();

    const onResize = () => {
      renderer.setSize(window.innerWidth, window.innerHeight);
      camera.aspect = window.innerWidth / window.innerHeight;
      camera.updateProjectionMatrix();
    };
    window.addEventListener("resize", onResize);

    // cleanup
    return () => {
      window.removeEventListener("resize", onResize);
      if (three.current.raf) cancelAnimationFrame(three.current.raf);
      try {
        geom.dispose();
        mat.dispose();
        renderer.dispose();
      } catch (e) {}
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []); // run once

  // UI JSX (styled to match landing/app)
  return (
    <>
      <style>
        {`
/* =============================
   Theme variables & base reset
   ============================= */
:root{
  --primary-blue:#0066ff;
  --secondary-cyan:#00d4ff;
  --accent-green:#00ff88;
  --deep-ocean:#001133;
  --dark-blue:#002266;
  --glass-border:rgba(255,255,255,0.1);
  --text-primary:#ffffff;
  --text-secondary:#b3d9ff;
  --text-muted:#7eb3ff;
  --gradient-primary:linear-gradient(135deg,var(--primary-blue) 0%,var(--secondary-cyan) 100%);
  --gradient-bg:radial-gradient(ellipse at center,var(--dark-blue) 0%,var(--deep-ocean) 100%);
}

/* Keep native page scrolling but hide horizontal overflow to remove sideways scroll */
html, body, #root {
  height: 100%;
  width: 100%;
  margin: 0;
  padding: 0;
  overflow-y: auto;    /* allow vertical scrolling */
  overflow-x: hidden;  /* remove horizontal scroll */
  background: var(--gradient-bg);
  color: var(--text-primary);
  font-family: 'Inter', system-ui, Roboto, sans-serif;
  -webkit-font-smoothing:antialiased;
}

/* =============================
   Page-level scrollbar styling
   (Chromium / Opera / WebKit)
   ============================= */
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

/* chunky cyan thumb with glow — matches inner scrolls */
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

/* =============================
   Firefox scrollbar fallback
   ============================= */
body {
  scrollbar-width: thin;
  scrollbar-color: rgba(0,212,255,0.95) transparent;
}

/* =============================
   Keep internal scrollables styled
   (unchanged inner scrollbars)
   ============================= */

/* Use 100% width (not 100vw) to avoid creating horizontal overflow when scrollbar is present */
#admin-bg-canvas{
  position:fixed;
  top:0;
  left:0;
  width:100%;
  height:100vh;
  z-index:0;
  pointer-events:none;
}

/* Container keeps padding but will not cause horizontal overflow due to overflow-x:hidden on body */
.container{position:relative;z-index:10;min-height:100vh;padding:2rem;max-width:1400px;margin:0 auto}

/* Header: center brand, keep badge at right */
.header{width:100%;text-align:left;margin-bottom:1.5rem;display:flex;align-items:center;justify-content:center;position:relative}
.brand{display:flex;align-items:center;gap:16px;flex-direction:column}
.logo{font-size:clamp(1.6rem,3vw,2.4rem);font-weight:800;background:var(--gradient-primary);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.subtitle{color:var(--text-muted);font-size:0.95rem}
.top-badge{position:absolute;right:2rem;top:50%;transform:translateY(-50%);display:flex;align-items:center;gap:8px;padding:8px 12px;border-radius:12px;background:rgba(0,0,0,0.18);border:1px solid rgba(255,255,255,0.04); color: var(--text-primary);}
.grid{display:grid;grid-template-columns:1fr;gap:1.25rem;margin:0 auto}
@media(min-width:1000px){.grid{grid-template-columns:1fr}}
.glass{background:rgba(255,255,255,0.04);backdrop-filter:blur(12px);border-radius:16px;padding:20px;border:1px solid var(--glass-border);box-shadow:0 20px 60px rgba(0,17,51,0.45)}
.panel-header{display:flex;align-items:center;gap:12px;margin-bottom:12px}
.panel-title{font-size:1.05rem;font-weight:700}
.kv{font-size:1.6rem;font-weight:800;background:var(--gradient-primary);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.small{color:var(--text-muted);font-size:0.85rem}
.btn{padding:10px 14px;border-radius:10px;border:none;cursor:pointer;font-weight:700}
.btn-primary{background:var(--gradient-primary);color:white;box-shadow:0 10px 30px rgba(0,102,255,0.24)}
.input,textarea{width:100%;padding:10px 12px;border-radius:10px;border:1px solid rgba(255,255,255,0.06);background:rgba(0,0,0,0.18);color:var(--text-primary)}
.small-muted{color:var(--text-muted);font-size:0.85rem}
.card{border-radius:12px;padding:12px;background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.04)}
.list-scroll{max-height:520px;overflow:auto;padding-right:6px}
.list-scroll::-webkit-scrollbar{width:8px}
.list-scroll::-webkit-scrollbar-thumb{background:linear-gradient(180deg,#0066ff,#00d4ff);border-radius:8px}
.spec-item{padding:12px;border-radius:10px;margin-bottom:10px;background:rgba(255,255,255,0.025);border:1px solid rgba(255,255,255,0.03)}
.spec-line{display:flex;justify-content:space-between;align-items:center;gap:12px}
.spec-name{font-weight:700;color:var(--text-primary)}
.spec-pct{font-weight:700}
.badge{padding:6px 8px;border-radius:999px;font-size:12px}
.badge-low{background:rgba(255,90,90,0.08);color:#ff9b9b}
.badge-mid{background:rgba(255,178,96,0.06);color:#ffc58a}
.note{font-size:0.9rem;color:var(--text-muted)}
.json-preview{font-family:monospace;font-size:12px;color:rgba(255,255,255,0.75);white-space:pre-wrap;max-height:180px;overflow:auto;background:rgba(0,0,0,0.2);padding:10px;border-radius:8px;border:1px solid rgba(255,255,255,0.03)}
.json-preview::-webkit-scrollbar{width:8px}
.json-preview::-webkit-scrollbar-thumb{background:linear-gradient(180deg,#0066ff,#00d4ff);border-radius:8px}
.status-msg{padding:10px;border-radius:8px;margin-top:8px}
.success{background:rgba(0,255,136,0.06);border:1px solid rgba(0,255,136,0.12);color:var(--accent-green)}
.error{background:rgba(255,80,80,0.06);border:1px solid rgba(255,80,80,0.12);color:#ff9b9b}

/* metrics grid */
.metrics-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 1.25rem;
  margin-bottom: 2rem;
  max-width: 1300px;
  margin: 0 auto 2rem;
}
.metric-card {
  padding: 1.5rem;
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.04);
  backdrop-filter: blur(12px);
  border: 1px solid rgba(255, 255, 255, 0.1);
  box-shadow: 0 20px 60px rgba(0, 17, 51, 0.45);
  display: flex;
  flex-direction: column;
  align-items: flex-start;
}
.metric-icon {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 1rem;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.1);
}
.metric-value {
  font-size: 2.5rem;
  font-weight: 800;
  background: linear-gradient(135deg, #00d4ff, #0066ff);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  line-height: 1;
}
.metric-title { font-size: 0.9rem; color: var(--text-muted); margin-top: 0.5rem; }
.metric-subtitle { font-size: 0.8rem; color: var(--text-secondary); }
        `}
      </style>

      {/* Three.js Background */}
      <canvas id="admin-bg-canvas" ref={canvasRef} />

      <div className="container">
        <header className="header">
          <div className="brand">
            <div>
              <div className="logo">eDNA Biodiversity Analyzer</div>
              <div className="small note">Admin • Review analyses and curate species</div>
            </div>
          </div>
          <div className="top-badge">
            <Database className="w-4 h-4" />
            <div className="small-muted">{analysis?.id || "No analysis loaded"}</div>
          </div>
        </header>

        {/* New cards for key metrics */}
        <div className="metrics-grid">
          <div className="metric-card">
            <div className="metric-icon">
              <TrendingUp size={24} color="#00d4ff" />
            </div>
            <div className="metric-value">{totalSpeciesCount}</div>
            <div className="metric-title">Total Species</div>
            <div className="metric-subtitle">Identified in analysis</div>
          </div>

          <div className="metric-card">
            <div className="metric-icon">
              <CheckCircle size={24} color="#00ff88" />
            </div>
            <div className="metric-value">{familiarityPct}%</div>
            <div className="metric-title">Familiarity</div>
            <div className="metric-subtitle">Known species ratio</div>
          </div>

          <div className="metric-card">
            <div className="metric-icon">
              <AlertTriangle size={24} color="#ffea00" />
            </div>
            <div className="metric-value">{unfamiliarityPct}%</div>
            <div className="metric-title">Novelty</div>
            <div className="metric-subtitle">Unknown species ratio</div>
          </div>

          <div className="metric-card">
            <div className="metric-icon">
              <Eye size={24} color="#0066ff" />
            </div>
            <div className="metric-value">{noveltyCandidates}</div>
            <div className="metric-title">Candidates</div>
            <div className="metric-subtitle">Below {Math.round(NOVELTY_THRESHOLD * 100)}% threshold</div>
          </div>
        </div>

        <main className="grid">
          {/* Left column: Comments / Upload */}
          <section className="glass">
            <div className="panel-header">
              <div className="card" style={{ padding: 8 }}>
                <MessageSquare />
              </div>
              <div>
                <div className="panel-title">Upload Comment</div>
                <div className="small-muted">Attach insights and metadata to this analysis</div>
              </div>
            </div>

            <div style={{ marginTop: 8 }}>
              <input
                className="input"
                placeholder="Full name"
                value={commentMeta.fullName}
                onChange={(e) => setCommentMeta((m) => ({ ...m, fullName: e.target.value }))}
              />
              <div style={{ height: 10 }} />
              <input
                className="input"
                placeholder="Job / Affiliation"
                value={commentMeta.job}
                onChange={(e) => setCommentMeta((m) => ({ ...m, job: e.target.value }))}
              />
              <div style={{ height: 10 }} />
              <input
                className="input"
                placeholder="Research goal"
                value={commentMeta.goal}
                onChange={(e) => setCommentMeta((m) => ({ ...m, goal: e.target.value }))}
              />
              <div style={{ height: 10 }} />
              <textarea
                className="input"
                placeholder="Share your insights..."
                rows={6}
                value={commentText}
                onChange={(e) => setCommentText(e.target.value)}
              />
            </div>

            <div style={{ display: "flex", gap: 10, marginTop: 12 }}>
              <button
                className="btn btn-primary"
                onClick={postComment}
                disabled={postingComment || !analysis?.id}
              >
                {postingComment ? "Uploading..." : "Upload Comment"}
              </button>
              <button className="btn" onClick={downloadJson}>
                <Download style={{ marginRight: 8 }} />
                Export JSON
              </button>
            </div>

            {postCommentMsg && (
              <div className={`status-msg ${postCommentMsg.includes("success") ? "success" : "error"}`}>
                {postCommentMsg}
              </div>
            )}
          </section>

          {/* Middle column: Novelty Candidates */}
          <section className="glass" style={{ minHeight: 520 }}>
            <div className="panel-header">
              <div className="card" style={{ padding: 8 }}>
                <AlertTriangle />
              </div>
              <div style={{ flex: 1 }}>
                <div className="panel-title">Novelty Candidates</div>
                <div className="small-muted">Species below {Math.round(NOVELTY_THRESHOLD * 100)}% confidence</div>
              </div>
              <div className="kv">{belowThreshold.length}</div>
            </div>

            <div className="list-scroll">
              {belowThreshold.length === 0 ? (
                <div style={{ textAlign: "center", padding: 40 }}>
                  <div style={{ width: 64, height: 64, borderRadius: 999, background: "rgba(0,255,136,0.06)", margin: "0 auto 12px", display: "flex", alignItems: "center", justifyContent: "center" }}>
                    <CheckCircle />
                  </div>
                  <div className="panel-title" style={{ marginBottom: 8 }}>All Clear</div>
                  <div className="small-muted">No low-confidence species found</div>
                </div>
              ) : (
                belowThreshold.map((s, i) => {
                  const idKey = s.id || s.name || i;
                  const similar = topNSimilar(s.id || s.name, 3);
                  const different = bottomNDifferent(s.id || s.name, 3);
                  const isSelected = selectedNovelty?.id === idKey;
                  const pct = ((s.confidence || 0) * 100).toFixed(1);

                  return (
                    <div key={idKey} className="spec-item">
                      <div className="spec-line">
                        <div style={{ flex: 1 }}>
                          <div className="spec-name">{s.name}</div>
                          <div className="small-muted">ID: {s.id || "—"}</div>
                        </div>
                        <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 8 }}>
                          <div className={`badge ${s.confidence < 0.2 ? "badge-low" : "badge-mid"}`}>{pct}%</div>
                          <div style={{ display: "flex", gap: 8 }}>
                            <button title="Copy ID" className="btn" onClick={() => copyToClipboard(s.id || s.name || "")}>
                              <Copy />
                            </button>
                            <button
                              className="btn"
                              onClick={() => {
                                setSelectedNovelty({ id: idKey, name: s.name, confidence: s.confidence || 0 });
                                setProposeMsg("");
                                setProposeReason("");
                                setProposedSpecies("");
                              }}
                              style={{ background: isSelected ? "linear-gradient(90deg,#0066ff,#00d4ff)" : "transparent", color: isSelected ? "#fff" : "var(--text-primary)", border: isSelected ? "none" : "1px solid rgba(255,255,255,0.06)" }}
                            >
                              {isSelected ? "Selected" : "Select"}
                            </button>
                          </div>
                        </div>
                      </div>

                      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginTop: 10 }}>
                        <div>
                          <div className="small-muted" style={{ marginBottom: 6 }}>MOST SIMILAR</div>
                          {similar.length ? similar.map((it, ii) => (
                            <div key={ii} style={{ display: "flex", justifyContent: "space-between", fontSize: 13, marginBottom: 6 }}>
                              <div style={{ color: "rgba(255,255,255,0.9)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{it.name}</div>
                              <div style={{ color: "var(--accent-green)", fontWeight: 700 }}>{(it.confidence * 100).toFixed(0)}%</div>
                            </div>
                          )) : <div className="small-muted">None</div>}
                        </div>
                        <div>
                          <div className="small-muted" style={{ marginBottom: 6 }}>LEAST SIMILAR</div>
                          {different.length ? different.map((it, ii) => (
                            <div key={ii} style={{ display: "flex", justifyContent: "space-between", fontSize: 13, marginBottom: 6 }}>
                              <div style={{ color: "rgba(255,255,255,0.9)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{it.name}</div>
                              <div style={{ color: "#ff6b6b", fontWeight: 700 }}>{(it.confidence * 100).toFixed(0)}%</div>
                            </div>
                          )) : <div className="small-muted">None</div>}
                        </div>
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </section>

          {/* Right column: Correction panel & JSON preview */}
          <section className="glass">
            <div className="panel-header">
              <div className="card" style={{ padding: 8 }}>
                <Zap />
              </div>
              <div>
                <div className="panel-title">Species Correction</div>
                <div className="small-muted">Propose corrections for the selected novelty</div>
              </div>
            </div>

            {!selectedNovelty ? (
              <div style={{ textAlign: "center", padding: 30 }}>
                <div style={{ width: 60, height: 60, borderRadius: 999, margin: "0 auto 12px", background: "rgba(0,102,255,0.06)", display: "flex", alignItems: "center", justifyContent: "center" }}>
                  <ChevronRight />
                </div>
                <div className="panel-title" style={{ marginBottom: 6 }}>Select a Species</div>
                <div className="small-muted">Pick a candidate from the center panel to propose a correction</div>
                <div style={{ marginTop: 12 }}>
                  <button className="btn btn-primary" onClick={() => window.history.back()}>Back to Results</button>
                </div>
                <div style={{ marginTop: 18 }}>
                  <div style={{ fontWeight: 700, marginBottom: 8 }}>Data Preview</div>
                  <div className="json-preview">
                    {originalJson
                      ? JSON.stringify(originalJson, null, 2)
                      : analysis
                      ? JSON.stringify({
                          id: analysis.id,
                          species: speciesList.slice(0, 6).map((s) => ({ id: s.id, name: s.name, confidence: s.confidence })),
                          "...": `and ${Math.max(0, speciesList.length - 6)} more`,
                        }, null, 2)
                      : "No data available"}
                  </div>
                </div>
              </div>
            ) : (
              <>
                <div className="card" style={{ marginBottom: 12 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <div>
                      <div style={{ fontWeight: 800 }}>{selectedNovelty.name}</div>
                      <div className="small-muted">ID: {selectedNovelty.id || "—"}</div>
                    </div>
                    <div style={{ textAlign: "right" }} className="badge" >
                      {((selectedNovelty.confidence || 0) * 100).toFixed(1)}%
                    </div>
                  </div>
                </div>

                <div style={{ display: "grid", gap: 10 }}>
                  <input className="input" placeholder="Proposed species name" value={proposedSpecies} onChange={(e) => setProposedSpecies(e.target.value)} />
                  <input className="input" placeholder="Proposed by (your name)" value={proposeBy} onChange={(e) => setProposeBy(e.target.value)} />
                  <textarea className="input" placeholder="Reason for correction..." rows={4} value={proposeReason} onChange={(e) => setProposeReason(e.target.value)} />
                </div>

                <div style={{ display: "flex", gap: 10, marginTop: 12 }}>
                  <button className="btn btn-primary" onClick={postPropose} disabled={proposing || !proposedSpecies}>
                    {proposing ? "Sending..." : "Submit Correction"}
                  </button>
                  <button className="btn" onClick={clearSelection}>Clear</button>
                </div>

                {proposeMsg && <div className={`status-msg ${proposeMsg.includes("success") ? "success" : "error"}`}>{proposeMsg}</div>}

                <div style={{ marginTop: 18 }}>
                  <div style={{ fontWeight: 700, marginBottom: 8 }}>Data Preview</div>
                  <div className="json-preview">
                    {originalJson
                      ? JSON.stringify(originalJson, null, 2)
                      : analysis
                      ? JSON.stringify({
                          id: analysis.id,
                          species: speciesList.slice(0, 6).map((s) => ({ id: s.id, name: s.name, confidence: s.confidence })),
                          "...": `and ${Math.max(0, speciesList.length - 6)} more`,
                        }, null, 2)
                      : "No data available"}
                  </div>
                </div>
              </>
            )}
          </section>
        </main>
      </div>
    </>
  );
};

export default Admin;
