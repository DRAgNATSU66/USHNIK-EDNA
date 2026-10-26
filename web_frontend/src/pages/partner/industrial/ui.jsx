// Small presentational pieces shared by the Industrial page panels.
import { tokens, pillStyle } from "../../../components/shared/tokens";
import { panelLabelStyle, s } from "./styles";

export function Pill({ tone = "pending", children, title }) {
  return <span style={{ ...pillStyle(tone), fontSize: 10.5, padding: "2px 9px" }} title={title}>{children}</span>;
}

/** Error text for a failed load: says what failed, never shows a fallback number. */
export function ErrorLine({ what, error }) {
  if (!error) return null;
  return (
    <span role="alert" style={{ fontSize: s(11.5), color: tokens.danger }}>
      Could not load {what}: {error.message || "request failed"}
    </span>
  );
}

export function SectionLabel({ children, right }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: s(10), flexWrap: "wrap" }}>
      <h2 style={{ ...panelLabelStyle, margin: 0 }}>{children}</h2>
      {right}
    </div>
  );
}
