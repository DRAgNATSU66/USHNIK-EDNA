// Shared look and small helpers for the Industrial partner page. Same scale
// convention as Academia.jsx / Legislative.jsx (s() = n * 1.18) so card
// padding, radii and type sizes stay on one ratio across Partner Report.
import { tokens } from "../../../components/shared/tokens";
import { liquidGlass } from "../../../styles/liquidGlass";

const SCALE = 1.18;
export const s = (n) => Math.round(n * SCALE * 10) / 10;

export const cardBase = {
  minWidth: 0,
  display: "flex",
  flexDirection: "column",
  gap: s(10),
  padding: `${s(20)}px ${s(22)}px`,
  borderRadius: s(9),
  border: "1px solid rgba(140,170,230,0.14)",
  background: "linear-gradient(180deg, rgba(140,170,230,0.06) 0%, rgba(6,10,20,0.7) 100%)",
  boxShadow: "inset 0 1px 0 rgba(255,255,255,0.10), 0 14px 34px rgba(0,0,0,0.4)",
};

export const panelLabelStyle = { fontSize: s(11), fontWeight: 600, letterSpacing: "0.08em", color: tokens.wordmark };

export const noteStyle = { fontSize: s(10.5), lineHeight: 1.5, color: tokens.pending };

export const rowStyle = {
  display: "flex",
  flexDirection: "column",
  gap: s(5),
  padding: `${s(11)}px ${s(13)}px`,
  borderRadius: s(6),
  border: "1px solid #101D33",
  background: "rgba(8,14,26,0.55)",
};

export const monoStyle = { fontFamily: "ui-monospace,monospace", fontSize: s(10.5), color: tokens.pending };

export const linkStyle = { fontSize: s(11.5), color: tokens.accentCyan, textDecoration: "none" };

// Raised controls use the app's shared liquid-glass material (same recipe
// as Legislative.jsx) so every primary button on Partner Report reads as one system.
export const primaryBtnStyle = {
  alignSelf: "flex-start",
  padding: `${s(8)}px ${s(18)}px`,
  borderRadius: 999,
  fontFamily: "inherit",
  fontSize: s(12),
  fontWeight: 600,
  color: "#FFFFFF",
  textShadow: "0 1px 2px rgba(8,50,140,0.4)",
  cursor: "pointer",
  ...liquidGlass({
    top: "rgba(120,185,255,0.95)",
    bottom: "rgba(20,110,255,0.88)",
    border: "rgba(255,255,255,0.40)",
    highlight: "rgba(255,255,255,0.55)",
    innerShadow: "rgba(10,60,170,0.35)",
    outerShadow: "0 10px 26px rgba(20,110,255,0.42)",
    blur: 16,
  }),
};

export const secondaryBtnStyle = {
  alignSelf: "flex-start",
  padding: `${s(6)}px ${s(13)}px`,
  border: "1px solid #1C2E4C",
  borderRadius: s(8),
  background: "#080F1C",
  fontFamily: "inherit",
  fontSize: s(11.5),
  fontWeight: 600,
  color: tokens.wordmark,
  cursor: "pointer",
};

export const inputStyle = {
  width: "100%",
  boxSizing: "border-box",
  padding: "8px 10px",
  border: "1px solid #17253D",
  borderRadius: 3,
  background: "#080F1C",
  color: tokens.textPrimary,
  fontFamily: "inherit",
  fontSize: 12.5,
  colorScheme: "dark",
};

export const fieldLabelStyle = {
  display: "flex", flexDirection: "column", gap: 4, fontSize: s(10), letterSpacing: "0.06em", color: tokens.sectionSubtext,
};

/** "2026-10-10T08:05:00" (naive UTC from the API) -> "2026-10-10". */
export const fmtDate = (v) => (v ? String(v).slice(0, 10) : "—");

/** -> "2026-10-10 08:05 UTC". */
export const fmtDateTime = (v) => (v ? `${String(v).slice(0, 16).replace("T", " ")} UTC` : "—");

export function plural(n, one, many = `${one}s`) {
  return `${n} ${n === 1 ? one : many}`;
}

/** Saves a Blob under `filename` via a temporary object URL. */
export function saveBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

/** FastAPI error (lib/api.js keeps a 422's [{loc, msg}] on e.detail) -> "field: message" lines. */
export function formatApiError(e) {
  if (Array.isArray(e?.detail)) {
    return e.detail.map((d) => {
      const loc = (d.loc || []).filter((p) => p !== "body").join(".");
      return loc ? `${loc}: ${d.msg}` : d.msg;
    });
  }
  return [e?.message || "Request failed"];
}
