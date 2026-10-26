import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import MatrixRain from "../components/upload/MatrixRain";
import SidebarMenu from "../components/sidebar/SidebarMenu";
import { useAuth } from "../contexts/AuthContext";
import { createUpload, createAnalysisJob, healthCheck, getModelStatus, getModels } from "../lib/api";
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
  segmentOptionStyle,
  segmentRadioOuterStyle,
  segmentRadioDotStyle,
  heroCardStyle,
  heroCardTitleStyle,
  heroCardSubtitleStyle,
} from "./uploadStyles";

const VALID_EXTS = [".fasta", ".fa", ".fastq", ".json", ".jsonl"];
// Fallback only until /health answers with the limit the backend enforces
// (settings.max_upload_size_mb); keep it equal to the backend default.
const DEFAULT_MAX_SIZE_MB = 100;

// Optional sample metadata, sent to POST /uploads under the API's own field
// names (OPTIONAL_METADATA_FIELDS in services/api/app/models/upload.py).
// Three inputs are reshaped in buildMetadata below: "date" + "time" become
// `collected_at` (ISO with the browser's UTC offset), "lat_long" is split
// into `latitude`/`longitude` (sent only as a pair), and the negative
// control is a tri-state segmented control rendered after this list.
// `hint` mirrors the backend's range checks; the backend stays the authority.
const META_FIELDS = [
  { key: "location_label", label: "Location label", type: "text", placeholder: "Indian Ocean, Site 7" },
  { key: "date", label: "Collection date", type: "date", placeholder: "" },
  { key: "time", label: "Collection time", type: "time", placeholder: "", hint: "local" },
  { key: "lat_long", label: "Latitude, Longitude", type: "text", placeholder: "-18.432, 73.211", hint: "±90, ±180" },
  { key: "depth_meters", label: "Depth (m)", type: "number", placeholder: "2500", min: 0, hint: "≥ 0" },
  { key: "source_type", label: "Source type", type: "text", placeholder: "water, sediment" },
  { key: "habitat", label: "Habitat", type: "text", placeholder: "hydrothermal_vent" },
  { key: "salinity_ppt", label: "Salinity (ppt)", type: "number", placeholder: "35.2" },
  { key: "temperature_celsius", label: "Temperature (°C)", type: "number", placeholder: "4.5" },
  { key: "dissolved_oxygen_mg_l", label: "Dissolved O₂ (mg/L)", type: "number", placeholder: "6.8", min: 0, hint: "≥ 0" },
  { key: "ph", label: "pH", type: "number", placeholder: "8.1", min: 0, max: 14, hint: "0–14" },
  { key: "methodology", label: "Methodology", type: "text", placeholder: "metabarcoding, qPCR" },
  { key: "collector", label: "Collector", type: "text", placeholder: "Name or team" },
];

// Tri-state. "" = not recorded, so the field is omitted and the result says
// "not recorded"; otherwise the string the API's bool form field parses.
const NEGATIVE_CONTROL_OPTIONS = [
  { value: "true", label: "Included" },
  { value: "false", label: "Not included" },
  { value: "", label: "Not recorded" },
];

// Same tolerance as the API's _COLLECTED_AT_FUTURE_TOLERANCE.
const COLLECTED_AT_FUTURE_TOLERANCE_MS = 24 * 60 * 60 * 1000;

const emptyMeta = () => ({ ...Object.fromEntries(META_FIELDS.map((f) => [f.key, ""])), negative_control: "" });

const MODES = [
  { value: "online_full", title: "Online Full", desc: "Full cloud analysis: router, reference lookup and route heads. Best for publishable results." },
  { value: "abyss_synced", title: "Abyss Synced", desc: "Process data synced from an offline Abyss Mode field expedition." },
];

