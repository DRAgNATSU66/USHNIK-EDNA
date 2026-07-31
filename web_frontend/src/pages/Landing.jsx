import React, { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";
import { healthCheck } from "../lib/api";

const css = `
:root{--primary-blue:#0066ff;--secondary-cyan:#00d4ff;--accent-green:#00ff88;--deep-ocean:#001133;--dark-blue:#002266;--glass-border:rgba(255,255,255,0.1);--text-primary:#ffffff;--text-secondary:#b3d9ff;--text-muted:#7eb3ff;--gradient-primary:linear-gradient(135deg,#0066ff 0%,#00d4ff 100%);--gradient-bg:radial-gradient(ellipse at center,#002266 0%,#001133 100%);}
*{box-sizing:border-box;margin:0;padding:0;}
html,body,#root{height:100%;width:100%;overflow:hidden !important;background:var(--gradient-bg) !important;}
body{font-family:'Inter',system-ui,Segoe UI,Roboto;color:var(--text-primary);}
.app-scroll{height:100vh;overflow:auto;-webkit-overflow-scrolling:touch;position:relative;scroll-behavior:smooth;}
#landing-canvas{position:fixed;top:0;left:0;width:100vw;height:100vh;z-index:0;pointer-events:none;}
.sv-container{position:relative;z-index:10;min-height:100vh;padding:2rem;display:flex;flex-direction:column;align-items:center;justify-content:flex-start;gap:1.5rem;}
.sv-header{width:100%;text-align:center;margin-bottom:1rem;}
.sv-logo{font-size:clamp(2rem,5vw,3.2rem);font-weight:800;background:var(--gradient-primary);-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:0.25rem;line-height:1.05;}
.sv-subtitle{color:var(--text-muted);max-width:840px;margin:0 auto;font-size:14px;line-height:1.4;}
.sv-card{width:100%;max-width:520px;background:rgba(255,255,255,0.04);border-radius:20px;padding:32px;border:1px solid var(--glass-border);backdrop-filter:blur(15px);box-shadow:0 25px 80px rgba(0,17,51,0.5);}
.sv-status-bar{position:fixed;top:18px;right:18px;display:flex;align-items:center;gap:12px;padding:8px 12px;border-radius:40px;background:rgba(0,0,0,0.2);border:1px solid rgba(255,255,255,0.06);backdrop-filter:blur(8px);z-index:20;}
.sv-dot{width:8px;height:8px;border-radius:50%;background:var(--accent-green);animation:pulse 2s infinite;}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:0.5}}
.sv-divider{border:none;border-top:1px solid rgba(255,255,255,0.08);margin:1.25rem 0;}
.sv-footer{margin-top:1.5rem;color:var(--text-muted);font-size:13px;text-align:center;}
.sv-cta-row{display:flex;gap:12px;flex-wrap:wrap;justify-content:center;}
.sv-btn{display:inline-flex;align-items:center;justify-content:center;padding:12px 28px;border-radius:999px;font-weight:600;font-size:14px;text-decoration:none;transition:transform 0.2s ease;}
.sv-btn:hover{transform:translateY(-2px);text-decoration:none;}
.sv-btn-primary{background:var(--gradient-primary);color:#ffffff;box-shadow:0 10px 30px rgba(0,102,255,0.4);}
.sv-btn-secondary{background:rgba(255,255,255,0.06);color:var(--text-primary);border:1px solid var(--glass-border);}
.app-scroll::-webkit-scrollbar{width:12px;}
.app-scroll::-webkit-scrollbar-track{background:transparent;}
.app-scroll::-webkit-scrollbar-thumb{background:linear-gradient(180deg,#00d4ff 0%,#0066ff 100%);border-radius:999px;min-height:28px;}
.app-scroll{scrollbar-width:thin;scrollbar-color:#00d4ff transparent;}
`;

export default function Landing() {
  const { isAuthenticated, loading } = useAuth();
  const navigate = useNavigate();
  const bgCanvasRef = useRef(null);
  const [backendStatus, setBackendStatus] = useState("Checking...");
  const [isOnline, setIsOnline] = useState(navigator.onLine);

  useEffect(() => {
    if (!loading && isAuthenticated) navigate("/dashboard", { replace: true });
  }, [isAuthenticated, loading, navigate]);

  useEffect(() => {
    const on = () => setIsOnline(true);
    const off = () => setIsOnline(false);
    window.addEventListener("online", on);
    window.addEventListener("offline", off);
    return () => { window.removeEventListener("online", on); window.removeEventListener("offline", off); };
  }, []);

  useEffect(() => {
    healthCheck()
      .then(() => setBackendStatus("Connected"))
      .catch(() => setBackendStatus("Unreachable"));
  }, []);

  useEffect(() => {
    const canvas = bgCanvasRef.current;
    if (!canvas) return;
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(75, window.innerWidth / window.innerHeight, 0.1, 1000);
    camera.position.z = 2.6;
    const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));

    const palette = [
      new THREE.Color(0x00ffaa), new THREE.Color(0x00d4ff),
      new THREE.Color(0x0066ff), new THREE.Color(0x00ff88),
    ];
    const particlesCount = 10000;
    const sphereGeom = new THREE.SphereGeometry(1, 64, 64);
    const srcPos = sphereGeom.attributes.position.array;
    const positions = new Float32Array(particlesCount * 3);
    for (let i = 0; i < particlesCount; i++) {
      const i3 = i * 3;
      const vIdx = i3 % srcPos.length;
      positions[i3] = srcPos[vIdx] * (1.05 + (Math.random() - 0.5) * 0.02);
      positions[i3 + 1] = srcPos[(vIdx + 1) % srcPos.length] * (1.05 + (Math.random() - 0.5) * 0.02);
      positions[i3 + 2] = srcPos[(vIdx + 2) % srcPos.length] * (1.05 + (Math.random() - 0.5) * 0.02);
    }
    const pGeom = new THREE.BufferGeometry();
    pGeom.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    const pMat = new THREE.PointsMaterial({
      size: 0.012, color: palette[0].clone(), transparent: true,
      opacity: 0.55, depthTest: false, blending: THREE.AdditiveBlending,
    });
    const sphere = new THREE.Points(pGeom, pMat);
    scene.add(sphere);

    const totalCycle = 14, minScale = 0.6, maxScale = 12.0;
    let rafId;
    const animate = () => {
      rafId = requestAnimationFrame(animate);
      const t = performance.now() * 0.001;
      const norm = 0.5 * (Math.sin((2 * Math.PI * t) / totalCycle - Math.PI / 2) + 1);
      const scale = minScale + (maxScale - minScale) * norm;
      sphere.scale.set(scale, scale, scale);
      const cycle = t * 0.12;
      const idx = Math.floor(cycle) % palette.length;
      pMat.color.copy(palette[idx]).lerp(palette[(idx + 1) % palette.length], cycle - Math.floor(cycle));
      pMat.opacity = 0.45 + 0.12 * (0.5 + 0.5 * Math.sin(t * 0.9));
      sphere.rotation.x += 0.0003;
      sphere.rotation.y += 0.0005;
      renderer.render(scene, camera);
    };
    animate();

    const onResize = () => {
      camera.aspect = window.innerWidth / window.innerHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(window.innerWidth, window.innerHeight);
    };
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      cancelAnimationFrame(rafId);
      try { pGeom.dispose(); pMat.dispose(); renderer.dispose(); } catch {}
    };
  }, []);

  return (
    <>
      <style>{css}</style>
      <div className="app-scroll">
        <canvas id="landing-canvas" ref={bgCanvasRef} />
        <div className="sv-status-bar">
          <div className="sv-dot" style={{ background: isOnline ? "var(--accent-green)" : "#ff6b6b" }} />
          <span style={{ color: "var(--text-secondary)", fontSize: 13, fontWeight: 600 }}>
            {isOnline ? "Online" : "Offline"} • Backend: {backendStatus}
          </span>
        </div>

        <div className="sv-container">
          <header className="sv-header">
            <div className="sv-logo">Synth Veda</div>
            <div className="sv-subtitle">
              eDNA Biodiversity Analysis Platform — AI-powered species identification
              and biodiversity assessment from environmental DNA samples
            </div>
          </header>

          <div className="sv-card">
            <h2 style={{ fontSize: 20, fontWeight: 700, marginBottom: 6, color: "var(--text-primary)" }}>
              Get started
            </h2>
            <p style={{ color: "var(--text-muted)", fontSize: 13, marginBottom: 20 }}>
              Sign in or create an account to submit samples and view results.
            </p>

            <div className="sv-cta-row">
              <Link to="/login" className="sv-btn sv-btn-primary">Sign in</Link>
              <Link to="/signup" className="sv-btn sv-btn-secondary">Create account</Link>
            </div>

            <hr className="sv-divider" />

            <div style={{ fontSize: 12, color: "var(--text-muted)", textAlign: "center", lineHeight: 1.6 }}>
              By signing in you agree that all analysis results are preliminary
              and require expert confirmation before use in scientific publications.
            </div>
          </div>

          <div className="sv-footer">
            Synth Veda · eDNA Biodiversity Analysis Platform
          </div>
        </div>
      </div>
    </>
  );
}
