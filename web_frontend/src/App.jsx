import React, { useState, useEffect, useRef } from "react";
import * as THREE from "three";
import axios from "axios";
import { analyzeFastaFile } from "./api"; // keep api helper

// Full App.jsx — replace your current file with this exact content.
const App = () => {
  // === Config ===
  const MAX_FILE_SIZE = 500 * 1024 * 1024; // 500 MB
  const VALID_EXTENSIONS = [".fasta", ".json"]; // strict per requirement
  const NOVELTY_THRESHOLD = 0.40; // 40%

  // === State Management ===
  const [selectedFile, setSelectedFile] = useState(null);
  const [parsedJsonPreview, setParsedJsonPreview] = useState(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false); // controls loading overlay/buffer
  const [vizActive, setVizActive] = useState(false); // keeps throbbing/spin active after analysis
  const [isFastSpin, setIsFastSpin] = useState(false); // controls faster spin (kept while vizActive if desired)
  const [metrics, setMetrics] = useState({ totalReads: 0, totalSpecies: 0 });
  const [results, setResults] = useState([]);
  const [previousResults, setPreviousResults] = useState([]); // To track for new species
  const [errorMessage, setErrorMessage] = useState("");
  const [backendStatus, setBackendStatus] = useState("Checking backend...");
  const [newSpeciesMessage, setNewSpeciesMessage] = useState("");
  const [showSecondBgHelix, setShowSecondBgHelix] = useState(false);
  const [blueGlowActive, setBlueGlowActive] = useState(false); // Blue helix glow toggle (faint overlay)
  const [modelUsed, setModelUsed] = useState(""); // show which model was used

  // === Refs for DOM elements and THREE.js objects ===
  const bgCanvasRef = useRef(null);
  const metricsCanvasRef = useRef(null);
  const fileInputRef = useRef(null);

  // THREE.js refs for background scene
  const bgSceneRef = useRef(null);
  const bgCameraRef = useRef(null);
  const bgRendererRef = useRef(null);
  const bgGroupRef = useRef(null); // The blue helix (base)
  const blueGlowRef = useRef(null); // glow overlay for blue helix
  const secondBgGroupRef = useRef(null); // The new helix that appears (red)
  const particlesRef = useRef(null);

  // THREE.js refs for metrics scene
  const metricsSceneRef = useRef(null);
  const metricsCameraRef = useRef(null);
  const metricsRendererRef = useRef(null);
  const helixRef = useRef(null); // The small helix

  // store metric strand refs & their glow overlays for dynamic brightness control
  const metricsGreenRef = useRef(null);
  const metricsRedRef = useRef(null);
  const metricsGreenGlowRef = useRef(null);
  const metricsRedGlowRef = useRef(null);

  // === Backend Endpoints ===
  const BASE_URL = "http://127.0.0.1:8000";
  const BACKEND_URL = `${BASE_URL}/analyze`;
  const HEALTH_URL = `${BASE_URL}/health`;

  // === Redirect to landing page on reload (ONLY reloads) ===
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
        // store base values for throbbing effect
        material.userData = { baseSize: 0.02, baseOpacity: 0.8 };
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

      // Green strand — increased contrast: slightly larger, more saturated, full opacity
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
        color: 0x00e65a, // richer green for stronger contrast
        size: 0.065,     // slightly larger
        blending: THREE.AdditiveBlending,
        transparent: true,
        opacity: 1.0,    // stronger, solid look
        sizeAttenuation: true,
        depthTest: false,   // <--- Prevent depth sorting popping
        depthWrite: false,  // <--- Prevent depth buffer writes (keeps additive blending stable)
      });
      greenMaterial.userData = { baseSize: 0.065, baseOpacity: 1.0 };
      const greenStrand = new THREE.Points(greenGeometry, greenMaterial);
      // ensure consistent draw order relative to glow
      greenStrand.renderOrder = 2;
      helixGroup.add(greenStrand);
      metricsGreenRef.current = greenStrand;

      // green glow overlay (larger, faint) — slightly stronger glow
      const greenGlowGeom = new THREE.BufferGeometry().setFromPoints(greenPoints);
      const greenGlowMat = new THREE.PointsMaterial({
        color: 0x00e65a,
        size: 0.12,
        blending: THREE.AdditiveBlending,
        transparent: true,
        opacity: 0.18,
        sizeAttenuation: true,
        depthTest: false,  // <--- keep glow always visible / not occluded in odd frames
        depthWrite: false,
      });
      greenGlowMat.userData = { baseSize: 0.12, baseOpacity: 0.18 };
      const greenGlow = new THREE.Points(greenGlowGeom, greenGlowMat);
      greenGlow.renderOrder = 1; // draw glow before the main strand or keep consistent
      helixGroup.add(greenGlow);
      metricsGreenGlowRef.current = greenGlow;

      // Red strand — increased contrast: richer red, larger size, full opacity
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
        color: 0xff3b3b, // brighter, punchier red
        size: 0.06,
        blending: THREE.AdditiveBlending,
        transparent: true,
        opacity: 1.0,
        sizeAttenuation: true,
        depthTest: false, // <--- same fix for red strand
        depthWrite: false,
      });
      redMaterial.userData = { baseSize: 0.06, baseOpacity: 1.0 };
      const redStrand = new THREE.Points(redGeometry, redMaterial);
      redStrand.renderOrder = 2;
      helixGroup.add(redStrand);
      metricsRedRef.current = redStrand;

      // red glow overlay — slightly stronger glow
      const redGlowGeom = new THREE.BufferGeometry().setFromPoints(redPoints);
      const redGlowMat = new THREE.PointsMaterial({
        color: 0xff3b3b,
        size: 0.12,
        blending: THREE.AdditiveBlending,
        transparent: true,
        opacity: 0.18,
        sizeAttenuation: true,
        depthTest: false,
        depthWrite: false,
      });
      redGlowMat.userData = { baseSize: 0.12, baseOpacity: 0.18 };
      const redGlow = new THREE.Points(redGlowGeom, redGlowMat);
      redGlow.renderOrder = 1;
      helixGroup.add(redGlow);
      metricsRedGlowRef.current = redGlow;

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

        // If blue glow overlay exists, match its rotation to the base helix
        if (blueGlowRef.current) {
          blueGlowRef.current.rotation.x = bgGroupRef.current.rotation.x;
          blueGlowRef.current.rotation.y = bgGroupRef.current.rotation.y;
        }

        // Throbbing (pulse) effect for all relevant glow materials when vizActive
        const now = performance.now() * 0.001; // seconds

        // === THROBBING frequency adjustments:
        // base 3.0; previous multipliers (0.7 * 0.85 * 0.8) kept; final multiplier unchanged
        const THROB_FREQ = 3.0 * 0.7 * 0.85 * 0.8; // ≈ 1.428

        if (vizActive) {
          const freq = THROB_FREQ;
          // Keep original amplitude for main bg and blueGlow but increase throbbing by +25%
          // original main amplitude was 0.5 -> now 0.5 * 1.25 = 0.625
          const mainAmp = 0.5 * 1.25; // 0.625
          const mainFactor = 1 + mainAmp * Math.sin(now * Math.PI * 2 * freq); // ±62.5% for bg & blueGlow

          // Reduced throbbing for color-changing helix: previous reduced amplitude was 0.15
          // increase that by +25% -> 0.15 * 1.25 = 0.1875
          const colorHelixAmp = 0.5 * 0.3 * 1.25; // 0.1875
          const colorFactor = 1 + colorHelixAmp * Math.sin(now * Math.PI * 2 * freq); // ±18.75%

          // BG group main points (smaller pulse) — original 0.2 -> increased by 25% -> 0.25
          const smallAmp = 0.2 * 1.25; // 0.25

          // Blue glow
          if (blueGlowRef.current && blueGlowRef.current.material && blueGlowRef.current.material.userData) {
            const ud = blueGlowRef.current.material.userData;
            blueGlowRef.current.material.size = ud.baseSize * mainFactor * 1.0;
            blueGlowRef.current.material.opacity = Math.min(ud.baseOpacity * mainFactor * 1.2, 0.95);
          }
          // BG group main points (smaller pulse updated)
          if (bgGroupRef.current && bgGroupRef.current.material && bgGroupRef.current.material.userData) {
            const ud = bgGroupRef.current.material.userData;
            bgGroupRef.current.material.size = ud.baseSize * (1 + smallAmp * Math.sin(now * Math.PI * 2 * freq)); // smaller pulse increased
            bgGroupRef.current.material.opacity = Math.min(ud.baseOpacity * (1 + smallAmp * Math.sin(now * Math.PI * 2 * freq)), 0.95);
          }
          // Red second background helix (if present) throbbing — reduced amplitude but slightly stronger now
          if (secondBgGroupRef.current) {
            secondBgGroupRef.current.traverse((obj) => {
              if (obj instanceof THREE.Points && obj.material && obj.material.userData) {
                const ud = obj.material.userData;
                // use colorFactor (reduced throbbing) for size/opacity adjustments
                obj.material.size = (ud.baseSize || obj.material.size) * colorFactor * 1.0;
                obj.material.opacity = Math.min((ud.baseOpacity || obj.material.opacity) * colorFactor * 1.2, 0.95);
              }
            });
          }
        } else {
          // revert to base
          if (blueGlowRef.current && blueGlowRef.current.material && blueGlowRef.current.material.userData) {
            const ud = blueGlowRef.current.material.userData;
            blueGlowRef.current.material.size = ud.baseSize;
            blueGlowRef.current.material.opacity = ud.baseOpacity;
          }
          if (bgGroupRef.current && bgGroupRef.current.material && bgGroupRef.current.material.userData) {
            const ud = bgGroupRef.current.material.userData;
            bgGroupRef.current.material.size = ud.baseSize;
            bgGroupRef.current.material.opacity = ud.baseOpacity;
          }
          if (secondBgGroupRef.current) {
            secondBgGroupRef.current.traverse((obj) => {
              if (obj instanceof THREE.Points && obj.material && obj.material.userData) {
                const ud = obj.material.userData;
                obj.material.size = ud.baseSize;
                obj.material.opacity = ud.baseOpacity;
              }
            });
          }
        }

        // ===== Animated color cycling for the red helix (if present) =====
        // New behavior: blue hold 4s -> 0.5s transition -> red hold 5s -> 0.5s transition -> loop (total 10s)
        if (secondBgGroupRef.current) {
          const BLUE_HOLD = 4.0;
          const TRANS = 0.5; // <-- changed from 0.25 to 0.5s per your request
          const RED_HOLD = 5.0;
          const LOOP = BLUE_HOLD + TRANS + RED_HOLD + TRANS; // 10.0s
          const tLoop = (now % LOOP); // 0 .. LOOP
          const redColor = new THREE.Color(0xff2b4b);
          const blueColor = new THREE.Color(0x00d4ff);

          let currentColor = new THREE.Color();
          if (tLoop < BLUE_HOLD) {
            // solid blue
            currentColor.copy(blueColor);
          } else if (tLoop < BLUE_HOLD + TRANS) {
            // blue -> red transition (0 .. TRANS)
            const p = (tLoop - BLUE_HOLD) / TRANS; // 0..1
            currentColor.lerpColors(blueColor, redColor, p);
          } else if (tLoop < BLUE_HOLD + TRANS + RED_HOLD) {
            // solid red
            currentColor.copy(redColor);
          } else {
            // red -> blue transition
            const p = (tLoop - (BLUE_HOLD + TRANS + RED_HOLD)) / TRANS; // 0..1
            currentColor.lerpColors(redColor, blueColor, p);
          }

          // apply color to materials (and keep small subtle opacity nudge)
          secondBgGroupRef.current.traverse((obj) => {
            if (obj instanceof THREE.Points && obj.material) {
              try {
                if (!obj.material._tmpColor) obj.material._tmpColor = new THREE.Color();
                obj.material._tmpColor.copy(currentColor);
                obj.material.color.copy(obj.material._tmpColor);

                if (obj.material.userData && obj.material.userData.baseOpacity !== undefined) {
                  const base = obj.material.userData.baseOpacity;
                  // tiny breathing on opacity synced with hold phases (very subtle)
                  const breath = 0.02 * Math.sin((now % LOOP) * Math.PI * 2 / LOOP);
                  obj.material.opacity = Math.min(Math.max(base + breath, 0), 1);
                }
              } catch (e) {
                // ignore color application errors
              }
            }
          });
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
        // base small rotation speeds
        const baseSpeed = isFastSpin ? 0.08 : 0.004;
        // If vizActive, front helix spins 50% faster
        let speed = vizActive ? baseSpeed * 1.5 : baseSpeed;

        // === Slow the metrics helix by 25% (kept from original) ===
        speed *= 0.75;

        // === Increase y axis movement by 10% (applied after existing multipliers) ===
        speed *= 1.10; // new: +10%

        // === Increase x axis movement by additional +30% (on top of previous multipliers) ===
        // previous x multiplier chain was: 0.002 * 1.2 * 1.3 = 0.00312
        // apply an extra *1.3 to get +30% more => 0.00312 * 1.3 = 0.004056
        const xSpeed = 0.002 * 1.2 * 1.3 * 1.3; // = 0.004056

        // === OMIT z-axis movement entirely (per request) ===

        // Apply rotations
        helixRef.current.rotation.x += xSpeed;
        helixRef.current.rotation.y += speed;

        // NOTE: throbbing/pulse for metrics strands intentionally REMOVED per request.
        // We still respect vizActive for overall spinning but do not manipulate
        // material sizes/opacities for metrics strands anymore.

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
  }, [isFastSpin, showSecondBgHelix, vizActive]); // depend on vizActive instead of isAnalyzing

  // ---------------------------
  // Manage red second helix (unchanged creation but glow intensity reacts to vizActive)
  // ---------------------------
  useEffect(() => {
    if (showSecondBgHelix && bgSceneRef.current && !secondBgGroupRef.current) {
        // create a red, fluorescent-looking helix for the SECOND helix
        const createRedGlowingHelix = (reverse = false) => {
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

            // Use a brighter red hex and larger point size to make it pop.
            // AdditiveBlending + higher opacity gives a fluorescent effect.
            const material = new THREE.PointsMaterial({
                color: 0xff2b4b, // bright red initial
                size: 0.03,     // slightly larger than the blue helix points
                blending: THREE.AdditiveBlending,
                transparent: true,
                opacity: 0.95,
            });
            material.userData = { baseSize: 0.03, baseOpacity: 0.95 };

            const pointsMesh = new THREE.Points(geometry, material);

            // subtle emissive glow can be simulated by adding a faint, slightly larger
            // copy with even higher transparency and same color
            const glowGeometry = new THREE.BufferGeometry().setFromPoints(points);
            const glowMaterial = new THREE.PointsMaterial({
                color: 0xff2b4b,
                size: 0.06,
                blending: THREE.AdditiveBlending,
                transparent: true,
                opacity: 0.12,
              });
            glowMaterial.userData = { baseSize: 0.06, baseOpacity: 0.12 };
            const glowMesh = new THREE.Points(glowGeometry, glowMaterial);

            const group = new THREE.Group();
            group.add(pointsMesh);
            group.add(glowMesh);

            return group;
        };

        secondBgGroupRef.current = createRedGlowingHelix(true);
        bgSceneRef.current.add(secondBgGroupRef.current);
    } else if (!showSecondBgHelix && secondBgGroupRef.current) {
        bgSceneRef.current.remove(secondBgGroupRef.current);
        secondBgGroupRef.current.traverse((obj) => {
            if (obj.geometry) obj.geometry.dispose();
            if (obj.material) {
                if (Array.isArray(obj.material)) {
                    obj.material.forEach((m) => m.dispose && m.dispose());
                } else {
                    obj.material.dispose && obj.material.dispose();
                }
            }
        });
        secondBgGroupRef.current = null;
    }
  }, [showSecondBgHelix]);

  // ---------------------------
  // Manage blue helix glow overlay (NEW)
  // ---------------------------
  useEffect(() => {
    // Add a faint glowing overlay when blueGlowActive is true.
    try {
      if (blueGlowActive && bgSceneRef.current && bgGroupRef.current && !blueGlowRef.current) {
        // Copy position buffer to avoid sharing same typed array
        const posAttr = bgGroupRef.current.geometry.attributes.position;
        const copy = new Float32Array(posAttr.array.length);
        copy.set(posAttr.array);

        const geom = new THREE.BufferGeometry();
        geom.setAttribute("position", new THREE.BufferAttribute(copy, 3));

        // translucent larger points for glow
        const mat = new THREE.PointsMaterial({
          color: 0x00d4ff,
          size: 0.06,
          blending: THREE.AdditiveBlending,
          transparent: true,
          opacity: 0.15,
        });
        mat.userData = { baseSize: 0.06, baseOpacity: 0.15 };

        blueGlowRef.current = new THREE.Points(geom, mat);
        // place behind slightly (optional subtlety); keep same position so rotation sync looks correct
        bgSceneRef.current.add(blueGlowRef.current);
      }

      if (!blueGlowActive && blueGlowRef.current && bgSceneRef.current) {
        bgSceneRef.current.remove(blueGlowRef.current);
        // dispose
        try {
          if (blueGlowRef.current.geometry) blueGlowRef.current.geometry.dispose();
          if (blueGlowRef.current.material) blueGlowRef.current.material.dispose();
        } catch (e) {}
        blueGlowRef.current = null;
      }
    } catch (e) {
      // don't block UI on glow errors
      console.error("Blue glow error:", e);
    }
  }, [blueGlowActive]);

  // === UI & Backend Logic ===
  const runAnalysis = async (isDemo = false) => {
    if (!isDemo && !selectedFile) {
      setErrorMessage("Please select a file first!");
      return;
    }

    setIsAnalyzing(true);
    // activate visuals immediately so user sees response even during buffering
    setVizActive(true);
    setIsFastSpin(true); // keep fast spin while vizActive
    setShowSecondBgHelix(false); // Hide second helix at the start
    setErrorMessage("");
    setMetrics({ totalReads: 0, totalSpecies: 0 });
    setResults([]);
    setNewSpeciesMessage("");
    setModelUsed("");

    // NEW: enable blue helix glow when an analysis is triggered
    setBlueGlowActive(true);

    // Also intensify all helix glows (we trigger vizActive to drive the useEffect adjustments)

    let data;
    if (isDemo) {
      await new Promise((r) => setTimeout(r, 900));
      data = {
        modelUsed: "demo-model",
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
        // ✅ Use helper instead of inline axios.post
        data = await analyzeFastaFile(selectedFile);
      } catch (err) {
        console.error("Backend error:", err);
        setErrorMessage(
          "Upload failed or backend unreachable. Showing demo data instead."
        );
        await new Promise((r) => setTimeout(r, 800));
        data = {
          modelUsed: "mock-fallback",
          metrics: { totalSpecies: 12, totalReads: 7654 },
          species: [
            { name: "Fallback_species_A", confidence: 0.93, id: "f1" },
            { name: "Fallback_species_B", confidence: 0.88, id: "f2" },
          ],
        };
      }
    }

    // Normalize species list & set modelUsed if available
    let speciesList = [];
    if (Array.isArray(data)) {
      speciesList = data.map((d, i) => ({
        id: d.id || d.sequence_id || `${i + 1}`,
        name: d.predicted_species || d.label || d.name || "Unknown",
        confidence: (d.confidence || d.score || d.match || 0),
      }));
    } else {
      speciesList = (data.species || []).map((d, i) => ({
        id: d.id || d.sequence_id || `${i + 1}`,
        name: d.name || d.predicted_species || d.label || "Unknown",
        confidence: (d.confidence || d.score || d.match || 0),
      }));
      if (data.metrics) setMetrics(data.metrics);
    }
    if (data.modelUsed) setModelUsed(data.modelUsed);

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

    // hide loading overlay, but KEEP vizActive (so throbbing/spin remain)
    setIsAnalyzing(false);

    // ensure visuals persist after analysis - vizActive stays true (user requested this)
    // we keep isFastSpin true while vizActive is true; user can reset to turn them off
    setVizActive(true);
    setIsFastSpin(true);
    // Note: we intentionally keep the blue glow active after analysis until user resets,
    // as you requested it glows after analyze. Reset will turn it off.
  };

  // === File validation helpers ===
  const validateFile = (file) => {
    if (!file) return "No file selected.";
    const lower = file.name.toLowerCase();
    const validExt = VALID_EXTENSIONS.some((ext) => lower.endsWith(ext));
    if (!validExt) return "Invalid file type. Only .fasta and .json allowed.";
    if (file.size > MAX_FILE_SIZE) return "File exceeds 500 MB limit.";
    return null;
  };

  // helper: human-readable bytes
  const formatBytes = (bytes) => {
    if (!bytes && bytes !== 0) return "";
    const sizes = ["B", "KB", "MB", "GB", "TB"];
    if (bytes === 0) return "0 B";
    const i = Math.floor(Math.log(bytes) / Math.log(1024));
    const value = bytes / Math.pow(1024, i);
    return `${value.toFixed(value < 10 && i > 0 ? 2 : 1)} ${sizes[i]}`;
  };

  const handleFileChange = (e) => {
    const uploadedFile = e.target.files?.[0];
    if (uploadedFile) {
      const err = validateFile(uploadedFile);
      if (err) {
        setErrorMessage(err);
        setSelectedFile(null);
        setParsedJsonPreview(null);
        return;
      }
      setSelectedFile(uploadedFile);
      setErrorMessage("");
      setMetrics({ totalReads: 0, totalSpecies: 0 });
      setResults([]);
      setNewSpeciesMessage("");
      setParsedJsonPreview(null);

      // If JSON, parse preview on client
      if (uploadedFile.name.toLowerCase().endsWith(".json")) {
        const fr = new FileReader();
        fr.onload = () => {
          try {
            const j = JSON.parse(fr.result);
            const sequences = j.sequences || j.data || j.records || [];
            setParsedJsonPreview({ count: sequences.length || 0, samples: sequences.slice(0, 5) });
          } catch (e) {
            setParsedJsonPreview(null);
            setErrorMessage("Invalid JSON file structure.");
          }
        };
        fr.readAsText(uploadedFile);
      }
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
      const err = validateFile(dropped);
      if (err) {
        setErrorMessage(err);
        setSelectedFile(null);
        setParsedJsonPreview(null);
        return;
      }
      setSelectedFile(dropped);
      setErrorMessage("");
      setMetrics({ totalReads: 0, totalSpecies: 0 });
      setResults([]);
      setNewSpeciesMessage("");
      setParsedJsonPreview(null);
      if (dropped.name.toLowerCase().endsWith(".json")) {
        const fr = new FileReader();
        fr.onload = () => {
          try {
            const j = JSON.parse(fr.result);
            const sequences = j.sequences || j.data || j.records || [];
            setParsedJsonPreview({ count: sequences.length || 0, samples: sequences.slice(0, 5) });
          } catch (e) {
            setParsedJsonPreview(null);
            setErrorMessage("Invalid JSON file structure.");
          }
        };
        fr.readAsText(dropped);
      }
    }
  };

  const resetState = () => {
    setSelectedFile(null);
    setErrorMessage("");
    setMetrics({ totalReads: 0, totalSpecies: 0 });
    setResults([]);
    setPreviousResults([]);
    setNewSpeciesMessage("");
    setParsedJsonPreview(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
    setShowSecondBgHelix(false);
    // NEW: remove blue glow on reset
    setBlueGlowActive(false);
    // turn visual persistence off
    setVizActive(false);
    setIsFastSpin(false);
    setModelUsed("");
  };

  // UI helper: ConfidenceBar (with gradient visually)
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

  // === Exports & actions ===
  const exportCSV = () => {
    if (!results.length) return;
    const rows = [
      ["id", "species", "confidence_pct"],
      ...results.map((s) => [s.id || "", `"${(s.name || "").replace(/"/g, '""')}"`, ((s.confidence || 0) * 100).toFixed(2)]),
    ];
    const csv = rows.map((r) => r.join(",")).join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "analysis_report.csv";
    a.click();
    URL.revokeObjectURL(url);
  };

  const exportPDF = () => {
    // Simple print-based PDF: open a new window with a minimal report and call print()
    const html = `
      <html>
      <head>
        <title>Analysis Report</title>
        <style>
          body { font-family: Arial, sans-serif; color: #0b2b3a; padding: 20px; }
          h1 { color: #0066ff; }
          table { width: 100%; border-collapse: collapse; margin-top: 12px; }
          th, td { padding: 8px 10px; border: 1px solid #ddd; text-align:left; }
        </style>
      </head>
      <body>
        <h1>Analysis Report</h1>
        <p>Model used: ${modelUsed || "N/A"}</p>
        <p>Sequences: ${metrics.totalReads || 0} — Species: ${metrics.totalSpecies || 0}</p>
        <table>
          <thead><tr><th>#</th><th>Species</th><th>Confidence (%)</th></tr></thead>
          <tbody>
            ${results.map((s, i) => `<tr><td>${i+1}</td><td>${(s.name || "").replace(/</g, "&lt;")}</td><td>${((s.confidence||0)*100).toFixed(1)}</td></tr>`).join("")}
          </tbody>
        </table>
      </body>
      </html>
    `;
    const w = window.open("", "_blank", "noopener");
    if (!w) return;
    w.document.write(html);
    w.document.close();
    w.focus();
    // give time for rendering then print
    setTimeout(() => {
      w.print();
    }, 500);
  };

  const rerun = () => {
    // re-use same file
    runAnalysis(false);
  };

  const moveToAdmin = () => {
    // Very simple navigation to /admin route; assumes your app will handle that path.
    // If you don't have routing yet, this can be replaced by a callback or open admin in same app.
    try {
      window.location.href = "/admin";
    } catch (e) {
      console.warn("Navigate to admin:", e);
    }
  };

  // === Render ===
  return (
    <>
      <style>
        {`
/* inline CSS preserved from your single-file UI for exact look */
:root{--primary-blue:#0066ff;--secondary-cyan:#00d4ff;--accent-green:#00ff88;--deep-ocean:#001133;--dark-blue:#002266;--light-blue:#f0f8ff;--glass-bg:rgba(255,255,255,0.05);--glass-border:rgba(255,255,255,0.1);--text-primary:#ffffff;--text-secondary:#b3d9ff;--text-muted:#7eb3ff;--shadow-glow:0 0 40px rgba(0,102,255,0.3);--shadow-card:0 20px 60px rgba(0,17,51,0.4);--gradient-primary:linear-gradient(135deg,var(--primary-blue) 0%,var(--secondary-cyan) 100%);--gradient-bg:radial-gradient(ellipse at center,var(--dark-blue) 0%,var(--deep-ocean) 100%);}
*{margin:0;padding:0;box-sizing:border-box}html,body,#root{height:100%;width:100%;overflow:hidden}body{font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto, 'Oxygen','Ubuntu','Cantarell',sans-serif;background:var(--gradient-bg);color:var(--text-primary);line-height:1.6;-webkit-font-smoothing:antialiased;position:relative;overflow-x:hidden}
*{margin:0;padding:0;box-sizing:border-box}html,body{height:100%;width:100%;overflow-x:hidden}#root{width:100%;min-height:100vh}body{font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto, 'Oxygen','Ubuntu','Cantarell',sans-serif;background:var(--gradient-bg);color:var(--text-primary);line-height:1.6;-webkit-font-smoothing:antialiased;position:relative}
#background-canvas{position:fixed;top:0;left:0;width:100vw;height:100vh;z-index:0;pointer-events:none}
.main-container{position:relative;z-index:10;min-height:100vh;display:flex;flex-direction:column;width:100%;max-width:100vw;overflow-x:hidden;padding:1rem}
.header{padding:2rem 2rem 1rem;text-align:center;position:relative;overflow:hidden;word-wrap:break-word}
.header::before{content:'';position:absolute;top:0;left:50%;transform:translateX(-50%);width:100px;height:4px;background:var(--gradient-primary);border-radius:2px;box-shadow:var(--shadow-glow)}
.logo{font-size:clamp(1.5rem,5vw,3.5rem);font-weight:800;background:var(--gradient-primary);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;margin-bottom:0.5rem;letter-spacing:-0.02em;text-shadow:0 0 30px rgba(0,102,255,0.5);word-wrap:break-word;line-height:1.1}
.tagline{font-size:1.1rem;color:var(--text-secondary);margin-bottom:0.5rem;font-weight:400;word-wrap:break-word}
.subtitle{font-size:0.9rem;color:var(--text-muted);max-width:600px;margin:0 auto;word-wrap:break-word;line-height:1.5}
.content-grid{flex:1;display:grid;grid-template-columns:1fr;gap:1.5rem;padding:1rem 0;max-width:1400px;margin:0 auto;width:100%}
@media(min-width:768px){.content-grid{grid-template-columns:repeat(2,1fr);gap:2rem;padding:1.5rem 0}.results-panel{grid-column:1 / -1}}
@media(min-width:1200px){.content-grid{grid-template-columns:400px 1fr 400px;gap:2.5rem;padding:2rem 0}.upload-panel{grid-column:1}.metrics-panel{grid-column:2}.results-panel{grid-column:3}}
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
.button-group{display:flex;gap:1rem;flex-wrap:wrap;margin-top:1.5rem;width:100%}
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
.results-container{max-height:350px;overflow-y:auto;padding-right:0.5rem}
@media(max-height:800px){.results-container{max-height:250px}}
@media(max-height:600px){.results-container{max-height:200px}}
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
.footer{padding:2rem;text-align:center;border-top:1px solid var(--glass-border);background:rgba(0,0,0,0.2);margin-top:2rem;flex-shrink:0}
.footer-content{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:1rem;max-width:1400px;margin:0 auto}
.footer-text{color:var(--text-muted);font-size:0.9rem}
.footer-brand{color:var(--text-primary);font-weight:700;background:var(--gradient-primary);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
@media(max-width:767px){
  .main-container{padding:0.5rem}
  .header{padding:1rem 0.5rem;position:relative}
  .content-grid{padding:0.5rem 0;gap:1rem}
  .glass-panel{padding:1rem;margin:0 0.25rem}
  .metrics-grid{grid-template-columns:1fr}
  .button-group{flex-direction:column;gap:0.75rem}
  .btn{justify-content:center;padding:0.875rem 1rem;font-size:0.875rem}
  .footer{margin-top:1rem;padding:1.5rem 0.5rem}
  .footer-content{flex-direction:column;text-align:center}
  .results-container{max-height:300px}
  .viz-container{height:150px}
  .metric-value{font-size:2rem}
  .backend-status{display:none !important;visibility:hidden !important}
}
/* Additional mobile and small screen improvements */
@media(max-width:480px){
  .main-container{padding:0.25rem}
  .glass-panel{padding:0.875rem;margin:0 0.125rem}
  .header{padding:0.75rem 0.25rem;position:relative;overflow:hidden}
  .logo{font-size:1.75rem;line-height:1.2;word-wrap:break-word}
  .tagline{font-size:1rem;margin-bottom:0.25rem}
  .subtitle{font-size:0.8rem;line-height:1.4;word-wrap:break-word}
  .results-container{max-height:250px}
  .viz-container{height:120px}

}
/* Ensure scrollability on very small screens */
@media(max-height:600px){
  .glass-panel{padding:0.75rem}
  .header{padding:0.5rem 0.25rem}
  .results-container{max-height:150px}
}
/* Extra small screens - prevent any text overflow */
@media(max-width:360px){
  .main-container{padding:0.125rem}
  .header{padding:0.5rem 0.125rem;word-wrap:break-word;overflow-wrap:break-word}
  .glass-panel{padding:0.75rem;margin:0}
  .logo{font-size:1.4rem;line-height:1.1}
  .tagline{font-size:0.9rem}
  .subtitle{font-size:0.75rem;line-height:1.3}
  .backend-status{display:none !important;visibility:hidden !important}
}
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
/* Backend status positioning */
.backend-status {
  position: absolute;
  right: 20px;
  top: 20px;
  color: #9fb4c8;
  font-size: 13px;
  z-index: 100;
  background: rgba(0, 0, 0, 0.3);
  padding: 4px 8px;
  border-radius: 4px;
  backdrop-filter: blur(10px);
}
/* Hide backend status on screens smaller than 900px to prevent overlap */
@media(max-width:900px){
  .backend-status{
    display: none !important;
    visibility: hidden !important;
  }
}
        `}
      </style>

      <div className="main-container">
        <canvas ref={bgCanvasRef} id="background-canvas" />

        {isAnalyzing && (
          <div className="loading-overlay active">
            <div className="loading-spinner"></div>
          </div>
        )}

        <header className="header">
          <h1 className="logo">eDNA Biodiversity Analyzer</h1>
          <p className="tagline">Smart India Hackathon 2025</p>
          <p className="subtitle">
            Advanced AI-driven platform for environmental DNA analysis,
            species identification, and biodiversity assessment from deep-sea
            samples
          </p>
          {typeof window !== 'undefined' && window.innerWidth > 900 && (
            <div className="backend-status">
              {backendStatus}
            </div>
          )}
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
                <p className="panel-subtitle">Upload FASTA or JSON files for species identification</p>
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
              <p className="upload-text">Click to select FASTA/JSON files<br /><small>or drag and drop here</small></p>
              <input ref={fileInputRef} type="file" className="file-input" onChange={handleFileChange} accept=".fasta,.json" />
              {selectedFile && <div className="file-name">{selectedFile.name} — {formatBytes(selectedFile.size)}</div>}
            </div>

            {parsedJsonPreview && (
              <div style={{ marginBottom: 12, fontSize: 13, color: "var(--text-secondary)" }}>
                JSON preview: {parsedJsonPreview.count} sequences — sample IDs: {parsedJsonPreview.samples.map((s, i) => <span key={i}>{s.id || s.sequence_id || s.name}{i < parsedJsonPreview.samples.length -1 ? ", " : ""}</span>)}
              </div>
            )}

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

            <div style={{ padding: "0 1rem 0 0", marginBottom: 8 }}>
              <strong style={{ color: "var(--text-secondary)" }}>Model used:</strong> <span style={{ color: "var(--secondary-cyan)", fontWeight: 700 }}>{modelUsed || "—"}</span>
            </div>

            <div className="results-container">
              {results.length > 0 ? (
                results.map((s, idx) => {
                  const pct = (s.confidence || 0) * 100;
                  // Threshold coloring: >= 40% green, < 40% red
                  const nameColor = pct >= NOVELTY_THRESHOLD * 100 ? "var(--accent-green)" : "#ff6b6b";
                  return (
                    <div className="result-item" key={s.id || s.name || idx}>
                      <div className="result-header">
                        <span className="sequence-id">{s.id || "-"}</span>
                        <span className="species-name" style={{ color: nameColor }}>
                          {s.name} ({pct.toFixed(1)}%)
                        </span>
                      </div>
                      <div style={{ marginTop: 6 }}>
                        <ConfidenceBar confidence={s.confidence || 0} />
                      </div>
                    </div>
                  );
                })
              ) : (
                <div className="empty-state">
                  <div className="empty-icon">🧬</div>
                  <div className="empty-text">No analysis results yet</div>
                  <div className="empty-subtext">Upload a FASTA or JSON file to begin species identification</div>
                </div>
              )}
            </div>

            {results.length > 0 && (
              <div style={{ marginTop: 16, paddingBottom: 8 }} className="button-group">
                <button className="btn btn-secondary" onClick={exportCSV}>Export CSV</button>
                <button className="btn btn-secondary" onClick={exportPDF}>Export PDF</button>
                <button className="btn btn-primary" onClick={rerun}>Re-run</button>
                <button className="btn btn-primary" onClick={moveToAdmin}>Move to Admin</button>
              </div>
            )}
          </section>
        </main>

        <footer className="footer">
          <div className="footer-content">
            <div className="footer-text">Built for Smart India Hackathon 2025 — Advanced eDNA Analysis Platform</div>
            <div className="footer-brand">By 6-Bit Coders</div>
          </div>
        </footer>
      </div>
    </>
  );
};

export default App;
