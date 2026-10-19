"""
FAIR ZIP export (roadmap M3, t-1027-2).

GET /reports/{analysis_id}/export/fair streams one ZIP holding everything
needed to reuse an analysis outside Synth Veda:

  results.csv            every per-sequence result (not only flagged rows)
  sample_metadata.json   upload + sample metadata, mapped to Darwin Core and
                         MIxS terms where the mapping is clear, with the
                         unmapped and missing fields listed by name
  provenance.json        model versions, router versions, reference DB +
                         version and orchestrator decisions when present,
                         reference-source licences from the reference manifest
  decision_traces.json   per-sequence orchestrator decision + trace (only
                         when the analysis has them)
  custody.json           the custody chain and its verification at export time
  raw/<file>             the uploaded file, only if its bytes re-hash to the
                         checksum recorded at upload
  README.md              what each file is, what is missing, licence notes
  manifest.json          sha256 + size of every file above
  manifest-sha256.txt    the same, in `sha256sum -c` format

Everything is built from stored data: the analysis_results document, the
upload document, the custody chain and the reference DB manifest. Nothing is
estimated or filled in; a missing optional field is listed as missing.

The orchestrator fields `decision` / `decision_trace` on each result are part
of a shared contract another task produces; this module only reads them.

Pure builders (no I/O) except write_fair_zip, which writes to a file object.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, BinaryIO, Iterable, Optional, Union

from ..custody.chain import canonical_json
from ..models.upload import OPTIONAL_METADATA_FIELDS
from ..uploads.context import build_metadata_context
from .models import REPORT_DISCLAIMER

FAIR_FORMAT = "synthveda-fair-export"
FAIR_FORMAT_VERSION = "1.0"

# ---------------------------------------------------------------------------
# Darwin Core / MIxS mapping
# ---------------------------------------------------------------------------
# One entry per OPTIONAL_METADATA_FIELDS key (tests enforce the match).
# "dwc": Darwin Core terms (https://dwc.tdwg.org/terms/); "mixs": MIxS term
# name (Genomic Standards Consortium, water/sediment packages). None = no
# term with the same meaning. Values are exported as recorded: units are not
# converted and free text is not coded to a vocabulary; "note" says so.
TERM_MAP: dict[str, dict[str, Any]] = {
    "collected_at": {
        "dwc": ["dwc:eventDate"], "mixs": "collection_date", "note": None,
    },
    "latitude": {
        "dwc": ["dwc:decimalLatitude"], "mixs": "lat_lon",
        "note": "Geodetic datum was not recorded at upload, so dwc:geodeticDatum is left empty. "
                "MIxS lat_lon combines latitude and longitude as 'lat lon'.",
    },
    "longitude": {
        "dwc": ["dwc:decimalLongitude"], "mixs": "lat_lon",
        "note": "See latitude.",
    },
    "location_label": {
        "dwc": ["dwc:locality"], "mixs": None,
        "note": "Free text. MIxS geo_loc_name needs an INSDC country:region value, which this "
                "label is not guaranteed to be, so it is not mapped to MIxS.",
    },
    "depth_meters": {
        "dwc": ["dwc:minimumDepthInMeters", "dwc:maximumDepthInMeters"], "mixs": "depth",
        "note": "A single depth was recorded; both Darwin Core depth bounds are set to it.",
    },
    "source_type": {
        "dwc": [], "mixs": "env_medium",
        "note": "Free text (e.g. seawater, sediment), not an ENVO term ID as MIxS recommends.",
    },
    "habitat": {
        "dwc": ["dwc:habitat"], "mixs": None,
        "note": "Free text. MIxS env_broad_scale/env_local_scale expect ENVO terms, so not mapped.",
    },
    "salinity_ppt": {
        "dwc": [], "mixs": "salinity",
        "note": "Recorded in ppt; MIxS salinity is usually reported in psu. Not converted. "
                "Darwin Core has no core term (use a MeasurementOrFact record).",
    },
    "temperature_celsius": {
        "dwc": [], "mixs": "temp",
        "note": "Degrees Celsius. Darwin Core has no core term (use a MeasurementOrFact record).",
    },
    "dissolved_oxygen_mg_l": {
        "dwc": [], "mixs": "diss_oxygen",
        "note": "Recorded in mg/L; MIxS diss_oxygen is usually reported in umol/kg. Not converted. "
                "Darwin Core has no core term (use a MeasurementOrFact record).",
    },
    "ph": {
        "dwc": [], "mixs": "ph",
        "note": "Darwin Core has no core term (use a MeasurementOrFact record).",
    },
    "methodology": {
        "dwc": [], "mixs": None,
        "note": "Lab method (e.g. metabarcoding, qPCR). dwc:samplingProtocol (field sampling) and "
                "MIxS seq_meth (sequencing platform) mean something else, so it is not mapped.",
    },
    "negative_control_included": {
        "dwc": [], "mixs": None,
        "note": "Whether a negative control was run. MIxS neg_cont_type names the kind of "
                "control, not whether one was run, so it is not mapped.",
    },
    "collector": {
        "dwc": ["dwc:recordedBy"], "mixs": None, "note": None,
    },
}


def _iso(value: Any) -> Any:
    return value.isoformat() if isinstance(value, datetime) else value


def _provided(value: Any) -> bool:
    return value is not None and not (isinstance(value, str) and not value.strip())


def build_sample_metadata(analysis_doc: dict[str, Any], upload: Optional[dict[str, Any]]) -> dict[str, Any]:
    """sample_metadata.json: every optional field with value, status and term mapping."""
    doc = upload or {}
    fields: dict[str, Any] = {}
    dwc_record: dict[str, Any] = {}
    mixs_record: dict[str, Any] = {}

    for name, label in OPTIONAL_METADATA_FIELDS.items():
        value = doc.get(name)
        provided = _provided(value)
        mapping = TERM_MAP[name]
        fields[name] = {
            "label": label,
            "value": _iso(value) if provided else None,
            "status": "provided" if provided else "missing",
            "darwin_core": mapping["dwc"] or None,
            "mixs": mapping["mixs"],
            "note": mapping["note"],
        }
        if provided:
            for term in mapping["dwc"]:
                dwc_record[term] = _iso(value)
            if mapping["mixs"] and mapping["mixs"] != "lat_lon":
                mixs_record[mapping["mixs"]] = _iso(value)

    if _provided(doc.get("latitude")) and _provided(doc.get("longitude")):
        mixs_record["lat_lon"] = f"{doc['latitude']} {doc['longitude']}"

    unmapped = [n for n, m in TERM_MAP.items() if not m["dwc"] and not m["mixs"]]
    context = build_metadata_context(upload)

    return {
        "upload": {
            "upload_found": upload is not None,
            "upload_id": doc.get("upload_id") or analysis_doc.get("upload_id"),
            "original_filename": doc.get("original_filename"),
            "file_size_bytes": doc.get("file_size_bytes"),
            "checksum_sha256": doc.get("checksum_sha256"),
            "uploaded_at": _iso(doc.get("created_at")),
            "uploaded_by_user_id": doc.get("user_id"),
        },
        "analysis": {
            "analysis_id": analysis_doc.get("analysis_id"),
            "job_id": analysis_doc.get("job_id"),
            "mode": analysis_doc.get("mode"),
            "analysed_at": _iso(analysis_doc.get("created_at")),
        },
        "fields": fields,
        "darwin_core": dwc_record,
        "mixs": mixs_record,
        "provided_fields": context.provided,
        "missing_fields": context.missing,
        "unmapped_fields": unmapped,
        "negative_control": context.negative_control,
        "accuracy_note": context.accuracy_note,
        "flags": [f.model_dump() for f in context.flags],
        "mapping_note": (
            "Darwin Core terms from https://dwc.tdwg.org/terms/; MIxS term names from the Genomic "
            "Standards Consortium checklists. Values are as recorded at upload: units are not "
            "converted and free text is not coded to a controlled vocabulary."
        ),
    }


# ---------------------------------------------------------------------------
# results.csv
# ---------------------------------------------------------------------------

RESULT_COLUMNS = [
    "sequence_id", "sequence_sha256", "length", "gc_ratio", "n_ratio",
    "route", "route_confidence", "router_method", "router_version", "router_fallback_reason",
    "result_class", "predicted_taxon", "confidence", "inference_mode", "model_version_used",
    "novelty_score", "novelty_level", "requires_cloud_confirmation", "abyss_recommendation",
    "contamination_score", "contamination_flagged", "contamination_type",
    "reason_codes",
]
# From the orchestrator's `decision` dict (shared result contract); only
# emitted when at least one result carries a decision.
DECISION_FIELDS = [
    "final_route", "result_class", "predicted_taxon", "taxon_rank", "percent_identity",
    "reference_db", "reference_db_version", "confidence", "rule",
]
_RESULT_KEY_ALIASES = {"sequence_sha256": "sha256"}


def _cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return "; ".join(str(v) for v in value)
    if isinstance(value, dict):
        return canonical_json(value)
    return _iso(value)


def has_decisions(results: list[dict[str, Any]]) -> bool:
    return any(isinstance(r.get("decision"), dict) for r in results)


def build_results_csv(results: list[dict[str, Any]]) -> str:
    """One row per sequence, in stored order. Empty cell = not recorded."""
    with_decision = has_decisions(results)
    columns = RESULT_COLUMNS + (["decision_" + f for f in DECISION_FIELDS] if with_decision else [])
    columns = columns + ["sequence"]

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(columns)
    for r in results:
        row = [_cell(r.get(_RESULT_KEY_ALIASES.get(c, c))) for c in RESULT_COLUMNS]
        if with_decision:
            d = r.get("decision") if isinstance(r.get("decision"), dict) else {}
            row += [_cell(d.get(f)) for f in DECISION_FIELDS]
        row.append(_cell(r.get("sequence")))
        writer.writerow(row)
    return buf.getvalue()


def build_decision_traces(results: list[dict[str, Any]]) -> Optional[list[dict[str, Any]]]:
    """decision_traces.json, or None when no result carries orchestrator output."""
    out = [
        {
            "sequence_id": r.get("sequence_id"),
            "decision": r.get("decision"),
            "decision_trace": r.get("decision_trace"),
        }
        for r in results
        if isinstance(r.get("decision"), dict) or isinstance(r.get("decision_trace"), dict)
    ]
    return out or None


# ---------------------------------------------------------------------------
# provenance.json
# ---------------------------------------------------------------------------

_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def _count(counter: dict, key: Any) -> None:
    key = "not recorded" if key in (None, "") else str(key)
    counter[key] = counter.get(key, 0) + 1


def reference_versions_used(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Distinct (reference_db, reference_db_version) pairs named by the results:
    the orchestrator decision, and any decision_trace evidence item that
    records them. Counted per sequence.
    """
    pairs: dict[tuple[str, str], set] = {}
    for i, r in enumerate(results):
        sid = r.get("sequence_id", i)
        sources: list[dict] = []
        if isinstance(r.get("decision"), dict):
            sources.append(r["decision"])
        trace = r.get("decision_trace")
        if isinstance(trace, dict) and isinstance(trace.get("evidence"), list):
            sources.extend(e for e in trace["evidence"] if isinstance(e, dict))
        for s in sources:
            db, ver = s.get("reference_db"), s.get("reference_db_version")
            if db or ver:
                pairs.setdefault((str(db or ""), str(ver or "")), set()).add(sid)
    return [
        {"reference_db": db or None, "reference_db_version": ver or None, "sequence_count": len(ids)}
        for (db, ver), ids in sorted(pairs.items())
    ]


