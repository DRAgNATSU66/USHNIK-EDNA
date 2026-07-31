export const uploadColors = {
  pageBg: "#020409",
  textPrimary: "#F5F5F3",
  wordmark: "#C7D3E6",
  headerMuted: "#7A8699",
  headerName: "#DCE6F5",
  headerDot: "#33455F",
  badgeBorder: "#1C3357",
  badgeBg: "rgba(20,110,255,0.10)",
  badgeText: "#7FBFFF",
  accentBlue: "#3B9EFF",
  accentCyan: "#7FD4FF",
  labelText: "#75849B",
  sectionBorder: "#15243C",
  sectionSubtext: "#5A6C86",
  cardBorderInactive: "#182B45",
  cardBorderActive: "#2E67B8",
  cardBgInactive: "rgba(7,13,24,0.9)",
  cardTitle: "#EAF2FF",
  cardDesc: "#7A8699",
  radioInactive: "#2C3E5C",
  actionsDivider: "#101E32",
  readyText: "#4A5B74",
  readyDot: "#2E67B8",
  resetBorder: "#22364F",
  resetText: "#AFC0D6",
  errorBg: "rgba(255,80,80,0.08)",
  errorBorder: "rgba(255,80,80,0.2)",
  errorText: "#FF9B9B",
};

export const uploadSlabHeaderStyle = {
  display: "flex",
  alignItems: "baseline",
  gap: 12,
  paddingLeft: 16,
  borderBottom: `1px solid ${uploadColors.sectionBorder}`,
  paddingBottom: 14,
  position: "relative",
};

// The 3px gradient tick to the left of each section header (.slab::before
// in the source design) — a pseudo-element in the original, done here as
// an explicit span since inline styles have no ::before.
export const uploadSlabTickStyle = {
  position: "absolute",
  left: 0,
  top: 2,
  width: 3,
  height: 16,
  background: "linear-gradient(#5AA9FF, #1F6FE0)",
  borderRadius: 2,
};

export const uploadSubmitButtonStyle = {
  padding: "15px 34px",
  borderRadius: 12,
  border: "1px solid rgba(150,200,255,0.35)",
  background:
    "linear-gradient(180deg, rgba(64,160,255,0.98) 0%, rgba(20,110,255,0.9) 55%, rgba(12,92,225,0.95) 100%)",
  boxShadow:
    "inset 0 1.5px 0 rgba(255,255,255,0.45), inset 0 -2px 6px rgba(10,60,170,0.4), 0 12px 34px rgba(20,110,255,0.42)",
  color: "#FFFFFF",
  textShadow: "0 1px 2px rgba(8,50,140,0.4)",
  fontFamily: "inherit",
  fontSize: 15,
  fontWeight: 600,
  cursor: "pointer",
  display: "flex",
  alignItems: "center",
  gap: 10,
  transition: "all .15s ease",
};

export const uploadResetButtonStyle = {
  padding: "15px 30px",
  borderRadius: 12,
  border: `1px solid ${uploadColors.resetBorder}`,
  background: "transparent",
  color: uploadColors.resetText,
  fontFamily: "inherit",
  fontSize: "14.5px",
  fontWeight: 600,
  cursor: "pointer",
  transition: "all .15s",
};

export function uploadDropzoneStyle(drag) {
  return {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    gap: 18,
    padding: "48px 24px",
    borderRadius: 16,
    cursor: "pointer",
    textAlign: "center",
    border: `1.5px dashed ${drag ? uploadColors.accentBlue : "#24374F"}`,
    background: drag
      ? "radial-gradient(120% 140% at 50% 0%, rgba(20,110,255,0.16), rgba(6,11,22,0.85))"
      : "linear-gradient(180deg, rgba(11,18,33,0.85), rgba(6,11,22,0.85))",
    boxShadow: drag
      ? "0 0 0 4px rgba(59,158,255,0.10), 0 18px 50px rgba(20,110,255,0.22)"
      : "inset 0 1px 0 rgba(120,170,255,0.05), 0 12px 40px rgba(0,0,0,0.35)",
    transition: "all .18s ease",
    backdropFilter: "blur(6px)",
    WebkitBackdropFilter: "blur(6px)",
  };
}

export function uploadDropzoneChipStyle(drag) {
  return {
    width: 62,
    height: 62,
    borderRadius: 16,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    background: drag
      ? "linear-gradient(180deg, rgba(80,175,255,0.42), rgba(20,110,255,0.22))"
      : "linear-gradient(180deg, rgba(50,120,220,0.24), rgba(16,90,210,0.10))",
    border: "1px solid rgba(90,170,255,0.32)",
    boxShadow: "inset 0 1px 0 rgba(255,255,255,0.22), 0 8px 22px rgba(20,110,255,0.20)",
    transition: "all .18s ease",
  };
}

function radioCard(active, { padding, borderRadius = 12 }) {
  return {
    display: "flex",
    gap: 14,
    padding,
    borderRadius,
    cursor: "pointer",
    transition: "all .15s ease",
    border: `1px solid ${active ? uploadColors.cardBorderActive : uploadColors.cardBorderInactive}`,
    background: active
      ? "linear-gradient(180deg, rgba(18,70,150,0.9), rgba(9,16,30,0.94))"
      : uploadColors.cardBgInactive,
    backdropFilter: "blur(4px)",
    WebkitBackdropFilter: "blur(4px)",
    boxShadow: active
      ? "inset 0 1px 0 rgba(120,180,255,0.16), 0 8px 24px rgba(20,110,255,0.14)"
      : "0 6px 18px rgba(0,0,0,0.35)",
  };
}

function radioOuter(active, size) {
  return {
    flex: "0 0 auto",
    width: size,
    height: size,
    marginTop: 1,
    borderRadius: "50%",
    border: `1.5px solid ${active ? uploadColors.accentBlue : uploadColors.radioInactive}`,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    background: active ? "rgba(59,158,255,0.15)" : "transparent",
    transition: "all .15s",
  };
}

function radioDot(active, size) {
  return {
    width: size,
    height: size,
    borderRadius: "50%",
    background: active ? uploadColors.accentBlue : "transparent",
    boxShadow: active ? "0 0 8px rgba(59,158,255,0.9)" : "none",
  };
}

// Analysis Mode cards — the larger of the two card sizes.
export const modeCardStyle = (active) => radioCard(active, { padding: "16px 18px" });
export const modeRadioOuterStyle = (active) => radioOuter(active, 18);
export const modeRadioDotStyle = (active) => radioDot(active, 8);

// Processing Model cards — slightly smaller.
export const modelCardStyle = (active) => radioCard(active, { padding: "14px 16px" });
export const modelRadioOuterStyle = (active) => radioOuter(active, 17);
export const modelRadioDotStyle = (active) => radioDot(active, 7.5);