// Processing Model: there is no user model choice. POST /analysis/jobs takes
// only `mode`; the worker's orchestrator (decision Q7, orchestrator-1.2.0,
// docs/qna.md QNA-024/025) picks the models per sequence. The old picker
// ("AbyssNet v3", "MetaGen Ensemble"...) named models that do not exist and
// changed nothing, so it is replaced by one honest "Auto" choice that says
// what the orchestrator does and which route heads are served now, read
// from GET /models/status (and the router's entry from GET /models/registry).
const ROUTE_LABELS = {
  fish: "Fish",
  plant: "Plant",
  bacteria_pathogen: "Bacteria / pathogen",
  animal_general: "Animal (general)",
  human_domestic_contamination: "Human / domestic",
  misc_unknown: "Misc / unknown",
};

// /models/status `status` per route (services/api/app/models/router.py
// _route_status). Anything but "ready" means the worker would stub that
// route's head or cannot be confirmed from the API host.
const HEAD_STATUS = {
  ready: { label: "served", color: "#5FD9A9" },
  unverified: { label: "unverified", color: "#E0C25C" },
  missing_artifacts: { label: "files missing — stub", color: "#FF7B7B" },
  no_model: { label: "no model — stub", color: "#FF7B7B" },
};

function ModelStatusList({ status, routerId, error }) {
  if (error) {
    return (
      <span style={{ fontSize: 12, color: uploadColors.errorText }}>
        Model status unavailable ({error}). Auto still applies; the worker uses whatever its registry serves.
      </span>
    );
  }
  if (!status) return <span style={{ fontSize: 12, color: uploadColors.cardDesc }}>Loading model status…</span>;
  const routes = Object.entries(status.routes ?? {});
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 7 }} data-testid="served-models">
      <div style={{ display: "flex", justifyContent: "space-between", gap: 10, fontSize: 12 }}>
        <span style={{ color: uploadColors.cardDesc }}>Router</span>
        <span style={{ color: uploadColors.cardTitle, fontFamily: "ui-monospace,monospace" }}>{routerId ?? "not reported"}</span>
      </div>
      {routes.map(([route, r]) => {
        const st = HEAD_STATUS[r.status] ?? { label: r.status ?? "unknown", color: "#8C9AB2" };
        return (
          <div key={route} style={{ display: "grid", gridTemplateColumns: "1fr auto", columnGap: 10, rowGap: 1, fontSize: 12 }}>
            <span style={{ color: uploadColors.cardDesc }}>{ROUTE_LABELS[route] ?? route}</span>
            <span style={{ color: st.color, whiteSpace: "nowrap", textAlign: "right" }} title={r.reason ?? undefined}>{st.label}</span>
            <span style={{ color: uploadColors.cardTitle, fontFamily: "ui-monospace,monospace", overflowWrap: "anywhere" }}>
              {r.model_id ?? "—"}
            </span>
            <span style={{ color: "#61708A", textAlign: "right" }}>{r.registry_status ?? ""}</span>
          </div>
        );
      })}
      <span style={{ fontSize: "11px", lineHeight: 1.5, color: "#61708A" }} title={status.note ?? undefined}>
        As seen by the API (registry + files on disk). The worker publishes no live state, so “served” means the files
        resolve, not that the worker has loaded them.
      </span>
    </div>
  );
}

const HERO_CARDS = [
  { title: "FASTA · JSON", subtitle: "Read formats", pos: { left: 0, top: 24 } },
  { title: "Sugar phosphate", subtitle: "Backbone", pos: { left: 0, bottom: 14 } },
  { title: "mRNA · tRNA", subtitle: "Transcripts", pos: { right: 0, top: 20 } },
  { title: "Peptide bonds", subtitle: "Residue links", pos: { right: 0, bottom: 14 } },
];

function validateFile(file, maxSizeMb) {
  if (!file) return "No file selected.";
  const name = file.name.toLowerCase();
  if (!VALID_EXTS.some((ext) => name.endsWith(ext))) {
    return `Invalid file type. Allowed: ${VALID_EXTS.join(", ")}`;
  }
  if (file.size > maxSizeMb * 1024 * 1024) return `File exceeds ${maxSizeMb} MB limit.`;
  return null;
}