def load_reference_manifests(versions: Iterable[str], data_root: Path) -> dict[str, Any]:
    """
    Licence and source summary per reference DB version, read from
    <data_root>/reference/<version>/manifest.json (written by
    services/worker/training/build_reference_db.py). A version whose manifest
    cannot be read is reported as unavailable with the reason, never guessed.
    """
    out: dict[str, Any] = {}
    for version in sorted(set(v for v in versions if v)):
        if not _VERSION_RE.match(version) or ".." in version:
            out[version] = {"available": False, "reason": "version string is not a safe directory name"}
            continue
        path = data_root / "reference" / version / "manifest.json"
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            out[version] = {"available": False, "reason": f"reference manifest not found at the API's data root ({path})"}
            continue
        except (OSError, ValueError) as exc:
            out[version] = {"available": False, "reason": f"reference manifest unreadable: {type(exc).__name__}"}
            continue
        out[version] = {
            "available": True,
            "version": manifest.get("version", version),
            "created": manifest.get("created"),
            "builder": manifest.get("builder"),
            "licences": manifest.get("licences") or {},
            "sources": [
                {"source": s.get("source"), "name": s.get("name"), "licence": s.get("licence")}
                for s in manifest.get("sources") or []
                if isinstance(s, dict)
            ],
            "sources_absent": manifest.get("sources_absent") or [],
        }
    return out


