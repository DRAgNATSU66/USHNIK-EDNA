import React, { useCallback, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import NavBar from "../components/NavBar";
import { createUpload, createAnalysisJob } from "../lib/api";

const PAGE = {
  background: "radial-gradient(ellipse at center, #002266 0%, #001133 100%)",
  minHeight: "100vh",
  color: "#ffffff",
  fontFamily: "'Inter', system-ui, sans-serif",
};

const CARD = {
  background: "rgba(255,255,255,0.05)",
  backdropFilter: "blur(20px)",
  border: "1px solid rgba(255,255,255,0.1)",
  borderRadius: 16,
  padding: "2rem",
  position: "relative",
  overflow: "hidden",
};

const INPUT = {
  width: "100%",
  padding: "10px 14px",
  borderRadius: 10,
  border: "1px solid rgba(255,255,255,0.12)",
  background: "rgba(0,0,0,0.25)",
  color: "#ffffff",
  fontSize: "0.9rem",
  outline: "none",
};

const LABEL = {
  display: "block",
  marginBottom: 6,
  fontSize: "0.8rem",
  color: "#7eb3ff",
  fontWeight: 600,
  textTransform: "uppercase",
  letterSpacing: "0.05em",
};

const VALID_EXTS = [".fasta", ".fa", ".fastq", ".json", ".jsonl"];
const MAX_SIZE_MB = 500;
const MAX_SIZE = MAX_SIZE_MB * 1024 * 1024;

function validateFile(file) {
  if (!file) return "No file selected.";
  const name = file.name.toLowerCase();
  if (!VALID_EXTS.some((ext) => name.endsWith(ext))) {
    return `Invalid file type. Allowed: ${VALID_EXTS.join(", ")}`;
  }
  if (file.size > MAX_SIZE) return `File exceeds ${MAX_SIZE_MB} MB limit.`;
  return null;
}

function formatBytes(bytes) {
  if (!bytes) return "";
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return `${(bytes / 1024 ** i).toFixed(1)} ${"BKMGT"[i]}B`;
}

export default function Upload() {
  const navigate = useNavigate();
  const fileInputRef = useRef(null);

  const [file, setFile] = useState(null);
  const [fileError, setFileError] = useState("");
  const [isDragging, setIsDragging] = useState(false);

  // Environmental metadata (all optional)
  const [meta, setMeta] = useState({
    location_label: "",
    depth_meters: "",
    latitude: "",
    longitude: "",
    source_type: "",
    habitat: "",
    salinity_ppt: "",
    temperature_celsius: "",
  });

  const [mode, setMode] = useState("online_full");
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

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!file) { setError("Please select a file first."); return; }
    setError("");
    setSubmitting(true);
    try {
      const formData = new FormData();
      formData.append("file", file, file.name);
      // Append non-empty metadata fields
      for (const [k, v] of Object.entries(meta)) {
        if (v !== "" && v !== null) formData.append(k, v);
      }

      const upload = await createUpload(formData);
      const job = await createAnalysisJob(upload.upload_id, mode);
      navigate(`/jobs/${job.job_id}`);
    } catch (err) {
      setError(err.message || "Upload failed. Please try again.");
      setSubmitting(false);
    }
  };

  return (
    <div style={PAGE}>
      <NavBar />
      <div style={{ maxWidth: 860, margin: "0 auto", padding: "2rem 1.5rem" }}>
        <h1 style={{
          fontSize: "1.75rem", fontWeight: 800, marginBottom: "0.5rem",
          background: "linear-gradient(135deg, #0066ff 0%, #00d4ff 100%)",
          WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent", backgroundClip: "text",
        }}>
          Upload Sample
        </h1>
        <p style={{ color: "#b3d9ff", fontSize: "0.9rem", marginBottom: "1.75rem" }}>
          Submit a FASTA or JSON file to start an analysis job.
        </p>

        <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: "1.5rem" }}>
          {/* File drop zone */}
          <div style={CARD}>
            <div
              onDrop={handleDrop}
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onClick={() => fileInputRef.current?.click()}
              style={{
                border: `2px dashed ${isDragging ? "#00d4ff" : file ? "#00ff88" : "rgba(255,255,255,0.15)"}`,
                borderRadius: 12,
                padding: "2.5rem 1.5rem",
                textAlign: "center",
                cursor: "pointer",
                transition: "all 0.2s",
                background: isDragging ? "rgba(0,212,255,0.05)" : "transparent",
              }}
            >
              <div style={{ fontSize: "2.5rem", marginBottom: 12 }}>
                {file ? "✅" : "📂"}
              </div>
              {file ? (
                <>
                  <div style={{ color: "#00ff88", fontWeight: 600, marginBottom: 4 }}>
                    {file.name}
                  </div>
                  <div style={{ color: "#7eb3ff", fontSize: "0.85rem" }}>{formatBytes(file.size)}</div>
                </>
              ) : (
                <>
                  <div style={{ color: "#b3d9ff", fontWeight: 500, marginBottom: 6 }}>
                    Click to select or drag & drop
                  </div>
                  <div style={{ color: "#7eb3ff", fontSize: "0.8rem" }}>
                    FASTA (.fasta, .fa, .fastq) or JSON (.json, .jsonl) · Max {MAX_SIZE_MB} MB
                  </div>
                </>
              )}
              <input
                ref={fileInputRef}
                type="file"
                accept={VALID_EXTS.join(",")}
                style={{ display: "none" }}
                onChange={(e) => { const f = e.target.files?.[0]; if (f) pickFile(f); }}
              />
            </div>
            {fileError && (
              <div style={{ marginTop: 10, color: "#ff9b9b", fontSize: "0.85rem" }}>{fileError}</div>
            )}
          </div>

          {/* Environmental metadata */}
          <div style={CARD}>
            <h3 style={{ fontSize: "1rem", fontWeight: 700, marginBottom: "1.25rem", color: "#b3d9ff" }}>
              Environmental Metadata <span style={{ color: "#7eb3ff", fontWeight: 400, fontSize: "0.8rem" }}>(optional)</span>
            </h3>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: "1rem" }}>
              {[
                { key: "location_label", label: "Location Label", type: "text", placeholder: "e.g. Indian Ocean, Site 7" },
                { key: "depth_meters", label: "Depth (m)", type: "number", placeholder: "e.g. 2500" },
                { key: "latitude", label: "Latitude", type: "number", placeholder: "e.g. -18.432" },
                { key: "longitude", label: "Longitude", type: "number", placeholder: "e.g. 73.211" },
                { key: "source_type", label: "Source Type", type: "text", placeholder: "e.g. water, sediment" },
                { key: "habitat", label: "Habitat", type: "text", placeholder: "e.g. hydrothermal_vent" },
                { key: "salinity_ppt", label: "Salinity (ppt)", type: "number", placeholder: "e.g. 35.2" },
                { key: "temperature_celsius", label: "Temperature (°C)", type: "number", placeholder: "e.g. 4.5" },
              ].map(({ key, label, type, placeholder }) => (
                <div key={key}>
                  <label style={LABEL}>{label}</label>
                  <input
                    style={INPUT}
                    type={type}
                    placeholder={placeholder}
                    value={meta[key]}
                    onChange={setMetaField(key)}
                  />
                </div>
              ))}
            </div>
          </div>

          {/* Analysis mode */}
          <div style={CARD}>
            <h3 style={{ fontSize: "1rem", fontWeight: 700, marginBottom: "1rem", color: "#b3d9ff" }}>
              Analysis Mode
            </h3>
            {[
              { value: "online_full", label: "Online Full", desc: "Full cloud analysis with all models. Recommended for final results." },
              { value: "abyss_synced", label: "Abyss Synced", desc: "Process data synced from an offline Abyss Mode expedition." },
            ].map(({ value, label, desc }) => (
              <label
                key={value}
                style={{
                  display: "flex",
                  alignItems: "flex-start",
                  gap: 10,
                  padding: "10px 12px",
                  borderRadius: 10,
                  border: `1px solid ${mode === value ? "rgba(0,212,255,0.4)" : "rgba(255,255,255,0.08)"}`,
                  background: mode === value ? "rgba(0,212,255,0.06)" : "transparent",
                  cursor: "pointer",
                  marginBottom: 8,
                  transition: "all 0.15s",
                }}
              >
                <input
                  type="radio"
                  name="mode"
                  value={value}
                  checked={mode === value}
                  onChange={() => setMode(value)}
                  style={{ marginTop: 2, accentColor: "#00d4ff" }}
                />
                <div>
                  <div style={{ fontWeight: 600, color: "#ffffff", fontSize: "0.9rem" }}>{label}</div>
                  <div style={{ color: "#7eb3ff", fontSize: "0.8rem", marginTop: 2 }}>{desc}</div>
                </div>
              </label>
            ))}
          </div>

          {error && (
            <div style={{
              padding: "12px 16px", borderRadius: 10,
              background: "rgba(255,80,80,0.08)", border: "1px solid rgba(255,80,80,0.2)",
              color: "#ff9b9b", fontSize: "0.9rem",
            }}>
              {error}
            </div>
          )}

          <div style={{ display: "flex", gap: "1rem" }}>
            <button
              type="submit"
              disabled={!file || submitting}
              style={{
                flex: 1,
                padding: "0.75rem 1.5rem",
                borderRadius: 12,
                border: "none",
                background: "linear-gradient(135deg, #0066ff 0%, #00d4ff 100%)",
                color: "white",
                fontWeight: 700,
                fontSize: "1rem",
                cursor: !file || submitting ? "not-allowed" : "pointer",
                opacity: !file || submitting ? 0.55 : 1,
                transition: "opacity 0.2s",
              }}
            >
              {submitting ? "Submitting..." : "Submit for Analysis →"}
            </button>
            <button
              type="button"
              onClick={() => { setFile(null); setFileError(""); setMeta(Object.fromEntries(Object.keys(meta).map(k => [k, ""]))); }}
              style={{
                padding: "0.75rem 1.25rem",
                borderRadius: 12,
                border: "1px solid rgba(255,255,255,0.12)",
                background: "transparent",
                color: "#7eb3ff",
                fontWeight: 600,
                cursor: "pointer",
              }}
            >
              Reset
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
