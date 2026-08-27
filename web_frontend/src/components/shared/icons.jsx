// Hand-drawn icon set for the shared cross-cutting components, matching the
// stroke weight (1.5-2px, round caps) already established in
// PlaceholderScreen's DNA-strand mark and Upload's hero icons -- kept here
// rather than pulling in lucide-react/react-icons (both installed, both
// unused by any live page) so new components don't introduce a second icon
// language.

// Matches the exact triangle mark used in the Analysis Report mockup's
// "Interpretation notice" banner (frontend_zips_claude_design/
// _extracted_fasta_output/Analysis Report.dc.html).
export function WarningTriangleIcon({ size = 16, color = "currentColor" }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none">
      <path d="M8 1.5 15 14H1L8 1.5z" stroke={color} strokeWidth="1.3" strokeLinejoin="round" />
      <path d="M8 6.2v3.4M8 11.6v.4" stroke={color} strokeWidth="1.4" strokeLinecap="round" />
    </svg>
  );
}

export function ArrowRightIcon({ size = 13, color = "currentColor" }) {
  return (
    <svg width={size} height={size} viewBox="0 0 14 14" fill="none">
      <path d="M2 7h8M7 3.5 10.5 7 7 10.5" stroke={color} strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function InfoCircleIcon({ size = 15, color = "currentColor" }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none">
      <circle cx="8" cy="8" r="6.25" stroke={color} strokeWidth="1.5" />
      <path d="M8 7.2v4" stroke={color} strokeWidth="1.5" strokeLinecap="round" />
      <circle cx="8" cy="5" r="0.9" fill={color} />
    </svg>
  );
}

export function ChevronIcon({ size = 12, color = "currentColor", open = false }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 12 12"
      fill="none"
      style={{ transform: open ? "rotate(180deg)" : "none", transition: "transform .18s ease" }}
    >
      <path d="M3 4.5 6 7.5 9 4.5" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function DatabaseIcon({ size = 13, color = "currentColor" }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none">
      <ellipse cx="8" cy="4" rx="5.5" ry="2" stroke={color} strokeWidth="1.4" />
      <path d="M2.5 4v4c0 1.1 2.46 2 5.5 2s5.5-.9 5.5-2V4" stroke={color} strokeWidth="1.4" strokeLinecap="round" />
      <path d="M2.5 8v4c0 1.1 2.46 2 5.5 2s5.5-.9 5.5-2V8" stroke={color} strokeWidth="1.4" strokeLinecap="round" />
    </svg>
  );
}

export function ClockIcon({ size = 13, color = "currentColor" }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none">
      <circle cx="8" cy="8" r="6.25" stroke={color} strokeWidth="1.4" />
      <path d="M8 4.6V8.2l2.6 1.5" stroke={color} strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function TrendIcon({ size = 13, color = "currentColor" }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none">
      <path d="M2 12.5 6 8l3 2.5 5-6" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M11 4.2h3v3" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function FlaskIcon({ size = 13, color = "currentColor" }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none">
      <path d="M6.3 2h3.4" stroke={color} strokeWidth="1.4" strokeLinecap="round" />
      <path d="M6.9 2v3.6L3.4 11.7c-.6 1 .1 2.3 1.3 2.3h6.6c1.2 0 1.9-1.3 1.3-2.3L9.1 5.6V2" stroke={color} strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M4.8 9.6h6.4" stroke={color} strokeWidth="1.4" strokeLinecap="round" />
    </svg>
  );
}