// "-18.432, 73.211" -> { latitude, longitude }, or null if it isn't two
// numbers. A malformed entry is now reported instead of silently dropped:
// coordinates decide whether a partner report is possible, so losing them
// without a word would be worse than asking the user to fix the format.
function parseLatLong(value) {
  const parts = value.split(",").map((x) => x.trim());
  if (parts.length !== 2 || parts.some((x) => x === "")) return null;
  const latitude = Number(parts[0]);
  const longitude = Number(parts[1]);
  if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) return null;
  return { latitude, longitude };
}

// "+05:30" for the browser's offset on that particular date (DST-correct).
function formatOffset(d) {
  const mins = -d.getTimezoneOffset();
  const sign = mins >= 0 ? "+" : "-";
  const abs = Math.abs(mins);
  return `${sign}${String(Math.floor(abs / 60)).padStart(2, "0")}:${String(abs % 60).padStart(2, "0")}`;
}

// Form state -> { fields, errors }. `fields` holds only values that were
// actually entered, under API field names: an empty input is omitted, never
// sent as "" (the API answers 422 for "" in a number or date field). Range
// checks match services/api/app/uploads/router.py.
function buildMetadata(meta) {
  const fields = {};
  const errors = {};
  const v = Object.fromEntries(Object.entries(meta).map(([k, x]) => [k, typeof x === "string" ? x.trim() : x]));

  for (const key of ["location_label", "source_type", "habitat", "methodology", "collector"]) {
    if (v[key]) fields[key] = v[key];
  }

  const num = (key, ok, message) => {
    if (v[key] === "") return;
    const n = Number(v[key]);
    if (!Number.isFinite(n) || (ok && !ok(n))) errors[key] = message;
    else fields[key] = n;
  };
  num("depth_meters", (n) => n >= 0, "Depth must be 0 or more.");
  num("salinity_ppt", null, "Enter a number.");
  num("temperature_celsius", null, "Enter a number.");
  num("dissolved_oxygen_mg_l", (n) => n >= 0, "Dissolved oxygen must be 0 or more.");
  num("ph", (n) => n >= 0 && n <= 14, "pH must be between 0 and 14.");

  if (v.lat_long) {
    const ll = parseLatLong(v.lat_long);
    if (!ll) errors.lat_long = "Enter two numbers: latitude, longitude.";
    else if (Math.abs(ll.latitude) > 90 || Math.abs(ll.longitude) > 180) errors.lat_long = "Latitude must be within ±90, longitude within ±180.";
    else Object.assign(fields, ll);
  }

  if (v.time && !v.date) {
    errors.date = "Add the date this time belongs to.";
  } else if (v.date) {
    // No time entered -> 00:00 local; the hint under the time field says so.
    const time = v.time || "00:00";
    const [y, mo, d] = v.date.split("-").map(Number);
    const [hh, mm] = time.split(":").map(Number);
    const local = new Date(y, mo - 1, d, hh, mm);
    if (Number.isNaN(local.getTime())) errors.date = "Enter a valid date.";
    else if (local.getTime() > Date.now() + COLLECTED_AT_FUTURE_TOLERANCE_MS) errors.date = "Collection date can't be in the future.";
    else fields.collected_at = `${v.date}T${time}:00${formatOffset(local)}`;
  }

  if (v.negative_control === "true" || v.negative_control === "false") {
    fields.negative_control_included = v.negative_control;
  }

  return { fields, errors };
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

  const [meta, setMeta] = useState(emptyMeta);
  const [metaErrors, setMetaErrors] = useState({});

  const [mode, setMode] = useState("online_full");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [maxSizeMb, setMaxSizeMb] = useState(DEFAULT_MAX_SIZE_MB);
  const [modelStatus, setModelStatus] = useState(null);
  const [modelStatusError, setModelStatusError] = useState("");
  const [routerId, setRouterId] = useState(null);

  useEffect(() => {
    healthCheck()
      .then((h) => { if (Number.isFinite(h?.max_upload_size_mb)) setMaxSizeMb(h.max_upload_size_mb); })
      .catch(() => {});
    getModelStatus()
      .then(setModelStatus)
      .catch((e) => setModelStatusError(e.message || "request failed"));
    // The router is not in /models/status; the registry names the entry the
    // worker would select for it. Missing -> "not reported", never a guess.
    getModels()
      .then((reg) => setRouterId(reg?.selected_by_route?.router ?? null))
      .catch(() => {});
  }, []);

  const pickFile = useCallback((f) => {
    const err = validateFile(f, maxSizeMb);
    if (err) { setFileError(err); setFile(null); return; }
    setFileError("");
    setFile(f);
  }, [maxSizeMb]);

  const handleDrop = useCallback((e) => {
    e.preventDefault();
    setIsDragging(false);
    const dropped = e.dataTransfer.files?.[0];
    if (dropped) pickFile(dropped);
  }, [pickFile]);

  const handleDragOver = (e) => { e.preventDefault(); setIsDragging(true); };
  const handleDragLeave = () => setIsDragging(false);

  const setMetaValue = (k, value) => {
    setMeta((prev) => ({ ...prev, [k]: value }));
    setMetaErrors((prev) => {
      if (!prev[k]) return prev;
      const next = { ...prev };
      delete next[k];
      return next;
    });
  };
  const setMetaField = (k) => (e) => setMetaValue(k, e.target.value);

  const handleModeSelect = (value) => setMode(value);

  const handleReset = () => {
    setFile(null);
    setFileError("");
    setMeta(emptyMeta());
    setMetaErrors({});
    setMode("online_full");
    setError("");
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!file) { setError("Please select a file first."); return; }
    const { fields, errors } = buildMetadata(meta);
    setMetaErrors(errors);
    if (Object.keys(errors).length > 0) {
      setError("Some metadata values are out of range. Fix them or clear the field.");
      return;
    }
    setError("");
    setSubmitting(true);
    try {
      const formData = new FormData();
      formData.append("file", file, file.name);
      for (const [k, v] of Object.entries(fields)) formData.append(k, String(v));

      const upload = await createUpload(formData);
      const job = await createAnalysisJob(upload.upload_id, mode);
      navigate(`/jobs/${job.job_id}`);
    } catch (err) {
      setError(err.message || "Upload failed. Please try again.");
      setSubmitting(false);
    }
  };

  return (
    <div style={{ background: uploadColors.pageBg, minHeight: "100vh" }}>
      <SidebarMenu />
      <div style={{ minHeight: "100vh", position: "relative", overflow: "hidden", padding: "60px 24px 80px", boxSizing: "border-box" }}>
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

          {/* noValidate: the min/max attributes on the metadata inputs are
              hints for the spinner only. buildMetadata reports every range
              error inline at once; native validation would stop the submit
              on the first one with a browser bubble and hide the rest. */}
          <form noValidate onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 44 }}>
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
                    FASTA <span style={{ color: "#48566E" }}>.fasta .fa .fastq</span> &nbsp;·&nbsp; JSON <span style={{ color: "#48566E" }}>.json .jsonl</span> &nbsp;·&nbsp; up to {maxSizeMb}&nbsp;MB
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
              {/* Subtitle states only what the code does: none of these
                  fields feeds inference yet (qna.md QNA-005 Q5), but the
                  partner report does need date + coordinates (Q2). */}
              <SlabHeader title="Environmental Metadata" subtitle="Optional — a partner report needs the collection date and coordinates" />
              <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "20px 24px" }}>
                {META_FIELDS.map(({ key, label, type, placeholder, min, max, hint }) => {
                  const fieldError = metaErrors[key];
                  const timeNote = key === "time" && meta.date && !meta.time ? "No time entered — 00:00 local will be recorded" : null;
                  return (
                    <label key={key} style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                      <span style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 8 }}>
                        <span style={{ fontSize: "10.5px", fontWeight: 600, letterSpacing: "0.11em", textTransform: "uppercase", color: uploadColors.labelText }}>
                          {label}
                        </span>
                        {hint && <span style={{ fontSize: "10.5px", color: uploadColors.sectionSubtext, letterSpacing: "0.02em" }}>{hint}</span>}
                      </span>
                      <input
                        type={type}
                        className="sv-upload-field"
                        placeholder={placeholder}
                        value={meta[key]}
                        onChange={setMetaField(key)}
                        min={min}
                        max={max}
                        step={type === "number" ? "any" : undefined}
                        aria-invalid={fieldError ? true : undefined}
                        style={fieldError ? { borderColor: uploadColors.errorText } : undefined}
                      />
                      {fieldError && <span style={{ fontSize: "11.5px", color: uploadColors.errorText }}>{fieldError}</span>}
                      {!fieldError && timeNote && <span style={{ fontSize: "11.5px", color: uploadColors.sectionSubtext }}>{timeNote}</span>}
                    </label>
                  );
                })}
                <div role="radiogroup" aria-label="Negative control" style={{ gridColumn: "span 2", display: "flex", flexDirection: "column", gap: 8 }}>
                  <span style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 8 }}>
                    <span style={{ fontSize: "10.5px", fontWeight: 600, letterSpacing: "0.11em", textTransform: "uppercase", color: uploadColors.labelText }}>
                      Negative control
                    </span>
                    <span style={{ fontSize: "10.5px", color: uploadColors.sectionSubtext, letterSpacing: "0.02em" }}>
                      blank extraction run alongside the sample
                    </span>
                  </span>
                  <div style={{ display: "flex", gap: 10 }}>
                    {NEGATIVE_CONTROL_OPTIONS.map((opt) => {
                      const active = meta.negative_control === opt.value;
                      return (
                        <button
                          key={opt.label}
                          type="button"
                          role="radio"
                          aria-checked={active}
                          onClick={() => setMetaValue("negative_control", opt.value)}
                          style={segmentOptionStyle(active)}
                        >
                          <span style={segmentRadioOuterStyle(active)}>
                            <span style={segmentRadioDotStyle(active)} />
                          </span>
                          {opt.label}
                        </button>
                      );
                    })}
                  </div>
                </div>
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
                  <div role="radiogroup" aria-label="Processing model">
                    {/* The shared radio card has a fixed 88px height; this one
                        holds the served-model list, so it grows with it. */}
                    <div role="radio" aria-checked="true" style={{ ...modelCardStyle(true), height: "auto", cursor: "default" }}>
                      <span style={modelRadioOuterStyle(true)}>
                        <span style={modelRadioDotStyle(true)} />
                      </span>
                      <div style={{ display: "flex", flexDirection: "column", gap: 8, minWidth: 0, flex: 1 }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
                          <span style={{ fontSize: 14, fontWeight: 600, color: uploadColors.cardTitle }}>Auto</span>
                          <span style={modelTagStyle(true)}>Orchestrator</span>
                        </div>
                        <span style={{ fontSize: 12, lineHeight: 1.5, color: uploadColors.cardDesc }}>
                          No manual model choice. The router ranks the routes for each sequence; when it is unsure, or
                          its pick is a route it often gets wrong, a few candidate routes are planned (default cap 3).
                          Each planned route's head runs and, when reference lookup is enabled on the worker, its
                          reference database is searched; fixed rules pick
                          the final route, taxon and class, and the full decision trace is saved with the result.
                        </span>
                        <ModelStatusList status={modelStatus} routerId={routerId} error={modelStatusError} />
                      </div>
                    </div>
                  </div>
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
