export const authColors = {
  pageBg: "#020409",
  cardBg: "#060A14",
  cardBorder: "#14233C",
  leftBg: "#02060F",
  textPrimary: "#F5F5F3",
  topRightPrompt: "#7A8093",
  textSecondary: "#7A8699",
  labelText: "#B8BECB",
  dividerText: "#4A5163",
  textMuted: "#3D4A61",
  border: "#1C2E4C",
  ghostBorder: "rgba(255,255,255,0.16)",
  inputBg: "#081020",
  dividerLine: "#1C2334",
  accentBlue: "#3B9EFF",
  accentCyan: "#7FD4FF",
  errorBg: "rgba(255,80,80,0.08)",
  errorBorder: "rgba(255,80,80,0.2)",
  errorText: "#FF9B9B",
  infoBg: "rgba(59,158,255,0.12)",
  infoBorder: "rgba(59,158,255,0.3)",
};

export const authInputStyle = {
  padding: "13px 16px",
  border: `1px solid ${authColors.border}`,
  borderRadius: 12,
  background: authColors.inputBg,
  fontFamily: "inherit",
  fontSize: "14.5px",
  color: authColors.textPrimary,
  outline: "none",
  width: "100%",
  boxSizing: "border-box",
};

export const authLabelStyle = {
  display: "flex",
  flexDirection: "column",
  gap: 7,
};

export const authLabelTextStyle = {
  fontSize: 13,
  fontWeight: 500,
  color: authColors.labelText,
};

export const authPrimaryButtonStyle = {
  marginTop: 8,
  width: "100%",
  padding: "14px 0",
  border: "1px solid rgba(255,255,255,0.28)",
  borderRadius: 999,
  background:
    "linear-gradient(180deg, rgba(64,160,255,0.95) 0%, rgba(20,110,255,0.80) 55%, rgba(10,90,225,0.88) 100%)",
  backdropFilter: "blur(14px)",
  WebkitBackdropFilter: "blur(14px)",
  boxShadow:
    "inset 0 1.5px 0 rgba(255,255,255,0.45), inset 0 -2px 6px rgba(10,60,170,0.4), 0 8px 28px rgba(20,110,255,0.42)",
  color: "#FFFFFF",
  textShadow: "0 1px 2px rgba(8,50,140,0.4)",
  fontFamily: "inherit",
  fontSize: 15,
  fontWeight: 500,
  cursor: "pointer",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  gap: 10,
};

export const authGoogleButtonStyle = {
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  gap: 10,
  width: "100%",
  padding: "13px 0",
  border: `1px solid ${authColors.ghostBorder}`,
  borderRadius: 999,
  background: "linear-gradient(180deg, rgba(255,255,255,0.10) 0%, rgba(255,255,255,0.04) 100%)",
  backdropFilter: "blur(14px)",
  WebkitBackdropFilter: "blur(14px)",
  boxShadow:
    "inset 0 1px 0 rgba(255,255,255,0.22), inset 0 -1px 0 rgba(255,255,255,0.05), 0 6px 18px rgba(0,0,0,0.28)",
  fontFamily: "inherit",
  fontSize: "14.5px",
  fontWeight: 500,
  color: authColors.textPrimary,
};

export const authGhostButtonStyle = {
  display: "inline-flex",
  alignItems: "center",
  padding: "9px 20px",
  border: `1px solid ${authColors.ghostBorder}`,
  borderRadius: 999,
  color: authColors.textPrimary,
  fontWeight: 500,
  textDecoration: "none",
  background: "rgba(255,255,255,0.06)",
  backdropFilter: "blur(14px)",
  WebkitBackdropFilter: "blur(14px)",
  boxShadow:
    "inset 0 1px 0 rgba(255,255,255,0.22), inset 0 -1px 0 rgba(255,255,255,0.05), 0 4px 14px rgba(0,0,0,0.25)",
};

export const authDividerStyle = {
  display: "flex",
  alignItems: "center",
  gap: 14,
  color: authColors.dividerText,
  fontSize: 12,
  letterSpacing: "0.08em",
};

export const authErrorStyle = {
  marginTop: 12,
  padding: "10px 14px",
  borderRadius: 8,
  fontSize: 13,
  textAlign: "center",
  background: authColors.errorBg,
  border: `1px solid ${authColors.errorBorder}`,
  color: authColors.errorText,
};

export const authInfoStyle = {
  marginTop: 12,
  padding: "10px 14px",
  borderRadius: 8,
  fontSize: 13,
  textAlign: "center",
  background: authColors.infoBg,
  border: `1px solid ${authColors.infoBorder}`,
  color: authColors.accentBlue,
};
