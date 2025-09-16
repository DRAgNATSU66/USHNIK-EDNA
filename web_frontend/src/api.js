// src/api.js
// Small API helper for the React frontend to call the FastAPI /analyze endpoint.
// - Reads backend URL from Vite or CRA env vars (VITE_API_URL or REACT_APP_API_URL).
// - Falls back to http://127.0.0.1:8000
// - Exports analyzeFastaFile(file) which returns a normalized array:
//   [{ sequence_id, sequence, predicted_species, confidence, source }, ...]
// - Throws helpful errors when network/backend fails.

import axios from "axios";

export const API_BASE =
  (typeof import.meta !== "undefined" && import.meta.env && import.meta.env.VITE_API_URL) ||
  (typeof process !== "undefined" && process.env && process.env.REACT_APP_API_URL) ||
  "http://127.0.0.1:8000";

/**
 * Sends a FASTA file to the backend for analysis and returns normalized results.
 * @param {File} file The FASTA file to analyze.
 * @returns {Promise<Array<{sequence_id:string, sequence?:string, predicted_species:string, confidence:number, source:string}>>}
 */
export const analyzeFastaFile = async (file) => {
  if (!file) throw new Error("No file provided to analyzeFastaFile");

  const url = `${API_BASE.replace(/\/$/, "")}/analyze`;
  const form = new FormData();
  form.append("file", file, file.name || "upload.fasta");

  try {
    const resp = await axios.post(url, form, {
      headers: {
        // Let axios/multipart set the proper Content-Type with boundary
        // but providing it explicitly is harmless in most browsers: omitted here for safety.
        Accept: "application/json",
      },
      timeout: 120000,
    });

    const data = resp.data;

    // Normalize accepted backend shapes into an array of entries with consistent keys.
    // Acceptable shapes:
    //  - Array of { sequence_id, sequence, predicted_species, confidence, source }
    //  - Object { metrics: ..., species: [ { name, confidence, id }, ... ] }
    //  - Legacy shapes with id / label / score
    let speciesList = [];

    if (Array.isArray(data)) {
      speciesList = data.map((d, i) => ({
        sequence_id: d.sequence_id ?? d.id ?? `${i + 1}`,
        sequence: d.sequence ?? "",
        predicted_species: d.predicted_species ?? d.label ?? d.name ?? "Unknown",
        confidence: Number(d.confidence ?? d.score ?? 0),
        source: d.source ?? "unknown",
      }));
    } else if (data && Array.isArray(data.species)) {
      speciesList = data.species.map((s, i) => ({
        sequence_id: s.id ?? s.sequence_id ?? `${i + 1}`,
        sequence: s.sequence ?? "",
        predicted_species: s.name ?? s.label ?? "Unknown",
        confidence: Number(s.confidence ?? s.score ?? 0),
        source: s.source ?? "unknown",
      }));
    } else {
      throw new Error("Invalid response format from backend.");
    }

    return speciesList;
  } catch (err) {
    // Axios errors are helpful; construct user-friendly errors
    if (axios.isAxiosError && axios.isAxiosError(err)) {
      if (err.response) {
        // Server responded with an error status
        const detail =
          (err.response.data && (err.response.data.detail || err.response.data.message)) ||
          JSON.stringify(err.response.data) ||
          err.response.statusText;
        console.error("API Error:", err.response.status, detail);
        throw new Error(`Backend error: ${err.response.status} - ${detail}`);
      } else if (err.request) {
        // Request sent but no response
        console.error("Network/No-Response Error:", err.message);
        throw new Error("Network error or backend did not respond.");
      } else {
        console.error("Axios Error:", err.message);
        throw new Error(`Request failed: ${err.message}`);
      }
    }

    // Non-axios error
    console.error("Analysis Error:", err);
    throw new Error(err && err.message ? `Analysis failed: ${err.message}` : "Analysis failed");
  }
};

export default { analyzeFastaFile, API_BASE };
