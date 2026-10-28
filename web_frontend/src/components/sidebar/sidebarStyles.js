import { liquidGlass } from "../../styles/liquidGlass";
import { uploadColors } from "../../pages/uploadStyles";

// Reuses the same palette as the New Analysis page (uploadColors) since the
// sidebar currently only appears there — keeps the two visually identical
// without a second source of truth for the shared blues/borders.
export const sidebarColors = {
  ...uploadColors,
  panelBg: "#070C17",
  panelBgSoft: "rgba(9,15,27,0.94)",
  overlayBg: "rgba(2,4,9,0.6)",
  itemHoverBg: "rgba(120,170,255,0.06)",
  itemActiveBg: "linear-gradient(90deg, rgba(20,110,255,0.16) 0%, rgba(9,16,30,0) 100%)",
  itemText: "#AEBBD1",
  itemTextActive: "#EAF2FF",
  itemIcon: "#7A8699",
  itemIconActive: "#7FBFFF",
  groupLabel: "#4A5B74",
};

export const sidebarTriggerStyle = {
  position: "fixed",
  top: 28,
  left: 24,
  zIndex: 210,
  width: 46,
  height: 46,
  borderRadius: 14,
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  cursor: "pointer",
  ...liquidGlass({
    top: "rgba(20,32,54,0.85)",
    bottom: "rgba(6,10,20,0.92)",
    border: "rgba(120,170,255,0.22)",
    highlight: "rgba(255,255,255,0.14)",
    innerShadow: "rgba(0,0,0,0.4)",
    outerShadow: "0 10px 30px rgba(0,0,0,0.45)",
    blur: 16,
  }),
};

export const sidebarOverlayStyle = (open) => ({
  position: "fixed",
  inset: 0,
  background: sidebarColors.overlayBg,
  backdropFilter: "blur(2px)",
  WebkitBackdropFilter: "blur(2px)",
  opacity: open ? 1 : 0,
  pointerEvents: open ? "auto" : "none",
  transition: "opacity .22s ease",
  zIndex: 205,
});

export const sidebarPanelStyle = (open) => ({
  position: "fixed",
  top: 0,
  left: 0,
  bottom: 0,
  width: 300,
  maxWidth: "84vw",
  display: "flex",
  flexDirection: "column",
  padding: "26px 18px 22px",
  boxSizing: "border-box",
  background: `linear-gradient(180deg, ${sidebarColors.panelBgSoft} 0%, ${sidebarColors.panelBg} 100%)`,
  borderRight: `1px solid ${sidebarColors.sectionBorder}`,
  boxShadow: "20px 0 60px rgba(0,0,0,0.5)",
  backdropFilter: "blur(20px) saturate(150%)",
  WebkitBackdropFilter: "blur(20px) saturate(150%)",
  transform: open ? "translateX(0)" : "translateX(-100%)",
  transition: "transform .25s cubic-bezier(.4,0,.2,1)",
  zIndex: 208,
});

export function navItemStyle(active) {
  return {
    display: "flex",
    alignItems: "center",
    gap: 12,
    padding: "11px 14px",
    borderRadius: 10,
    cursor: "pointer",
    textDecoration: "none",
    position: "relative",
    background: active ? sidebarColors.itemActiveBg : "transparent",
    transition: "background .15s ease",
  };
}

export const navItemTickStyle = {
  position: "absolute",
  left: 0,
  top: "50%",
  transform: "translateY(-50%)",
  width: 3,
  height: 16,
  borderRadius: 2,
  background: "linear-gradient(#5AA9FF, #1F6FE0)",
};

export function navItemLabelStyle(active) {
  return {
    fontSize: "14px",
    fontWeight: active ? 600 : 500,
    color: active ? sidebarColors.itemTextActive : sidebarColors.itemText,
    letterSpacing: "0.01em",
  };
}

export function subNavItemStyle(active) {
  return {
    display: "flex",
    alignItems: "center",
    gap: 10,
    padding: "9px 14px 9px 20px",
    marginLeft: 17,
    borderLeft: `1px solid ${sidebarColors.sectionBorder}`,
    cursor: "pointer",
    textDecoration: "none",
    fontSize: "13px",
    fontWeight: active ? 600 : 500,
    color: active ? sidebarColors.itemTextActive : sidebarColors.sectionSubtext,
    transition: "color .15s ease",
  };
}

export const sidebarGroupLabelStyle = {
  fontSize: "10.5px",
  fontWeight: 600,
  letterSpacing: "0.11em",
  textTransform: "uppercase",
  color: sidebarColors.groupLabel,
  padding: "20px 14px 8px",
};

export const sidebarFooterWrapStyle = {
  marginTop: "auto",
  paddingTop: 14,
  borderTop: `1px solid ${sidebarColors.sectionBorder}`,
  display: "flex",
  flexDirection: "column",
  gap: 4,
};

export const sidebarUserRowStyle = {
  display: "flex",
  flexDirection: "column",
  gap: 2,
  padding: "8px 14px 14px",
};
