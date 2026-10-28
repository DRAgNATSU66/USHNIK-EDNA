import { liquidGlass } from "../../styles/liquidGlass";

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

// Inputs need this same recessed-glass look (see .sv-auth-input in
// index.css, not here): pseudo-classes like :focus and :-webkit-autofill
// have to override the base box-shadow/background, and inline styles beat
// any CSS class rule regardless of selector, so an input's glass material
// can't live in this JS object the way buttons' does — only layout and
// typography stay inline here.
export const authInputStyle = {
  padding: "13px 16px",
  borderRadius: 12,
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
  borderRadius: 999,
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
  ...liquidGlass({
    top: "rgba(120,185,255,0.95)",
    bottom: "rgba(20,110,255,0.88)",
    border: "rgba(255,255,255,0.40)",
    highlight: "rgba(255,255,255,0.65)",
    innerShadow: "rgba(10,60,170,0.35)",
    outerShadow: "0 12px 32px rgba(20,110,255,0.50)",
    blur: 18,
  }),
};

// Our own button (triggers useGoogleLogin's auth-code popup — see
// Login.jsx/Signup.jsx), not Google's rendered widget, so it can carry the
// exact same liquid-glass recipe as authPrimaryButtonStyle — just tinted
// black/charcoal instead of blue, per the original theme="filled_black"
// look it replaces.
export const authGoogleButtonStyle = {
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  gap: 10,
  width: "100%",
  padding: "13px 0",
  borderRadius: 999,
  fontFamily: "inherit",
  fontSize: "14.5px",
  fontWeight: 500,
  color: "#FFFFFF",
  cursor: "pointer",
  ...liquidGlass({
    top: "rgba(72,74,82,0.92)",
    bottom: "rgba(8,9,13,0.95)",
    border: "rgba(255,255,255,0.22)",
    highlight: "rgba(255,255,255,0.38)",
    innerShadow: "rgba(0,0,0,0.45)",
    outerShadow: "0 8px 24px rgba(0,0,0,0.45)",
  }),
};

export const authGhostButtonStyle = {
  display: "inline-flex",
  alignItems: "center",
  padding: "9px 20px",
  borderRadius: 999,
  color: authColors.textPrimary,
  fontWeight: 500,
  textDecoration: "none",
  ...liquidGlass({
    top: "rgba(255,255,255,0.16)",
    bottom: "rgba(255,255,255,0.04)",
    border: "rgba(255,255,255,0.28)",
    highlight: "rgba(255,255,255,0.45)",
    innerShadow: "rgba(0,0,0,0.08)",
    outerShadow: "0 6px 18px rgba(0,0,0,0.25)",
    blur: 14,
  }),
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
