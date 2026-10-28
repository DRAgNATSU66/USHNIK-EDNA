import { useEffect, useRef, useState } from "react";
import { tokens } from "./tokens";
import { ChevronIcon } from "./icons";

/**
 * Custom-styled dropdown -- replaces native <select>. A native select's
 * closed box can be restyled with CSS, but its open options popup is
 * rendered by the OS/browser and largely ignores CSS (default white
 * background, default blue highlight in Chromium) -- it breaks straight
 * out of the dark theme the moment a user opens it. This renders the whole
 * thing (trigger + option list) as real DOM we control.
 *
 * @param {{value: string, label: string}[]} options
 */
export default function Dropdown({ options, value, onChange, minWidth = 150 }) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef(null);
  const current = options.find((o) => o.value === value);

  useEffect(() => {
    if (!open) return;
    const onDocClick = (e) => {
      if (rootRef.current && !rootRef.current.contains(e.target)) setOpen(false);
    };
    const onKey = (e) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDocClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div ref={rootRef} style={{ position: "relative", minWidth }}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        style={{
          width: "100%",
          boxSizing: "border-box",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 10,
          padding: "8px 12px",
          border: `1px solid ${open ? tokens.accentBlue : "#17253D"}`,
          borderRadius: 3,
          background: "#080F1C",
          color: tokens.textPrimary,
          fontFamily: "inherit",
          fontSize: 12.5,
          cursor: "pointer",
          boxShadow: open ? "0 0 0 3px rgba(59,158,255,0.18)" : "none",
        }}
      >
        <span>{current?.label ?? ""}</span>
        <ChevronIcon size={11} color={tokens.pending} open={open} />
      </button>

      {open && (
        <div
          style={{
            position: "absolute",
            top: "calc(100% + 6px)",
            left: 0,
            minWidth: "100%",
            zIndex: 30,
            padding: 4,
            borderRadius: 6,
            border: `1px solid ${tokens.sectionBorder}`,
            background: "#0A1120",
            boxShadow: "0 16px 40px rgba(0,0,0,0.5)",
            display: "flex",
            flexDirection: "column",
            gap: 1,
          }}
        >
          {options.map((o) => {
            const active = o.value === value;
            return (
              <button
                key={o.value}
                type="button"
                onClick={() => { onChange(o.value); setOpen(false); }}
                style={{
                  textAlign: "left",
                  padding: "8px 10px",
                  borderRadius: 4,
                  border: "none",
                  background: active ? "rgba(20,110,255,0.14)" : "transparent",
                  color: active ? tokens.accentCyan : tokens.wordmark,
                  fontFamily: "inherit",
                  fontSize: 12.5,
                  fontWeight: active ? 600 : 400,
                  cursor: "pointer",
                  whiteSpace: "nowrap",
                }}
                onMouseEnter={(e) => { if (!active) e.currentTarget.style.background = "rgba(120,170,255,0.06)"; }}
                onMouseLeave={(e) => { if (!active) e.currentTarget.style.background = "transparent"; }}
              >
                {o.label}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
