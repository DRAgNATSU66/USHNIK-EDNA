import { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../../contexts/AuthContext";
import {
  sidebarColors,
  sidebarTriggerStyle,
  sidebarOverlayStyle,
  sidebarPanelStyle,
  navItemStyle,
  navItemTickStyle,
  navItemLabelStyle,
  subNavItemStyle,
  sidebarFooterWrapStyle,
  sidebarUserRowStyle,
} from "./sidebarStyles";

function HamburgerIcon({ open }) {
  const bar = {
    display: "block",
    height: 2,
    borderRadius: 1,
    background: sidebarColors.wordmark,
    transition: "transform .22s ease, opacity .22s ease, width .22s ease",
  };
  return (
    <div style={{ width: 18, height: 14, display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
      <span style={{ ...bar, width: 18, transform: open ? "translateY(6px) rotate(45deg)" : "none" }} />
      <span style={{ ...bar, width: 18, opacity: open ? 0 : 1 }} />
      <span style={{ ...bar, width: 18, transform: open ? "translateY(-6px) rotate(-45deg)" : "none" }} />
    </div>
  );
}

function UploadNavIcon({ color }) {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
      <path d="M12 15V4m0 0-4 4m4-4 4 4" stroke={color} strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3" stroke={color} strokeWidth="1.7" strokeLinecap="round" />
    </svg>
  );
}

function ResearcherNavIcon({ color }) {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
      <path d="M9 2h6M10 2v6.2L4.8 18a2 2 0 0 0 1.8 3h10.8a2 2 0 0 0 1.8-3L14 8.2V2" stroke={color} strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M7.5 14.5h9" stroke={color} strokeWidth="1.7" strokeLinecap="round" />
    </svg>
  );
}

function PartnerReportNavIcon({ color }) {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
      <rect x="4" y="3" width="16" height="18" rx="2" stroke={color} strokeWidth="1.7" />
      <path d="M8 8h8M8 12h8M8 16h5" stroke={color} strokeWidth="1.7" strokeLinecap="round" />
    </svg>
  );
}

function AbyssNavIcon({ color }) {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
      <path d="M3 8c2 1.5 4 1.5 6 0s4-1.5 6 0 4 1.5 6 0" stroke={color} strokeWidth="1.7" strokeLinecap="round" />
      <path d="M3 13c2 1.5 4 1.5 6 0s4-1.5 6 0 4 1.5 6 0" stroke={color} strokeWidth="1.7" strokeLinecap="round" />
      <path d="M3 18c2 1.5 4 1.5 6 0s4-1.5 6 0 4 1.5 6 0" stroke={color} strokeWidth="1.7" strokeLinecap="round" />
    </svg>
  );
}

function ReviewsNavIcon({ color }) {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
      <path d="M9 11.5 11 13.5 15.5 9" stroke={color} strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
      <rect x="4" y="3" width="16" height="18" rx="2" stroke={color} strokeWidth="1.7" />
    </svg>
  );
}

function AdminNavIcon({ color }) {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
      <circle cx="12" cy="12" r="2.6" stroke={color} strokeWidth="1.7" />
      <path d="M12 3.5v2.2M12 18.3v2.2M20.5 12h-2.2M5.7 12H3.5M17.8 6.2l-1.5 1.5M7.7 16.3l-1.5 1.5M17.8 17.8l-1.5-1.5M7.7 7.7 6.2 6.2" stroke={color} strokeWidth="1.7" strokeLinecap="round" />
    </svg>
  );
}

