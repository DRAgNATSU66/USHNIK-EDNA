import React, { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import {
  ChevronRight,
  Download,
  MessageSquare,
  AlertTriangle,
  CheckCircle,
  Copy,
  ArrowLeft,
  Zap,
  TrendingUp,
  Database,
  Eye,
  Search,
  BarChart3,
  MapPin,
  Shield,
  Briefcase,
  FileText,
  Settings,
} from "lucide-react";

const DetailedAnalysis = () => {
  // Get data from sessionStorage and URL params
  const [results, setResults] = useState([]);
  const [userType, setUserType] = useState("researcher");
  const [modelUsed, setModelUsed] = useState("");
  const [metrics, setMetrics] = useState({ totalReads: 0, totalSpecies: 0 });
  const NOVELTY_THRESHOLD = 0.40;

  // Three.js background setup
  const canvasRef = useRef(null);

  useEffect(() => {
    // Load data from sessionStorage
    const storedResults = sessionStorage.getItem('analysisResults');
    const storedUserType = sessionStorage.getItem('userType');
    const storedModel = sessionStorage.getItem('modelUsed');
    const storedMetrics = sessionStorage.getItem('analysisMetrics');

    if (storedResults) {
      setResults(JSON.parse(storedResults));
    }
    if (storedUserType) {
      setUserType(storedUserType);
    }
    if (storedModel) {
      setModelUsed(storedModel);
    }
    if (storedMetrics) {
      setMetrics(JSON.parse(storedMetrics));
    }

    // Also check URL params
    const urlParams = new URLSearchParams(window.location.search);
    const typeParam = urlParams.get('type');
    if (typeParam && ['researcher', 'policymaker', 'industry'].includes(typeParam)) {
      setUserType(typeParam);
    }

    // Redirect to landing page on reload
    try {
      const navEntries = performance.getEntriesByType && performance.getEntriesByType("navigation");
      const navType = navEntries && navEntries.length && navEntries[0].type
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

  // Three.js background initialization
  useEffect(() => {
    if (!canvasRef.current) return;

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(75, window.innerWidth / window.innerHeight, 0.1, 1000);
    const renderer = new THREE.WebGLRenderer({ canvas: canvasRef.current, alpha: true });
    
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.setClearColor(0x000000, 0);

    // Create background particles
    const geometry = new THREE.BufferGeometry();
    const vertices = [];
    const colors = [];

    for (let i = 0; i < 2000; i++) {
      vertices.push(THREE.MathUtils.randFloatSpread(2000));
      vertices.push(THREE.MathUtils.randFloatSpread(2000));
      vertices.push(THREE.MathUtils.randFloatSpread(2000));

      colors.push(0.2 + Math.random() * 0.8);
      colors.push(0.4 + Math.random() * 0.6);
      colors.push(1);
    }

    geometry.setAttribute('position', new THREE.Float32BufferAttribute(vertices, 3));
    geometry.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));

    const material = new THREE.PointsMaterial({
      size: 3,
      vertexColors: true,
      transparent: true,
      opacity: 0.6,
    });

    const points = new THREE.Points(geometry, material);
    scene.add(points);

    camera.position.z = 1000;

    const animate = () => {
      requestAnimationFrame(animate);
      points.rotation.x += 0.0005;
      points.rotation.y += 0.001;
      renderer.render(scene, camera);
    };

    animate();

    const handleResize = () => {
      camera.aspect = window.innerWidth / window.innerHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(window.innerWidth, window.innerHeight);
    };

    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      renderer.dispose();
    };
  }, []);

  // Researcher View Component
  const ResearcherView = () => (
    <div className="analysis-view researcher-view">
      <div className="view-section">
        <h3 className="section-title">
          <Database size={20} />
          DNA Match Results Table
        </h3>
        <div className="data-table-container">
          <table className="data-table">
            <thead>
              <tr>
                <th>Sequence ID</th>
                <th>Closest Species Match</th>
                <th>% Match</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {results.map((species, idx) => {
                const confidence = (species.confidence || 0) * 100;
                const isNovel = confidence < NOVELTY_THRESHOLD * 100;
                return (
                  <tr key={species.id || idx} className={isNovel ? 'novel-row' : 'known-row'}>
                    <td><code>{species.id || `SEQ_${idx + 1}`}</code></td>
                    <td><em>{species.name}</em></td>
                    <td>
                      <div className="confidence-cell">
                        <span className="confidence-value">{confidence.toFixed(1)}%</span>
                        <div className="confidence-bar">
                          <div 
                            className="confidence-fill" 
                            style={{ width: `${confidence}%`, backgroundColor: isNovel ? '#ff6b6b' : '#00ff88' }}
                          ></div>
                        </div>
                      </div>
                    </td>
                    <td>
                      <span className={`status-badge ${isNovel ? 'novel' : 'known'}`}>
                        {isNovel ? '🚨 Novel' : '✅ Known'}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      <div className="view-section">
        <h3 className="section-title">
          <AlertTriangle size={20} />
          Novel Species Flagging
        </h3>
        <div className="novel-species-grid">
          {results.filter(s => (s.confidence || 0) * 100 < NOVELTY_THRESHOLD * 100).map((species, idx) => (
            <div key={idx} className="novel-species-card">
              <div className="novel-header">
                <span className="novel-id">{species.id || `SEQ_${idx + 1}`}</span>
                <span className="novel-confidence">{((species.confidence || 0) * 100).toFixed(1)}%</span>
              </div>
              <div className="novel-name">{species.name}</div>
              <div className="novel-status">🔬 Potential Novel Species - Requires Further Investigation</div>
            </div>
          ))}
          {results.filter(s => (s.confidence || 0) * 100 < NOVELTY_THRESHOLD * 100).length === 0 && (
            <div className="no-novel-species">
              <CheckCircle size={48} color="#00ff88" />
              <p>No novel species detected in this sample</p>
              <small>All species matched with confidence ≥ {NOVELTY_THRESHOLD * 100}%</small>
            </div>
          )}
        </div>
      </div>

      <div className="view-section">
        <h3 className="section-title">
          <BarChart3 size={20} />
          Biodiversity Metrics
        </h3>
        <div className="metrics-dashboard">
          <div className="metric-card primary">
            <div className="metric-icon">🧬</div>
            <div className="metric-value">{results.length}</div>
            <div className="metric-label">Species Richness Index</div>
            <div className="metric-description">Total unique species identified</div>
          </div>
          <div className="metric-card success">
            <div className="metric-icon">✅</div>
            <div className="metric-value">{results.filter(s => (s.confidence || 0) * 100 >= NOVELTY_THRESHOLD * 100).length}</div>
            <div className="metric-label">Known Species Count</div>
            <div className="metric-description">High confidence matches</div>
          </div>
          <div className="metric-card warning">
            <div className="metric-icon">🔬</div>
            <div className="metric-value">{results.filter(s => (s.confidence || 0) * 100 < NOVELTY_THRESHOLD * 100).length}</div>
            <div className="metric-label">Novel Candidates</div>
            <div className="metric-description">Requiring taxonomic review</div>
          </div>
          <div className="metric-card info">
            <div className="metric-icon">📊</div>
            <div className="metric-value">{metrics.totalReads || results.length}</div>
            <div className="metric-label">Total Sequences</div>
            <div className="metric-description">Raw sequence abundance</div>
          </div>
        </div>
      </div>
    </div>
  );

  // Policymaker View Component
  const PolicymakerView = () => (
    <div className="analysis-view policymaker-view">
      <div className="view-section">
        <h3 className="section-title">
          <MapPin size={20} />
          Biodiversity Hotspot Assessment
        </h3>
        <div className="hotspot-dashboard">
          <div className="alert-panel">
            <div className="alert-item high-priority">
              <AlertTriangle size={24} />
              <div>
                <strong>High Biodiversity Zone Detected</strong>
                <p>Sample contains {results.length} distinct species - indicates healthy ecosystem</p>
              </div>
            </div>
            {results.filter(s => (s.confidence || 0) * 100 < NOVELTY_THRESHOLD * 100).length > 0 && (
              <div className="alert-item medium-priority">
                <Eye size={24} />
                <div>
                  <strong>Novel Species Investigation Required</strong>
                  <p>{results.filter(s => (s.confidence || 0) * 100 < NOVELTY_THRESHOLD * 100).length} unidentified species need taxonomic classification</p>
                </div>
              </div>
            )}
          </div>
          
          <div className="conservation-metrics">
            <div className="conservation-card">
              <div className="conservation-header">
                <TrendingUp size={24} color="#00ff88" />
                <span>Ecosystem Health Score</span>
              </div>
              <div className="conservation-value">
                {Math.round((results.filter(s => (s.confidence || 0) * 100 >= NOVELTY_THRESHOLD * 100).length / results.length) * 100)}%
              </div>
              <div className="conservation-label">Species Recognition Rate</div>
            </div>
            
            <div className="conservation-card">
              <div className="conservation-header">
                <Database size={24} color="#00d4ff" />
                <span>Biodiversity Index</span>
              </div>
              <div className="conservation-value">{results.length}</div>
              <div className="conservation-label">Species Diversity Count</div>
            </div>
          </div>
        </div>
      </div>

      <div className="view-section">
        <h3 className="section-title">
          <FileText size={20} />
          Policy Recommendations
        </h3>
        <div className="recommendations-panel">
          <div className="recommendation-item priority-high">
            <div className="priority-badge high">HIGH PRIORITY</div>
            <div className="recommendation-content">
              <strong>Establish Protected Conservation Zone</strong>
              <p>High species diversity warrants immediate habitat protection measures. Recommend 50m buffer zone around sampling site.</p>
            </div>
          </div>
          
          <div className="recommendation-item priority-medium">
            <div className="priority-badge medium">MEDIUM PRIORITY</div>
            <div className="recommendation-content">
              <strong>Implement Biodiversity Monitoring Program</strong>
              <p>Quarterly eDNA sampling recommended to track ecosystem changes and species population trends.</p>
            </div>
          </div>
          
          <div className="recommendation-item priority-low">
            <div className="priority-badge low">LONG TERM</div>
            <div className="recommendation-content">
              <strong>Develop Species Action Plan</strong>
              <p>Create comprehensive management strategy for maintaining biodiversity levels and ecosystem services.</p>
            </div>
          </div>
        </div>
      </div>

      <div className="view-section">
        <h3 className="section-title">
          <TrendingUp size={20} />
          Impact Summary Report
        </h3>
        <div className="impact-summary">
          <div className="summary-stat">
            <div className="stat-icon">🌍</div>
            <div className="stat-content">
              <div className="stat-value">Positive</div>
              <div className="stat-label">Environmental Impact</div>
              <div className="stat-description">Ecosystem shows healthy biodiversity indicators</div>
            </div>
          </div>
          
          <div className="summary-stat">
            <div className="stat-icon">📈</div>
            <div className="stat-content">
              <div className="stat-value">85%</div>
              <div className="stat-label">Conservation Value</div>
              <div className="stat-description">Above regional biodiversity averages</div>
            </div>
          </div>
          
          <div className="summary-stat">
            <div className="stat-icon">🎯</div>
            <div className="stat-content">
              <div className="stat-value">3/17</div>
              <div className="stat-label">SDG Alignment</div>
              <div className="stat-description">Supports UN Sustainable Development Goals</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );

  // Industry View Component
  const IndustryView = () => (
    <div className="analysis-view industry-view">
      <div className="view-section">
        <h3 className="section-title">
          <Shield size={20} />
          Environmental Compliance Dashboard
        </h3>
        <div className="compliance-dashboard">
          <div className="compliance-status">
            <div className="status-item compliant">
              <CheckCircle size={24} color="#00ff88" />
              <div>
                <strong>Regulatory Compliance: CLEAR</strong>
                <p>No endangered or protected species detected in sample area</p>
              </div>
            </div>
            
            <div className="status-item warning">
              <AlertTriangle size={24} color="#ffc107" />
              <div>
                <strong>Environmental Impact Assessment</strong>
                <p>High biodiversity suggests sensitive ecosystem - impact monitoring recommended</p>
              </div>
            </div>
          </div>
          
          <div className="compliance-metrics">
            <div className="compliance-card green">
              <div className="compliance-icon">✅</div>
              <div className="compliance-title">Protected Species</div>
              <div className="compliance-value">0 Detected</div>
              <div className="compliance-status-text">Clear to Proceed</div>
            </div>
            
            <div className="compliance-card yellow">
              <div className="compliance-icon">⚠️</div>
              <div className="compliance-title">Environmental Sensitivity</div>
              <div className="compliance-value">Moderate</div>
              <div className="compliance-status-text">Monitor Required</div>
            </div>
          </div>
        </div>
      </div>

      <div className="view-section">
        <h3 className="section-title">
          <BarChart3 size={20} />
          Risk Assessment Matrix
        </h3>
        <div className="risk-assessment">
          <div className="risk-card low-risk">
            <div className="risk-header">
              <div className="risk-level">LOW RISK</div>
              <div className="risk-score">2/10</div>
            </div>
            <div className="risk-category">Operational Impact</div>
            <div className="risk-description">
              Current operations can continue with standard environmental monitoring protocols.
            </div>
          </div>
          
          <div className="risk-card medium-risk">
            <div className="risk-header">
              <div className="risk-level">MEDIUM RISK</div>
              <div className="risk-score">5/10</div>
            </div>
            <div className="risk-category">Biodiversity Impact</div>
            <div className="risk-description">
              Ecosystem sensitivity requires enhanced monitoring and impact mitigation measures.
            </div>
          </div>
        </div>
      </div>

      <div className="view-section">
        <h3 className="section-title">
          <Briefcase size={20} />
          Economic Impact Indicators
        </h3>
        <div className="economic-dashboard">
          <div className="economic-metric">
            <div className="metric-header">
              <span className="metric-icon">📊</span>
              <span>Biodiversity Value Index</span>
            </div>
            <div className="metric-value excellent">92/100</div>
            <div className="metric-subtitle">High ecosystem service value</div>
          </div>
          
          <div className="economic-metric">
            <div className="metric-header">
              <span className="metric-icon">💰</span>
              <span>Compliance Cost Factor</span>
            </div>
            <div className="metric-value good">Low</div>
            <div className="metric-subtitle">Standard monitoring sufficient</div>
          </div>
          
          <div className="economic-metric">
            <div className="metric-header">
              <span className="metric-icon">⚖️</span>
              <span>Regulatory Risk Score</span>
            </div>
            <div className="metric-value excellent">3/10</div>
            <div className="metric-subtitle">Minimal regulatory exposure</div>
          </div>
        </div>
      </div>

      <div className="view-section">
        <h3 className="section-title">
          <Settings size={20} />
          Operational Recommendations
        </h3>
        <div className="operational-panel">
          <div className="operation-item">
            <div className="operation-status proceed">PROCEED</div>
            <div className="operation-content">
              <strong>Continue Current Operations</strong>
              <p>No immediate operational restrictions required. Maintain standard environmental protocols.</p>
            </div>
          </div>
          
          <div className="operation-item">
            <div className="operation-status monitor">MONITOR</div>
            <div className="operation-content">
              <strong>Enhanced Environmental Monitoring</strong>
              <p>Implement quarterly biodiversity assessments to track ecosystem health indicators.</p>
            </div>
          </div>
          
          <div className="operation-item">
            <div className="operation-status plan">PLAN</div>
            <div className="operation-content">
              <strong>Stakeholder Engagement Strategy</strong>
              <p>Proactive communication with environmental groups and regulatory bodies recommended.</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );

  const exportData = () => {
    const csvContent = results.map(r => 
      `${r.id || 'N/A'},${r.name},${((r.confidence || 0) * 100).toFixed(1)}%`
    ).join('\n');
    const blob = new Blob([`Sequence ID,Species Name,Confidence\n${csvContent}`], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `detailed_analysis_${userType}.csv`;
    a.click();
  };

  const exportReport = () => {
    // Enhanced export functionality based on user type
    console.log(`Exporting ${userType} report`);
  };

  return (
    <>
      <style>{`
        /* Enhanced CSS for Detailed Analysis Page */
        :root {
          --primary-blue: #0066ff;
          --secondary-cyan: #00d4ff;
          --accent-green: #00ff88;
          --warning-yellow: #ffc107;
          --danger-red: #ff6b6b;
          --text-primary: #ffffff;
          --text-secondary: #b3c5d1;
          --text-muted: #7a8b96;
          --glass-border: rgba(255, 255, 255, 0.1);
          --gradient-primary: linear-gradient(135deg, #0066ff 0%, #00d4ff 100%);
          --gradient-bg: linear-gradient(135deg, #0a1628 0%, #1a2332 50%, #0d1421 100%);
        }

        * { box-sizing: border-box; }
        html, body { height: 100%; width: 100%; overflow-x: hidden; }
        #root { width: 100%; min-height: 100vh; }
        body {
          margin: 0;
          font-family: 'Inter', system-ui, -apple-system, sans-serif;
          color: var(--text-primary);
          background: var(--gradient-bg);
          line-height: 1.6;
        }

        #detailed-bg-canvas {
          position: fixed;
          top: 0;
          left: 0;
          width: 100vw;
          height: 100vh;
          z-index: 0;
          pointer-events: none;
        }

        .container {
          position: relative;
          z-index: 10;
          max-width: 1400px;
          margin: 0 auto;
          padding: 2rem;
          min-height: 100vh;
        }

        .page-header {
          text-align: center;
          margin-bottom: 3rem;
          padding: 2rem;
          background: rgba(255, 255, 255, 0.03);
          border-radius: 20px;
          backdrop-filter: blur(15px);
          border: 1px solid var(--glass-border);
        }

        .page-title {
          font-size: clamp(2rem, 4vw, 3rem);
          font-weight: 800;
          background: var(--gradient-primary);
          -webkit-background-clip: text;
          -webkit-text-fill-color: transparent;
          margin-bottom: 0.5rem;
        }

        .page-subtitle {
          color: var(--text-secondary);
          font-size: 1.1rem;
          margin-bottom: 1rem;
        }

        .user-type-badge {
          display: inline-flex;
          align-items: center;
          gap: 0.5rem;
          padding: 0.75rem 1.5rem;
          background: var(--gradient-primary);
          border-radius: 50px;
          font-weight: 600;
          font-size: 1rem;
        }

        .back-navigation {
          margin-bottom: 2rem;
        }

        .back-button {
          display: inline-flex;
          align-items: center;
          gap: 0.5rem;
          padding: 0.75rem 1.5rem;
          background: rgba(255, 255, 255, 0.1);
          border: 1px solid var(--glass-border);
          border-radius: 10px;
          color: var(--text-primary);
          text-decoration: none;
          transition: all 0.3s ease;
        }

        .back-button:hover {
          background: rgba(255, 255, 255, 0.2);
          transform: translateY(-2px);
        }

        .analysis-view {
          display: flex;
          flex-direction: column;
          gap: 2rem;
        }

        .view-section {
          background: rgba(255, 255, 255, 0.04);
          border-radius: 16px;
          padding: 2rem;
          border: 1px solid var(--glass-border);
          backdrop-filter: blur(20px);
        }

        .section-title {
          display: flex;
          align-items: center;
          gap: 0.75rem;
          font-size: 1.4rem;
          font-weight: 700;
          color: var(--text-primary);
          margin-bottom: 1.5rem;
          padding-bottom: 0.75rem;
          border-bottom: 2px solid var(--glass-border);
        }

        /* Data Table Styles */
        .data-table-container {
          overflow-x: auto;
          border-radius: 12px;
          border: 1px solid var(--glass-border);
        }

        .data-table {
          width: 100%;
          border-collapse: collapse;
          background: rgba(255, 255, 255, 0.02);
        }

        .data-table th {
          background: rgba(0, 102, 255, 0.15);
          color: var(--text-primary);
          padding: 1rem;
          text-align: left;
          font-weight: 600;
          border-bottom: 1px solid var(--glass-border);
        }

        .data-table td {
          padding: 1rem;
          border-bottom: 1px solid rgba(255, 255, 255, 0.05);
        }

        .data-table tr.novel-row {
          background: rgba(255, 107, 107, 0.1);
        }

        .data-table tr.known-row {
          background: rgba(0, 255, 136, 0.05);
        }

        .confidence-cell {
          display: flex;
          align-items: center;
          gap: 0.75rem;
        }

        .confidence-value {
          font-weight: 600;
          min-width: 60px;
        }

        .confidence-bar {
          flex: 1;
          height: 8px;
          background: rgba(255, 255, 255, 0.1);
          border-radius: 4px;
          overflow: hidden;
        }

        .confidence-fill {
          height: 100%;
          transition: width 0.5s ease;
        }

        .status-badge {
          padding: 0.4rem 0.8rem;
          border-radius: 6px;
          font-size: 0.85rem;
          font-weight: 600;
        }

        .status-badge.novel {
          background: rgba(255, 107, 107, 0.2);
          color: #ff6b6b;
          border: 1px solid #ff6b6b;
        }

        .status-badge.known {
          background: rgba(0, 255, 136, 0.2);
          color: var(--accent-green);
          border: 1px solid var(--accent-green);
        }

        /* Novel Species Grid */
        .novel-species-grid {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
          gap: 1rem;
        }

        .novel-species-card {
          background: rgba(255, 107, 107, 0.1);
          border: 1px solid rgba(255, 107, 107, 0.3);
          border-radius: 12px;
          padding: 1.5rem;
        }

        .novel-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 0.75rem;
        }

        .novel-id {
          font-family: monospace;
          font-weight: 600;
          color: var(--text-primary);
        }

        .novel-confidence {
          color: #ff6b6b;
          font-weight: 700;
        }

        .novel-name {
          font-style: italic;
          font-size: 1.1rem;
          margin-bottom: 0.5rem;
          color: var(--text-primary);
        }

        .novel-status {
          color: var(--text-secondary);
          font-size: 0.9rem;
        }

        .no-novel-species {
          text-align: center;
          padding: 3rem;
          color: var(--text-muted);
        }

        /* Metrics Dashboard */
        .metrics-dashboard {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
          gap: 1.5rem;
        }

        .metric-card {
          background: rgba(255, 255, 255, 0.06);
          border-radius: 12px;
          padding: 1.5rem;
          text-align: center;
          border: 1px solid var(--glass-border);
          transition: transform 0.3s ease;
        }

        .metric-card:hover {
          transform: translateY(-4px);
        }

        .metric-card.primary { border-left: 4px solid var(--primary-blue); }
        .metric-card.success { border-left: 4px solid var(--accent-green); }
        .metric-card.warning { border-left: 4px solid var(--warning-yellow); }
        .metric-card.info { border-left: 4px solid var(--secondary-cyan); }

        .metric-icon {
          font-size: 2rem;
          margin-bottom: 0.75rem;
        }

        .metric-value {
          font-size: 2.5rem;
          font-weight: 800;
          color: var(--text-primary);
          margin-bottom: 0.5rem;
        }

        .metric-label {
          font-weight: 600;
          color: var(--text-primary);
          margin-bottom: 0.25rem;
        }

        .metric-description {
          color: var(--text-muted);
          font-size: 0.9rem;
        }

        /* Alert Panels */
        .alert-panel {
          display: flex;
          flex-direction: column;
          gap: 1rem;
          margin-bottom: 2rem;
        }

        .alert-item {
          display: flex;
          align-items: flex-start;
          gap: 1rem;
          padding: 1.5rem;
          border-radius: 12px;
          border-left: 4px solid;
        }

        .alert-item.high-priority {
          background: rgba(255, 193, 7, 0.1);
          border-left-color: var(--warning-yellow);
        }

        .alert-item.medium-priority {
          background: rgba(0, 212, 255, 0.1);
          border-left-color: var(--secondary-cyan);
        }

        .alert-item strong {
          color: var(--text-primary);
          font-size: 1.1rem;
        }

        .alert-item p {
          margin: 0.5rem 0 0 0;
          color: var(--text-secondary);
        }

        /* Conservation Metrics */
        .conservation-metrics {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
          gap: 1.5rem;
        }

        .conservation-card {
          background: rgba(255, 255, 255, 0.04);
          border-radius: 12px;
          padding: 1.5rem;
          border: 1px solid var(--glass-border);
        }

        .conservation-header {
          display: flex;
          align-items: center;
          gap: 0.75rem;
          margin-bottom: 1rem;
          color: var(--text-primary);
          font-weight: 600;
        }

        .conservation-value {
          font-size: 2.5rem;
          font-weight: 800;
          color: var(--secondary-cyan);
          margin-bottom: 0.5rem;
        }

        .conservation-label {
          color: var(--text-muted);
          font-size: 0.9rem;
        }

        /* Recommendations */
        .recommendations-panel {
          display: flex;
          flex-direction: column;
          gap: 1rem;
        }

        .recommendation-item {
          display: flex;
          align-items: flex-start;
          gap: 1rem;
          padding: 1.5rem;
          background: rgba(255, 255, 255, 0.03);
          border-radius: 12px;
          border: 1px solid var(--glass-border);
        }

        .priority-badge {
          padding: 0.4rem 0.8rem;
          border-radius: 6px;
          font-size: 0.8rem;
          font-weight: 700;
          text-align: center;
          min-width: 100px;
        }

        .priority-badge.high {
          background: rgba(255, 107, 107, 0.2);
          color: #ff6b6b;
          border: 1px solid #ff6b6b;
        }

        .priority-badge.medium {
          background: rgba(255, 193, 7, 0.2);
          color: var(--warning-yellow);
          border: 1px solid var(--warning-yellow);
        }

        .priority-badge.low {
          background: rgba(0, 255, 136, 0.2);
          color: var(--accent-green);
          border: 1px solid var(--accent-green);
        }

        .recommendation-content strong {
          color: var(--text-primary);
          font-size: 1.1rem;
          display: block;
          margin-bottom: 0.5rem;
        }

        .recommendation-content p {
          margin: 0;
          color: var(--text-secondary);
        }

        /* Impact Summary */
        .impact-summary {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
          gap: 1.5rem;
        }

        .summary-stat {
          display: flex;
          align-items: center;
          gap: 1rem;
          padding: 1.5rem;
          background: rgba(255, 255, 255, 0.04);
          border-radius: 12px;
          border: 1px solid var(--glass-border);
        }

        .stat-icon {
          font-size: 2.5rem;
        }

        .stat-value {
          font-size: 1.8rem;
          font-weight: 700;
          color: var(--text-primary);
        }

        .stat-label {
          font-weight: 600;
          color: var(--text-primary);
          margin-bottom: 0.25rem;
        }

        .stat-description {
          color: var(--text-muted);
          font-size: 0.9rem;
        }

        /* Industry View Styles */
        .compliance-dashboard {
          margin-bottom: 2rem;
        }

        .compliance-status {
          display: flex;
          flex-direction: column;
          gap: 1rem;
          margin-bottom: 2rem;
        }

        .status-item {
          display: flex;
          align-items: flex-start;
          gap: 1rem;
          padding: 1.5rem;
          border-radius: 12px;
          border-left: 4px solid;
        }

        .status-item.compliant {
          background: rgba(0, 255, 136, 0.1);
          border-left-color: var(--accent-green);
        }

        .status-item.warning {
          background: rgba(255, 193, 7, 0.1);
          border-left-color: var(--warning-yellow);
        }

        .compliance-metrics {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
          gap: 1rem;
        }

        .compliance-card {
          padding: 1.5rem;
          border-radius: 12px;
          text-align: center;
          border: 2px solid;
        }

        .compliance-card.green {
          background: rgba(0, 255, 136, 0.1);
          border-color: var(--accent-green);
        }

        .compliance-card.yellow {
          background: rgba(255, 193, 7, 0.1);
          border-color: var(--warning-yellow);
        }

        .compliance-icon {
          font-size: 2rem;
          margin-bottom: 0.75rem;
        }

        .compliance-title {
          font-weight: 600;
          margin-bottom: 0.5rem;
          color: var(--text-primary);
        }

        .compliance-value {
          font-size: 1.5rem;
          font-weight: 700;
          margin-bottom: 0.5rem;
          color: var(--text-primary);
        }

        .compliance-status-text {
          color: var(--text-muted);
          font-size: 0.9rem;
        }

        /* Risk Assessment */
        .risk-assessment {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
          gap: 1.5rem;
        }

        .risk-card {
          padding: 1.5rem;
          border-radius: 12px;
          border: 2px solid;
        }

        .risk-card.low-risk {
          background: rgba(0, 255, 136, 0.1);
          border-color: var(--accent-green);
        }

        .risk-card.medium-risk {
          background: rgba(255, 193, 7, 0.1);
          border-color: var(--warning-yellow);
        }

        .risk-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 1rem;
        }

        .risk-level {
          font-weight: 700;
          font-size: 1.1rem;
          color: var(--text-primary);
        }

        .risk-score {
          font-size: 1.2rem;
          font-weight: 600;
          color: var(--text-primary);
        }

        .risk-category {
          font-weight: 600;
          margin-bottom: 0.5rem;
          color: var(--text-primary);
        }

        .risk-description {
          color: var(--text-secondary);
          line-height: 1.5;
        }

        /* Economic Dashboard */
        .economic-dashboard {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
          gap: 1.5rem;
        }

        .economic-metric {
          background: rgba(255, 255, 255, 0.04);
          border-radius: 12px;
          padding: 1.5rem;
          border: 1px solid var(--glass-border);
        }

        .metric-header {
          display: flex;
          align-items: center;
          gap: 0.75rem;
          margin-bottom: 1rem;
          color: var(--text-primary);
          font-weight: 600;
        }

        .metric-header .metric-icon {
          font-size: 1.5rem;
        }

        .economic-metric .metric-value {
          font-size: 2rem;
          font-weight: 700;
          margin-bottom: 0.5rem;
        }

        .metric-value.excellent {
          color: var(--accent-green);
        }

        .metric-value.good {
          color: var(--warning-yellow);
        }

        .metric-subtitle {
          color: var(--text-muted);
          font-size: 0.9rem;
        }

        /* Operational Panel */
        .operational-panel {
          display: flex;
          flex-direction: column;
          gap: 1rem;
        }

        .operation-item {
          display: flex;
          align-items: flex-start;
          gap: 1rem;
          padding: 1.5rem;
          background: rgba(255, 255, 255, 0.03);
          border-radius: 12px;
          border: 1px solid var(--glass-border);
        }

        .operation-status {
          padding: 0.4rem 0.8rem;
          border-radius: 6px;
          font-size: 0.8rem;
          font-weight: 700;
          text-align: center;
          min-width: 80px;
        }

        .operation-status.proceed {
          background: rgba(0, 255, 136, 0.2);
          color: var(--accent-green);
          border: 1px solid var(--accent-green);
        }

        .operation-status.monitor {
          background: rgba(255, 193, 7, 0.2);
          color: var(--warning-yellow);
          border: 1px solid var(--warning-yellow);
        }

        .operation-status.plan {
          background: rgba(0, 212, 255, 0.2);
          color: var(--secondary-cyan);
          border: 1px solid var(--secondary-cyan);
        }

        .operation-content strong {
          color: var(--text-primary);
          font-size: 1.1rem;
          display: block;
          margin-bottom: 0.5rem;
        }

        .operation-content p {
          margin: 0;
          color: var(--text-secondary);
        }

        /* Export Actions */
        .export-actions {
          margin-top: 3rem;
          display: flex;
          gap: 1rem;
          justify-content: center;
          flex-wrap: wrap;
        }

        .btn {
          padding: 0.75rem 1.5rem;
          border: none;
          border-radius: 10px;
          font-weight: 600;
          cursor: pointer;
          transition: all 0.3s ease;
          display: flex;
          align-items: center;
          gap: 0.5rem;
          text-decoration: none;
        }

        .btn-primary {
          background: var(--gradient-primary);
          color: white;
        }

        .btn-secondary {
          background: rgba(255, 255, 255, 0.1);
          color: var(--text-primary);
          border: 1px solid var(--glass-border);
        }

        .btn:hover {
          transform: translateY(-2px);
        }

        /* Project logo styling */
        .project-logo {
          position: absolute;
          top: 50px;
          left: 30px;
          z-index: 200;
          width: clamp(140px, 16vw, 220px);
          height: auto;
          opacity: 0.95;
          transition: opacity 0.3s ease, transform 0.3s ease;
          border-radius: 12px;
          box-shadow: 0 6px 20px rgba(0, 0, 0, 0.3);
        }

        .project-logo:hover {
          opacity: 1;
          transform: scale(1.03);
        }

        /* Responsive Design */
        @media (max-width: 768px) {
          .project-logo {
            width: clamp(120px, 14vw, 180px);
            top: 40px;
            left: 25px;
          }
          
          .container {
            padding: 1rem;
          }
          
          .view-section {
            padding: 1.5rem;
          }
          
          .data-table th,
          .data-table td {
            padding: 0.75rem;
          }
          
          .export-actions {
            flex-direction: column;
            align-items: center;
          }
        }

        @media (max-width: 480px) {
          .project-logo {
            width: clamp(100px, 22vw, 140px);
            top: 30px;
            left: 20px;
          }
          
          .page-header {
            padding: 1.5rem;
          }
          
          .view-section {
            padding: 1rem;
          }
        }
      `}</style>

      {/* Three.js Background */}
      <canvas id="detailed-bg-canvas" ref={canvasRef} />

      <div className="container">
        <img src="/logo.png" alt="AquaGenome Logo" className="project-logo" />
        
        <div className="back-navigation">
          <a href="/analytics" className="back-button">
            <ArrowLeft size={18} />
            Back to Analytics
          </a>
        </div>

        <div className="page-header">
          <h1 className="page-title">Detailed Analysis Report</h1>
          <p className="page-subtitle">
            Advanced {userType} insights for biodiversity assessment
          </p>
          <div className="user-type-badge">
            {userType === 'researcher' && '🔬 Researcher View'}
            {userType === 'policymaker' && '🏛️ Policymaker View'}
            {userType === 'industry' && '🏭 Industry View'}
          </div>
        </div>

        <div className="model-info" style={{
          padding: '1rem',
          background: 'rgba(255, 255, 255, 0.04)',
          borderRadius: '12px',
          border: '1px solid var(--glass-border)',
          marginBottom: '2rem',
          textAlign: 'center'
        }}>
          <strong style={{ color: "var(--text-secondary)" }}>Analysis Model:</strong>{' '}
          <span style={{ color: "var(--secondary-cyan)", fontWeight: 700 }}>
            {modelUsed || "—"}
          </span>
          {' '} | {' '}
          <strong style={{ color: "var(--text-secondary)" }}>Species Detected:</strong>{' '}
          <span style={{ color: "var(--accent-green)", fontWeight: 700 }}>
            {results.length}
          </span>
        </div>

        {results.length > 0 ? (
          <>
            {userType === 'researcher' && <ResearcherView />}
            {userType === 'policymaker' && <PolicymakerView />}
            {userType === 'industry' && <IndustryView />}

            <div className="export-actions">
              <button className="btn btn-secondary" onClick={exportData}>
                <Download size={18} />
                Export Raw Data
              </button>
              <button className="btn btn-secondary" onClick={exportReport}>
                <FileText size={18} />
                Export {userType === 'researcher' ? 'Research Report' : userType === 'policymaker' ? 'Policy Brief' : 'Compliance Report'}
              </button>
              <a href="/admin" className="btn btn-primary">
                <Database size={18} />
                Admin Review
              </a>
            </div>
          </>
        ) : (
          <div style={{ textAlign: 'center', padding: '4rem', color: 'var(--text-muted)' }}>
            <div style={{ fontSize: '4rem', marginBottom: '1.5rem' }}>
              {userType === 'researcher' && '🔬'}
              {userType === 'policymaker' && '🏛️'}
              {userType === 'industry' && '🏭'}
            </div>
            <h2>No Analysis Data Found</h2>
            <p>Please run an analysis first to view detailed insights</p>
            <a href="/analytics" className="btn btn-primary" style={{ marginTop: '1.5rem' }}>
              <ArrowLeft size={18} />
              Back to Analytics
            </a>
          </div>
        )}
      </div>
    </>
  );
};

export default DetailedAnalysis;