def build_provenance(
    analysis_doc: dict[str, Any],
    *,
    reference_manifests: dict[str, Any],
    custody: dict[str, Any],
    generator: dict[str, Any],
) -> dict[str, Any]:
    results: list[dict] = analysis_doc.get("results", [])

    router_versions: dict[str, int] = {}
    router_methods: dict[str, int] = {}
    fallback_reasons: dict[str, int] = {}
    models: dict[tuple, int] = {}
    rules: dict[str, int] = {}
    orchestrator_versions: dict[str, int] = {}
    with_decision = 0

    for r in results:
        _count(router_versions, r.get("router_version"))
        _count(router_methods, r.get("router_method"))
        if r.get("router_fallback_reason"):
            _count(fallback_reasons, r.get("router_fallback_reason"))
        key = (r.get("route") or "not recorded", r.get("model_version_used") or "not recorded",
               r.get("inference_mode") or "not recorded")
        models[key] = models.get(key, 0) + 1
        if isinstance(r.get("decision"), dict):
            with_decision += 1
            _count(rules, r["decision"].get("rule"))
        if isinstance(r.get("decision_trace"), dict):
            _count(orchestrator_versions, r["decision_trace"].get("orchestrator_version"))

    refs = reference_versions_used(results)
    return {
        "generated_by": generator,
        "analysis": {
            "analysis_id": analysis_doc.get("analysis_id"),
            "job_id": analysis_doc.get("job_id"),
            "upload_id": analysis_doc.get("upload_id"),
            "mode": analysis_doc.get("mode"),
            "model_version_set": analysis_doc.get("model_version_set"),
            "analysed_at": _iso(analysis_doc.get("created_at")),
            "total_sequences": len(results),
        },
        "router": {
            "versions": router_versions,
            "methods": router_methods,
            "fallback_reasons": fallback_reasons,
        },
        "models": [
            {"route": route, "model_version_used": ver, "inference_mode": mode, "sequence_count": n}
            for (route, ver, mode), n in sorted(models.items(), key=lambda kv: (-kv[1], kv[0]))
        ],
        "reference_db": {
            "used": refs,
            "note": None if refs else "No result in this analysis names a reference DB or version.",
            "manifests": reference_manifests,
        },
        "orchestrator": {
            "present": with_decision > 0 or bool(orchestrator_versions),
            "sequences_with_decision": with_decision,
            "versions": orchestrator_versions,
            "rules": rules,
            "file": "decision_traces.json" if (with_decision or orchestrator_versions) else None,
        },
        "custody": custody,
    }


