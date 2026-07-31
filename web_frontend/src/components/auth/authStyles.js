export const authColors = {
  pageBg: "#05070C",
  cardBg: "#12141C",
  leftBg: "#0C1220",
  textPrimary: "#F5F5F3",
  textSecondary: "rgba(245,245,243,0.62)",
  textMuted: "rgba(245,245,243,0.45)",
  border: "rgba(245,245,243,0.14)",
  inputBg: "rgba(255,255,255,0.04)",
  accentPurple: "#8B7BE0",
  accentAmber: "#F59E0B",
  errorBg: "rgba(255,80,80,0.08)",
  errorBorder: "rgba(255,80,80,0.2)",
  errorText: "#FF9B9B",
  infoBg: "rgba(139,123,224,0.12)",
  infoBorder: "rgba(139,123,224,0.3)",
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
  color: authColors.textSecondary,
};

export const authPrimaryButtonStyle = {
  marginTop: 8,
  width: "100%",
  padding: "14px 0",
  border: "none",
  borderRadius: 999,
  background: authColors.textPrimary,
  color: authColors.leftBg,
  fontFamily: "inherit",
  fontSize: 15,
  fontWeight: 500,
  cursor: "pointer",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  gap: 10,
};

export const authDividerStyle = {
  display: "flex",
  alignItems: "center",
  gap: 14,
  color: authColors.textMuted,
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
  color: authColors.accentPurple,
};
