import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import SidebarMenu from "../../components/sidebar/SidebarMenu";
import { tokens } from "../../components/shared/tokens";
import MockTag from "../../components/shared/MockTag";
import { getReport, getUpload, listReports, listFieldEntries, createFieldEntry } from "../../lib/api";
import treeArt from "../../assets/fieldlog-tree.png";

// Single scale factor applied to every size on this page (container width,
// padding, gaps, font sizes) -- keeps every ratio identical to the
// pre-scale design while letting the three panels sit side by side as
// squarer cards that fill more of the viewport, per direct feedback that
// the stacked layout read as a tall, narrow rectangle.
const SCALE = 1.32;
const s = (n) => Math.round(n * SCALE * 10) / 10;

// Sample content for the two panels the backend doesn't support writes for
// yet (per-note edit history, file attachments). Shown with full designed
// interactivity per the mockup, but tagged MOCK everywhere it appears so
// nobody mistakes it for a real record.
const MOCK_NOTE = {
  author_name: "Ushnik Chakrabarti",
  created_at_label: "2026-08-14 17:22",
  body: "Heavy rainfall runoff entered the sampling zone ~40 min before collection — flagging possible freshwater dilution for replicate B.",
  orig: "Rainfall runoff near sampling zone, may not matter.",
  orig_when: "2026-08-14 16:58",
};

const MOCK_FILES = [
  { id: 1, name: "collection-site-north.jpg", ext: "JPG", size: "4.1 MB", who: "M. Fernandes", when: "12 Aug" },
  { id: 2, name: "bloom-surface-photo.png", ext: "PNG", size: "6.8 MB", who: "Dr. A. Rao", when: "13 Aug" },
  { id: 3, name: "regional-vibrio-survey-2025.pdf", ext: "PDF", size: "1.2 MB", who: "Ushnik Chakrabarti", when: "14 Aug" },
];
const FILE_ICON_COLOR = { PDF: tokens.danger, JPG: tokens.accentCyan, PNG: tokens.success };

const pageStyle = {
  position: "relative",
  background: tokens.pageBg,
  minHeight: "100vh",
  color: tokens.textPrimary,
  fontFamily: "'Instrument Sans', system-ui, sans-serif",
};

const ambientGlow = {
  position: "fixed",
  inset: 0,
  pointerEvents: "none",
  background: "radial-gradient(70% 40% at 55% 0%, rgba(20,110,255,0.10) 0%, rgba(2,6,15,0) 60%)",
};

// Fully opaque at the base (0.7 -> 0.97 -> 1) since the tree art now sits
// as a fixed, page-wide background behind every card instead of embedded
// in just one -- 0.97 still let it show through enough to hurt text
// readability at the animation's brighter end, so this goes all the way to
// solid; the top-of-gradient sheen stays faint and translucent for texture,
// but the card body itself no longer lets anything behind it read through
// (same fix used for Abyss Mode's and Novelty DNA's panelStyle for the
// same reason).
function panel() {
  return {
    display: "flex",
    flexDirection: "column",
    gap: s(14),
    padding: `${s(20)}px ${s(22)}px`,
    borderRadius: s(9),
    border: "1px solid rgba(140,170,230,0.14)",
    background: "linear-gradient(180deg, rgba(140,170,230,0.08) 0%, rgba(4,7,12,1) 100%)",
    boxShadow: "inset 0 1px 0 rgba(255,255,255,0.10), 0 14px 34px rgba(0,0,0,0.4)",
    minWidth: 0,
    minHeight: 0,
  };
}

const panelLabelStyle = { fontSize: s(12.5), fontWeight: 600, letterSpacing: "0.08em", color: tokens.wordmark };

// Minimal renderer for the same **bold** + "- " bullet convention as the
// reference mockup -- display-only, no markdown library needed for two rules.
function formatBody(text) {
  const lines = text.split("\n");
  const out = [];
  let bullets = [];
  const inline = (str, key) =>
    str.split(/\*\*(.+?)\*\*/g).map((part, i) =>
      i % 2 ? <strong key={`${key}-${i}`} style={{ color: tokens.textPrimary }}>{part}</strong> : part
    );
  const flushBullets = (key) => {
    if (bullets.length) {
      out.push(<ul key={key} style={{ margin: `${s(4)}px 0`, paddingLeft: s(18) }}>{bullets}</ul>);
      bullets = [];
    }
  };
  lines.forEach((ln, i) => {
    const trimmed = ln.trim();
    if (trimmed.startsWith("- ")) {
      bullets.push(<li key={`li${i}`}>{inline(trimmed.slice(2), `b${i}`)}</li>);
    } else {
      flushBullets(`ul${i}`);
      if (trimmed) out.push(<div key={`d${i}`}>{inline(ln, `l${i}`)}</div>);
    }
  });
  flushBullets("ulend");
  return out;
}

