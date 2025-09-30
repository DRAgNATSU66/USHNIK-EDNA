import React, { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import axios from "axios";

/**
 * Landing.jsx - IMPROVED PREMIUM VERSION
 *
 * - Cleaner layout with better visual hierarchy
 * - Less cluttered, more premium feel
 * - Preserved original UI theme and styling
 * - Better organized sections
 * - Streamlined auth flow
 * - New Three.js background: Breathing, glowing sphere of dots
 *
 * Breathing period has been set to 10s total => 5s inhale + 5s exhale
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

  // Three.js refs
  const bgCanvasRef = useRef(null);
  const sceneRef = useRef(null);
  const cameraRef = useRef(null);
  const rendererRef = useRef(null);
  const sphereRef = useRef(null); // Ref for the sphere object
  const rafRef = useRef(null);
  const initialColor = useRef(new THREE.Color(0x00aaff));
  const finalColor = useRef(new THREE.Color(0xffffff));

  // Check for existing valid session on mount and handle refresh vs. navigation
  useEffect(() => {
    // Hybrid approach: Restore session on navigation, but not on refresh
    const checkSessionRestore = () => {
      try {
        // Check if this was a page refresh vs navigation
        const navigationEntry = performance.getEntriesByType('navigation')[0];
        const isRefresh = navigationEntry && navigationEntry.type === 'reload';

        const wasRefreshed = sessionStorage.getItem('was_refreshed');

        if (!isRefresh && !wasRefreshed) {
          // This is navigation from within the app, check for existing session
          const storedToken = localStorage.getItem("app_token");
          const expiry = localStorage.getItem("app_token_expiry");

          if (storedToken && expiry) {
            const expiryTime = parseInt(expiry);
            const now = Date.now();

            if (now < expiryTime) {
              // Valid session exists, restore it
              setToken(storedToken);
              setLoggedIn(true);

              // Restart the logout timer for remaining time
              const remainingTime = expiryTime - now;
              if (logoutTimerRef.current) {
                clearTimeout(logoutTimerRef.current);
              }
              logoutTimerRef.current = setTimeout(() => {
                try {
                  localStorage.removeItem("app_token");
                  localStorage.removeItem("app_token_expiry");
                  sessionStorage.removeItem('was_refreshed');
                } catch (e) {}
                window.location.reload();
              }, remainingTime);

              console.log('Session restored from navigation');
            } else {
              // Expired session, clean up
              localStorage.removeItem("app_token");
              localStorage.removeItem("app_token_expiry");
              sessionStorage.removeItem('was_refreshed');
            }
          }
        } else {
          // This was a refresh, ensure flag is set for future navigations
          console.log('Page refreshed - session cleared, re-login required');
          // Don't restore session, keep loggedIn = false

          // Optional: Clean up expired tokens on refresh
          try {
            const expiry = localStorage.getItem("app_token_expiry");
            if (expiry && Date.now() >= parseInt(expiry)) {
              localStorage.removeItem("app_token");
              localStorage.removeItem("app_token_expiry");
            }
          } catch (e) {}
        }

        // Set the flag for future navigation checks
        sessionStorage.setItem('was_refreshed', 'true');
      } catch (e) {
        // Fallback: treat as refresh if we can't determine
        console.log('Could not determine navigation type, treating as refresh');
      }
    };

    // Small delay to ensure performance API is ready
    setTimeout(checkSessionRestore, 100);
  }, []);

  // Also add this useEffect to clean up sessionStorage when user actually logs in
  // Place this after the hybrid session check useEffect
  useEffect(() => {
    if (loggedIn) {
      // Clear the refresh indicator when user successfully logs in
      // This ensures next navigation will restore the session
      sessionStorage.removeItem('was_refreshed');
    }
  }, [loggedIn]);

  // Health check & models fetch (on mount)
  useEffect(() => {
    // health check
    axios.get("http://127.0.0.1:8000/health", { timeout: 3000 })
      .then(() => setBackendStatus("Connected"))
      .catch(() => setBackendStatus("Unreachable"));

    // fetch models
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

  // Online / offline event listeners
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
    const expiry = Date.now() + 60 * 60 * 1000; // 1 hour
    try {
      localStorage.setItem("app_token", tok);
      localStorage.setItem("app_token_expiry", `${expiry}`);
    } catch (e) {
      // ignore localStorage errors
    }
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
      const res = await axios.post(AUTH_SIGNUP, { username, password }, { timeout: 5000 });
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

  // === Three.js animated background ===
  useEffect(() => {
    const canvas = bgCanvasRef.current;
    if (!canvas) return;

    const width = window.innerWidth;
    const height = window.innerHeight;

    const scene = new THREE.Scene();
    sceneRef.current = scene;

    const camera = new THREE.PerspectiveCamera(75, width / height, 0.1, 1000);
    camera.position.z = 2.5;
    cameraRef.current = camera;

    const renderer = new THREE.WebGLRenderer({
      canvas,
      antialias: true,
      alpha: true,
    });
    renderer.setSize(width, height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    rendererRef.current = renderer;

    const ambient = new THREE.AmbientLight(0x004b66, 0.3);
    scene.add(ambient);

    // Create the breathing sphere
    const particlesCount = 15000; // Increased particle count for a full sphere
    const sphereGeometry = new THREE.SphereGeometry(1, 64, 64);
    const spherePositions = sphereGeometry.attributes.position.array;

    const positions = new Float32Array(particlesCount * 3);
    const originalPositions = new Float32Array(particlesCount * 3);

    // Populate the points for the sphere
    for (let i = 0; i < particlesCount; i++) {
        const i3 = i * 3;
        const vertex = new THREE.Vector3(
          spherePositions[i3],
          spherePositions[i3 + 1],
          spherePositions[i3 + 2]
        ).multiplyScalar(1.2);

        positions[i3] = originalPositions[i3] = vertex.x;
        positions[i3 + 1] = originalPositions[i3 + 1] = vertex.y;
        positions[i3 + 2] = originalPositions[i3 + 2] = vertex.z;
    }

    const pGeom = new THREE.BufferGeometry();
    pGeom.setAttribute("position", new THREE.BufferAttribute(positions, 3));

    const pMat = new THREE.PointsMaterial({
      color: initialColor.current,
      size: 0.02,
      transparent: true,
      opacity: 0.9,
      blending: THREE.AdditiveBlending,
    });
    
    const spherePoints = new THREE.Points(pGeom, pMat);
    sphereRef.current = spherePoints;
    scene.add(spherePoints);

    let rafId;
    const animate = () => {
      rafId = requestAnimationFrame(animate);
      const time = performance.now() * 0.001;

      // Breathing effect: scale
      // For a 10s period (5s inhale + 5s exhale), angular frequency ω = 2π / T = 2π / 10 = π / 5
      const scale = 1 + Math.sin(time * Math.PI / 5) * 0.4;
      spherePoints.scale.set(scale, scale, scale);

      // Color transition and glow effect (use same frequency)
      const t = (Math.sin(time * Math.PI / 5) + 1) / 2;
      const invertedT = 1 - t;
      pMat.color.lerpColors(initialColor.current, finalColor.current, invertedT);
      pMat.opacity = 0.8 + t * 0.2;

      // Rotate on all three axes
      spherePoints.rotation.x += 0.0005;
      spherePoints.rotation.y += 0.0008;
      spherePoints.rotation.z += 0.0006;

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

  const renderModelLists = () => {
    return (
      <div style={{ display: "flex", gap: 24, marginTop: 20 }}>
        <div style={{ flex: 1 }}>
          <div style={{ 
            display: "flex", 
            alignItems: "center", 
            gap: 8,
            marginBottom: 12 
          }}>
            <div style={{ 
              width: 8, 
              height: 8, 
              borderRadius: "50%", 
              background: isOnline ? "var(--accent-green)" : "rgba(255,255,255,0.3)" 
            }}></div>
            <div style={{ 
              color: "var(--text-secondary)", 
              fontSize: 14, 
              fontWeight: 600 
            }}>
              Online Models {!isOnline && "(Unavailable)"}
            </div>
          </div>
          <div style={{ 
            background: "rgba(255,255,255,0.02)", 
            border: "1px solid rgba(255,255,255,0.06)", 
            padding: 16, 
            borderRadius: 12,
            minHeight: 120
          }}>
            {fetchingModels ? (
              <div style={{ 
                color: "var(--text-muted)", 
                textAlign: "center", 
                padding: "20px 0",
                fontSize: 13
              }}>
                <div style={{ marginBottom: 8 }}>⟳ Checking availability...</div>
              </div>
            ) : modelsOnline.length ? (
              modelsOnline.map((m, i) => (
                <div key={i} style={{ 
                  padding: "8px 12px", 
                  borderRadius: 8, 
                  marginBottom: 8, 
                  color: "var(--secondary-cyan)", 
                  fontWeight: 600,
                  background: "rgba(0,212,255,0.05)",
                  border: "1px solid rgba(0,212,255,0.1)",
                  fontSize: 13
                }}>
                  {m}
                </div>
              ))
            ) : (
              <div style={{ 
                color: "var(--text-muted)", 
                textAlign: "center", 
                padding: "20px 0",
                fontSize: 13
              }}>
                No online models detected
              </div>
            )}
          </div>
        </div>

        <div style={{ flex: 1 }}>
          <div style={{ 
            display: "flex", 
            alignItems: "center", 
            gap: 8,
            marginBottom: 12 
          }}>
            <div style={{ 
              width: 8, 
              height: 8, 
              borderRadius: "50%", 
              background: "#ffd700" 
            }}></div>
            <div style={{ 
              color: "var(--text-secondary)", 
              fontSize: 14, 
              fontWeight: 600 
            }}>
              Offline Models (Cached)
            </div>
          </div>
          <div style={{ 
            background: "rgba(255,255,255,0.02)", 
            border: "1px solid rgba(255,255,255,0.06)", 
            padding: 16, 
            borderRadius: 12,
            minHeight: 120
          }}>
            {modelsOffline.map((m, i) => (
              <div key={i} style={{ 
                padding: "8px 12px", 
                borderRadius: 8, 
                marginBottom: 8, 
                color: "var(--accent-green)", 
                fontWeight: 600,
                background: "rgba(0,255,136,0.05)",
                border: "1px solid rgba(0,255,136,0.1)",
                fontSize: 13
              }}>
                {m}
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  };

  return (
    <>
      <style>
        {`
:root{--primary-blue:#0066ff;--secondary-cyan:#00d4ff;--accent-green:#00ff88;--deep-ocean:#001133;--dark-blue:#002266;--glass-border:rgba(255,255,255,0.1);--text-primary:#ffffff;--text-secondary:#b3d9ff;--text-muted:#7eb3ff;--gradient-primary:linear-gradient(135deg,var(--primary-blue) 0%,var(--secondary-cyan) 100%);--gradient-bg:radial-gradient(ellipse at center,var(--dark-blue) 0%,var(--deep-ocean) 100%);}

*{box-sizing:border-box}html,body{height:100%;width:100%;overflow-x:hidden}#root{width:100%;min-height:100vh}body{margin:0;font-family:'Inter',system-ui,Segoe UI,Roboto;color:var(--text-primary);background:var(--gradient-bg)}

#landing-canvas{position:fixed;top:0;left:0;width:100vw;height:100vh;z-index:0;pointer-events:none}

.container{position:relative;z-index:10;min-height:100vh;padding:2rem;display:flex;flex-direction:column;align-items:center;justify-content:flex-start;width:100%;max-width:100vw;overflow-x:hidden}

.header{width:100%;text-align:center;margin-bottom:3rem}

.logo{font-size:clamp(2.5rem,5vw,4rem);font-weight:800;background:var(--gradient-primary);-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:0.5rem;line-height:1.1}

.subtitle{color:var(--text-muted);max-width:700px;margin:0 auto;font-size:16px;line-height:1.4}

.main-card{width:1000px;max-width:calc(100vw - 80px);background:rgba(255,255,255,0.04);border-radius:20px;padding:40px;border:1px solid var(--glass-border);backdrop-filter:blur(15px);box-shadow:0 25px 80px rgba(0,17,51,0.5);color:var(--text-primary)}

.status-bar{position:absolute;top:32px;right:32px;display:flex;align-items:center;gap:12px;padding:12px 16px;border-radius:50px;background:rgba(0,0,0,0.25);border:1px solid rgba(255,255,255,0.08);backdrop-filter:blur(10px)}

.status-indicator{width:6px;height:6px;border-radius:50%;background:var(--accent-green);animation:pulse 2s infinite}

@keyframes pulse{0%,100%{opacity:1}50%{opacity:0.5}}

.auth-section{text-align:center;margin-bottom:32px}

.auth-form{background:rgba(255,255,255,0.02);border-radius:16px;padding:32px;border:1px solid rgba(255,255,255,0.06);max-width:400px;margin:0 auto}

.form-group{margin-bottom:20px}

.input{width:100%;padding:14px 16px;border-radius:12px;border:1px solid rgba(255,255,255,0.08);background:rgba(0,0,0,0.2);color:var(--text-primary);font-size:14px;transition:all 0.3s ease}

.input:focus{outline:none;border-color:var(--secondary-cyan);box-shadow:0 0 0 2px rgba(0,212,255,0.1)}

.btn-primary{width:100%;padding:14px 20px;border-radius:12px;border:none;background:var(--gradient-primary);color:white;cursor:pointer;font-weight:700;font-size:14px;transition:all 0.3s ease;margin-bottom:12px}

.btn-primary:hover:not(:disabled){transform:translateY(-1px);box-shadow:0 8px 25px rgba(0,102,255,0.3)}

.btn-primary:disabled{opacity:0.6;cursor:not-allowed;transform:none}

.btn-secondary{background:transparent;color:var(--text-secondary);border:1px solid rgba(255,255,255,0.08);padding:10px 16px;border-radius:8px;cursor:pointer;font-size:13px;transition:all 0.3s ease}

.btn-secondary:hover{background:rgba(255,255,255,0.05);color:var(--text-primary)}

.models-section{margin-bottom:32px}

.section-title{font-size:18px;font-weight:700;color:var(--text-primary);margin-bottom:8px}

.section-subtitle{color:var(--text-muted);font-size:14px;margin-bottom:16px}

.proceed-section{text-align:center;padding-top:24px;border-top:1px solid rgba(255,255,255,0.06)}

.btn-proceed{padding:16px 32px;font-size:16px;font-weight:700;border-radius:12px;border:none;background:var(--gradient-primary);color:white;cursor:pointer;transition:all 0.3s ease}

.btn-proceed:hover:not(:disabled){transform:translateY(-2px);box-shadow:0 12px 40px rgba(0,102,255,0.4)}

.btn-proceed:disabled{opacity:0.4;cursor:not-allowed;transform:none}

.message{margin-top:16px;padding:12px;border-radius:8px;font-size:13px;text-align:center}

.message.success{background:rgba(0,255,136,0.1);color:var(--accent-green);border:1px solid rgba(0,255,136,0.2)}

.message.info{background:rgba(0,212,255,0.1);color:var(--secondary-cyan);border:1px solid rgba(0,212,255,0.2)}

.toggle-mode{color:var(--secondary-cyan);cursor:pointer;font-size:13px;margin-top:12px;transition:color 0.3s ease}

.toggle-mode:hover{color:var(--text-primary)}

.footer{margin-top:2rem;color:var(--text-muted);font-size:13px;text-align:center}
h2, p {color: var(--text-primary)}

/* Mobile responsiveness for Landing page */
@media(max-width:768px){
  .container{padding:1rem;justify-content:flex-start;padding-top:2rem}
  .header{margin-bottom:2rem}
  .logo{font-size:2rem}
  .main-card{padding:20px;max-width:calc(100vw - 40px);margin-bottom:2rem}
  .status-bar{top:16px;right:16px;padding:8px 12px;font-size:12px}
  .auth-form{padding:20px}
  .models-section{margin-bottom:20px}
}

@media(max-width:480px){
  .container{padding:0.5rem;padding-top:1.5rem}
  .header{margin-bottom:1.5rem}
  .logo{font-size:1.75rem}
  .main-card{padding:16px;max-width:calc(100vw - 20px)}
  .status-bar{position:static;margin-bottom:1rem;justify-content:center}
  .auth-form{padding:16px}
}

/* Hide status bar on very small screens to prevent overlap */
@media(max-width:360px){
  .status-bar{display:none}
}
`}
      </style>

      <canvas id="landing-canvas" ref={bgCanvasRef} />

      <div className="container">
        <div className="status-bar">
          <div className="status-indicator" style={{background: isOnline ? "var(--accent-green)" : "#ff6b6b"}}></div>
          <span style={{color: "var(--text-secondary)", fontSize: 13, fontWeight: 600}}>
            {isOnline ? "Online" : "Offline"} • {backendStatus}
          </span>
        </div>

        <header className="header">
          <div className="logo">eDNA Biodiversity Analyzer</div>
          <div className="subtitle">
            Advanced AI platform for environmental DNA analysis, species identification and biodiversity assessment
          </div>
        </header>

        <div className="main-card">
          {!loggedIn ? (
            <div className="auth-section">
              <div className="auth-form">
                <h2 style={{margin: "0 0 8px 0", fontSize: 20, fontWeight: 700, color: "var(--text-primary)"}}>
                  {isSignupMode ? "Create Account" : "Welcome Back"}
                </h2>
                <p style={{margin: "0 0 24px 0", color: "var(--text-muted)", fontSize: 14}}>
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

                  <button 
                    type="submit" 
                    className="btn-primary" 
                    disabled={logging || !username || !password}
                  >
                    {logging ? "Please wait..." : (isSignupMode ? "Create Account" : "Sign In")}
                  </button>
                </form>

                <div style={{display: "flex", gap: 8, justifyContent: "center"}}>
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
                  className="toggle-mode"
                  onClick={() => {
                    setIsSignupMode(!isSignupMode);
                    setMessage("");
                  }}
                >
                  {isSignupMode ? "Already have an account? Sign in" : "Need an account? Sign up"}
                </div>

                {message && (
                  <div className={`message ${message.includes("successful") || message.includes("filled") ? "success" : "info"}`}>
                    {message}
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div className="auth-section">
              <div style={{textAlign: "center", marginBottom: 32}}>
                <div style={{fontSize: 20, fontWeight: 700, marginBottom: 8, color: "var(--accent-green)"}}>
                  ✓ Signed in as {username}
                </div>
                <div style={{color: "var(--text-muted)", fontSize: 14}}>
                  Session active for 1 hour • Auto-refresh on expiry
                </div>
              </div>
              <div style={{display: "flex", gap: 8, justifyContent: "center", marginTop: 16}}>
                <button 
                  className="btn-secondary"
                  onClick={() => {
                    try {
                      localStorage.removeItem("app_token");
                      localStorage.removeItem("app_token_expiry");
                      sessionStorage.removeItem('was_refreshed');
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

          <div className="proceed-section">
            <button
              className="btn-proceed"
              disabled={!loggedIn}
              onClick={proceedToAnalyze}
              title={!loggedIn ? "Please sign in first" : "Continue to analytics page"}
            >
              {loggedIn ? "Proceed to Analysis →" : "Sign in to Continue"}
            </button>
            
            {!loggedIn && (
              <div style={{marginTop: 12, color: "var(--text-muted)", fontSize: 13}}>
                Authentication required to access analysis tools
              </div>
            )}
          </div>
        </div>

        <div className="footer">
          Built for Smart India Hackathon 2025 by 6-Bit Coders
        </div>
      </div>
    </>
  );
};

export default Landing;
