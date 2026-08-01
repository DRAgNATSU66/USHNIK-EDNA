import { useCallback, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import NavBar from "../components/NavBar";
import MatrixRain from "../components/upload/MatrixRain";
import { useAuth } from "../contexts/AuthContext";
import { createUpload, createAnalysisJob } from "../lib/api";
import dnaHero from "../assets/dna.png";
import {
  uploadColors,
  uploadSlabHeaderStyle,
  uploadSlabTickStyle,
  uploadSubmitButtonStyle,
  uploadResetButtonStyle,
  uploadDropzoneStyle,
  uploadDropzoneChipStyle,
  modeCardStyle,
  modeRadioOuterStyle,
  modeRadioDotStyle,
  modelCardStyle,
  modelRadioOuterStyle,
  modelRadioDotStyle,
  modelTagStyle,
  heroCardStyle,
  heroCardTitleStyle,
  heroCardSubtitleStyle,
} from "./uploadStyles";

const VALID_EXTS = [".fasta", ".fa", ".fastq", ".json", ".jsonl"];
const MAX_SIZE_MB = 500;
const MAX_SIZE = MAX_SIZE_MB * 1024 * 1024;

// "Date", "Time", and the combined "Latitude, Longitude" field are handled
// separately from this list (see META_FIELDS below + parseLatLong) since
// they need custom input types / parsing before hitting the backend, which
// only accepts separate `latitude`/`longitude` floats and has no date/time
// field at all yet (see the note above handleSubmit).
const META_FIELDS = [
  { key: "location_label", label: "Location label", type: "text", placeholder: "Indian Ocean, Site 7" },
  { key: "date", label: "Date", type: "date", placeholder: "" },
  { key: "time", label: "Time", type: "time", placeholder: "" },
  { key: "lat_long", label: "Latitude, Longitude", type: "text", placeholder: "-18.432, 73.211" },
  { key: "depth_meters", label: "Depth (m)", type: "number", placeholder: "2500" },
  { key: "source_type", label: "Source type", type: "text", placeholder: "water, sediment" },
  { key: "habitat", label: "Habitat", type: "text", placeholder: "hydrothermal_vent" },
  { key: "salinity_ppt", label: "Salinity (ppt)", type: "number", placeholder: "35.2" },
  { key: "temperature_celsius", label: "Temperature (°C)", type: "number", placeholder: "4.5" },
];

const MODES = [
  { value: "online_full", title: "Online Full", desc: "Full cloud analysis with every model. Best for publishable results." },
  { value: "abyss_synced", title: "Abyss Synced", desc: "Process data synced from an offline Abyss Mode field expedition." },
];

// Processing Model is a design-only concept for now — the backend's
// POST /analysis/jobs only accepts `mode`, no model field, so this
// selection is real UI state but doesn't affect the actual analysis run
// yet. Wiring it up for real is separate backend work (job-level model
// routing), not something to fake here.
const MODELS_BY_MODE = {
  online_full: [
    { name: "AbyssNet v3", tag: "Main", desc: "Full ensemble, species-level resolution. Best for publishable results." },
    { name: "MetaGen Ensemble", tag: "Fallback", desc: "Consensus voting fallback if AbyssNet is unavailable." },
  ],
  abyss_synced: [
    { name: "AbyssNet Lite", tag: "Main", desc: "Offline-trained weights synced from the expedition unit." },
    { name: "MetaGen Lite", tag: "Fallback", desc: "Fast genus-level fallback for field-collected reads." },
  ],
};

const HERO_CARDS = [
  { title: "FASTA · JSON", subtitle: "Read formats", pos: { left: 0, top: 24 } },
  { title: "Sugar phosphate", subtitle: "Backbone", pos: { left: 0, bottom: 14 } },
  { title: "mRNA · tRNA", subtitle: "Transcripts", pos: { right: 0, top: 20 } },
  { title: "Peptide bonds", subtitle: "Residue links", pos: { right: 0, bottom: 14 } },
];

function validateFile(file) {
  if (!file) return "No file selected.";
  const name = file.name.toLowerCase();
  if (!VALID_EXTS.some((ext) => name.endsWith(ext))) {
    return `Invalid file type. Allowed: ${VALID_EXTS.join(", ")}`;
  }
  if (file.size > MAX_SIZE) return `File exceeds ${MAX_SIZE_MB} MB limit.`;
  return null;
}

// "-18.432, 73.211" -> { latitude, longitude } — returns {} (and silently
// drops the field, same as leaving it blank) if it doesn't parse cleanly.
// This is optional metadata, not a validated form field, so a malformed
// entry just doesn't get sent rather than blocking submission.
function parseLatLong(value) {
  const parts = value.split(",").map((s) => s.trim());
  if (parts.length !== 2) return {};
  const latitude = parseFloat(parts[0]);
  const longitude = parseFloat(parts[1]);
  if (Number.isNaN(latitude) || Number.isNaN(longitude)) return {};
  return { latitude, longitude };
}

function UploadIcon() {
  return (
    <svg width="28" height="28" viewBox="0 0 24 24" fill="none">
      <path d="M12 15V4m0 0-4 4m4-4 4 4" stroke="#BFE0FF" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3" stroke="#BFE0FF" strokeWidth="1.7" strokeLinecap="round" />
    </svg>
  );
}

function SlabHeader({ title, subtitle }) {
  return (
    <div style={uploadSlabHeaderStyle}>
      <span style={uploadSlabTickStyle} />
      <h2 style={{ margin: 0, fontSize: 15, fontWeight: 600, letterSpacing: "0.02em", color: uploadColors.textPrimary }}>
        {title}
      </h2>
      {subtitle && (
        <span style={{ fontSize: "11.5px", color: uploadColors.sectionSubtext, letterSpacing: "0.02em" }}>
          {subtitle}
        </span>
      )}
    </div>
  );
}

function HeroCard({ title, subtitle, pos }) {
  return (
    <div style={{ ...heroCardStyle, ...pos }}>
      <span style={heroCardTitleStyle}>{title}</span>
      <span style={heroCardSubtitleStyle}>{subtitle}</span>
    </div>
  );
}

export default function Upload() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const fileInputRef = useRef(null);

  const [file, setFile] = useState(null);
  const [fileError, setFileError] = useState("");
  const [isDragging, setIsDragging] = useState(false);

  const [meta, setMeta] = useState(
    Object.fromEntries(META_FIELDS.map((f) => [f.key, ""]))
  );

  const [mode, setMode] = useState("online_full");
  const [modelIndex, setModelIndex] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const pickFile = (f) => {
    const err = validateFile(f);
    if (err) { setFileError(err); setFile(null); return; }
    setFileError("");
    setFile(f);
  };

  const handleDrop = useCallback((e) => {
    e.preventDefault();
    setIsDragging(false);
    const dropped = e.dataTransfer.files?.[0];
    if (dropped) pickFile(dropped);
  }, []);

  const handleDragOver = (e) => { e.preventDefault(); setIsDragging(true); };
  const handleDragLeave = () => setIsDragging(false);

  const setMetaField = (k) => (e) => setMeta((prev) => ({ ...prev, [k]: e.target.value }));

  const handleModeSelect = (value) => {
    setMode(value);
    setModelIndex(0);
  };

  const handleReset = () => {
    setFile(null);
    setFileError("");
    setMeta(Object.fromEntries(META_FIELDS.map((f) => [f.key, ""])));
    setMode("online_full");
    setModelIndex(0);
    setError("");
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!file) { setError("Please select a file first."); return; }
    setError("");
    setSubmitting(true);
    try {
      const formData = new FormData();
      formData.append("file", file, file.name);

      // date/time have no backend field yet — not sent (see META_FIELDS
      // comment). lat_long gets parsed and split into the two fields the
      // backend actually accepts.
      const { date, time, lat_long, ...rest } = meta;
      for (const [k, v] of Object.entries(rest)) {
        if (v !== "" && v !== null) formData.append(k, v);
      }
      if (lat_long) {
        const { latitude, longitude } = parseLatLong(lat_long);
        if (latitude !== undefined) {
          formData.append("latitude", latitude);
          formData.append("longitude", longitude);
        }
      }

      const upload = await createUpload(formData);
      const job = await createAnalysisJob(upload.upload_id, mode);
      navigate(`/jobs/${job.job_id}`);
    } catch (err) {
      setError(err.message || "Upload failed. Please try again.");
      setSubmitting(false);
    }
  };

  const models = MODELS_BY_MODE[mode];

  return (
    <div style={{ background: uploadColors.pageBg, minHeight: "100vh" }}>
      <NavBar />
      <div style={{ minHeight: "calc(100vh - 56px)", position: "relative", overflow: "hidden", padding: "60px 24px 80px", boxSizing: "border-box" }}>
        <MatrixRain />
        {/* ambient glows */}
        <div
          style={{
            position: "absolute",
            inset: 0,
            pointerEvents: "none",
            background:
              "radial-gradient(52% 40% at 50% -4%, rgba(20,110,255,0.14) 0%, rgba(2,6,15,0) 60%), radial-gradient(46% 46% at 96% 44%, rgba(40,130,255,0.10) 0%, rgba(2,6,15,0) 60%)",
          }}
        />

        <div style={{ position: "relative", width: 840, maxWidth: "100%", margin: "0 auto", display: "flex", flexDirection: "column", gap: 44 }}>
          {/* Header */}
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 16, textAlign: "center" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 11 }}>
              <svg width="22" height="22" viewBox="0 0 26 26" fill="none">
                <path d="M6 2c0 6 14 8 14 13S6 20 6 24" stroke={uploadColors.accentBlue} strokeWidth="2" strokeLinecap="round" />
                <path d="M20 2c0 6-14 8-14 13s14 5 14 9" stroke={uploadColors.accentCyan} strokeWidth="2" strokeLinecap="round" />
              </svg>
              <span style={{ fontWeight: 600, letterSpacing: "0.28em", fontSize: 12, color: uploadColors.wordmark }}>SYNTH VEDA</span>
            </div>
            <h1 style={{ margin: 0, fontSize: 40, fontWeight: 600, letterSpacing: "-0.03em", lineHeight: 1.05, color: uploadColors.textPrimary }}>
              New Analysis
            </h1>
            <div style={{ display: "flex", alignItems: "center", gap: 12, fontSize: "13.5px", color: uploadColors.headerMuted, flexWrap: "wrap", justifyContent: "center" }}>
              <span>
                Welcome back, <span style={{ color: uploadColors.headerName, fontWeight: 500 }}>{user?.display_name || "Researcher"}</span>
              </span>
              <span style={{ width: 4, height: 4, borderRadius: "50%", background: uploadColors.headerDot }} />
              <span>{user?.email}</span>
              {user?.role && (
                <span
                  style={{
                    display: "inline-flex", alignItems: "center", gap: 6, padding: "3px 11px",
                    border: `1px solid ${uploadColors.badgeBorder}`, borderRadius: 6, background: uploadColors.badgeBg,
                    color: uploadColors.badgeText, fontSize: 11, fontWeight: 600, letterSpacing: "0.07em", textTransform: "uppercase",
                  }}
                >
                  <span style={{ width: 5, height: 5, borderRadius: "50%", background: uploadColors.accentBlue, boxShadow: `0 0 6px ${uploadColors.accentBlue}` }} />
                  {user.role.replace(/_/g, " ")}
                </span>
              )}
            </div>
          </div>

          {/* DNA hero with floating cards */}
          <div style={{ position: "relative", height: 360, display: "flex", alignItems: "center", justifyContent: "center", margin: "-8px 0 -6px" }}>
            <div
              style={{
                position: "absolute", width: 520, height: 340, borderRadius: "50%",
                background: "radial-gradient(closest-side, rgba(20,110,255,0.26), rgba(2,6,15,0) 72%)",
                filter: "blur(6px)", animation: "sv-halo-breathe 10s ease-in-out infinite", willChange: "transform, opacity",
              }}
            />
            <img
              src={dnaHero}
              alt="DNA double helix"
              style={{ position: "relative", height: 340, width: "auto", filter: "drop-shadow(0 20px 50px rgba(20,110,255,0.35))" }}
            />
            {HERO_CARDS.map((c) => (
              <HeroCard key={c.title} {...c} />
            ))}
          </div>

          <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 44 }}>
            {/* Upload dropzone */}
            <div>
              <div
                onClick={() => fileInputRef.current?.click()}
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                onDrop={handleDrop}
                style={uploadDropzoneStyle(isDragging)}
              >
                <div style={uploadDropzoneChipStyle(isDragging)}>
                  <UploadIcon />
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: 7, alignItems: "center" }}>
                  <span style={{ fontSize: 18, fontWeight: 600, color: "#EAF2FF", letterSpacing: "-0.01em" }}>
                    {file ? file.name : "Click to select, or drag & drop your sequence file"}
                  </span>
                  <span style={{ fontSize: "12.5px", color: "#61708A", letterSpacing: "0.01em" }}>
                    FASTA <span style={{ color: "#48566E" }}>.fasta .fa .fastq</span> &nbsp;·&nbsp; JSON <span style={{ color: "#48566E" }}>.json .jsonl</span> &nbsp;·&nbsp; up to {MAX_SIZE_MB}&nbsp;MB
                  </span>
                </div>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept={VALID_EXTS.join(",")}
                  style={{ display: "none" }}
                  onChange={(e) => { const f = e.target.files?.[0]; if (f) pickFile(f); }}
                />
              </div>
              {fileError && (
                <div style={{ marginTop: 10, color: uploadColors.errorText, fontSize: "0.85rem" }}>{fileError}</div>
              )}
            </div>

            {/* Environmental Metadata */}
            <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
              <SlabHeader title="Environmental Metadata" subtitle="Optional — improves classification accuracy" />
              <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "20px 24px" }}>
                {META_FIELDS.map(({ key, label, type, placeholder }) => (
                  <label key={key} style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                    <span style={{ fontSize: "10.5px", fontWeight: 600, letterSpacing: "0.11em", textTransform: "uppercase", color: uploadColors.labelText }}>
                      {label}
                    </span>
                    <input
                      type={type}
                      className="sv-upload-field"
                      placeholder={placeholder}
                      value={meta[key]}
                      onChange={setMetaField(key)}
                    />
                  </label>
                ))}
              </div>
            </div>

            {/* Analysis Mode + Processing Model */}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 44 }}>
              <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
                <SlabHeader title="Analysis Mode" />
                <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                  {MODES.map((m) => {
                    const active = m.value === mode;
                    return (
                      <div key={m.value} onClick={() => handleModeSelect(m.value)} style={modeCardStyle(active)}>
                        <span style={modeRadioOuterStyle(active)}>
                          <span style={modeRadioDotStyle(active)} />
                        </span>
                        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                          <span style={{ fontSize: "14.5px", fontWeight: 600, color: uploadColors.cardTitle }}>{m.title}</span>
                          <span style={{ fontSize: "12.5px", lineHeight: 1.5, color: uploadColors.cardDesc }}>{m.desc}</span>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
                <SlabHeader title="Processing Model" />
                <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                  {models.map((md, i) => {
                    const active = i === modelIndex;
                    return (
                      <div key={md.name} onClick={() => setModelIndex(i)} style={modelCardStyle(active)}>
                        <span style={modelRadioOuterStyle(active)}>
                          <span style={modelRadioDotStyle(active)} />
                        </span>
                        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                          <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
                            <span style={{ fontSize: 14, fontWeight: 600, color: uploadColors.cardTitle }}>{md.name}</span>
                            <span style={modelTagStyle(i === 0)}>{md.tag}</span>
                          </div>
                          <span style={{ fontSize: 12, lineHeight: 1.45, color: uploadColors.cardDesc }}>{md.desc}</span>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>

            {error && (
              <div style={{ padding: "12px 16px", borderRadius: 10, background: uploadColors.errorBg, border: `1px solid ${uploadColors.errorBorder}`, color: uploadColors.errorText, fontSize: "0.9rem" }}>
                {error}
              </div>
            )}

            {/* Actions */}
            <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 14, paddingTop: 20, borderTop: `1px solid ${uploadColors.actionsDivider}` }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 16 }}>
                <button type="submit" disabled={!file || submitting} style={{ ...uploadSubmitButtonStyle, opacity: !file || submitting ? 0.55 : 1, cursor: !file || submitting ? "not-allowed" : "pointer" }}>
                  {submitting ? "Submitting..." : "Submit for Analysis"}
                  <svg width="15" height="15" viewBox="0 0 14 14" fill="none">
                    <path d="M2 7h10M8 3l4 4-4 4" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </button>
                <button type="button" onClick={handleReset} style={uploadResetButtonStyle}>
                  Reset
                </button>
              </div>
              <span style={{ fontSize: "12.5px", color: uploadColors.readyText, display: "flex", alignItems: "center", gap: 7 }}>
                <span style={{ width: 6, height: 6, borderRadius: "50%", background: uploadColors.readyDot }} />
                {file ? "File ready — 1 sequence set" : "Awaiting sequence file"}
              </span>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}