function FormatButton({ children, onClick, title }) {
  return (
    <button
      onClick={onClick}
      title={title}
      type="button"
      style={{ width: s(28), height: s(26), border: `1px solid ${tokens.sectionBorder}`, borderRadius: s(3), background: "#080F1C", color: tokens.wordmark, fontFamily: "inherit", fontSize: s(12), fontWeight: 700, cursor: "pointer" }}
    >
      {children}
    </button>
  );
}

function PostButton({ children, onClick, disabled }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      style={{
        alignSelf: "flex-end",
        padding: `${s(9)}px ${s(22)}px`,
        borderRadius: s(12),
        border: "1px solid rgba(160,205,255,0.55)",
        background: "linear-gradient(180deg, #459AF5 0%, #1A71F0 48%, #0D57D1 100%)",
        boxShadow: disabled ? "none" : "inset 0 1.5px 0 rgba(255,255,255,0.55), inset 0 -3px 8px rgba(8,50,140,0.45), 0 10px 30px rgba(30,123,255,0.38)",
        fontFamily: "inherit",
        fontSize: s(12.5),
        fontWeight: 600,
        color: "#FFFFFF",
        textShadow: disabled ? "none" : "0 1px 2px rgba(8,50,140,0.4)",
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.45 : 1,
      }}
    >
      {children}
    </button>
  );
}

