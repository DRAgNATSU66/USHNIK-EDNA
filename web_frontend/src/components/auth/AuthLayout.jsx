import { Link } from "react-router-dom";
import HelixCanvas from "./HelixCanvas";
import { authColors } from "./authStyles";

export default function AuthLayout({ topRightPrompt, topRightLabel, topRightHref, children }) {
  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 24,
        boxSizing: "border-box",
        background: authColors.pageBg,
        fontFamily: "'Instrument Sans', system-ui, sans-serif",
      }}
    >
      <div
        style={{
          width: 1240,
          maxWidth: "100%",
          minHeight: 720,
          background: authColors.cardBg,
          borderRadius: 20,
          display: "grid",
          gridTemplateColumns: "minmax(320px,500px) minmax(0,1fr)",
          overflow: "hidden",
          boxShadow: "0 24px 60px rgba(0,0,0,0.5)",
        }}
      >
        {/* Left: dark DNA panel */}
        <div
          style={{
            position: "relative",
            background: authColors.leftBg,
            color: authColors.textPrimary,
            display: "flex",
            flexDirection: "column",
            justifyContent: "space-between",
            padding: "44px 44px 40px",
            overflow: "hidden",
          }}
        >
          <div
            style={{
              position: "absolute",
              inset: 0,
              background:
                "radial-gradient(90% 70% at 15% 100%, rgba(41,171,226,0.20) 0%, rgba(12,18,32,0) 60%), radial-gradient(70% 50% at 90% 8%, rgba(109,91,208,0.22) 0%, rgba(12,18,32,0) 55%)",
            }}
          />
          <div style={{ position: "relative", display: "flex", alignItems: "center", justifyContent: "center", gap: 12 }}>
            <svg width="26" height="26" viewBox="0 0 26 26" fill="none">
              <path d="M6 2c0 6 14 8 14 13S6 20 6 24" stroke={authColors.accentAmber} strokeWidth="2" strokeLinecap="round" />
              <path d="M20 2c0 6-14 8-14 13s14 5 14 9" stroke={authColors.accentPurple} strokeWidth="2" strokeLinecap="round" />
            </svg>
            <span style={{ fontWeight: 600, letterSpacing: "0.22em", fontSize: 13 }}>SYNTH VEDA</span>
          </div>
          <div style={{ position: "relative", alignSelf: "center", animation: "sv-helix-float 7s ease-in-out infinite" }}>
            <HelixCanvas />
          </div>
          <div style={{ position: "relative", display: "flex", flexDirection: "column", gap: 14 }}>
            <h1 style={{ margin: 0, fontSize: 32, lineHeight: 1.18, fontWeight: 500, letterSpacing: "-0.02em" }}>
              Unravel the intricacies of your genetic code.
            </h1>
            <p style={{ margin: 0, fontSize: 14, lineHeight: 1.6, color: "rgba(245,245,243,0.62)", maxWidth: "36ch" }}>
              Precision eDNA sequencing and AI-driven analysis, from sample to insight.
            </p>
            <div style={{ display: "flex", gap: 8, marginTop: 6 }}>
              <span style={{ width: 22, height: 4, borderRadius: 2, background: authColors.accentPurple }} />
              <span style={{ width: 8, height: 4, borderRadius: 2, background: "rgba(245,245,243,0.25)" }} />
              <span style={{ width: 8, height: 4, borderRadius: 2, background: "rgba(245,245,243,0.25)" }} />
            </div>
          </div>
        </div>

        {/* Right: form */}
        <div style={{ display: "flex", flexDirection: "column", padding: "44px clamp(32px,7vw,96px) 36px", boxSizing: "border-box", minWidth: 0 }}>
          <div style={{ display: "flex", justifyContent: "flex-end", alignItems: "center", gap: 12, fontSize: 13, color: authColors.textMuted }}>
            <span>{topRightPrompt}</span>
            <Link
              to={topRightHref}
              style={{
                display: "inline-flex",
                alignItems: "center",
                padding: "9px 20px",
                border: `1px solid ${authColors.border}`,
                borderRadius: 999,
                color: authColors.textPrimary,
                fontWeight: 500,
                textDecoration: "none",
              }}
            >
              {topRightLabel}
            </Link>
          </div>
          <div style={{ flex: 1, display: "flex", flexDirection: "column", justifyContent: "center", maxWidth: 400, width: "100%", alignSelf: "center" }}>
            {children}
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, color: authColors.textMuted }}>
            <span>© 2026 Synth Veda Labs</span>
            <div style={{ display: "flex", gap: 18 }}>
              <a href="#" style={{ color: authColors.textMuted }}>Privacy</a>
              <a href="#" style={{ color: authColors.textMuted }}>Terms</a>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
