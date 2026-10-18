import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import SidebarMenu from "../../components/sidebar/SidebarMenu";
import { tokens } from "../../components/shared/tokens";
import { useAuth } from "../../contexts/AuthContext";
import {
  getReport,
  listReports,
  listFieldEntries,
  createFieldEntry,
  updateFieldEntry,
  listFieldAttachments,
  uploadFieldAttachment,
  downloadFieldAttachment,
} from "../../lib/api";
import { NOT_RECORDED, formatLatLong, formatMetadataField } from "../../lib/sampleMetadata";
import treeArt from "../../assets/fieldlog-tree.png";

// Single scale factor applied to every size on this page (container width,
// padding, gaps, font sizes) -- keeps every ratio identical to the
// pre-scale design while letting the three panels sit side by side as
// squarer cards that fill more of the viewport, per direct feedback that
// the stacked layout read as a tall, narrow rectangle.
const SCALE = 1.32;
const s = (n) => Math.round(n * SCALE * 10) / 10;

// Attachments (B10): the API decides the type from the file's bytes and only
// accepts these three; the cap is FIELD_LOG_ATTACHMENT_MAX_MB (default 25).
const ATTACHMENT_ACCEPT = ".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png";
const FILE_EXT = { "application/pdf": "PDF", "image/jpeg": "JPG", "image/png": "PNG" };
const FILE_ICON_COLOR = { PDF: tokens.danger, JPG: tokens.accentCyan, PNG: tokens.success };
const FIELD_LABEL = { body: "Text", anchor_sequence_id: "Anchored sequence" };

