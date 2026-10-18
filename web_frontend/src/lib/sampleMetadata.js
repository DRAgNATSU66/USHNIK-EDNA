// Display helpers for the optional upload metadata carried on
// report.metadata (14 fields, null = not recorded) and the per-result
// `context` block (services/api/app/uploads/context.py). The field list
// itself lives in the API (OPTIONAL_METADATA_FIELDS); `context.labels`
// carries its labels, so this file only formats values.

export const NOT_RECORDED = "Not recorded";

// The API stores collected_at in MongoDB, which hands datetimes back as
// naive UTC ("2026-08-12T01:10:00"). JS would read a naive string as local
// time, so an offset-less value is pinned to UTC here.
export function parseApiDateTime(value) {
  if (!value) return null;
  const hasOffset = /([zZ]|[+-]\d{2}:?\d{2})$/.test(value);
  const d = new Date(hasOffset ? value : `${value}Z`);
  return Number.isNaN(d.getTime()) ? null : d;
}

// Shown in the viewer's own timezone with its abbreviation, since the
// offset the collector entered is not kept once stored.
export function formatCollectedAt(value) {
  const d = parseApiDateTime(value);
  if (!d) return NOT_RECORDED;
  const date = d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
  const time = d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", timeZoneName: "short" });
  return `${date} · ${time}`;
}

export function formatLatLong(lat, lon) {
  if (lat == null || lon == null) return NOT_RECORDED;
  const ns = lat >= 0 ? "N" : "S";
  const ew = lon >= 0 ? "E" : "W";
  return `${Math.abs(lat).toFixed(4)}° ${ns}, ${Math.abs(lon).toFixed(4)}° ${ew}`;
}

export function formatNegativeControl(value) {
  if (value === true) return "Included";
  if (value === false) return "Not included";
  return NOT_RECORDED;
}

// One field of report.metadata as display text. Returns NOT_RECORDED for
// null / blank values.
export function formatMetadataField(field, metadata) {
  const v = metadata?.[field];
  if (field === "negative_control_included") return formatNegativeControl(v);
  if (v == null || (typeof v === "string" && !v.trim())) return NOT_RECORDED;
  switch (field) {
    case "collected_at": return formatCollectedAt(v);
    case "latitude": return `${Math.abs(v).toFixed(4)}° ${v >= 0 ? "N" : "S"}`;
    case "longitude": return `${Math.abs(v).toFixed(4)}° ${v >= 0 ? "E" : "W"}`;
    case "depth_meters": return `${v.toLocaleString()} m`;
    case "salinity_ppt": return `${v} ppt`;
    case "temperature_celsius": return `${v} °C`;
    case "dissolved_oxygen_mg_l": return `${v} mg/L`;
    case "ph": return `${v}`;
    default: return String(v);
  }
}
