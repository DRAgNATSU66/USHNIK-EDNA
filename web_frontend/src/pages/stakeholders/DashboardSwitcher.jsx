// DashboardSwitcher.jsx
import React from "react";

/**
 * DashboardSwitcher
 *
 * Full, copy/paste-ready component that:
 * - Applies the same deep-electric-blue gradient to html/body/#root so no white corners show.
 * - Styles scrollbar track to avoid white showing on edges.
 * - Keeps the themed sticky top bar & buttons you requested.
 *
 * Usage:
 * <DashboardSwitcher
 *    currentDashboard="policymaker"
 *    onSwitch={(id) => setDashboard(id)}
 *    onBackToSelection={() => setSelectionOpen(true)}
 * />
 */

export default function DashboardSwitcher({
  currentDashboard = "policymaker",
  onSwitch = () => {},
  onBackToSelection = () => {},
}) {
  const labels = {
    researcher: "Researcher",
    policymaker: "Policymaker",
    industry: "Industry",
  };

  const allIDs = ["researcher", "policymaker", "industry"];

  return (
    <>
      <style>{`
/* ---------------------------
   Theme variables (match dashboard)
   --------------------------- */
:root{
  --primary-blue: #0066ff;
  --secondary-cyan: #00d4ff;
  --marine-green: #00ffaa;
  --deep-ocean: #001133;
  --dark-blue: #002266;
  --glass-border: rgba(255,255,255,0.06);
  --text-primary: #eaf6ff;
  --text-muted: #9acfff;
  --gradient-primary: linear-gradient(135deg,var(--primary-blue) 0%,var(--secondary-cyan) 100%);
  --gradient-bg: radial-gradient(ellipse at center,var(--dark-blue) 0%,var(--deep-ocean) 100%);
}

/* ---------------------------
   GLOBAL FIXES: ensure viewport is fully covered
   --------------------------- */
html, body, #root {
  height: 100%;
  width: 100%;
  margin: 0;
  padding: 0;
  background: var(--gradient-bg) !important; /* force the same background everywhere */
  background-color: var(--deep-ocean) !important;
  color: var(--text-primary);
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  box-sizing: border-box;
}

/* Make sure no element unintentionally shows default background */
* { box-sizing: inherit; }

/* Scrollbar track: keep it dark / transparent so edges don't show white */
::-webkit-scrollbar { width: 12px; height: 12px; }
::-webkit-scrollbar-thumb {
  background: rgba(0,0,0,0.35);
  border-radius: 10px;
  border: 2px solid rgba(0,0,0,0.15);
}
::-webkit-scrollbar-track {
  background: transparent;
}

/* ---------------------------
   Dashboard switcher bar (sticky top)
   --------------------------- */
.dashboard-switcher {
  position: sticky;
  top: 0;
  left: 0;
  right: 0;
  z-index: 80;
  background: linear-gradient(180deg, rgba(0,14,40,0.92), rgba(0,14,40,0.82));
  border-bottom: 1px solid rgba(255,255,255,0.03);
  box-shadow: 0 6px 18px rgba(0,0,0,0.45);
  backdrop-filter: blur(6px);
  /* ensure no rounding so corners remain the same color */
  border-radius: 0;
}

/* wrapper aligns width to the main app max width */
.dashboard-switcher .bar-content {
  max-width: 1300px;
  margin: 0 auto;
  padding: 9px 20px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  box-sizing: border-box;
}

/* left content */
.switcher-left {
  display:flex;
  align-items:center;
  gap:12px;
  color:var(--text-muted);
  font-size: 13px;
  font-weight:600;
}
.switcher-left .dot {
  width:10px;
  height:10px;
  border-radius:50%;
  background: linear-gradient(180deg, var(--secondary-cyan), var(--marine-green));
  box-shadow: 0 0 10px rgba(0,255,170,0.12), inset 0 1px 1px rgba(255,255,255,0.02);
  flex-shrink:0;
}

/* controls on the right */
.switcher-controls {
  display:flex;
  align-items:center;
  gap:10px;
  flex-wrap:wrap;
}

/* theme buttons */
.dash-btn {
  display:inline-flex;
  align-items:center;
  gap:8px;
  padding:9px 14px;
  border-radius:12px;
  border: 1px solid rgba(255,255,255,0.04);
  background: linear-gradient(180deg, rgba(255,255,255,0.02), rgba(255,255,255,0.01));
  color: var(--text-muted);
  font-weight:700;
  cursor:pointer;
  transition: all 180ms ease;
  box-shadow: 0 8px 24px rgba(0,0,0,0.45);
}

/* Active/primary button */
.dash-btn.active {
  background: linear-gradient(90deg, var(--primary-blue), var(--secondary-cyan));
  color: white;
  transform: translateY(-2px);
  box-shadow: 0 12px 30px rgba(0,102,255,0.28), 0 2px 8px rgba(0,0,0,0.35), inset 0 1px 0 rgba(255,255,255,0.12);
  border: 1px solid rgba(255,255,255,0.12);
}

/* hover */
.dash-btn:hover { transform: translateY(-2px); color: white; }

/* glassy back button */
.back-btn {
  padding:9px 14px;
  border-radius:12px;
  font-weight:700;
  color: var(--text-muted);
  background: linear-gradient(180deg, rgba(255,255,255,0.03), rgba(255,255,255,0.01));
  border: 1px solid rgba(255,255,255,0.03);
  cursor:pointer;
  box-shadow: 0 8px 24px rgba(0,0,0,0.35), inset 0 1px 0 rgba(255,255,255,0.02);
  transition: all 160ms ease;
}
.back-btn:hover {
  color: white;
  transform: translateY(-2px);
  box-shadow: 0 12px 36px rgba(0,102,255,0.12);
}

/* small text */
.switcher-small { font-size: 13px; color: var(--text-muted); }

/* Ensure the sticky area doesn't leave a white gap on very small screens */
@media (max-width: 520px) {
  .bar-content { padding: 8px 10px; }
  .dash-btn, .back-btn { padding:8px 10px; font-size: 13px; }
}
      `}</style>

      <div className="dashboard-switcher" role="navigation" aria-label="Dashboard switcher">
        <div className="bar-content">
          {/* left side: currently viewing */}
          <div className="switcher-left" aria-hidden={false}>
            <div className="switcher-small">Currently viewing:</div>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <div className="dot" aria-hidden />
              <div style={{ color: "var(--text-primary)", fontWeight: 800 }}>
                {labels[currentDashboard]}
              </div>
            </div>
          </div>

          {/* right side: controls */}
          <div className="switcher-controls" role="toolbar" aria-label="Dashboard controls">
            {allIDs.map((id) => {
              const isActive = id === currentDashboard;
              return (
                <button
                  key={id}
                  onClick={() => onSwitch(id)}
                  className={`dash-btn ${isActive ? "active" : ""}`}
                  aria-pressed={isActive}
                  title={labels[id]}
                >
                  <span
                    style={{
                      width: 10,
                      height: 10,
                      borderRadius: 999,
                      background: isActive ? "rgba(255,255,255,0.95)" : "rgba(255,255,255,0.06)",
                      display: "inline-block",
                      boxShadow: isActive ? "0 6px 18px rgba(0,0,0,0.35), 0 0 12px rgba(0,212,255,0.12)" : "none",
                    }}
                    aria-hidden
                  />
                  <span style={{ minWidth: 86, textAlign: "center" }}>{labels[id]}</span>
                </button>
              );
            })}

            <button
              onClick={onBackToSelection}
              className="back-btn"
              title="Back to stakeholder selection"
              aria-label="Back to selection"
            >
              ⟲ Back to Selection
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
