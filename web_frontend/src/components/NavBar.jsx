import React, { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";

const NAV_STYLE = {
  position: "sticky",
  top: 0,
  zIndex: 100,
  background: "rgba(0,17,51,0.85)",
  backdropFilter: "blur(16px)",
  borderBottom: "1px solid rgba(255,255,255,0.08)",
  padding: "0 1.5rem",
  display: "flex",
  alignItems: "center",
  height: 56,
  gap: "1.5rem",
};

const LOGO_STYLE = {
  fontWeight: 800,
  fontSize: "1.1rem",
  background: "linear-gradient(135deg, #0066ff 0%, #00d4ff 100%)",
  WebkitBackgroundClip: "text",
  WebkitTextFillColor: "transparent",
  backgroundClip: "text",
  textDecoration: "none",
  marginRight: "0.5rem",
};

const LINK_STYLE = (active) => ({
  color: active ? "#00d4ff" : "#b3d9ff",
  textDecoration: "none",
  fontSize: "0.875rem",
  fontWeight: active ? 600 : 400,
  padding: "0.25rem 0",
  borderBottom: active ? "2px solid #00d4ff" : "2px solid transparent",
  transition: "color 0.2s, border-color 0.2s",
});

const ROLE_BADGE = {
  fontSize: "0.7rem",
  padding: "2px 8px",
  borderRadius: 999,
  background: "rgba(0,102,255,0.2)",
  border: "1px solid rgba(0,102,255,0.4)",
  color: "#7eb3ff",
  fontWeight: 600,
  letterSpacing: "0.05em",
  textTransform: "uppercase",
};

export default function NavBar() {
  const { user, isAdmin, isCurator, logout } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const [menuOpen, setMenuOpen] = useState(false);

  const at = (path) => location.pathname === path;

  const handleLogout = () => {
    logout();
    navigate("/");
  };

  return (
    <nav style={NAV_STYLE}>
      <Link to="/dashboard" style={LOGO_STYLE}>Synth Veda</Link>

      {/* Desktop links */}
      <div style={{ display: "flex", gap: "1.25rem", alignItems: "center", flex: 1 }}>
        <Link to="/dashboard" style={LINK_STYLE(at("/dashboard"))}>Dashboard</Link>
        <Link to="/upload" style={LINK_STYLE(at("/upload"))}>Upload</Link>
        <Link to="/models" style={LINK_STYLE(at("/models"))}>Models</Link>
        <Link to="/abyss" style={LINK_STYLE(at("/abyss"))}>Abyss Mode</Link>
        {isCurator && (
          <Link to="/reviews" style={LINK_STYLE(at("/reviews"))}>Reviews</Link>
        )}
        {isAdmin && (
          <Link to="/admin" style={LINK_STYLE(at("/admin"))}>Admin</Link>
        )}
      </div>

      {/* Right side: user info + logout */}
      <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", marginLeft: "auto" }}>
        {user && (
          <>
            <span style={ROLE_BADGE}>{user.role}</span>
            <span style={{ color: "#b3d9ff", fontSize: "0.85rem" }}>
              {user.display_name || user.email}
            </span>
          </>
        )}
        <button
          onClick={handleLogout}
          style={{
            background: "transparent",
            border: "1px solid rgba(255,255,255,0.15)",
            color: "#7eb3ff",
            padding: "0.3rem 0.8rem",
            borderRadius: 8,
            cursor: "pointer",
            fontSize: "0.8rem",
          }}
        >
          Sign out
        </button>
      </div>
    </nav>
  );
}
