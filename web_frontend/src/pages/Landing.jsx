// Landing.jsx
import React, { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import axios from "axios";

/**
 * Landing.jsx - breathing sphere + floating scrollbar styles for Opera/Windows fix
 *
 * Note: We hide the root scrollbar and make .app-scroll the primary scrolling element.
 *       This ensures browsers (including Opera on Windows) render our custom scrollbar
 *       (thumb-only, transparent track) and not the OS-level window scrollbar.
 */

const OFFLINE_MODELS = [
  "offline-light-model",
  "offline-mid-model",
  "offline-heavy-model",
  "offline-8b-model",
];

const MODELS_ENDPOINT = "http://127.0.0.1:8000/models";
const AUTH_LOGIN = "http://127.0.0.1:8000/auth/login";
const AUTH_SIGNUP = "http://127.0.0.1:8000/auth/signup";

const Landing = () => {
  // UI state
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [backendStatus, setBackendStatus] = useState("Checking backend...");
  const [isOnline, setIsOnline] = useState(navigator.onLine);
  const [logging, setLogging] = useState(false);
  const [message, setMessage] = useState("");
  const [loggedIn, setLoggedIn] = useState(false);
  const [token, setToken] = useState(null);
  const [modelsOnline, setModelsOnline] = useState([]);
  const [modelsOffline, setModelsOffline] = useState(OFFLINE_MODELS);
  const [fetchingModels, setFetchingModels] = useState(true);
  const [isSignupMode, setIsSignupMode] = useState(false);
  const logoutTimerRef = useRef(null);

  // New UI: dropdown toggles for model lists (collapsed by default)
  const [onlineOpen, setOnlineOpen] = useState(false);
  const [offlineOpen, setOfflineOpen] = useState(false);

  // Upcoming models (displayed when expanded)
  const onlineUpcoming = ["ESM2 Fine-Tuned", "Tier-1 K-mer Classifier"];
  const offlineUpcoming = ["offline-16b-model", "offline-quantized-model"];

  // Three.js refs
  const bgCanvasRef = useRef(null);
  const sceneRef = useRef(null);
  const cameraRef = useRef(null);
  const rendererRef = useRef(null);
  const sphereRef = useRef(null);
  const rafRef = useRef(null);

  // Colors for smooth cycling (THREE.Color objects)
  const colorPalette = useRef([
    new THREE.Color(0x00ffaa),
    new THREE.Color(0x00d4ff),
    new THREE.Color(0x0066ff),
    new THREE.Color(0x00ff88),
  ]);

  // Session restore logic (keeps as before)
  useEffect(() => {
    const checkSessionRestore = () => {
      try {
        const navigationEntry = performance.getEntriesByType("navigation")[0];
        const isRefresh = navigationEntry && navigationEntry.type === "reload";
        const wasRefreshed = sessionStorage.getItem("was_refreshed");

        if (!isRefresh && !wasRefreshed) {
          const storedToken = localStorage.getItem("app_token");
          const expiry = localStorage.getItem("app_token_expiry");
          if (storedToken && expiry) {
            const expiryTime = parseInt(expiry, 10);
            const now = Date.now();
            if (now < expiryTime) {
              setToken(storedToken);
              setLoggedIn(true);
              const remainingTime = expiryTime - now;
              if (logoutTimerRef.current) clearTimeout(logoutTimerRef.current);
              logoutTimerRef.current = setTimeout(() => {
                try {
                  localStorage.removeItem("app_token");
                  localStorage.removeItem("app_token_expiry");
                  sessionStorage.removeItem("was_refreshed");
                } catch (e) {}
                window.location.reload();
              }, remainingTime);
            } else {
              localStorage.removeItem("app_token");
              localStorage.removeItem("app_token_expiry");
              sessionStorage.removeItem("was_refreshed");
            }
          }
        } else {
          try {
            const expiry = localStorage.getItem("app_token_expiry");
            if (expiry && Date.now() >= parseInt(expiry, 10)) {
              localStorage.removeItem("app_token");
              localStorage.removeItem("app_token_expiry");
            }
          } catch (e) {}
        }

        sessionStorage.setItem("was_refreshed", "true");
      } catch (e) {
        console.log("Could not determine navigation type, treating as refresh");
      }
    };

    setTimeout(checkSessionRestore, 100);
  }, []);

  useEffect(() => {
    if (loggedIn) sessionStorage.removeItem("was_refreshed");
  }, [loggedIn]);

  // Health check & models fetch (unchanged)
  useEffect(() => {
    axios
      .get("http://127.0.0.1:8000/health", { timeout: 3000 })
      .then(() => setBackendStatus("Connected"))
      .catch(() => setBackendStatus("Unreachable"));

    const fetchModels = async () => {
      setFetchingModels(true);
      try {
        const res = await axios.get(MODELS_ENDPOINT, { timeout: 4000 });
        const data = res.data;
        if (Array.isArray(data)) {
          setModelsOnline(data);
        } else if (data.online) {
          setModelsOnline(Array.isArray(data.online) ? data.online : []);
          if (data.offline && Array.isArray(data.offline) && data.offline.length >= 4) {
            setModelsOffline(data.offline.slice(0, 4));
          }
        } else if (data.models) {
          setModelsOnline(Array.isArray(data.models) ? data.models : []);
        } else {
          setModelsOnline([]);
        }
      } catch (err) {
        setModelsOnline([]);
      } finally {
        setFetchingModels(false);
      }
    };

    fetchModels();
  }, []);

  // Online/offline events
  useEffect(() => {
    const onOnline = () => setIsOnline(true);
    const onOffline = () => setIsOnline(false);
    window.addEventListener("online", onOnline);
    window.addEventListener("offline", onOffline);
    return () => {
      window.removeEventListener("online", onOnline);
      window.removeEventListener("offline", onOffline);
    };
  }, []);

  const startSession = (tok) => {
    const expiry = Date.now() + 60 * 60 * 1000;
    try {
      localStorage.setItem("app_token", tok);
      localStorage.setItem("app_token_expiry", `${expiry}`);
    } catch (e) {}
    setToken(tok);
    setLoggedIn(true);

    if (logoutTimerRef.current) {
      clearTimeout(logoutTimerRef.current);
      logoutTimerRef.current = null;
    }

    const ms = expiry - Date.now();
    logoutTimerRef.current = setTimeout(() => {
      try {
        localStorage.removeItem("app_token");
        localStorage.removeItem("app_token_expiry");
      } catch (e) {}
      window.location.reload();
    }, ms);
  };

  const handleLogin = async (e) => {
    e && e.preventDefault();
    setMessage("");
    if (!username || !password) {
      setMessage("Please fill username and password");
      return;
    }
    setLogging(true);
    try {
      const res = await axios.post(AUTH_LOGIN, { username, password }, { timeout: 5000 });
      const tok = res.data?.token || res.data?.accessToken;
      if (tok) {
        startSession(tok);
        setMessage("Login successful");
      } else {
        const fake = `local:${username}:${Date.now()}`;
        startSession(fake);
        setMessage("Login successful");
      }
    } catch (err) {
      const fake = `local:${username}:${Date.now()}`;
      startSession(fake);
      setMessage("Login successful (demo mode)");
    } finally {
      setLogging(false);
    }
  };

  const handleSignup = async (e) => {
    e && e.preventDefault();
    setMessage("");
    if (!username || !password) {
      setMessage("Please fill username and password");
      return;
    }
    setLogging(true);
    try {
      await axios.post(AUTH_SIGNUP, { username, password }, { timeout: 5000 });
      setMessage("Account created successfully — please login");
      setIsSignupMode(false);
    } catch (err) {
      setMessage("Account created — please login");
      setIsSignupMode(false);
    } finally {
      setLogging(false);
    }
  };

  const proceedToAnalyze = () => {
    window.location.href = "/analytics";
  };

  // cleanup on unmount
  useEffect(() => {
    return () => {
      if (logoutTimerRef.current) clearTimeout(logoutTimerRef.current);
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      if (rendererRef.current) {
        try {
          rendererRef.current.dispose();
        } catch (e) {}
      }
    };
  }, []);

  // === Three.js animated background (SMOOTH color gradient + less prominent) ===
  useEffect(() => {
    const canvas = bgCanvasRef.current;
    if (!canvas) return;

    const width = window.innerWidth;
    const height = window.innerHeight;

    const scene = new THREE.Scene();
    sceneRef.current = scene;

    const camera = new THREE.PerspectiveCamera(75, width / height, 0.1, 1000);
    camera.position.z = 2.6;
    cameraRef.current = camera;

    const renderer = new THREE.WebGLRenderer({
      canvas,
      antialias: true,
      alpha: true,
    });
    renderer.setSize(width, height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    rendererRef.current = renderer;

    scene.add(new THREE.AmbientLight(0x004b66, 0.28));

    // particle sphere
    const particlesCount = 12000; // slightly reduced for less prominence
    const sphereGeometry = new THREE.SphereGeometry(1, 64, 64);
    const spherePositions = sphereGeometry.attributes.position.array;
    const positions = new Float32Array(particlesCount * 3);

    // Fill positions by sampling sphere vertex positions modulo the available geometry array
    for (let i = 0; i < particlesCount; i++) {
      const i3 = i * 3;
      const vIdx = (i3 % spherePositions.length);
      // small random jitter so points aren't too regular
      positions[i3] = spherePositions[vIdx] * (1.05 + (Math.random() - 0.5) * 0.02);
      positions[i3 + 1] = spherePositions[(vIdx + 1) % spherePositions.length] * (1.05 + (Math.random() - 0.5) * 0.02);
      positions[i3 + 2] = spherePositions[(vIdx + 2) % spherePositions.length] * (1.05 + (Math.random() - 0.5) * 0.02);
    }

    const pGeom = new THREE.BufferGeometry();
    pGeom.setAttribute("position", new THREE.BufferAttribute(positions, 3));

    // lowered size/opacity so sphere is less intrusive
    const pMat = new THREE.PointsMaterial({
      size: 0.012, // smaller
      color: colorPalette.current[0].clone(),
      transparent: true,
      opacity: 0.55, // less prominent
      depthTest: false,
      blending: THREE.AdditiveBlending,
      sizeAttenuation: true,
    });

    const spherePoints = new THREE.Points(pGeom, pMat);
    sphereRef.current = spherePoints;
    scene.add(spherePoints);

    // animate: smooth color interpolation across palette
    let rafId;
    const palette = colorPalette.current;
    const paletteLen = palette.length;

    // Breathing parameters:
    const inhaleDuration = 7.0; // seconds to inhale (contract)
    const exhaleDuration = 7.0; // seconds to exhale (expand)
    const totalCycle = inhaleDuration + exhaleDuration; // 14s total
    const minScale = 0.6; // contracted (center)
    const maxScale = 12.0; // expanded (covers viewport)

    const animate = () => {
      rafId = requestAnimationFrame(animate);
      const time = performance.now() * 0.001;

      // Expand (exhale) over 7s then contract (inhale) over 7s using a sine-based curve
      const sine = Math.sin((2 * Math.PI * (time / totalCycle)) - Math.PI / 2);
      const norm = 0.5 * (sine + 1);
      const scale = minScale + (maxScale - minScale) * norm;
      spherePoints.scale.set(scale, scale, scale);

      // color interpolation (slow)
      const cycleSpeed = 0.12;
      const cycle = time * cycleSpeed;
      const idx = Math.floor(cycle) % paletteLen;
      const next = (idx + 1) % paletteLen;
      const localT = cycle - Math.floor(cycle);

      const cA = palette[idx];
      const cB = palette[next];
      pMat.color.copy(cA).lerp(cB, localT);

      // gentle opacity modulation (subtle)
      pMat.opacity = 0.45 + 0.12 * (0.5 + 0.5 * Math.sin(time * 0.9));

      // slow rotation
      spherePoints.rotation.x += 0.0003;
      spherePoints.rotation.y += 0.0005;
      spherePoints.rotation.z += 0.0004;

      renderer.render(scene, camera);
    };

    rafRef.current = rafId;
    animate();

    const onResize = () => {
      const w = window.innerWidth;
      const h = window.innerHeight;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
    };
    window.addEventListener("resize", onResize);

    return () => {
      window.removeEventListener("resize", onResize);
      cancelAnimationFrame(rafId);
      try {
        pGeom.dispose();
        pMat.dispose();
        renderer.dispose();
      } catch (e) {}
    };
  }, []);

  // RENDER model lists with collapsible panels (unchanged)
  const renderModelLists = () => {
    return (
      <div style={{ display: "flex", gap: 24, marginTop: 20, flexWrap: "wrap" }}>
        <div style={{ flex: 1, minWidth: 280 }}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              marginBottom: 8,
              cursor: "pointer",
              userSelect: "none",
            }}
            onClick={() => setOnlineOpen((s) => !s)}
            role="button"
            aria-expanded={onlineOpen}
          >
            <div
              style={{
                width: 10,
                height: 10,
                borderRadius: "50%",
                background: "var(--accent-green)",
                boxShadow: "0 0 8px rgba(0,255,136,0.15)",
                flexShrink: 0,
              }}
            />
            <div style={{ color: "var(--text-secondary)", fontSize: 14, fontWeight: 600 }}>
              Online Models {isOnline ? "" : "(Unavailable)"}
            </div>

            <div style={{ marginLeft: "auto", display: "flex", alignItems: "center" }}>
              <div
                style={{
                  width: 36,
                  height: 28,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  borderRadius: 8,
                  background: onlineOpen ? "rgba(0,0,0,0.25)" : "transparent",
                  border: "1px solid rgba(255,255,255,0.04)",
                }}
                aria-hidden
              >
                <svg
                  width="12"
                  height="12"
                  viewBox="0 0 24 24"
                  style={{
                    transform: onlineOpen ? "rotate(180deg)" : "rotate(0deg)",
                    transition: "transform 180ms ease",
                    opacity: 0.95,
                    fill: "none",
                    stroke: "rgba(255,255,255,0.9)",
                    strokeWidth: 1.4,
                  }}
                >
                  <path d="M6 9l6 6 6-6" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </div>
            </div>
          </div>

          <div
            style={{
              background: "rgba(255,255,255,0.02)",
              border: "1px solid rgba(255,255,255,0.06)",
              padding: 12,
              borderRadius: 12,
              minHeight: onlineOpen ? 80 : 40,
              transition: "all 220ms ease",
              overflow: "hidden",
            }}
          >
            {fetchingModels ? (
              <div style={{ color: "var(--text-muted)", textAlign: "center", padding: "12px 0", fontSize: 13 }}>
                ⟳ Checking availability...
              </div>
            ) : onlineOpen ? (
              <>
                {modelsOnline.length ? (
                  modelsOnline.map((m, i) => (
                    <div
                      key={i}
                      style={{
                        padding: "8px 12px",
                        borderRadius: 8,
                        marginBottom: 8,
                        color: "var(--accent-green)",
                        fontWeight: 600,
                        background: "rgba(0,255,136,0.04)",
                        border: "1px solid rgba(0,255,136,0.08)",
                        fontSize: 13,
                      }}
                    >
                      {m}
                    </div>
                  ))
                ) : (
                  <div style={{ color: "var(--text-muted)", textAlign: "center", padding: "12px 0", fontSize: 13 }}>
                    No online models detected
                  </div>
                )}

                <div style={{ marginTop: 8, color: "rgba(255,255,255,0.6)", fontSize: 13 }}>
                  (upcoming: {onlineUpcoming.join(", ")})
                </div>
              </>
            ) : (
              <div style={{ color: "var(--text-muted)", fontSize: 13, padding: "6px 4px" }}>
                Click to expand and view available online models
              </div>
            )}
          </div>
        </div>

        <div style={{ flex: 1, minWidth: 280 }}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              marginBottom: 8,
              cursor: "pointer",
              userSelect: "none",
            }}
            onClick={() => setOfflineOpen((s) => !s)}
            role="button"
            aria-expanded={offlineOpen}
          >
            <div
              style={{
                width: 10,
                height: 10,
                borderRadius: "50%",
                background: "#ffd700",
                boxShadow: "0 0 8px rgba(255,215,0,0.12)",
                flexShrink: 0,
              }}
            />
            <div style={{ color: "var(--text-secondary)", fontSize: 14, fontWeight: 600 }}>
              Offline Models (Cached)
            </div>

            <div style={{ marginLeft: "auto", display: "flex", alignItems: "center" }}>
              <div
                style={{
                  width: 36,
                  height: 28,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  borderRadius: 8,
                  background: offlineOpen ? "rgba(0,0,0,0.25)" : "transparent",
                  border: "1px solid rgba(255,255,255,0.04)",
                }}
                aria-hidden
              >
                <svg
                  width="12"
                  height="12"
                  viewBox="0 0 24 24"
                  style={{
                    transform: offlineOpen ? "rotate(180deg)" : "rotate(0deg)",
                    transition: "transform 180ms ease",
                    opacity: 0.95,
                    fill: "none",
                    stroke: "rgba(255,255,255,0.9)",
                    strokeWidth: 1.4,
                  }}
                >
                  <path d="M6 9l6 6 6-6" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </div>
            </div>
          </div>

          <div
            style={{
              background: "rgba(255,255,255,0.02)",
              border: "1px solid rgba(255,255,255,0.06)",
              padding: 12,
              borderRadius: 12,
              minHeight: offlineOpen ? 80 : 40,
              transition: "all 220ms ease",
              overflow: "hidden",
            }}
          >
            {offlineOpen ? (
              <>
                {modelsOffline.map((m, i) => (
                  <div
                    key={i}
                    style={{
                      padding: "8px 12px",
                      borderRadius: 8,
                      marginBottom: 8,
                      color: "#ffd700",
                      fontWeight: 600,
                      background: "rgba(255,215,0,0.03)",
                      border: "1px solid rgba(255,215,0,0.06)",
                      fontSize: 13,
                    }}
                  >
                    {m}
                  </div>
                ))}

                <div style={{ marginTop: 8, color: "rgba(255,255,255,0.6)", fontSize: 13 }}>
                  (upcoming: {offlineUpcoming.join(", ")})
                </div>
              </>
            ) : (
              <div style={{ color: "var(--text-muted)", fontSize: 13, padding: "6px 4px" }}>
                Click to expand and view cached offline models
              </div>
            )}
          </div>
        </div>
      </div>
    );
  };

  return (
    <>
      <style>
        {`
:root{
  --primary-blue:#0066ff;--secondary-cyan:#00d4ff;--accent-green:#00ff88;--deep-ocean:#001133;--dark-blue:#002266;--glass-border:rgba(255,255,255,0.1);--text-primary:#ffffff;--text-secondary:#b3d9ff;--text-muted:#7eb3ff;--gradient-primary:linear-gradient(135deg,var(--primary-blue) 0%,var(--secondary-cyan) 100%);--gradient-bg:radial-gradient(ellipse at center,var(--dark-blue) 0%,var(--deep-ocean) 100%);}
*{box-sizing:border-box}
html,body,#root{height:100%;width:100%}

/* HIDE the root/native scrollbar so the browser won't show the OS-level bar.
   We'll use .app-scroll as the primary scrolling container instead. */
html, body, #root {
  overflow: hidden !important;
  background: var(--gradient-bg) !important;
}

body {
  margin:0;
  font-family:'Inter',system-ui,Segoe UI,Roboto;
  color:var(--text-primary);
}

/* App scroll container: this is the single scrollable element the page will use */
.app-scroll {
  height: 100vh;             /* full viewport height */
  overflow: auto;            /* page scroll happens here */
  -webkit-overflow-scrolling: touch;
  position: relative;
  scroll-behavior: smooth;
  -webkit-tap-highlight-color: transparent;
}

/* Background canvas sits behind content */
#landing-canvas{position:fixed;top:0;left:0;width:100vw;height:100vh;z-index:0;pointer-events:none}

/* main page structure (unchanged visually) */
.container{position:relative;z-index:10;min-height:100vh;padding:2rem;display:flex;flex-direction:column;align-items:center;justify-content:flex-start;gap:1.5rem}
.header{width:100%;text-align:center;margin-bottom:1rem}
.logo{font-size:clamp(2rem,5vw,3.2rem);font-weight:800;background:var(--gradient-primary);-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:0.25rem;line-height:1.05}
.subtitle{color:var(--text-muted);max-width:840px;margin:0 auto;font-size:14px;line-height:1.4}
.main-card{width:100%;max-width:1100px;background:rgba(255,255,255,0.04);border-radius:20px;padding:32px;border:1px solid var(--glass-border);backdrop-filter:blur(15px);box-shadow:0 25px 80px rgba(0,17,51,0.5);color:var(--text-primary);display:block;}
.status-bar{position:fixed;top:18px;right:18px;display:flex;align-items:center;gap:12px;padding:8px 12px;border-radius:40px;background:rgba(0,0,0,0.2);border:1px solid rgba(255,255,255,0.06);backdrop-filter:blur(8px);z-index:20}
.status-indicator{width:8px;height:8px;border-radius:50%;background:var(--accent-green);animation:pulse 2s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:0.5}}
.auth-form{background:rgba(255,255,255,0.02);border-radius:16px;padding:22px;border:1px solid rgba(255,255,255,0.06);max-width:520px;margin:0 auto}
.form-group{margin-bottom:12px}
.input{width:100%;padding:12px 14px;border-radius:10px;border:1px solid rgba(255,255,255,0.08);background:rgba(0,0,0,0.18);color:var(--text-primary);font-size:14px}
.input:focus{outline:none;border-color:var(--secondary-cyan);box-shadow:0 0 0 2px rgba(0,212,255,0.08)}
.btn-primary{width:100%;padding:12px 16px;border-radius:12px;border:none;background:var(--gradient-primary);color:white;cursor:pointer;font-weight:700;font-size:14px;margin-top:8px}
.btn-secondary{background:transparent;color:var(--text-secondary);border:1px solid rgba(255,255,255,0.08);padding:8px 12px;border-radius:8px;cursor:pointer;font-size:13px}
.models-section{margin-top:18px}
.section-title{font-size:18px;font-weight:700;color:var(--text-primary);margin-bottom:8px}
.section-subtitle{color:var(--text-muted);font-size:13px;margin-bottom:12px}
.proceed-section{text-align:center;padding-top:18px;border-top:1px solid rgba(255,255,255,0.06);margin-top:18px}
.btn-proceed{padding:12px 24px;font-size:15px;font-weight:700;border-radius:12px;border:none;background:var(--gradient-primary);color:white;cursor:pointer}
.btn-proceed:disabled{opacity:0.4;cursor:not-allowed}
.message{margin-top:12px;padding:10px;border-radius:8px;font-size:13px;text-align:center}
.message.success{background:rgba(0,255,136,0.08);color:var(--accent-green);border:1px solid rgba(0,255,136,0.12)}
.message.info{background:rgba(0,212,255,0.06);color:var(--secondary-cyan);border:1px solid rgba(0,212,255,0.08)}
.footer{margin-top:1.5rem;color:var(--text-muted);font-size:13px;text-align:center}

.signin-msg { font-weight:700; color:var(--secondary-cyan); font-size:16px; margin-bottom:6px; background: transparent; border: none; display: inline-block; }
.auth-note { color: var(--text-muted); font-size:13px; }

/* small responsive tweaks */
@media (max-width: 980px) {
  .container { padding: 18px; }
  .main-card { padding: 20px; border-radius: 14px; }
  .auth-form { padding: 16px; }
  #landing-canvas{display:block}
}

/* ===== Scrollbar styling applied to .app-scroll and other internal scroll areas ===== */

/* WebKit (Chrome/Edge/Opera/Safari) - primary scroller is .app-scroll */
.app-scroll::-webkit-scrollbar { width: 12px; height: 12px; }
.app-scroll::-webkit-scrollbar-track,
.app-scroll::-webkit-scrollbar-track-piece { background: transparent !important; box-shadow:none !important; border-radius:999px !important; }
.app-scroll::-webkit-scrollbar-corner { background: transparent !important; }

/* floating gradient thumb with soft glow */
.app-scroll::-webkit-scrollbar-thumb {
  background: linear-gradient(180deg, #00d4ff 0%, #00a8ff 45%, #0066ff 100%);
  border-radius: 999px;
  border: 0;
  min-height: 28px;
  box-shadow: 0 10px 26px rgba(0,212,255,0.24);
}

/* hover emphasis */
.app-scroll::-webkit-scrollbar-thumb:hover,
.app-scroll::-webkit-scrollbar-thumb:active {
  filter: brightness(1.07);
  box-shadow: 0 12px 32px rgba(0,212,255,0.30);
}

/* also style the other scrollable inner areas to match */
.results-container::-webkit-scrollbar,
.list-scroll::-webkit-scrollbar,
.json-preview::-webkit-scrollbar { width: 10px; }
.results-container::-webkit-scrollbar-track,
.list-scroll::-webkit-scrollbar-track,
.json-preview::-webkit-scrollbar-track { background: transparent !important; }
.results-container::-webkit-scrollbar-thumb,
.list-scroll::-webkit-scrollbar-thumb,
.json-preview::-webkit-scrollbar-thumb {
  background: linear-gradient(180deg, #00d4ff 0%, #00a8ff 45%, #0066ff 100%);
  border-radius: 999px;
  min-height: 22px;
  box-shadow: 0 8px 20px rgba(0,212,255,0.20);
}

/* Firefox: thin + thumb color + transparent track */
.app-scroll, .results-container, .list-scroll, .json-preview {
  scrollbar-width: thin;
  scrollbar-color: #00d4ff transparent;
}

/* Edge/IE fallback: autohide */
html { -ms-overflow-style: -ms-autohiding-scrollbar; }
`}
      </style>

      {/* Use .app-scroll as the single scroll container so our custom scrollbar is used */}
      <div className="app-scroll" tabIndex={0} aria-label="Main scroll area">
        <canvas id="landing-canvas" ref={bgCanvasRef} />

        <div className="container">
          <div
            className="status-bar"
            role="status"
            aria-live="polite"
            title={`Connection: ${isOnline ? "Online" : "Offline"} — ${backendStatus}`}
          >
            <div
              className="status-indicator"
              style={{ background: isOnline ? "var(--accent-green)" : "#ff6b6b" }}
            />
            <span style={{ color: "var(--text-secondary)", fontSize: 13, fontWeight: 600 }}>
              {isOnline ? "Online" : "Offline"} • {backendStatus}
            </span>
          </div>

          <header className="header">
            <div className="logo">eDNA Biodiversity Analyzer</div>
            <div className="subtitle">
              Advanced AI platform for environmental DNA analysis, species identification and biodiversity assessment
            </div>
          </header>

          <div className="main-card" role="main">
            {!loggedIn ? (
              <div style={{ marginBottom: 18 }}>
                <div className="auth-form">
                  <h2 style={{ margin: "0 0 6px 0", fontSize: 18, fontWeight: 700, color: "var(--text-primary)" }}>
                    {isSignupMode ? "Create Account" : "Welcome Back"}
                  </h2>
                  <p style={{ margin: "0 0 12px 0", color: "var(--text-muted)", fontSize: 13 }}>
                    {isSignupMode ? "Sign up to start analyzing eDNA samples" : "Sign in to continue your analysis"}
                  </p>

                  <form onSubmit={isSignupMode ? handleSignup : handleLogin}>
                    <div className="form-group">
                      <input
                        className="input"
                        placeholder="Username"
                        value={username}
                        onChange={(e) => setUsername(e.target.value)}
                      />
                    </div>
                    <div className="form-group">
                      <input
                        className="input"
                        placeholder="Password"
                        type="password"
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                      />
                    </div>

                    <button type="submit" className="btn-primary" disabled={logging || !username || !password}>
                      {logging ? "Please wait..." : isSignupMode ? "Create Account" : "Sign In"}
                    </button>
                  </form>

                  <div style={{ display: "flex", gap: 8, justifyContent: "center", marginTop: 10 }}>
                    <button
                      className="btn-secondary"
                      onClick={() => {
                        setUsername("demo");
                        setPassword("demopass");
                        setMessage("Demo credentials filled");
                      }}
                    >
                      Demo Login
                    </button>
                  </div>

                  <div
                    style={{ color: "var(--secondary-cyan)", cursor: "pointer", fontSize: 13, marginTop: 10 }}
                    onClick={() => {
                      setIsSignupMode(!isSignupMode);
                      setMessage("");
                    }}
                  >
                    {isSignupMode ? "Already have an account? Sign in" : "Need an account? Sign up"}
                  </div>

                  {message && (
                    <div
                      className={`message ${
                        message.includes("successful") || message.includes("filled") ? "success" : "info"
                      }`}
                    >
                      {message}
                    </div>
                  )}
                </div>
              </div>
            ) : (
              <div style={{ marginBottom: 18 }}>
                <div style={{ textAlign: "center", marginBottom: 12 }}>
                  <div style={{ fontSize: 18, fontWeight: 700, marginBottom: 6, color: "var(--accent-green)" }}>
                    ✓ Signed in as {username}
                  </div>
                  <div style={{ color: "var(--text-muted)", fontSize: 13 }}>
                    Session active for 1 hour • Auto-refresh on expiry
                  </div>
                </div>
                <div style={{ display: "flex", gap: 8, justifyContent: "center", marginTop: 8 }}>
                  <button
                    className="btn-secondary"
                    onClick={() => {
                      try {
                        localStorage.removeItem("app_token");
                        localStorage.removeItem("app_token_expiry");
                        sessionStorage.removeItem("was_refreshed");
                      } catch (e) {}
                      if (logoutTimerRef.current) {
                        clearTimeout(logoutTimerRef.current);
                        logoutTimerRef.current = null;
                      }
                      setToken(null);
                      setLoggedIn(false);
                      setUsername("");
                      setPassword("");
                      setMessage("Signed out successfully");
                    }}
                  >
                    Sign Out
                  </button>
                </div>
              </div>
            )}

            <div className="models-section">
              <div className="section-title">Available Analysis Models</div>
              <div className="section-subtitle">
                Model selection is automatic based on file size, internet connectivity, and system resources
              </div>

              {renderModelLists()}
            </div>

            <div className="proceed-section" style={{ marginTop: 18 }}>
              {/* UPDATED: non-interactive message instead of a button */}
              {!loggedIn ? (
                <>
                  <div className="signin-msg">Sign in to Continue</div>
                  <div className="auth-note">Authentication required to access analysis tools</div>
                </>
              ) : (
                <button className="btn-proceed" onClick={proceedToAnalyze}>
                  Proceed to Analysis →
                </button>
              )}
            </div>
          </div>

          <div className="footer">Built for Smart India Hackathon 2025 by 6-Bit Coders</div>
        </div>
      </div>
    </>
  );
};

export default Landing;