function formatBytes(n) {
  if (n >= 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MB`;
  if (n >= 1024) return `${Math.round(n / 1024)} KB`;
  return `${n} B`;
}

// The API stores naive UTC datetimes (datetime.utcnow) and serializes them
// without an offset; read them as UTC so local display isn't shifted.
function parseApiDate(value) {
  if (!value) return null;
  return new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(value) ? value : `${value}Z`);
}
const formatWhen = (value) => parseApiDate(value)?.toLocaleString() ?? "";

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

const linkButtonStyle = {
  padding: 0,
  border: "none",
  background: "none",
  fontSize: s(10.5),
  fontWeight: 600,
  textDecoration: "underline",
  textUnderlineOffset: "2px",
  fontFamily: "inherit",
  cursor: "pointer",
};

// An entry's edit history, straight from the API's append-only `edits`
// (oldest first; shown newest first). Each edit lists the fields it
// changed with the value before (struck through) and after.
function EntryHistory({ edits }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: s(8), padding: `${s(10)}px ${s(12)}px`, borderRadius: s(4), border: "1px dashed #17253D", background: "rgba(4,8,17,0.6)" }}>
      {[...edits].reverse().map((e) => (
        <div key={e.edit_id} style={{ display: "flex", flexDirection: "column", gap: s(4) }}>
          <span style={{ fontSize: s(10), letterSpacing: "0.07em", color: tokens.pending }}>
            EDITED · {formatWhen(e.edited_at)} · {e.editor_name}
          </span>
          {e.changes.map((c) => (
            <div key={c.field} style={{ display: "flex", flexDirection: "column", gap: 2 }}>
              {c.field !== "body" && (
                <span style={{ fontSize: s(10), color: tokens.pending }}>{FIELD_LABEL[c.field] || c.field}</span>
              )}
              <span style={{ fontSize: s(12), lineHeight: 1.55, color: tokens.sectionSubtext, textDecoration: "line-through", whiteSpace: "pre-wrap" }}>
                {c.old ?? "(none)"}
              </span>
              <span style={{ fontSize: s(12), lineHeight: 1.55, color: tokens.textPrimary, whiteSpace: "pre-wrap" }}>
                {c.new ?? "(none)"}
              </span>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

// "edited N× · view history" toggle, inline edit form, and the history
// itself, shared by notes and comments. Editing is offered to the author and
// to curators, matching the PATCH route's rule; the server enforces it.
function EntryEditControls({ entry, canEdit, onSaved, onConflict, renderBody }) {
  const [showHistory, setShowHistory] = useState(false);
  const [draft, setDraft] = useState(null);
  const [saving, setSaving] = useState(false);
  const [editError, setEditError] = useState("");
  const edits = entry.edits || [];

  const save = async () => {
    const body = draft.trim();
    if (!body) return;
    setSaving(true);
    setEditError("");
    try {
      onSaved(await updateFieldEntry(entry.entry_id, { body }));
      setDraft(null);
    } catch (e) {
      if (e.status === 409) {
        setEditError("Someone else edited this entry first — reloaded; check it and edit again.");
        setDraft(null);
        onConflict();
      } else {
        setEditError(e.message || "Failed to save edit.");
      }
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      {draft === null ? (
        renderBody(entry.body)
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: s(6) }}>
          <textarea
            className="sv-upload-field"
            rows={3}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            style={{ resize: "vertical", fontFamily: "inherit", fontSize: s(13) }}
          />
          <div style={{ display: "flex", gap: s(12), justifyContent: "flex-end", alignItems: "center" }}>
            <button type="button" onClick={() => setDraft(null)} disabled={saving} style={{ ...linkButtonStyle, color: tokens.sectionSubtext }}>
              Cancel
            </button>
            <PostButton onClick={save} disabled={saving || !draft.trim() || draft.trim() === entry.body}>
              {saving ? "Saving..." : "Save edit"}
            </PostButton>
          </div>
        </div>
      )}
      {editError && <span style={{ fontSize: s(11), color: tokens.danger }}>{editError}</span>}
      {(edits.length > 0 || (canEdit && draft === null)) && (
        <div style={{ display: "flex", gap: s(14), alignItems: "center", flexWrap: "wrap" }}>
          {canEdit && draft === null && (
            <button type="button" onClick={() => { setDraft(entry.body); setEditError(""); }} style={{ ...linkButtonStyle, color: tokens.accentBlue }}>
              Edit
            </button>
          )}
          {edits.length > 0 && (
            <button type="button" onClick={() => setShowHistory((v) => !v)} style={{ ...linkButtonStyle, color: tokens.warningAlt }}>
              edited {edits.length}× · {showHistory ? "hide history" : "view history"}
            </button>
          )}
        </div>
      )}
      {showHistory && edits.length > 0 && <EntryHistory edits={edits} />}
    </>
  );
}

export default function FieldLog() {
  const [searchParams] = useSearchParams();
  const requestedId = searchParams.get("analysis_id");

  const [analysisId, setAnalysisId] = useState(requestedId);
  const [report, setReport] = useState(null);
  const [notes, setNotes] = useState(null);
  const [comments, setComments] = useState(null);
  const [error, setError] = useState("");

  const [noteInput, setNoteInput] = useState("");
  const [postingNote, setPostingNote] = useState(false);
  const [commentInput, setCommentInput] = useState("");
  const [replyTo, setReplyTo] = useState(null);
  const [postingComment, setPostingComment] = useState(false);

  const { user, isCurator } = useAuth();
  const canEdit = (entry) => isCurator || (!!user?.user_id && user.user_id === entry.author_id);

  const [attachments, setAttachments] = useState(null);
  const [attachError, setAttachError] = useState("");
  const [uploadingCount, setUploadingCount] = useState(0);
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
    refreshAttachments();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [analysisId]);

  function refreshNotes() {
    listFieldEntries(analysisId, "note").then(setNotes).catch((e) => setError(e.message || "Failed to load field notes."));
  }
  function refreshComments() {
    listFieldEntries(analysisId, "comment").then(setComments).catch((e) => setError(e.message || "Failed to load discussion."));
  }
  // Attachment failures stay inside the Attachments card instead of
  // replacing the whole page with an error.
  function refreshAttachments() {
    listFieldAttachments(analysisId)
      .then(setAttachments)
      .catch((e) => {
        setAttachments([]);
        setAttachError(e.message || "Failed to load attachments.");
      });
  }

  // PATCH returns the updated entry (with its new history row); swap it in.
  const replaceEntry = (setter) => (updated) =>
    setter((list) => list.map((x) => (x.entry_id === updated.entry_id ? updated : x)));

  const handleFiles = async (fileList) => {
    const files = Array.from(fileList || []);
    if (!files.length) return;
    setAttachError("");
    setUploadingCount(files.length);
    const failures = [];
    for (const file of files) {
      try {
        const saved = await uploadFieldAttachment(analysisId, file);
        setAttachments((list) => [...(list || []), saved]);
      } catch (e) {
        failures.push(`${file.name}: ${e.message}`);
      } finally {
        setUploadingCount((n) => n - 1);
      }
    }
    if (failures.length) setAttachError(failures.join(" · "));
  };

  const handleDownload = async (a) => {
    try {
      const resp = await downloadFieldAttachment(a.attachment_id);
      const url = URL.createObjectURL(await resp.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = a.original_filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      setAttachError(`${a.original_filename}: ${e.message || "download failed"}`);
    }
  };

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

  // Every value comes from report.metadata (all 14 optional upload fields,
  // null = not recorded), not GET /uploads/{id}, which curators get a 403
  // on. Nulls say "Not recorded" rather than showing a sample value. The
  // date is metadata.collected_at; metadata.created_at is the analysis time.
  const md = report.metadata;
  const habitatSource = [md?.habitat, md?.source_type].filter((x) => x && x.trim()).join(" · ");
  const meta = [
    { k: "LOCATION", v: formatMetadataField("location_label", md) },
    { k: "DATE / TIME", v: formatMetadataField("collected_at", md) },
    { k: "LAT / LONG", v: formatLatLong(md?.latitude, md?.longitude) },
    { k: "DEPTH", v: formatMetadataField("depth_meters", md) },
    { k: "HABITAT / SOURCE", v: habitatSource || NOT_RECORDED },
    { k: "SALINITY", v: formatMetadataField("salinity_ppt", md) },
    { k: "TEMPERATURE", v: formatMetadataField("temperature_celsius", md) },
    { k: "DISSOLVED O₂", v: formatMetadataField("dissolved_oxygen_mg_l", md) },
    { k: "PH", v: formatMetadataField("ph", md) },
    { k: "METHODOLOGY", v: formatMetadataField("methodology", md) },
    { k: "NEGATIVE CONTROL", v: formatMetadataField("negative_control_included", md) },
    { k: "COLLECTOR", v: formatMetadataField("collector", md) },
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
                      <span style={{ fontSize: s(10.5), color: tokens.pending, fontFamily: "ui-monospace,monospace" }}>{formatWhen(n.created_at)}</span>
                    </div>
                    <EntryEditControls
                      entry={n}
                      canEdit={canEdit(n)}
                      onSaved={replaceEntry(setNotes)}
                      onConflict={refreshNotes}
                      renderBody={(body) => <div style={{ fontSize: s(13), lineHeight: 1.6, color: "#D8DCE5" }}>{formatBody(body)}</div>}
                    />
                  </div>
                ))}
              </div>
            ) : (
              <div style={{ padding: s(26), textAlign: "center", borderRadius: s(6), border: "1px dashed #17253D", fontSize: s(12.5), color: tokens.sectionSubtext }}>
                No field notes yet — log the first observation above.
              </div>
            )}
          </div>

        {/* Run Context, Attachments, Team Discussion side by side -- Run
            Context was the full-width card above (swapped positions with
            Field Notes, per direct request), so it's now the narrower
            column here; its tree art and list widths are scaled down to
            fit. Fields with no recorded value say "Not recorded". */}
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
                  </span>
                  <span style={{ fontSize: s(12), color: m.v === NOT_RECORDED ? tokens.pending : tokens.textPrimary, fontStyle: m.v === NOT_RECORDED ? "italic" : "normal" }}>{m.v}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Attachments -- stored through the API's storage backend
              (POST/GET /field-log/attachments, B10). Permanent like
              entries: there is no remove; each file can be downloaded. */}
          <div style={panel()}>
            <span style={panelLabelStyle}>ATTACHMENTS</span>
            <div
              role="button"
              tabIndex={0}
              onClick={() => {
                if (!uploadingCount) fileInputRef.current?.click();
              }}
              onKeyDown={(e) => {
                if ((e.key === "Enter" || e.key === " ") && !uploadingCount) fileInputRef.current?.click();
              }}
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => {
                e.preventDefault();
                if (!uploadingCount) handleFiles(e.dataTransfer.files);
              }}
              style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: s(6), padding: `${s(26)}px ${s(20)}px`, borderRadius: s(6), border: "1.5px dashed #1C2E4C", background: "rgba(8,14,26,0.4)", cursor: uploadingCount ? "progress" : "pointer", opacity: uploadingCount ? 0.6 : 1 }}
            >
              <svg width={s(22)} height={s(22)} viewBox="0 0 24 24" fill="none">
                <path d="M7 15a4.5 4.5 0 0 1 .6-8.96A5.25 5.25 0 0 1 17.65 7.6 4.13 4.13 0 0 1 17 15.75H7z" stroke={tokens.accentBlue} strokeWidth="1.4" strokeLinejoin="round" />
                <path d="M12 19v-7M9.5 14 12 11.5 14.5 14" stroke={tokens.accentBlue} strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              <span style={{ fontSize: s(13), fontWeight: 500, color: tokens.textPrimary, textAlign: "center" }}>
                {uploadingCount ? `Uploading ${uploadingCount} file${uploadingCount > 1 ? "s" : ""}…` : "Drop files or click to browse"}
              </span>
              <span style={{ fontSize: s(11), color: tokens.pending, textAlign: "center" }}>PDF, JPG, PNG — up to 25 MB each</span>
            </div>
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept={ATTACHMENT_ACCEPT}
              style={{ display: "none" }}
              onChange={(e) => {
                handleFiles(e.target.files);
                e.target.value = "";
              }}
            />
            {attachError && <span style={{ fontSize: s(11), color: tokens.danger }}>{attachError}</span>}
            {attachments === null ? (
              <div style={{ textAlign: "center", fontSize: s(12), color: tokens.pending }}>Loading attachments…</div>
            ) : attachments.length > 0 ? (
              <div style={{ display: "flex", flexDirection: "column", gap: s(8) }}>
                {attachments.map((a) => {
                  const ext = FILE_EXT[a.content_type] || "FILE";
                  return (
                    <div key={a.attachment_id} style={{ display: "flex", alignItems: "center", gap: s(12), padding: `${s(10)}px ${s(14)}px`, borderRadius: s(6), border: "1px solid #101D33", background: "rgba(8,14,26,0.55)" }}>
                      <span style={{ width: s(38), height: s(38), borderRadius: s(6), flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "center", fontSize: s(9.5), fontWeight: 700, letterSpacing: "0.05em", border: "1px solid #17253D", background: "rgba(8,16,32,0.8)", color: FILE_ICON_COLOR[ext] || tokens.wordmark }}>
                        {ext}
                      </span>
                      <div style={{ display: "flex", flexDirection: "column", gap: 1, minWidth: 0, flex: 1 }}>
                        <span title={a.original_filename} style={{ fontSize: s(12.5), color: tokens.textPrimary, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{a.original_filename}</span>
                        <span style={{ fontSize: s(10.5), color: tokens.pending }}>
                          {formatBytes(a.size_bytes)} · {a.uploader_name} · {formatWhen(a.created_at)}
                        </span>
                        <span title={`sha256 ${a.checksum_sha256}`} style={{ fontSize: s(9.5), color: tokens.pending, fontFamily: "ui-monospace,monospace" }}>
                          sha256 {a.checksum_sha256.slice(0, 12)}…
                        </span>
                      </div>
                      <button
                        type="button"
                        title={`Download ${a.original_filename}`}
                        aria-label={`Download ${a.original_filename}`}
                        onClick={() => handleDownload(a)}
                        style={{ width: s(26), height: s(26), borderRadius: s(6), border: `1px solid ${tokens.sectionBorder}`, background: "#080F1C", color: tokens.accentBlue, fontSize: s(12), cursor: "pointer", flexShrink: 0 }}
                      >
                        ↓
                      </button>
                    </div>
                  );
                })}
              </div>
            ) : (
              <div style={{ textAlign: "center", fontSize: s(12), color: tokens.pending }}>
                No attachments yet — add site photos or PDFs above.
              </div>
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
                      <span style={{ fontSize: s(10.5), color: tokens.pending }}>{formatWhen(c.created_at)}</span>
                      {c.anchor_sequence_id && (
                        <span style={{ fontSize: s(10.5), fontWeight: 600, color: tokens.accentCyan, fontFamily: "ui-monospace,monospace" }}>
                          {c.anchor_sequence_id}
                        </span>
                      )}
                    </div>
                    <EntryEditControls
                      entry={c}
                      canEdit={canEdit(c)}
                      onSaved={replaceEntry(setComments)}
                      onConflict={refreshComments}
                      renderBody={(body) => <p style={{ margin: 0, fontSize: s(13), lineHeight: 1.6, color: tokens.textPrimary }}>{body}</p>}
                    />
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
            Run {analysisId} · Pipeline: {report?.metadata?.model_version_set || "not recorded"} · Field log entries and attachments are permanent — nothing can be deleted. Notes and comments can be edited by their author or a curator; every edit is kept in the entry's history.
          </span>
        </div>
      </div>
    </div>
  );
}
