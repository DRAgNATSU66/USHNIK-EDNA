import React, { useState, useEffect, useRef } from "react";
import * as THREE from "three";
import axios from "axios";

// This component is the main application file for the eDNA Analysis platform.
// It handles UI state, backend communication, and THREE.js visualizations.
const App = () => {
  // === State Management ===
  const [selectedFile, setSelectedFile] = useState(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [metrics, setMetrics] = useState({ totalReads: 0, totalSpecies: 0 });
  const [results, setResults] = useState([]);
  const [previousResults, setPreviousResults] = useState([]); // To track for new species
  const [errorMessage, setErrorMessage] = useState("");
  const [backendStatus, setBackendStatus] = useState("Checking backend...");
  const [newSpeciesMessage, setNewSpeciesMessage] = useState("");
  const [isFastSpin, setIsFastSpin] = useState(false);
  const [showSecondBgHelix, setShowSecondBgHelix] = useState(false);

  // === Refs for DOM elements and THREE.js objects ===
  const bgCanvasRef = useRef(null);
  const metricsCanvasRef = useRef(null);
  const fileInputRef = useRef(null);

  // THREE.js refs for background scene
  const bgSceneRef = useRef(null);
  const bgCameraRef = useRef(null);
  const bgRendererRef = useRef(null);
  const bgGroupRef = useRef(null); // The blue helix
  const secondBgGroupRef = useRef(null); // The new helix that appears
  const particlesRef = useRef(null);

  // THREE.js refs for metrics scene
  const metricsSceneRef = useRef(null);
  const metricsCameraRef = useRef(null);
  const metricsRendererRef = useRef(null);
  const helixRef = useRef(null); // The small helix

  // === Backend Endpoints ===
  const BASE_URL = "http://127.0.0.1:8000";
  const BACKEND_URL = `${BASE_URL}/analyze`;
  const HEALTH_URL = `${BASE_URL}/health`;

  // === Health Check on Mount ===
  useEffect(() => {
    let mounted = true;
    axios
      .get(HEALTH_URL, { timeout: 4000 })
      .then((r) => {
        if (mounted) setBackendStatus("Backend: Connected ✓");
      })
      .catch((e) => {
        if (mounted)
          setBackendStatus(
            "Backend: Unreachable (start backend or check CORS)"
          );
      });
    return () => {
      mounted = false;
    };
  }, []);

  // === New Species Notification Effect ===
  useEffect(() => {
    if (newSpeciesMessage) {
      const timeout = setTimeout(() => {
        setNewSpeciesMessage("");
      }, 5000);
      return () => clearTimeout(timeout);
    }
  }, [newSpeciesMessage]);

  // === THREE.js Scenes: Background and Metrics Helix ===
  useEffect(() => {
    // BACKGROUND SCENE (Blue and Red Helix + Particles)
    const initBackground = () => {
      const canvas = bgCanvasRef.current;
      if (!canvas) return;
      const width = window.innerWidth;
      const height = window.innerHeight;

      bgSceneRef.current = new THREE.Scene();
      bgCameraRef.current = new THREE.PerspectiveCamera(75, width / height, 0.1, 1000);
      bgCameraRef.current.position.z = 2.5;

      bgRendererRef.current = new THREE.WebGLRenderer({
        canvas,
        antialias: true,
        alpha: true,
      });
      bgRendererRef.current.setSize(width, height);
      bgRendererRef.current.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));

      // Lights
      const ambientLight = new THREE.AmbientLight(0x4080ff, 0.2);
      bgSceneRef.current.add(ambientLight);
      const pointLight = new THREE.PointLight(0x00d4ff, 1);
      pointLight.position.set(0, 0, 50);
      bgSceneRef.current.add(pointLight);

      // Main Blue Helix (always present)
      const createHelix = (color, reverse = false) => {
        const points = [];
        const numPoints = 300;
        const helixRadius = 1;
        const helixHeight = 3;
        for (let i = 0; i < numPoints; i++) {
          const t = (i / (numPoints - 1)) * Math.PI * 4;
          const x = reverse ? -helixRadius * Math.cos(t) : helixRadius * Math.cos(t);
          const y = helixHeight * (i / numPoints) - helixHeight / 2;
          const z = reverse ? -helixRadius * Math.sin(t) : helixRadius * Math.sin(t);
          points.push(new THREE.Vector3(x, y, z));
        }
        const geometry = new THREE.BufferGeometry().setFromPoints(points);
        const material = new THREE.PointsMaterial({
          color: color,
          size: 0.02,
          blending: THREE.AdditiveBlending,
          transparent: true,
          opacity: 0.8,
        });
        return new THREE.Points(geometry, material);
      };

      bgGroupRef.current = createHelix(0x00d4ff, false);
      bgSceneRef.current.add(bgGroupRef.current);

      // Floating Particles Background
      const particlesGeometry = new THREE.BufferGeometry();
      const particlesCount = 1800;
      const posArray = new Float32Array(particlesCount * 3);
      for (let i = 0; i < particlesCount * 3; i++) {
        posArray[i] = (Math.random() - 0.5) * 12;
      }
      particlesGeometry.setAttribute(
        "position",
        new THREE.BufferAttribute(posArray, 3)
      );
      const particlesMaterial = new THREE.PointsMaterial({
        size: 0.012,
        color: 0x00ff88,
        blending: THREE.AdditiveBlending,
        transparent: true,
        opacity: 0.45,
      });
      particlesRef.current = new THREE.Points(
        particlesGeometry,
        particlesMaterial
      );
      bgSceneRef.current.add(particlesRef.current);
    };

    // METRICS SCENE (Small Helix)
    const initMetricsViz = () => {
      const canvas = metricsCanvasRef.current;
      if (!canvas) return;
      const width = canvas.clientWidth || 300;
      const height = canvas.clientHeight || 160;

      metricsSceneRef.current = new THREE.Scene();
      metricsCameraRef.current = new THREE.PerspectiveCamera(75, width / height, 0.1, 1000);
      metricsCameraRef.current.position.z = 2;

      metricsRendererRef.current = new THREE.WebGLRenderer({
        canvas,
        antialias: true,
        alpha: true,
      });
      metricsRendererRef.current.setSize(width, height);
      metricsRendererRef.current.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));

      const helixGroup = new THREE.Group();
      const numPoints = 120;
      const helixRadius = 0.5;
      const helixHeight = 1.6;

      // Green strand
      const greenPoints = [];
      for (let i = 0; i < numPoints; i++) {
        const t = (i / (numPoints - 1)) * Math.PI * 6;
        const x = helixRadius * Math.cos(t);
        const y = helixHeight * (i / numPoints) - helixHeight / 2;
        const z = helixRadius * Math.sin(t);
        greenPoints.push(new THREE.Vector3(x, y, z));
      }
      const greenGeometry = new THREE.BufferGeometry().setFromPoints(greenPoints);
      const greenMaterial = new THREE.PointsMaterial({
        color: 0x00ff88,
        size: 0.055,
        blending: THREE.AdditiveBlending,
        transparent: true,
        opacity: 0.95,
      });
      const greenStrand = new THREE.Points(greenGeometry, greenMaterial);
      helixGroup.add(greenStrand);

      // Red strand
      const redPoints = [];
      for (let i = 0; i < numPoints; i++) {
        const t = (i / (numPoints - 1)) * Math.PI * 6;
        const x = -helixRadius * Math.cos(t);
        const y = helixHeight * (i / numPoints) - helixHeight / 2;
        const z = -helixRadius * Math.sin(t);
        redPoints.push(new THREE.Vector3(x, y, z));
      }
      const redGeometry = new THREE.BufferGeometry().setFromPoints(redPoints);
      const redMaterial = new THREE.PointsMaterial({
        color: 0xff6b6b,
        size: 0.052,
        blending: THREE.AdditiveBlending,
        transparent: true,
        opacity: 0.95,
      });
      const redStrand = new THREE.Points(redGeometry, redMaterial);
      helixGroup.add(redStrand);

      helixRef.current = helixGroup;
      metricsSceneRef.current.add(helixRef.current);

      const pointLight = new THREE.PointLight(0x00ff88, 0.8, 100);
      pointLight.position.set(0, 0, 8);
      metricsSceneRef.current.add(pointLight);
    };

    // Handle Window Resize
    const onWindowResize = () => {
      if (bgCameraRef.current && bgRendererRef.current) {
        bgCameraRef.current.aspect = window.innerWidth / window.innerHeight;
        bgCameraRef.current.updateProjectionMatrix();
        bgRendererRef.current.setSize(window.innerWidth, window.innerHeight);
      }
      if (metricsCameraRef.current && metricsRendererRef.current && metricsCanvasRef.current) {
        const w = metricsCanvasRef.current.clientWidth;
        const h = metricsCanvasRef.current.clientHeight;
        metricsCameraRef.current.aspect = w / h;
        metricsCameraRef.current.updateProjectionMatrix();
        metricsRendererRef.current.setSize(w, h);
      }
    };

    // Animation Loop for Background Helices
    let bgRafId;
    const animateBackground = () => {
      bgRafId = requestAnimationFrame(animateBackground);
      if (bgGroupRef.current && bgRendererRef.current) {
        // Reversed rotation for opposite movement to the metrics helix
        bgGroupRef.current.rotation.x -= 0.002;
        bgGroupRef.current.rotation.y -= 0.0045;
        if (secondBgGroupRef.current) {
          secondBgGroupRef.current.rotation.x -= 0.002;
          secondBgGroupRef.current.rotation.y += 0.006;
        }
        if (particlesRef.current) particlesRef.current.rotation.y += 0.0008;
        bgRendererRef.current.render(bgSceneRef.current, bgCameraRef.current);
      }
    };

    // Animation Loop for Metrics Helix
    let metricsRafId;
    const animateMetrics = () => {
      metricsRafId = requestAnimationFrame(animateMetrics);
      if (helixRef.current && metricsRendererRef.current) {
        const speed = isFastSpin ? 0.08 : 0.004;
        helixRef.current.rotation.x += 0.002;
        helixRef.current.rotation.y += speed;
        metricsRendererRef.current.render(metricsSceneRef.current, metricsCameraRef.current);
      }
    };
    
    initBackground();
    initMetricsViz();
    animateBackground();
    animateMetrics();
    window.addEventListener("resize", onWindowResize);

    return () => {
      window.removeEventListener("resize", onWindowResize);
      if (bgRendererRef.current) bgRendererRef.current.dispose();
      if (metricsRendererRef.current) metricsRendererRef.current.dispose();
      cancelAnimationFrame(bgRafId);
      cancelAnimationFrame(metricsRafId);
    };
  }, [isFastSpin, showSecondBgHelix]);

  // === UI & Backend Logic ===
  const runAnalysis = async (isDemo = false) => {
    if (!isDemo && !selectedFile) {
      setErrorMessage("Please select a file first!");
      return;
    }

    setIsAnalyzing(true);
    setIsFastSpin(true);
    setShowSecondBgHelix(false); // Hide second helix at the start
    setErrorMessage("");
    setMetrics({ totalReads: 0, totalSpecies: 0 });
    setResults([]);
    setNewSpeciesMessage("");

    let data;
    if (isDemo) {
      await new Promise((r) => setTimeout(r, 900));
      data = {
        metrics: { totalSpecies: 50, totalReads: 10243 },
        species: [
          { name: "Saccharomyces cerevisiae", confidence: 0.98, id: "1" },
          { name: "Escherichia coli", confidence: 0.91, id: "2" },
          { name: "Homo sapiens", confidence: 0.85, id: "3" },
          { name: "Gallus gallus", confidence: 0.72, id: "4" },
          { name: "Oryza sativa", confidence: 0.65, id: "5" },
        ],
      };
    } else {
      try {
        const formData = new FormData();
        formData.append("file", selectedFile);
        const resp = await axios.post(BACKEND_URL, formData, {
          headers: { "Content-Type": "multipart/form-data" },
          timeout: 120000,
        });
        data = resp.data;
      } catch (err) {
        console.error("Backend error:", err);
        setErrorMessage(
          "Upload failed or backend unreachable. Showing demo data instead."
        );
        await new Promise((r) => setTimeout(r, 800));
        data = {
          metrics: { totalSpecies: 12, totalReads: 7654 },
          species: [
            { name: "Fallback_species_A", confidence: 0.93, id: "f1" },
            { name: "Fallback_species_B", confidence: 0.88, id: "f2" },
          ],
        };
      }
    }

    let speciesList = [];
    if (Array.isArray(data)) {
      speciesList = data.map((d, i) => ({
        // FIX: Use sequence_id from the backend, as 'id' may not exist.
        id: d.id || d.sequence_id || `${i + 1}`,
        name: d.predicted_species || d.label || "Unknown",
        confidence: d.confidence || d.score || 0,
      }));
    } else {
      speciesList = data.species || [];
      if (data.metrics) setMetrics(data.metrics);
    }
    
    const previousSpeciesNames = new Set(previousResults.map(s => s.name));
    const newSpecies = speciesList.filter(s => !previousSpeciesNames.has(s.name));
    if (newSpecies.length > 0) {
      setNewSpeciesMessage(`New species found: ${newSpecies.map(s => s.name).join(", ")}`);
      setShowSecondBgHelix(true);
    } else {
      setShowSecondBgHelix(false);
    }

    setPreviousResults(speciesList);
    setResults(speciesList);
    setMetrics(prevMetrics => ({
      ...prevMetrics,
      totalSpecies: new Set(speciesList.map((s) => s.name)).size,
      totalReads: speciesList.length
    }));
    
    setIsAnalyzing(false);
    setIsFastSpin(false);
  };

  const handleFileChange = (e) => {
    const uploadedFile = e.target.files?.[0];
    if (uploadedFile) {
      setSelectedFile(uploadedFile);
      setErrorMessage("");
      setMetrics({ totalReads: 0, totalSpecies: 0 });
      setResults([]);
      setNewSpeciesMessage("");
    }
  };

  const handleDragOver = (e) => {
    e.preventDefault();
  };
  const handleDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    const dropped = e.dataTransfer.files?.[0];
    if (dropped) {
      setSelectedFile(dropped);
      setErrorMessage("");
      setMetrics({ totalReads: 0, totalSpecies: 0 });
      setResults([]);
      setNewSpeciesMessage("");
    }
  };

  const resetState = () => {
    setSelectedFile(null);
    setErrorMessage("");
    setMetrics({ totalReads: 0, totalSpecies: 0 });
    setResults([]);
    setPreviousResults([]);
    setNewSpeciesMessage("");
    if (fileInputRef.current) fileInputRef.current.value = "";
    setShowSecondBgHelix(false);
  };

  // UI helper: ConfidenceBar
  const ConfidenceBar = ({ confidence = 0 }) => (
    <div className="progress-track" style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <div
        style={{
          flex: 1,
          height: 12,
          background: "rgba(255,255,255,0.08)",
          borderRadius: 6,
          overflow: "hidden",
        }}
      >
        <div
          style={{
            width: `${Math.min(Math.max(confidence * 100, 0), 100)}%`,
            height: "100%",
            background: "linear-gradient(90deg,#0066ff,#00d4ff)",
            borderRadius: 6,
            transition: "width 0.7s",
          }}
        />
      </div>
    </div>
  );

  useEffect(() => {
    if (showSecondBgHelix && bgSceneRef.current && !secondBgGroupRef.current) {
        const createHelix = (color, reverse = false) => {
            const points = [];
            const numPoints = 300;
            const helixRadius = 1;
            const helixHeight = 3;
            for (let i = 0; i < numPoints; i++) {
                const t = (i / (numPoints - 1)) * Math.PI * 4;
                const x = reverse ? -helixRadius * Math.cos(t) : helixRadius * Math.cos(t);
                const y = helixHeight * (i / numPoints) - helixHeight / 2;
                const z = reverse ? -helixRadius * Math.sin(t) : helixRadius * Math.sin(t);
                points.push(new THREE.Vector3(x, y, z));
            }
            const geometry = new THREE.BufferGeometry().setFromPoints(points);
            const material = new THREE.PointsMaterial({
                color: color,
                size: 0.02,
                blending: THREE.AdditiveBlending,
                transparent: true,
                opacity: 0.8,
            });
            return new THREE.Points(geometry, material);
        };
        secondBgGroupRef.current = createHelix(0x00d4ff, true);
        bgSceneRef.current.add(secondBgGroupRef.current);
    } else if (!showSecondBgHelix && secondBgGroupRef.current) {
        bgSceneRef.current.remove(secondBgGroupRef.current);
        secondBgGroupRef.current.geometry.dispose();
        secondBgGroupRef.current.material.dispose();
        secondBgGroupRef.current = null;
    }
  }, [showSecondBgHelix]);


  return (
    <>
      <style>
        {`
/* inline CSS preserved from your single-file UI for exact look */
:root{--primary-blue:#0066ff;--secondary-cyan:#00d4ff;--accent-green:#00ff88;--deep-ocean:#001133;--dark-blue:#002266;--light-blue:#f0f8ff;--glass-bg:rgba(255,255,255,0.05);--glass-border:rgba(255,255,255,0.1);--text-primary:#ffffff;--text-secondary:#b3d9ff;--text-muted:#7eb3ff;--shadow-glow:0 0 40px rgba(0,102,255,0.3);--shadow-card:0 20px 60px rgba(0,17,51,0.4);--gradient-primary:linear-gradient(135deg,var(--primary-blue) 0%,var(--secondary-cyan) 100%);--gradient-bg:radial-gradient(ellipse at center,var(--dark-blue) 0%,var(--deep-ocean) 100%);}
*{margin:0;padding:0;box-sizing:border-box}html,body,#root{height:100%;width:100%;overflow:hidden}body{font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto, 'Oxygen','Ubuntu','Cantarell',sans-serif;background:var(--gradient-bg);color:var(--text-primary);line-height:1.6;-webkit-font-smoothing:antialiased;position:relative;overflow-x:hidden}
#background-canvas{position:fixed;top:0;left:0;width:100vw;height:100vh;z-index:0;pointer-events:none}
.main-container{position:relative;z-index:10;min-height:100vh;display:flex;flex-direction:column;overflow-y:auto;padding:2rem}
.header{padding:2rem 2rem 1rem;text-align:center;position:relative}
.header::before{content:'';position:absolute;top:0;left:50%;transform:translateX(-50%);width:100px;height:4px;background:var(--gradient-primary);border-radius:2px;box-shadow:var(--shadow-glow)}
.logo{font-size:clamp(2rem,5vw,3.5rem);font-weight:800;background:var(--gradient-primary);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;margin-bottom:0.5rem;letter-spacing:-0.02em;text-shadow:0 0 30px rgba(0,102,255,0.5)}
.tagline{font-size:1.1rem;color:var(--text-secondary);margin-bottom:0.5rem;font-weight:400}
.subtitle{font-size:0.9rem;color:var(--text-muted);max-width:600px;margin:0 auto}
.content-grid{flex:1;display:grid;grid-template-columns:1fr;gap:2rem;padding:2rem;max-width:1400px;margin:0 auto;width:100%}
@media(min-width:768px){.content-grid{grid-template-columns:repeat(2,1fr)}.results-panel{grid-column:1 / -1}}
@media(min-width:1200px){.content-grid{grid-template-columns:400px 1fr 400px;gap:2.5rem}.upload-panel{grid-column:1}.metrics-panel{grid-column:2}.results-panel{grid-column:3}}
.glass-panel{background:rgba(255,255,255,0.05);backdrop-filter:blur(20px);border:1px solid rgba(255,255,255,0.1);border-radius:20px;padding:2rem;box-shadow:0 20px 60px rgba(0,17,51,0.4);transition:all 0.4s cubic-bezier(0.4,0,0.2,1);position:relative;overflow:hidden}
.glass-panel::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;background:linear-gradient(135deg,#0066ff 0%,#00d4ff 100%);opacity:0.8}
.glass-panel:hover{transform:translateY(-5px);box-shadow:0 30px 80px rgba(0,17,51,0.6);border-color:rgba(255,255,255,0.2)}
.panel-header{display:flex;align-items:center;gap:1rem;margin-bottom:1.5rem}
.panel-icon{width:24px;height:24px;color:var(--secondary-cyan);filter:drop-shadow(0 0 10px var(--secondary-cyan))}
.panel-title{font-size:1.25rem;font-weight:600;color:var(--text-primary);margin:0}
.panel-subtitle{font-size:0.85rem;color:var(--text-muted);margin-top:0.25rem}
.upload-zone{border:2px dashed var(--glass-border);border-radius:12px;padding:2rem;text-align:center;background:rgba(255,255,255,0.02);transition:all 0.3s ease;margin-bottom:1.5rem;cursor:pointer;position:relative;overflow:hidden}
.upload-zone:hover{border-color:var(--primary-blue);background:rgba(0,102,255,0.05);transform:scale(1.02)}
.upload-zone.dragover{border-color:var(--accent-green);background:rgba(0,255,136,0.1);transform:scale(1.05)}
.upload-icon{width:48px;height:48px;color:var(--secondary-cyan);margin:0 auto 1rem;filter:drop-shadow(0 0 20px var(--secondary-cyan));animation:float 3s ease-in-out infinite}
@keyframes float{0%,100%{transform:translateY(0px)}50%{transform:translateY(-10px)}}
.upload-text{color:var(--text-secondary);font-weight:500}
.file-input{display:none}
.file-name{margin-top:1rem;padding:0.5rem 1rem;background:rgba(0,102,255,0.1);border-radius:8px;color:var(--accent-green);font-size:0.85rem;font-weight:500}
.button-group{display:flex;gap:1rem;flex-wrap:wrap;margin-top:1.5rem}
.btn{padding:0.75rem 1.5rem;border:none;border-radius:10px;font-weight:600;font-size:0.9rem;cursor:pointer;transition:all 0.3s ease;position:relative;overflow:hidden;text-decoration:none;display:inline-flex;align-items:center;gap:0.5rem}
.btn:disabled{opacity:0.5;cursor:not-allowed;transform:none !important}
.btn-primary{background:var(--gradient-primary);color:white;box-shadow:0 10px 30px rgba(0,102,255,0.4)}
.btn-primary:hover:not(:disabled){transform:translateY(-2px);box-shadow:0 15px 40px rgba(0,102,255,0.6)}
.btn-secondary{background:rgba(255,255,255,0.1);color:var(--text-primary);border:1px solid var(--glass-border)}
.btn-secondary:hover:not(:disabled){background:rgba(255,255,255,0.2);transform:translateY(-2px)}
.btn-ghost{background:transparent;color:var(--text-muted);border:1px dashed var(--glass-border)}
.btn-ghost:hover:not(:disabled){color:var(--text-primary);border-color:var(--primary-blue)}
.status-indicator{margin-top:1rem;padding:0.75rem 1rem;background:rgba(0,255,136,0.1);border:1px solid rgba(0,255,136,0.3);border-radius:8px;font-size:0.85rem;color:var(--accent-green);display:flex;align-items:center;gap:0.5rem}
.status-dot{width:8px;height:8px;background:var(--accent-green);border-radius:50%;animation:pulse 2s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:0.5}}
.metrics-grid{display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin-bottom:1.5rem}
.metric-card{background:rgba(255,255,255,0.03);border:1px solid var(--glass-border);border-radius:12px;padding:1.5rem;text-align:center;transition:all 0.3s ease;position:relative;overflow:hidden}
.metric-card::before{content:'';position:absolute;top:0;left:0;right:0;height:1px;background:var(--gradient-primary)}
.metric-card:hover{transform:scale(1.05);background:rgba(255,255,255,0.08)}
.metric-value{font-size:2.5rem;font-weight:800;background:var(--gradient-primary);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;margin-bottom:0.5rem;filter:drop-shadow(0 0 20px rgba(0,102,255,0.5))}
.metric-label{font-size:0.8rem;color:var(--text-muted);text-transform:uppercase;letter-spacing:1px;font-weight:500}
.viz-container{height:200px;border-radius:12px;background:rgba(0,0,0,0.2);border:1px solid var(--glass-border);overflow:hidden;position:relative}
#metrics-canvas{width:100%;height:100%}
.results-container{max-height:400px;overflow-y:auto;padding-right:0.5rem}
.results-container::-webkit-scrollbar{width:6px}
.results-container::-webkit-scrollbar-track{background:rgba(255,255,255,0.05);border-radius:3px}
.results-container::-webkit-scrollbar-thumb{background:var(--primary-blue);border-radius:3px}
.result-item{background:rgba(255,255,255,0.03);border:1px solid var(--glass-border);border-radius:10px;padding:1rem;margin-bottom:0.75rem;transition:all 0.3s ease;position:relative;overflow:hidden}
.result-item:hover{background:rgba(255,255,255,0.08);transform:translateX(5px);border-color:var(--primary-blue)}
.result-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:0.75rem}
.sequence-id{font-weight:600;color:var(--text-primary);font-size:0.9rem}
.species-name{font-weight:600;color:var(--accent-green);font-size:0.9rem;text-align:right;flex:1;margin-left:1rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.confidence-bar{display:flex;align-items:center;gap:0.75rem;margin-bottom:0.5rem}
.progress-track{flex:1;height:6px;background:rgba(255,255,255,0.1);border-radius:3px;overflow:hidden}
.progress-fill{height:100%;background:var(--gradient-primary);border-radius:3px;transition:width 0.8s cubic-bezier(0.4,0,0.2,1);position:relative}
.progress-fill::after{content:'';position:absolute;top:0;left:0;right:0;bottom:0;background:linear-gradient(90deg,transparent,rgba(255,255,255,0.4),transparent);animation:shimmer 2s infinite}
@keyframes shimmer{0%{transform:translateX(-100%)}100%{transform:translateX(100%)}}
.confidence-value{font-weight:700;color:var(--secondary-cyan);font-size:0.85rem;min-width:50px;text-align:right}
.empty-state{text-align:center;padding:3rem 1rem;color:var(--text-muted)}
.empty-icon{font-size:4rem;margin-bottom:1rem;opacity:0.5}
.empty-text{font-size:1rem;font-weight:500;color:var(--text-secondary);margin-bottom:0.5rem}
.empty-subtext{font-size:0.85rem;color:var(--text-muted)}
.footer{padding:2rem;text-align:center;border-top:1px solid var(--glass-border);background:rgba(0,0,0,0.2);margin-top:2rem}
.footer-content{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:1rem;max-width:1400px;margin:0 auto}
.footer-text{color:var(--text-muted);font-size:0.9rem}
.footer-brand{color:var(--text-primary);font-weight:700;background:var(--gradient-primary);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
@media(max-width:767px){.header{padding:1.5rem 1rem 1rem}.content-grid{padding:1rem;gap:1.5rem}.glass-panel{padding:1.5rem}.metrics-grid{grid-template-columns:1fr}.button-group{flex-direction:column}.btn{justify-content:center}.footer-content{flex-direction:column;text-align:center}}
.loading-overlay{position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,17,51,0.9);backdrop-filter:blur(10px);display:flex;align-items:center;justify-content:center;z-index:1000;opacity:0;visibility:hidden;transition:all 0.3s ease}
.loading-overlay.active{opacity:1;visibility:visible}
.loading-spinner{width:60px;height:60px;border:3px solid rgba(255,255,255,0.05);border-top:3px solid var(--primary-blue);border-radius:50%;animation:spin 1s linear infinite}
@keyframes spin{0%{transform:rotate(0deg)}100%{transform:rotate(360deg)}}

/* New species glow animation */
.new-species-glow {
  animation: glow 1.5s ease-in-out infinite alternate;
}

@keyframes glow {
  from {
    text-shadow: 0 0 5px #00ff88, 0 0 10px #00ff88, 0 0 15px #00ff88;
  }
  to {
    text-shadow: 0 0 20px #00ff88, 0 0 30px #00ff88, 0 0 40px #00ff88;
  }
}
        `}
      </style>

      <div className="main-container container">
        <canvas ref={bgCanvasRef} id="background-canvas" />

        {isAnalyzing && (
          <div className="loading-overlay active">
            <div className="loading-spinner"></div>
          </div>
        )}

        <header className="header">
          <h1 className="logo">eDNA Biodiversity Analyzer</h1>
          <p className="tagline">Smart India Hackathon 2024</p>
          <p className="subtitle">
            Advanced AI-driven platform for environmental DNA analysis,
            species identification, and biodiversity assessment from deep-sea
            samples
          </p>
          <div style={{ position: "absolute", right: 20, top: 20, color: "#9fb4c8", fontSize: 13 }}>
            {backendStatus}
          </div>
        </header>

        <main className="content-grid">
          <section className="glass-panel upload-panel">
            <div className="panel-header">
              <svg className="panel-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                <polyline points="7,10 12,5 17,10" />
                <line x1="12" y1="5" x2="12" y2="19" />
              </svg>
              <div>
                <h3 className="panel-title">Sample Upload</h3>
                <p className="panel-subtitle">Upload FASTA files for species identification</p>
              </div>
            </div>

            <div className="upload-zone" onDragOver={handleDragOver} onDrop={handleDrop} onClick={() => fileInputRef.current?.click()}>
              <svg className="upload-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                <polyline points="14,2 14,8 20,8" />
                <line x1="16" y1="13" x2="8" y2="13" />
                <line x1="16" y1="17" x2="8" y2="17" />
                <polyline points="10,9 9,9 8,9" />
              </svg>
              <p className="upload-text">Click to select FASTA files<br /><small>or drag and drop here</small></p>
              <input ref={fileInputRef} type="file" className="file-input" onChange={handleFileChange} accept=".fa,.fasta" />
              {selectedFile && <div className="file-name">{selectedFile.name}</div>}
            </div>

            <div className="button-group">
              <button className="btn btn-primary" onClick={() => runAnalysis(false)} disabled={!selectedFile || isAnalyzing}>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="22,12 18,12 15,21 9,3 6,12 2,12" /></svg>
                Analyze Sample
              </button>
              <button className="btn btn-secondary" onClick={() => runAnalysis(true)} disabled={isAnalyzing}>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10" /><polygon points="10,8 16,12 10,16 10,8" /></svg>
                Demo Sample
              </button>
              <button className="btn btn-ghost" onClick={resetState} disabled={isAnalyzing}>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="1,4 1,10 7,10" /><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10" /></svg>
                Reset
              </button>
            </div>

            {errorMessage && (
              <div style={{ marginTop: 12, color: "#ff9b9b" }}>{errorMessage}</div>
            )}
            {!errorMessage && !isAnalyzing && selectedFile && (
              <div className="status-indicator"><div className="status-dot" /> File selected</div>
            )}
            {!errorMessage && !isAnalyzing && !selectedFile && (
              <div className="status-indicator"><div className="status-dot" /> Ready for analysis</div>
            )}
            {!errorMessage && isAnalyzing && (
              <div style={{ marginTop: 12, color: "#ffd57a" }}><div className="status-dot" style={{ background: "#ffd57a" }} /> Analyzing...</div>
            )}
          </section>

          <section className="glass-panel metrics-panel">
            <div className="panel-header">
              <svg className="panel-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="20" x2="18" y2="10" /><line x1="12" y1="20" x2="12" y2="4" /><line x1="6" y1="20" x2="6" y2="14" /></svg>
              <div>
                <h3 className="panel-title">Biodiversity Metrics</h3>
                <p className="panel-subtitle">Real-time analysis statistics</p>
              </div>
            </div>

            <div className="metrics-grid">
              <div className="metric-card">
                <div className="metric-value">{metrics.totalReads.toLocaleString()}</div>
                <div className="metric-label">Sequences</div>
              </div>
              <div className="metric-card">
                <div className="metric-value">{metrics.totalSpecies.toLocaleString()}</div>
                <div className="metric-label">Species</div>
              </div>
            </div>

            <div className="viz-container">
              <canvas ref={metricsCanvasRef} id="metrics-canvas"></canvas>
            </div>
            {newSpeciesMessage && (
              <div style={{ textAlign: 'center', marginTop: '1.5rem' }}>
                <p className="new-species-glow" style={{ color: 'var(--accent-green)', fontWeight: 'bold' }}>{newSpeciesMessage}</p>
              </div>
            )}
          </section>

          <section className="glass-panel results-panel">
            <div className="panel-header">
              <svg className="panel-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><polyline points="14,2 14,8 20,8" /><line x1="16" y1="13" x2="8" y2="13" /><line x1="16" y1="17" x2="8" y2="17" /></svg>
              <div>
                <h3 className="panel-title">Analysis Results</h3>
                <p className="panel-subtitle">Species predictions with confidence scores</p>
              </div>
            </div>

            <div className="results-container">
              {results.length > 0 ? (
                results.map((s) => (
                  <div className="result-item" key={s.id || s.name}>
                    <div className="result-header">
                      <span className="sequence-id">{s.id || "-"}</span>
                      <span className="species-name">{s.name} ({ (s.confidence * 100).toFixed(1) }%)</span>
                    </div>
                    <div style={{ marginTop: 6 }}>
                      <ConfidenceBar confidence={s.confidence || 0} />
                    </div>
                  </div>
                ))
              ) : (
                <div className="empty-state">
                  <div className="empty-icon">🧬</div>
                  <div className="empty-text">No analysis results yet</div>
                  <div className="empty-subtext">Upload a FASTA file to begin species identification</div>
                </div>
              )}
            </div>
          </section>
        </main>

        <footer className="footer">
          <div className="footer-content">
            <div className="footer-text">Built for Smart India Hackathon 2024 — Advanced eDNA Analysis Platform</div>
            <div className="footer-brand">Frontend by 6-Bit Coders</div>
          </div>
        </footer>
      </div>
    </>
  );
};

export default App;