# ---------------------------------------------------------------------------
# README.md
# ---------------------------------------------------------------------------

def build_readme(
    *,
    analysis_id: str,
    generated_at: str,
    files: list[str],
    sample_metadata: dict[str, Any],
    provenance: dict[str, Any],
    raw_file: dict[str, Any],
    custody: dict[str, Any],
) -> str:
    md: list[str] = []
    add = md.append
    add(f"# Synth Veda FAIR export: {analysis_id}")
    add("")
    add(f"Generated {generated_at} by {provenance['generated_by'].get('service')} "
        f"{provenance['generated_by'].get('version')}. Format {FAIR_FORMAT} {FAIR_FORMAT_VERSION}.")
    add("")
    add(f"> {REPORT_DISCLAIMER}")
    add("")
    add("## Contents")
    add("")
    descriptions = {
        "results.csv": "One row per sequence with route, router version, model version, prediction, "
                       "novelty and contamination scores and reason codes. An empty cell means the value "
                       "was not recorded. decision_* columns appear only when the orchestrator produced a "
                       "combined decision for the analysis.",
        "sample_metadata.json": "Upload and sample metadata. Each optional field has its value, whether it "
                                "was provided, and its Darwin Core / MIxS term where a clear mapping exists.",
        "provenance.json": "Router and model versions per sequence count, reference DB and version used, "
                           "reference-source licences, orchestrator presence, custody head at export.",
        "decision_traces.json": "Per-sequence orchestrator decision and decision trace.",
        "custody.json": "The hash-chained custody log for this sample and its verification at export time.",
        "manifest.json": "sha256 and size of every file except the two manifests.",
        "manifest-sha256.txt": "The same checksums in sha256sum format.",
    }
    for f in files:
        if f.startswith("raw/"):
            add(f"- `{f}`: the uploaded file, byte-identical to the upload (sha256 re-checked at export).")
        else:
            add(f"- `{f}`: {descriptions.get(f, '')}")
    add("- `manifest.json`: " + descriptions["manifest.json"])
    add("- `manifest-sha256.txt`: " + descriptions["manifest-sha256.txt"])
    add("")

    add("## Not included or not recorded")
    add("")
    missing = sample_metadata.get("missing_fields") or []
    labels = OPTIONAL_METADATA_FIELDS
    if missing:
        add("Optional sample metadata not recorded at upload: "
            + ", ".join(f"{labels.get(m, m)} (`{m}`)" for m in missing) + ".")
    else:
        add("All optional sample metadata fields were recorded at upload.")
    unmapped = sample_metadata.get("unmapped_fields") or []
    if unmapped:
        add("")
        add("Fields with no Darwin Core or MIxS term (kept under their Synth Veda names): "
            + ", ".join(f"`{u}`" for u in unmapped) + ".")
    if not provenance["orchestrator"]["present"]:
        add("")
        add("No orchestrator decision or decision trace is stored for this analysis, so "
            "`decision_traces.json` is not included and results.csv has no decision_* columns.")
    if not raw_file.get("included"):
        add("")
        add(f"The uploaded file is not included: {raw_file.get('reason')}.")
    add("")

    add("## Reference sources and licences")
    add("")
    used = provenance["reference_db"]["used"]
    manifests = provenance["reference_db"]["manifests"]
    if not used:
        add("No result in this analysis names a reference database, so no reference-source licence "
            "applies to these results.")
    for ref in used:
        ver = ref.get("reference_db_version")
        add(f"- {ref.get('reference_db') or 'reference DB'} version {ver or 'not recorded'} "
            f"({ref['sequence_count']} sequence(s))")
    for ver, m in manifests.items():
        add("")
        add(f"### Reference DB {ver}")
        add("")
        if not m.get("available"):
            add(f"Licence notes unavailable: {m.get('reason')}.")
            continue
        for src, licence in sorted((m.get("licences") or {}).items()):
            add(f"- {src}: {licence}")
        if m.get("sources_absent"):
            add(f"- Not present in this build: {', '.join(m['sources_absent'])}")
    add("")
    add("The sample data and results belong to the uploader. Synth Veda asserts no licence over them; "
        "reuse terms for the reference sources above apply to any reference-derived assignment.")
    add("")

    add("## Chain of custody")
    add("")
    v = custody.get("verification", {})
    add(f"custody.json holds {v.get('length', 0)} event(s) for chain `{custody.get('chain_id')}`; "
        f"verification at export: {'intact' if v.get('valid') else 'BROKEN at seq ' + str((v.get('first_break') or {}).get('seq'))}. "
        f"Head hash: `{v.get('head_hash')}`.")
    add("Each event's hash is sha256(prev_hash || canonical JSON of the event). This export is itself "
        "recorded as the next custody event (report_exported), whose payload carries the sha256 of this "
        "ZIP's manifest.json.")
    add("")

    add("## Verifying this export")
    add("")
    add("```")
    add("sha256sum -c manifest-sha256.txt")
    add("```")
    add("")
    return "\n".join(md)