function ChevronIcon({ color, open }) {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      style={{ marginLeft: "auto", transform: open ? "rotate(90deg)" : "none", transition: "transform .18s ease" }}
    >
      <path d="M9 6l6 6-6 6" stroke={color} strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function SignOutIcon({ color }) {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
      <path d="M15 17.5V19a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h7a2 2 0 0 1 2 2v1.5" stroke={color} strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M9.5 12H21m0 0-3.2-3.2M21 12l-3.2 3.2" stroke={color} strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

const PARTNER_SECTORS = [
  { key: "academia", label: "Academia" },
  { key: "legislative", label: "Legislative" },
  { key: "industrial", label: "Industrial" },
];

const RESEARCHER_SECTIONS = [
  { key: "novelty-dna", label: "Novelty DNA" },
  { key: "species-correction", label: "Species correction" },
  { key: "comments", label: "Comments" },
];

function NavItem({ to, label, icon, active, onNavigate }) {
  return (
    <Link to={to} onClick={onNavigate} style={navItemStyle(active)}>
      {active && <span style={navItemTickStyle} />}
      {icon}
      <span style={navItemLabelStyle(active)}>{label}</span>
    </Link>
  );
}

function NavGroup({ basePath, label, icon, sections, isActive, open, setOpen, close }) {
  const activeBase = isActive(basePath);
  return (
    <>
      <div onClick={() => setOpen((v) => !v)} style={{ ...navItemStyle(activeBase), cursor: "pointer" }}>
        {activeBase && <span style={navItemTickStyle} />}
        {icon}
        <span style={navItemLabelStyle(activeBase)}>{label}</span>
        <ChevronIcon color={sidebarColors.itemIcon} open={open || activeBase} />
      </div>
      {(open || activeBase) && (
        <div style={{ display: "flex", flexDirection: "column", gap: 1, marginTop: 2, marginBottom: 4 }}>
          {sections.map((s) => (
            <Link
              key={s.key}
              to={`${basePath}/${s.key}`}
              onClick={close}
              style={subNavItemStyle(isActive(`${basePath}/${s.key}`))}
            >
              {s.label}
            </Link>
          ))}
        </div>
      )}
    </>
  );
}

export default function SidebarMenu() {
  const [open, setOpen] = useState(false);
  const [partnerOpen, setPartnerOpen] = useState(false);
  const [researcherOpen, setResearcherOpen] = useState(false);
  const { user, isAdmin, isCurator, logout } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();

  const close = () => setOpen(false);

  const isActive = (path) => location.pathname.startsWith(path);

  const handleSignOut = () => {
    close();
    logout();
    navigate("/");
  };

  return (
    <>
      <button
        aria-label={open ? "Close menu" : "Open menu"}
        onClick={() => setOpen((v) => !v)}
        style={sidebarTriggerStyle}
      >
        <HamburgerIcon open={open} />
      </button>

      <div style={sidebarOverlayStyle(open)} onClick={close} />

      <aside style={sidebarPanelStyle(open)} aria-hidden={!open}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 11, padding: "56px 14px 22px" }}>
          <svg width="20" height="20" viewBox="0 0 26 26" fill="none">
            <path d="M6 2c0 6 14 8 14 13S6 20 6 24" stroke={sidebarColors.accentBlue} strokeWidth="2" strokeLinecap="round" />
            <path d="M20 2c0 6-14 8-14 13s14 5 14 9" stroke={sidebarColors.accentCyan} strokeWidth="2" strokeLinecap="round" />
          </svg>
          <span style={{ fontWeight: 600, letterSpacing: "0.28em", fontSize: 12, color: sidebarColors.wordmark }}>
            SYNTH VEDA
          </span>
        </div>

        <nav style={{ display: "flex", flexDirection: "column", gap: 3 }}>
          <NavItem
            to="/upload"
            label="Upload Analysis"
            active={isActive("/upload")}
            onNavigate={close}
            icon={<UploadNavIcon color={isActive("/upload") ? sidebarColors.itemIconActive : sidebarColors.itemIcon} />}
          />
          <NavGroup
            basePath="/researcher-mode"
            label="Researcher Mode"
            icon={<ResearcherNavIcon color={isActive("/researcher-mode") ? sidebarColors.itemIconActive : sidebarColors.itemIcon} />}
            sections={RESEARCHER_SECTIONS}
            isActive={isActive}
            open={researcherOpen}
            setOpen={setResearcherOpen}
            close={close}
          />

          <NavGroup
            basePath="/partner-report"
            label="Partner Report"
            icon={<PartnerReportNavIcon color={isActive("/partner-report") ? sidebarColors.itemIconActive : sidebarColors.itemIcon} />}
            sections={PARTNER_SECTORS}
            isActive={isActive}
            open={partnerOpen}
            setOpen={setPartnerOpen}
            close={close}
          />

          <NavItem
            to="/abyss"
            label="Abyss Mode"
            active={isActive("/abyss")}
            onNavigate={close}
            icon={<AbyssNavIcon color={isActive("/abyss") ? sidebarColors.itemIconActive : sidebarColors.itemIcon} />}
          />
          {isCurator && (
            <NavItem
              to="/reviews"
              label="Reviews"
              active={isActive("/reviews")}
              onNavigate={close}
              icon={<ReviewsNavIcon color={isActive("/reviews") ? sidebarColors.itemIconActive : sidebarColors.itemIcon} />}
            />
          )}
          {isAdmin && (
            <NavItem
              to="/admin"
              label="Admin"
              active={isActive("/admin")}
              onNavigate={close}
              icon={<AdminNavIcon color={isActive("/admin") ? sidebarColors.itemIconActive : sidebarColors.itemIcon} />}
            />
          )}
        </nav>

        <div style={sidebarFooterWrapStyle}>
          {user && (
            <div style={sidebarUserRowStyle}>
              <span style={{ fontSize: 13, fontWeight: 500, color: sidebarColors.headerName }}>
                {user.display_name || "Researcher"}
              </span>
              <span style={{ fontSize: "11.5px", color: sidebarColors.headerMuted }}>{user.email}</span>
            </div>
          )}
          <div onClick={handleSignOut} style={navItemStyle(false)}>
            <SignOutIcon color={sidebarColors.itemIcon} />
            <span style={navItemLabelStyle(false)}>Sign out</span>
          </div>
        </div>
      </aside>
    </>
  );
}
