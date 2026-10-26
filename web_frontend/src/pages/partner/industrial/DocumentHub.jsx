// Document hub: only files the API can actually produce for one of your
// analyses -- the FAIR ZIP export, the chain-of-custody JSON (verified on
// request) and field-log attachments (stored via app/storage.py, sha256
// re-checked on download). Nothing is listed that the server cannot serve.
import { useEffect, useState } from "react";
import { downloadFieldAttachment, exportReportFair, getReportCustody, listFieldAttachments } from "../../../lib/api";
import Dropdown from "../../../components/shared/Dropdown";
import { tokens } from "../../../components/shared/tokens";
import {
  cardBase, fmtDate, fmtDateTime, monoStyle, noteStyle, rowStyle, s, saveBlob, secondaryBtnStyle,
} from "./styles";
import { ErrorLine, Pill, SectionLabel } from "./ui";

const kb = (n) => (n >= 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`);

function CustodyResult({ custody, analysisId }) {
  const v = custody.verification || {};
  const ri = custody.results_integrity?.status;
  const mi = custody.metadata_integrity?.status;
  const fi = custody.file_integrity?.status;
  return (
    <div style={{ ...rowStyle, borderLeft: `3px solid ${v.valid ? tokens.success : tokens.danger}` }} data-testid="custody-result">
      <div style={{ display: "flex", gap: s(8), alignItems: "center", flexWrap: "wrap" }}>
        <Pill tone={v.valid ? "success" : "danger"}>{v.valid ? "chain valid" : "chain broken"}</Pill>
        <span style={{ fontSize: s(11.5), color: tokens.wordmark }}>{v.length} events</span>
        {ri && <Pill tone={ri === "match" ? "success" : ri === "mismatch" ? "danger" : "pending"}>results {ri.replace(/_/g, " ")}</Pill>}
        {mi && <Pill tone={mi === "unchanged" ? "success" : "warning"}>metadata {mi.replace(/_/g, " ")}</Pill>}
        {fi && <Pill tone={fi === "verified" ? "success" : "warning"}>file {fi.replace(/_/g, " ")}</Pill>}
      </div>
      {v.first_break && <span style={{ fontSize: s(11), color: tokens.danger }}>First break at seq {v.first_break.seq}: {v.first_break.reason}</span>}
      {v.head_hash && <span style={monoStyle}>head {v.head_hash.slice(0, 20)}… · checked {fmtDateTime(v.checked_at)}</span>}
      <button type="button" style={secondaryBtnStyle}
        onClick={() => saveBlob(new Blob([JSON.stringify(custody, null, 2)], { type: "application/json" }), `custody_${analysisId}.json`)}>
        Save custody JSON
      </button>
    </div>
  );
}

export default function DocumentHub({ reports, reportsError }) {
  const [analysisId, setAnalysisId] = useState(null);
  const [attachments, setAttachments] = useState(null);
  const [attachError, setAttachError] = useState(null);
  const [custody, setCustody] = useState(null);
  const [busy, setBusy] = useState(null); // "fair" | "custody" | attachment_id
  const [actionError, setActionError] = useState(null);

  useEffect(() => {
    if (!analysisId && reports?.length) setAnalysisId(reports[0].analysis_id);
  }, [reports, analysisId]);

  useEffect(() => {
    if (!analysisId) return undefined;
    let live = true;
    setAttachments(null);
    setAttachError(null);
    setCustody(null);
    setActionError(null);
    listFieldAttachments(analysisId)
      .then((rows) => { if (live) setAttachments(rows); })
      .catch((e) => { if (live) setAttachError(e); });
    return () => { live = false; };
  }, [analysisId]);

  const run = async (key, fn) => {
    setBusy(key);
    setActionError(null);
    try {
      await fn();
    } catch (e) {
      setActionError(e.message || "request failed");
    } finally {
      setBusy(null);
    }
  };

  // The export is appended to the custody chain before the ZIP is sent, so a
  // verification already on screen is re-read rather than left one event short.
  const downloadFair = () => run("fair", async () => {
    const resp = await exportReportFair(analysisId);
    saveBlob(await resp.blob(), `synthveda_fair_${analysisId}.zip`);
    if (custody) setCustody(await getReportCustody(analysisId));
  });
  const verifyCustody = () => run("custody", async () => setCustody(await getReportCustody(analysisId)));
  const downloadAttachment = (a) => run(a.attachment_id, async () => {
    const resp = await downloadFieldAttachment(a.attachment_id);
    saveBlob(await resp.blob(), a.original_filename);
  });

  const options = (reports || []).map((r) => ({
    value: r.analysis_id,
    label: `${r.source_file || r.analysis_id} · ${fmtDate(r.created_at)}`,
  }));

  return (
    <div style={cardBase} id="document-hub">
      <SectionLabel>DOCUMENT HUB</SectionLabel>
      <ErrorLine what="your analyses" error={reportsError} />
      {!reportsError && reports === null && <span style={noteStyle}>Loading analyses…</span>}
      {!reportsError && reports?.length === 0 && (
        <span style={{ fontSize: s(12), color: tokens.sectionSubtext }}>
          No analyses of yours yet, so there are no exports, custody logs or attachments to list.
        </span>
      )}
      {options.length > 0 && (
        <>
          <Dropdown options={options} value={analysisId} onChange={setAnalysisId} minWidth={0} />
          <div style={{ display: "flex", gap: s(8), flexWrap: "wrap" }}>
            <button type="button" style={secondaryBtnStyle} onClick={downloadFair} disabled={busy === "fair"}>
              {busy === "fair" ? "Building ZIP…" : "Download FAIR ZIP"}
            </button>
            <button type="button" style={secondaryBtnStyle} onClick={verifyCustody} disabled={busy === "custody"}>
              {busy === "custody" ? "Verifying…" : "Verify chain of custody"}
            </button>
          </div>
          {actionError && <span role="alert" style={{ fontSize: s(11.5), color: tokens.danger }}>{actionError}</span>}
          {custody && <CustodyResult custody={custody} analysisId={analysisId} />}

          <span style={{ ...noteStyle, color: tokens.sectionSubtext, marginTop: s(4) }}>FIELD-LOG ATTACHMENTS</span>
          <ErrorLine what="attachments" error={attachError} />
          {attachments?.length === 0 && <span style={noteStyle}>No attachments on this analysis.</span>}
          {attachments?.map((a) => (
            <div key={a.attachment_id} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: s(8) }}>
              <div style={{ display: "flex", flexDirection: "column", minWidth: 0 }}>
                <span style={{ fontSize: s(12), color: tokens.wordmark, overflow: "hidden", textOverflow: "ellipsis" }}>{a.original_filename}</span>
                <span style={monoStyle}>{kb(a.size_bytes)} · {a.uploader_name} · {fmtDate(a.created_at)} · sha256 {a.checksum_sha256.slice(0, 10)}…</span>
              </div>
              <button type="button" style={secondaryBtnStyle} onClick={() => downloadAttachment(a)} disabled={busy === a.attachment_id}>
                Download
              </button>
            </div>
          ))}
          <span style={noteStyle}>
            Your 20 most recent analyses. Each FAIR export is recorded on the sample's custody chain before it downloads;
            attachment bytes are re-hashed against their stored sha256.
          </span>
        </>
      )}
    </div>
  );
}