# ---------------------------------------------------------------------------
# ZIP writer
# ---------------------------------------------------------------------------

FileSource = Union[bytes, BinaryIO]
_COPY_CHUNK = 1024 * 1024


def safe_filename(name: Optional[str]) -> str:
    base = (name or "upload").replace("\\", "/").rsplit("/", 1)[-1]
    base = re.sub(r"[^A-Za-z0-9._-]", "_", base).lstrip(".")
    return base or "upload"


def write_fair_zip(
    out: BinaryIO,
    folder: str,
    entries: list[tuple[str, FileSource]],
    *,
    analysis_id: str,
    generated_at: str,
) -> dict[str, Any]:
    """
    Write `entries` (path, bytes-or-readable) under `folder/` in a ZIP on
    `out`, then manifest.json and manifest-sha256.txt. Each sha256 is taken
    over the bytes as written. Returns the manifest dict plus
    "manifest_sha256" (of the manifest.json bytes).
    """
    listed: list[dict[str, Any]] = []
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path, source in entries:
            h = hashlib.sha256()
            size = 0
            with zf.open(f"{folder}/{path}", "w", force_zip64=True) as dst:
                if isinstance(source, (bytes, bytearray)):
                    dst.write(source)
                    h.update(source)
                    size = len(source)
                else:
                    source.seek(0)
                    for chunk in iter(lambda: source.read(_COPY_CHUNK), b""):
                        dst.write(chunk)
                        h.update(chunk)
                        size += len(chunk)
            listed.append({"path": path, "sha256": h.hexdigest(), "bytes": size})

        manifest = {
            "format": FAIR_FORMAT,
            "format_version": FAIR_FORMAT_VERSION,
            "analysis_id": analysis_id,
            "generated_at": generated_at,
            "hash_algorithm": "sha256",
            "files": listed,
        }
        manifest_bytes = json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8")
        zf.writestr(f"{folder}/manifest.json", manifest_bytes)
        zf.writestr(
            f"{folder}/manifest-sha256.txt",
            "".join(f"{f['sha256']}  {f['path']}\n" for f in listed).encode("utf-8"),
        )
    return {**manifest, "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest()}


def json_bytes(obj: Any) -> bytes:
    return json.dumps(obj, indent=2, ensure_ascii=False, default=_iso_default).encode("utf-8")


def _iso_default(obj: Any) -> Any:
    if isinstance(obj, datetime):
        return obj.isoformat()
    return str(obj)
