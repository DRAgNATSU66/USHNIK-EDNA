import SidebarMenu from "./sidebar/SidebarMenu";
import { uploadColors } from "../pages/uploadStyles";

// Themed stub for sidebar destinations that don't have real UI yet —
// keeps navigation functional and on-brand while each page's actual
// UX (loading/blank/slow-network/processing states, etc.) gets designed
// separately later.
export default function PlaceholderScreen({ title, description }) {
  return (
    <div style={{ background: uploadColors.pageBg, minHeight: "100vh" }}>
      <SidebarMenu />
      <div
        style={{
          minHeight: "100vh",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          gap: 16,
          padding: "24px",
          textAlign: "center",
          position: "relative",
        }}
      >
        <div
          style={{
            position: "absolute",
            inset: 0,
            pointerEvents: "none",
            background:
              "radial-gradient(52% 40% at 50% -4%, rgba(20,110,255,0.14) 0%, rgba(2,6,15,0) 60%), radial-gradient(46% 46% at 96% 44%, rgba(40,130,255,0.10) 0%, rgba(2,6,15,0) 60%)",
          }}
        />
        <div style={{ display: "flex", alignItems: "center", gap: 11, position: "relative" }}>
          <svg width="20" height="20" viewBox="0 0 26 26" fill="none">
            <path d="M6 2c0 6 14 8 14 13S6 20 6 24" stroke={uploadColors.accentBlue} strokeWidth="2" strokeLinecap="round" />
            <path d="M20 2c0 6-14 8-14 13s14 5 14 9" stroke={uploadColors.accentCyan} strokeWidth="2" strokeLinecap="round" />
          </svg>
          <span style={{ fontWeight: 600, letterSpacing: "0.28em", fontSize: 12, color: uploadColors.wordmark }}>
            SYNTH VEDA
          </span>
        </div>
        <h1 style={{ margin: 0, fontSize: 32, fontWeight: 600, letterSpacing: "-0.02em", color: uploadColors.textPrimary, position: "relative" }}>
          {title}
        </h1>
        <p style={{ margin: 0, maxWidth: 420, fontSize: 14.5, lineHeight: 1.6, color: uploadColors.sectionSubtext, position: "relative" }}>
          {description}
        </p>
        <span
          style={{
            marginTop: 6,
            fontSize: 11.5,
            fontWeight: 600,
            letterSpacing: "0.08em",
            textTransform: "uppercase",
            color: uploadColors.badgeText,
            border: `1px solid ${uploadColors.badgeBorder}`,
            background: uploadColors.badgeBg,
            borderRadius: 6,
            padding: "4px 12px",
            position: "relative",
          }}
        >
          Coming soon
        </span>
      </div>
    </div>
  );
}