export default function FieldLog() {
  const [searchParams] = useSearchParams();
  const requestedId = searchParams.get("analysis_id");

  const [analysisId, setAnalysisId] = useState(requestedId);
  const [report, setReport] = useState(null);
  const [upload, setUpload] = useState(null);
  const [notes, setNotes] = useState(null);
  const [comments, setComments] = useState(null);
  const [error, setError] = useState("");

  const [noteInput, setNoteInput] = useState("");
  const [postingNote, setPostingNote] = useState(false);
  const [commentInput, setCommentInput] = useState("");
  const [replyTo, setReplyTo] = useState(null);
  const [postingComment, setPostingComment] = useState(false);

  const [showMockHistory, setShowMockHistory] = useState(false);
  const [mockFiles, setMockFiles] = useState(MOCK_FILES);
  const fileInputRef = useRef(null);

  useEffect(() => {
    if (requestedId) {
      setAnalysisId(requestedId);
      return;
    }
    listReports(1)
      .then((rows) => {
        if (rows.length === 0) setError("No analyses yet — upload a sample first.");
        else setAnalysisId(rows[0].analysis_id);
      })
      .catch((e) => setError(e.message || "Failed to load your analyses."));
  }, [requestedId]);

  useEffect(() => {
    if (!analysisId) return;
    getReport(analysisId).then(setReport).catch((e) => setError(e.message || "Failed to load report."));
    refreshNotes();
    refreshComments();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [analysisId]);

  useEffect(() => {
    if (!report?.metadata?.upload_id) return;
    getUpload(report.metadata.upload_id).then(setUpload).catch(() => setUpload(null));
  }, [report]);

  function refreshNotes() {
    listFieldEntries(analysisId, "note").then(setNotes).catch((e) => setError(e.message || "Failed to load field notes."));
  }
  function refreshComments() {
    listFieldEntries(analysisId, "comment").then(setComments).catch((e) => setError(e.message || "Failed to load discussion."));
  }

  const handleAddNote = async () => {
    const body = noteInput.trim();
    if (!body) return;
    setPostingNote(true);
    try {
      await createFieldEntry({ analysis_id: analysisId, kind: "note", body });
      setNoteInput("");
      refreshNotes();
    } catch (e) {
      alert("Failed to log entry: " + e.message);
    } finally {
      setPostingNote(false);
    }
  };

  const handleAddComment = async () => {
    const body = commentInput.trim();
    if (!body) return;
    setPostingComment(true);
    try {
      await createFieldEntry({ analysis_id: analysisId, kind: "comment", body, reply_to: replyTo });
      setCommentInput("");
      setReplyTo(null);
      refreshComments();
    } catch (e) {
      alert("Failed to post comment: " + e.message);
    } finally {
      setPostingComment(false);
    }
  };

  const replyToEntry = useMemo(() => comments?.find((c) => c.entry_id === replyTo) ?? null, [comments, replyTo]);

  const initials = (name) => (name || "?").split(" ").map((w) => w[0]).join("").slice(0, 2).toUpperCase();

  if (error) {
    return (
      <div style={pageStyle}>
        <div style={ambientGlow} />
        <SidebarMenu />
        <div style={{ position: "relative", maxWidth: 800, margin: "4rem auto", padding: "0 1.5rem", textAlign: "center" }}>
          <div style={{ fontSize: "2.5rem", marginBottom: 16 }}>⚠</div>
          <div style={{ color: tokens.danger, fontSize: "1.1rem", marginBottom: 16 }}>{error}</div>
          <Link to="/upload" style={{ color: tokens.accentBlue, textDecoration: "none" }}>← New Analysis</Link>
        </div>
      </div>
    );
  }

  if (!report || notes === null || comments === null) {
    return (
      <div style={pageStyle}>
        <div style={ambientGlow} />
        <SidebarMenu />
        <div style={{ position: "relative", textAlign: "center", padding: "4rem", color: tokens.sectionSubtext }}>Loading field log...</div>
      </div>
    );
  }

  // Order matches the mockup's 5-column grid exactly. Fields the backend
  // actually stores (location/lat-long/depth/habitat/salinity/temperature)
  // use real upload data or an honest "not recorded". Fields with no backend
  // field at all (date/time, methodology, negative control, collector) show
  // the mockup's sample values, tagged MOCK.
  const meta = [
    { k: "LOCATION", v: upload?.location_label || "not recorded", mock: false },
    { k: "DATE / TIME", v: "12 Aug 2026 · 06:40 IST", mock: true },
    { k: "LAT / LONG", v: upload?.latitude != null && upload?.longitude != null ? `${upload.latitude.toFixed(4)}° N, ${upload.longitude.toFixed(4)}° E` : "not recorded", mock: false },
    { k: "DEPTH", v: upload?.depth_meters != null ? `${upload.depth_meters.toLocaleString()} m` : "not recorded", mock: false },
    { k: "HABITAT", v: upload?.habitat || "not recorded", mock: false },
    { k: "SALINITY", v: upload?.salinity_ppt != null ? `${upload.salinity_ppt} PSU` : "not recorded", mock: false },
    { k: "TEMPERATURE", v: upload?.temperature_celsius != null ? `${upload.temperature_celsius} °C` : "not recorded", mock: false },
    { k: "METHODOLOGY", v: "Metabarcoding", mock: true },
    { k: "NEGATIVE CONTROL", v: "Included", mock: true },
    { k: "COLLECTOR", v: "M. Fernandes", mock: true },
  ];

  return (
    <div style={pageStyle}>
      <div style={ambientGlow} />
      {/* Decorative background, not a real telemetry feed -- fixed and
          centered behind the entire page (same pattern as Abyss Mode's
          whale), rather than scoped to just one card or one section, so it
          reads as a true page-level backdrop that stays put while the page
          scrolls past it. */}
      <div
        style={{
          position: "fixed",
          top: "50%",
          left: "50%",
          transform: "translate(-50%, -50%)",
          width: "82vw",
          maxWidth: s(1300),
          minWidth: s(600),
          // No extra dimming here anymore -- that was a stopgap for when
          // the cards were only at 0.97 opacity and the tree could still
          // fight text for legibility at the throb's brighter end. Now
          // that every card sits on a fully opaque (1.0) background, the
          // tree can never bleed through a card regardless of its own
          // brightness, so it's left at full strength to keep its
          // glow-in/glow-out throb (via sv-tree-throb on the img below)
          // clearly visible in the gaps around the cards.
          pointerEvents: "none",
          zIndex: 0,
        }}
      >
        <img
          src={treeArt}
          alt=""
          aria-hidden="true"
          className="sv-tree-throb"
          style={{ display: "block", width: "100%", height: "auto" }}
        />
      </div>
      <SidebarMenu />
      <div style={{ position: "relative", zIndex: 1, maxWidth: s(1780), margin: "0 auto", padding: `${s(32)}px ${s(44)}px ${s(44)}px`, display: "flex", flexDirection: "column", gap: s(20) }}>
        {/* Header */}
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", textAlign: "center", gap: s(6) }}>
          <div style={{ fontSize: s(12), letterSpacing: "0.08em", color: tokens.labelText }}>RESEARCHER MODE</div>
          <h1 style={{ margin: 0, fontSize: s(27), fontWeight: 600, letterSpacing: "-0.01em" }}>Field Log</h1>
          <p style={{ margin: 0, fontSize: s(14), color: tokens.sectionSubtext }}>
            Field observations, notes, and team discussion for this analysis run.
          </p>
        </div>

        {/* Field notes -- full-width card at the top (swapped positions
            with Run Context below, per direct request), so its own
            content reads as one wide horizontal strip. */}
            <div style={panel()}>
              <span style={panelLabelStyle}>FIELD NOTES &amp; ANOMALIES</span>
            <div style={{ display: "flex", flexDirection: "column", gap: s(8) }}>
              <div style={{ display: "flex", gap: s(6), alignItems: "center" }}>
                <FormatButton title="Wrap as bold" onClick={() => setNoteInput((v) => v + "**bold**")}>B</FormatButton>
                <FormatButton title="Insert bullet" onClick={() => setNoteInput((v) => v + (v && !v.endsWith("\n") ? "\n" : "") + "- ")}>•</FormatButton>
                <span style={{ fontSize: s(10.5), color: tokens.pending }}>**bold** · "- " bullets</span>
              </div>
              <textarea
                className="sv-upload-field"
                rows={3}
                placeholder="Log a field observation… e.g. Algal bloom present at surface level during collection"
                value={noteInput}
                onChange={(e) => setNoteInput(e.target.value)}
                style={{ resize: "vertical", fontFamily: "inherit", fontSize: s(13) }}
              />
              <PostButton onClick={handleAddNote} disabled={!noteInput.trim() || postingNote}>
                {postingNote ? "Logging..." : "Log entry"}
              </PostButton>
            </div>

            {notes.length > 0 ? (
              <div style={{ display: "flex", flexDirection: "column", gap: s(12) }}>
                {[...notes].reverse().map((n) => (
                  <div key={n.entry_id} style={{ display: "flex", flexDirection: "column", gap: s(7), padding: `${s(14)}px ${s(16)}px`, borderRadius: s(6), border: "1px solid #101D33", borderLeft: `2px solid ${tokens.cardBorderActive}`, background: "rgba(8,14,26,0.55)" }}>
                    <div style={{ display: "flex", alignItems: "baseline", gap: s(10), flexWrap: "wrap" }}>
                      <span style={{ fontSize: s(12.5), fontWeight: 600 }}>{n.author_name}</span>
                      <span style={{ fontSize: s(10.5), color: tokens.pending, fontFamily: "ui-monospace,monospace" }}>{new Date(n.created_at).toLocaleString()}</span>
                    </div>
                    <div style={{ fontSize: s(13), lineHeight: 1.6, color: "#D8DCE5" }}>{formatBody(n.body)}</div>
                  </div>
                ))}
              </div>
            ) : (
              <div style={{ padding: s(26), textAlign: "center", borderRadius: s(6), border: "1px dashed #17253D", fontSize: s(12.5), color: tokens.sectionSubtext }}>
                No field notes yet — log the first observation above.
              </div>
            )}

            {/* Edit history has no backend support (notes are append-only,
                no PATCH endpoint) -- shown as a tagged mock preview of the
                designed interaction rather than omitted. */}
            <div style={{ display: "flex", flexDirection: "column", gap: s(8) }}>
              <span style={{ fontSize: s(10), letterSpacing: "0.06em", color: tokens.pending }}>PREVIEW — EDIT HISTORY</span>
              <div style={{ display: "flex", flexDirection: "column", gap: s(7), padding: `${s(14)}px ${s(16)}px`, borderRadius: s(6), border: "1px solid #101D33", borderLeft: `2px solid ${tokens.cardBorderActive}`, background: "rgba(8,14,26,0.55)" }}>
                <div style={{ display: "flex", alignItems: "baseline", gap: s(10), flexWrap: "wrap" }}>
                  <span style={{ fontSize: s(12.5), fontWeight: 600 }}>{MOCK_NOTE.author_name}</span>
                  <span style={{ fontSize: s(10.5), color: tokens.pending, fontFamily: "ui-monospace,monospace" }}>{MOCK_NOTE.created_at_label}</span>
                  <MockTag />
                  <button
                    onClick={() => setShowMockHistory((v) => !v)}
                    style={{ padding: 0, border: "none", background: "none", fontSize: s(10.5), fontWeight: 600, color: tokens.warningAlt, textDecoration: "underline", textUnderlineOffset: "2px", fontFamily: "inherit", cursor: "pointer" }}
                  >
                    edited · {showMockHistory ? "hide original" : "view original"}
                  </button>
                </div>
                <div style={{ fontSize: s(13), lineHeight: 1.6, color: "#D8DCE5" }}>{formatBody(MOCK_NOTE.body)}</div>
                {showMockHistory && (
                  <div style={{ display: "flex", flexDirection: "column", gap: s(4), padding: `${s(10)}px ${s(12)}px`, borderRadius: s(4), border: "1px dashed #17253D", background: "rgba(4,8,17,0.6)" }}>
                    <span style={{ fontSize: s(10), letterSpacing: "0.07em", color: tokens.pending }}>ORIGINAL · {MOCK_NOTE.orig_when}</span>
                    <span style={{ fontSize: s(12), lineHeight: 1.55, color: tokens.sectionSubtext, textDecoration: "line-through" }}>{MOCK_NOTE.orig}</span>
                  </div>
                )}
              </div>
            </div>
          </div>

        {/* Run Context, Attachments, Team Discussion side by side -- Run
            Context was the full-width card above (swapped positions with
            Field Notes, per direct request), so it's now the narrower
            column here; its tree art and list widths are scaled down to
            fit. Fields with no real data honestly say so; fields with no
            backend field at all show the mockup's sample values, tagged
            MOCK. */}
        <div style={{ display: "grid", gridTemplateColumns: "1.15fr 0.85fr 1fr", gap: s(18), alignItems: "stretch" }}>
          {/* Run context -- read-only, sourced from Upload Analysis; single
              source of truth per SYNTHVEDA_BUILD_SPEC.md 2.4 (no duplicate
              input form here). */}
          <div style={panel()}>
            <div style={{ display: "flex", flexDirection: "column", gap: s(4) }}>
              <span style={{ display: "flex", alignItems: "center", gap: s(8), fontSize: s(10.5), letterSpacing: "0.08em", color: tokens.labelText }}>
                <svg width={s(12)} height={s(12)} viewBox="0 0 14 14" fill="none">
                  <rect x="2" y="2" width="10" height="10" rx="2" stroke={tokens.accentBlue} strokeWidth="1.2" />
                  <path d="M5 7l1.5 1.5L9.5 5.5" stroke={tokens.accentBlue} strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                RUN CONTEXT · READ-ONLY
              </span>
              <Link to="/upload" style={{ fontSize: s(11), color: tokens.accentBlue }}>Edit at Upload →</Link>
            </div>
            {/* Two-column grid, not a single vertical list -- with the tree
                no longer sitting to the right of this card, a single narrow
                column left a lot of dead space on that side. Each cell
                still reads label-then-value top-to-bottom and stays
                left-aligned within its own column, but the pair of columns
                now stretches to fill the card's full width so the card
                reads as evenly filled/symmetric rather than lopsided. */}
            <div style={{ position: "relative", display: "grid", gridTemplateColumns: "1fr 1fr", columnGap: s(20), rowGap: s(12) }}>
              {meta.map((m, i) => (
                <div key={m.k} style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                  <span style={{ display: "flex", alignItems: "center", gap: s(5), fontSize: s(9.5), letterSpacing: "0.07em", color: tokens.pending }}>
                    {/* Same per-row dot convention as Species Correction's
                        match table -- grey here since these fields have no
                        confidence tier to color-code, just a subtle throb
                        (staggered per row) rather than the static
                        severity dots there. */}
                    <span
                      className="sv-tree-throb"
                      style={{ width: s(6), height: s(6), borderRadius: "50%", flexShrink: 0, background: tokens.sectionSubtext, boxShadow: `0 0 6px ${tokens.sectionSubtext}`, animationDelay: `${i * 0.18}s` }}
                    />
                    {m.k}
                    {m.mock && <MockTag label="MOCK" />}
                  </span>
                  <span style={{ fontSize: s(12), color: m.v === "not recorded" ? tokens.pending : tokens.textPrimary, fontStyle: m.v === "not recorded" ? "italic" : "normal" }}>{m.v}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Attachments -- full designed UI (dropzone, file rows, remove)
              per the mockup; no file-storage backend exists yet, so
              nothing here persists. Tagged MOCK rather than hidden. Sits
              beside Field Notes, not stacked under it. */}
          <div style={panel()}>
            <div style={{ display: "flex", alignItems: "center", gap: s(8), flexWrap: "wrap" }}>
              <span style={panelLabelStyle}>ATTACHMENTS</span>
              <MockTag />
            </div>
            <div
              onClick={() => {
                fileInputRef.current?.click();
              }}
              style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: s(6), padding: `${s(26)}px ${s(20)}px`, borderRadius: s(6), border: "1.5px dashed #1C2E4C", background: "rgba(8,14,26,0.4)", cursor: "pointer" }}
            >
              <svg width={s(22)} height={s(22)} viewBox="0 0 24 24" fill="none">
                <path d="M7 15a4.5 4.5 0 0 1 .6-8.96A5.25 5.25 0 0 1 17.65 7.6 4.13 4.13 0 0 1 17 15.75H7z" stroke={tokens.accentBlue} strokeWidth="1.4" strokeLinejoin="round" />
                <path d="M12 19v-7M9.5 14 12 11.5 14.5 14" stroke={tokens.accentBlue} strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              <span style={{ fontSize: s(13), fontWeight: 500, color: tokens.textPrimary, textAlign: "center" }}>Drop files or click to browse</span>
              <span style={{ fontSize: s(11), color: tokens.pending, textAlign: "center" }}>PDF, JPG, PNG — up to 25 MB each</span>
            </div>
            <input
              ref={fileInputRef}
              type="file"
              style={{ display: "none" }}
              onChange={(e) => {
                if (e.target.files?.length) alert("File storage isn't wired up yet — this is a mock preview of the attachments UI.");
                e.target.value = "";
              }}
            />
            {mockFiles.length > 0 ? (
              <div style={{ display: "flex", flexDirection: "column", gap: s(8) }}>
                {mockFiles.map((f) => (
                  <div key={f.id} style={{ display: "flex", alignItems: "center", gap: s(12), padding: `${s(10)}px ${s(14)}px`, borderRadius: s(6), border: "1px solid #101D33", background: "rgba(8,14,26,0.55)" }}>
                    <span style={{ width: s(38), height: s(38), borderRadius: s(6), flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "center", fontSize: s(9.5), fontWeight: 700, letterSpacing: "0.05em", border: "1px solid #17253D", background: "rgba(8,16,32,0.8)", color: FILE_ICON_COLOR[f.ext] || tokens.wordmark }}>
                      {f.ext}
                    </span>
                    <div style={{ display: "flex", flexDirection: "column", gap: 1, minWidth: 0, flex: 1 }}>
                      <span style={{ fontSize: s(12.5), color: tokens.textPrimary, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{f.name}</span>
                      <span style={{ fontSize: s(10.5), color: tokens.pending }}>{f.size} · {f.who} · {f.when}</span>
                    </div>
                    <button
                      onClick={() => setMockFiles((fs) => fs.filter((x) => x.id !== f.id))}
                      style={{ width: s(26), height: s(26), borderRadius: s(6), border: `1px solid ${tokens.sectionBorder}`, background: "#080F1C", color: tokens.sectionSubtext, fontSize: s(12), cursor: "pointer", flexShrink: 0 }}
                    >
                      ✕
                    </button>
                  </div>
                ))}
              </div>
            ) : (
              <div style={{ textAlign: "center", fontSize: s(12), color: tokens.pending }}>No attachments yet.</div>
            )}
          </div>

          {/* Team discussion -- uses the same shared panel() as the other
              three cards (was a hand-rolled style with a different flat
              background and no gradient sheen/shadow) so all four cards
              read as one consistent material rather than looking like
              different opacities against the tree background. */}
          <div style={panel()}>
            <span style={panelLabelStyle}>TEAM DISCUSSION</span>

            {comments.length > 0 ? (
              <div style={{ display: "flex", flexDirection: "column", gap: s(14) }}>
                {comments.map((c) => (
                  <div
                    key={c.entry_id}
                    style={{
                      display: "flex",
                      flexDirection: "column",
                      gap: s(6),
                      ...(c.reply_to ? { marginLeft: s(26), paddingLeft: s(14), borderLeft: `1px solid ${tokens.sectionBorder}` } : {}),
                    }}
                  >
                    <div style={{ display: "flex", alignItems: "center", gap: s(9), flexWrap: "wrap" }}>
                      <div style={{ width: s(24), height: s(24), borderRadius: "50%", flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "center", fontSize: s(9.5), fontWeight: 600, background: "linear-gradient(135deg,#146EFF,#7FD4FF)", color: "#04101F" }}>
                        {initials(c.author_name)}
                      </div>
                      <span style={{ fontSize: s(12.5), fontWeight: 600 }}>{c.author_name}</span>
                      <span style={{ fontSize: s(10.5), color: tokens.pending }}>{new Date(c.created_at).toLocaleString()}</span>
                      {c.anchor_sequence_id && (
                        <span style={{ fontSize: s(10.5), fontWeight: 600, color: tokens.accentCyan, fontFamily: "ui-monospace,monospace" }}>
                          {c.anchor_sequence_id}
                        </span>
                      )}
                    </div>
                    <p style={{ margin: 0, fontSize: s(13), lineHeight: 1.6, color: tokens.textPrimary }}>{c.body}</p>
                    <button
                      onClick={() => setReplyTo(c.entry_id)}
                      style={{ alignSelf: "flex-start", padding: "2px 0", border: "none", background: "none", fontFamily: "inherit", fontSize: s(11.5), color: tokens.accentBlue, cursor: "pointer" }}
                    >
                      Reply
                    </button>
                  </div>
                ))}
              </div>
            ) : (
              <div style={{ padding: s(26), textAlign: "center", borderRadius: s(6), border: "1px dashed #17253D", fontSize: s(12.5), color: tokens.sectionSubtext }}>
                No discussion yet — start the conversation.
              </div>
            )}

            <div style={{ display: "flex", flexDirection: "column", gap: s(8), borderTop: `1px solid ${tokens.sectionBorder}`, paddingTop: s(14) }}>
              {replyTo && (
                <span style={{ fontSize: s(11), color: tokens.sectionSubtext }}>
                  Replying to <span style={{ color: tokens.textPrimary }}>{replyToEntry?.author_name}</span> ·{" "}
                  <a href="#" onClick={(e) => { e.preventDefault(); setReplyTo(null); }} style={{ color: tokens.accentBlue }}>cancel</a>
                </span>
              )}
              <textarea
                className="sv-upload-field"
                rows={2}
                placeholder="Write a comment…"
                value={commentInput}
                onChange={(e) => setCommentInput(e.target.value)}
                style={{ resize: "vertical", fontFamily: "inherit", fontSize: s(13) }}
              />
              <button
                onClick={handleAddComment}
                disabled={!commentInput.trim() || postingComment}
                style={{
                  alignSelf: "flex-end",
                  padding: `${s(8)}px ${s(20)}px`,
                  borderRadius: s(10),
                  border: "1px solid rgba(160,205,255,0.4)",
                  background: "linear-gradient(180deg, rgba(69,154,245,0.28) 0%, rgba(13,87,209,0.22) 100%)",
                  boxShadow: "inset 0 1px 0 rgba(255,255,255,0.2)",
                  fontFamily: "inherit",
                  fontSize: s(12),
                  fontWeight: 600,
                  color: "#BFDCFF",
                  cursor: !commentInput.trim() || postingComment ? "not-allowed" : "pointer",
                  opacity: !commentInput.trim() || postingComment ? 0.45 : 1,
                }}
              >
                {postingComment ? "Posting..." : "Post"}
              </button>
            </div>
          </div>
        </div>

        <div style={{ display: "flex", justifyContent: "center", padding: `${s(8)}px 0 ${s(2)}px`, borderTop: `1px solid ${tokens.sectionBorder}` }}>
          <span style={{ fontSize: s(11), color: tokens.pending, textAlign: "center" }}>
            Run {analysisId} · Pipeline: {report?.metadata?.model_version_set || "not recorded"} · Field log entries are permanent — notes and comments can't be edited or deleted once posted.
            <br />
            Edit history and attachments above are mock previews of the designed UI — backend support is coming later.
          </span>
        </div>
      </div>
    </div>
  );
}
