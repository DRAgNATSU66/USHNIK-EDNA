import { tokens } from "./tokens";

// Shared "this is sample content, not a real computation" pill -- first used
// on Field Log's edit-history/attachments previews, reused across Partner
// Report's statistics panels that have no backend computation behind them
// yet (rarefaction, network modularity, phylogenetics, etc.).
export default function MockTag({ label = "MOCK — NO BACKEND YET" }) {
  return (
    <span
      style={{
        fontSize: 8.5,
        padding: "1px 7px",
        borderRadius: 999,
        border: `1px solid ${tokens.purpleBorder}`,
        background: tokens.purpleBg,
        color: tokens.purple,
        letterSpacing: "0.03em",
        fontWeight: 700,
        whiteSpace: "nowrap",
      }}
    >
      {label}
    </span>
  );
}
