import { uploadColors } from "./uploadStyles";

export const jobColors = {
  ...uploadColors,
  circlePendingBorder: "#2C3E5C",
  circlePendingBg: "rgba(8,14,26,0.5)",
  circleDoneBorderColor: "rgba(255,255,255,0.35)",
  trackColor: "#152439",
  failedBg: "linear-gradient(180deg, rgba(255,110,110,0.95) 0%, rgba(210,50,50,0.92) 100%)",
  failedGlow: "0 0 24px rgba(255,90,90,0.4)",
};

export const CIRCLE_SIZE = 60;
export const RING_SIZE = 72;

export function circleWrapStyle() {
  return {
    position: "relative",
    width: RING_SIZE,
    height: RING_SIZE,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    flex: "0 0 auto",
  };
}

export const spinnerRingStyle = {
  position: "absolute",
  inset: 0,
  borderRadius: "50%",
  border: "3px solid rgba(59,158,255,0.15)",
  borderTopColor: jobColors.accentBlue,
  animation: "sv-spin 0.85s linear infinite",
};

export function circleCoreStyle(status) {
  // status: "pending" | "active" | "done" | "failed"
  const base = {
    width: CIRCLE_SIZE,
    height: CIRCLE_SIZE,
    borderRadius: "50%",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    fontSize: 17,
    fontWeight: 700,
    transition: "background .35s ease, border-color .35s ease, box-shadow .35s ease, transform .3s ease",
    boxSizing: "border-box",
  };
  if (status === "done") {
    return {
      ...base,
      background: "linear-gradient(180deg, rgba(120,185,255,0.95) 0%, rgba(20,110,255,0.9) 100%)",
      border: `1px solid ${jobColors.circleDoneBorderColor}`,
      boxShadow: "0 8px 22px rgba(20,110,255,0.4)",
      color: "#FFFFFF",
    };
  }
  if (status === "failed") {
    return {
      ...base,
      background: jobColors.failedBg,
      border: "1px solid rgba(255,255,255,0.35)",
      boxShadow: jobColors.failedGlow,
      color: "#FFFFFF",
    };
  }
  if (status === "active") {
    return {
      ...base,
      background: jobColors.circlePendingBg,
      border: `1.5px solid ${jobColors.accentBlue}`,
      boxShadow: "0 0 22px rgba(59,158,255,0.32)",
      color: jobColors.accentBlue,
    };
  }
  return {
    ...base,
    background: jobColors.circlePendingBg,
    border: `2px solid ${jobColors.circlePendingBorder}`,
    color: jobColors.sectionSubtext,
  };
}

export function stepLabelStyle(status) {
  return {
    marginTop: 12,
    fontSize: 12.5,
    fontWeight: status === "active" ? 700 : 500,
    color:
      status === "done"
        ? jobColors.headerName
        : status === "active"
        ? "#EAF2FF"
        : status === "failed"
        ? "#FF9B9B"
        : jobColors.sectionSubtext,
    textAlign: "center",
    maxWidth: 96,
    lineHeight: 1.35,
    transition: "color .3s ease",
  };
}

export function connectorTrackStyle() {
  return {
    flex: "1 1 28px",
    minWidth: 20,
    height: 3,
    borderRadius: 2,
    background: jobColors.trackColor,
    position: "relative",
    overflow: "hidden",
    marginBottom: 34, // vertically aligns with circle centers, above labels
  };
}

export function connectorFillStyle(filled) {
  return {
    position: "absolute",
    inset: 0,
    borderRadius: 2,
    background: "linear-gradient(90deg, #5AA9FF, #1F6FE0)",
    transform: filled ? "scaleX(1)" : "scaleX(0)",
    transformOrigin: "left",
    transition: "transform .4s ease .08s",
  };
}

export const metaChipStyle = {
  display: "inline-flex",
  alignItems: "center",
  gap: 8,
  padding: "6px 14px",
  borderRadius: 999,
  border: `1px solid ${jobColors.sectionBorder}`,
  background: "rgba(9,15,27,0.6)",
  fontSize: 12.5,
  color: jobColors.headerMuted,
};

export const metaChipValueStyle = {
  color: jobColors.headerName,
  fontWeight: 600,
  fontFamily: "monospace",
};
