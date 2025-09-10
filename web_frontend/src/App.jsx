// src/App.jsx
import React, { useState, useEffect } from "react";
import axios from "axios";

export default function App() {
  const [file, setFile] = useState(null);
  const [results, setResults] = useState([]);
  const [metrics, setMetrics] = useState({ sequences: 0, unique_species: 0 });
  const [loading, setLoading] = useState(false);
  const [backendInfo, setBackendInfo] = useState({ model_loaded: false, device: "none", label_map: {} });

  useEffect(() => {
    // fetch health on mount
    async function fetchHealth() {
      try {
        const r = await axios.get("http://127.0.0.1:8000/health");
        setBackendInfo({
          model_loaded: r.data.model_loaded,
          device: r.data.device || "none",
          label_map: r.data.label_map || {},
        });
      } catch (e) {
        console.warn("Health check failed", e);
      }
    }
    fetchHealth();
  }, []);

  const handleFileChange = (e) => {
    setFile(e.target.files[0]);
  };

  function mapLabel(rawLabel) {
    // If backend provided mapping (LABEL_0 -> human). Use it; fallback to raw label.
    if (!rawLabel) return rawLabel;
    const map = backendInfo.label_map || {};
    if (map[rawLabel]) return map[rawLabel];
    // if backend map keys are numeric like {"0": "Homo sapiens"} then map LABEL_0 -> map["0"]
    const m = rawLabel.match(/LABEL_(\d+)/);
    if (m && map[m[1]]) return map[m[1]];
    return rawLabel;
  }

  const handleUpload = async () => {
    if (!file) {
      alert("Please select a FASTA file or use demo sample");
      return;
    }
    const formData = new FormData();
    formData.append("file", file);

    try {
      setLoading(true);
      const res = await axios.post("http://127.0.0.1:8000/analyze", formData, {
        headers: { "Content-Type": "multipart/form-data" },
        timeout: 120000,
      });

      // Backend sends { sequence_count, predictions: [...], device, label_map }
      let predictions = [];
      let label_map = {};
      if (res.data && Array.isArray(res.data.predictions)) {
        predictions = res.data.predictions;
        label_map = res.data.label_map || {};
      } else if (Array.isArray(res.data)) {
        predictions = res.data;
      } else {
        // try to find array in response
        const arr = Object.values(res.data).find((v) => Array.isArray(v));
        if (arr) predictions = arr;
      }

      // normalize predictions to expected shape
      const normalized = predictions.map((p, i) => ({
        sequence_id: p.sequence_id || p.id || `seq${i + 1}`,
        sequence: p.sequence || p.sequence || "",
        predicted_species: mapLabel(p.predicted_species || p.label || p.predicted || "Unknown"),
        raw_label: p.predicted_species || p.label || p.predicted || "Unknown",
        confidence: typeof p.confidence === "number" ? p.confidence : (p.score || 0),
      }));

      setResults(normalized);
      const seqCount = normalized.length;
      const uniq = new Set(normalized.map((r) => r.predicted_species)).size;
      setMetrics({ sequences: seqCount, unique_species: uniq });
      // update local backend info label map / device
      setBackendInfo((prev) => ({ ...prev, device: res.data.device || prev.device, label_map: res.data.label_map || prev.label_map }));
    } catch (err) {
      console.error("Upload failed:", err);
      alert("Upload failed. Open DevTools console for details.");
    } finally {
      setLoading(false);
    }
  };

  const handleDemo = async () => {
    try {
      const response = await fetch("/test_sample.fasta");
      const text = await response.text();
      const blob = new Blob([text], { type: "text/plain" });
      const demoFile = new File([blob], "test_sample.fasta", { type: "text/plain" });
      setFile(demoFile);
    } catch (err) {
      console.error("Failed to load demo sample", err);
      alert("Failed to load demo sample");
    }
  };

  const reset = () => {
    setFile(null);
    setResults([]);
    setMetrics({ sequences: 0, unique_species: 0 });
  };

  const showCpuWarning = backendInfo.device !== "cuda" && backendInfo.model_loaded;

  return (
    <div className="min-h-screen bg-gray-50 p-6">
      <h1 className="text-3xl font-bold text-center text-blue-600 mb-4">
        🧬 eDNA Biodiversity Analyzer — Beta
      </h1>

      {showCpuWarning && (
        <div className="max-w-xl mx-auto mb-4 p-3 rounded border-l-4 border-yellow-400 bg-yellow-50 text-yellow-800">
          ⚠ Backend running in <strong>CPU mode</strong>. Inference will be slower.
        </div>
      )}

      <div className="max-w-xl mx-auto bg-white p-6 rounded shadow">
        <p className="mb-4 text-gray-700">
          Upload a FASTA file (.fasta, .fa) and get species predictions (demo).
        </p>

        <input type="file" accept=".fasta,.fa" onChange={handleFileChange} className="mb-4" />

        <div className="flex gap-2 mb-4">
          <button
            onClick={handleUpload}
            className="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700 disabled:opacity-60"
            disabled={loading}
          >
            {loading ? "Analyzing..." : "Upload & Analyze"}
          </button>

          <button onClick={handleDemo} className="bg-green-600 text-white px-4 py-2 rounded hover:bg-green-700">
            Use Demo Sample
          </button>

          <button onClick={reset} className="bg-gray-500 text-white px-4 py-2 rounded hover:bg-gray-600">
            Reset
          </button>
        </div>

        <h2 className="text-lg font-semibold mb-2">Quick Metrics</h2>
        <p>{metrics.sequences} sequences</p>
        <p>{metrics.unique_species} unique species</p>

        <h2 className="text-lg font-semibold mt-4 mb-2">Results</h2>
        {results.length > 0 ? (
          <table className="w-full text-sm border">
            <thead>
              <tr className="bg-gray-200">
                <th className="border px-2 py-1">ID</th>
                <th className="border px-2 py-1">Predicted Species</th>
                <th className="border px-2 py-1">Confidence</th>
                <th className="border px-2 py-1">Raw Label</th>
              </tr>
            </thead>
            <tbody>
              {results.map((r, i) => (
                <tr key={i}>
                  <td className="border px-2 py-1">{r.sequence_id}</td>
                  <td className="border px-2 py-1">{r.predicted_species}</td>
                  <td className="border px-2 py-1">{(r.confidence * 100).toFixed(1)}%</td>
                  <td className="border px-2 py-1">{r.raw_label}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="text-gray-600">No results yet. Upload a FASTA to start.</p>
        )}
      </div>
    </div>
  );
}