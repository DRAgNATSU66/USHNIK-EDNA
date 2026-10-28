// Audit trail: GET /partner/audits (newest first) and a form that records
// an audit with POST /partner/audits. The server is the only validator:
// a 422/403/404 comes back field by field and is shown as returned, and
// nothing is added to the list until the server has stored it.
import { useState } from "react";
import { createPartnerAudit } from "../../../lib/api";
import Dropdown from "../../../components/shared/Dropdown";
import { tokens } from "../../../components/shared/tokens";
import {
  cardBase, fieldLabelStyle, fmtDateTime, formatApiError, inputStyle, noteStyle, primaryBtnStyle, rowStyle, s,
  secondaryBtnStyle,
} from "./styles";
import { ErrorLine, Pill, SectionLabel } from "./ui";

const TARGET_KINDS = [
  { value: "site", label: "Site / zone" },
  { value: "upload", label: "Upload (upload_id)" },
  { value: "analysis", label: "Analysis (analysis_id)" },
  { value: "organisation", label: "Organisation" },
  { value: "other", label: "Other" },
];
const STATUSES = [
  { value: "scheduled", label: "Scheduled" },
  { value: "in_progress", label: "In progress" },
  { value: "completed", label: "Completed" },
  { value: "cancelled", label: "Cancelled" },
];
const SEVERITIES = ["info", "low", "medium", "high", "critical"].map((v) => ({ value: v, label: v }));

const STATUS_TONE = { scheduled: "accent", in_progress: "warning", completed: "success", cancelled: "pending" };
const SEVERITY_TONE = { info: "pending", low: "accent", medium: "warning", high: "danger", critical: "danger" };

const EMPTY_FORM = {
  kind: "site", ref: "", label: "", scope: "", status: "scheduled", due_date: "", completed_at: "", findings: [],
};

function buildBody(form) {
  const body = {
    target: { kind: form.kind, label: form.label },
    scope: form.scope,
    status: form.status,
    findings: form.findings.map((f) => ({
      severity: f.severity,
      description: f.description,
      ...(f.reference.trim() ? { reference: f.reference } : {}),
    })),
  };
  if (form.ref.trim()) body.target.ref = form.ref.trim();
  if (form.due_date) body.due_date = form.due_date;
  // datetime-local is the viewer's local time; send it as an absolute instant.
  if (form.status === "completed" && form.completed_at) body.completed_at = new Date(form.completed_at).toISOString();
  return body;
}

function AuditRow({ a }) {
  const sev = {};
  for (const f of a.findings || []) sev[f.severity] = (sev[f.severity] || 0) + 1;
  return (
    <div style={{ ...rowStyle, borderLeft: `3px solid ${tokens[STATUS_TONE[a.status]] || tokens.pending}` }} data-testid="audit-row">
      <div style={{ display: "flex", alignItems: "center", gap: s(8), flexWrap: "wrap" }}>
        <Pill tone={STATUS_TONE[a.status]}>{a.status.replace("_", " ")}</Pill>
        <span style={{ fontSize: s(12.5), fontWeight: 600 }}>{a.target.label}</span>
        <span style={{ fontSize: s(10.5), color: tokens.pending }}>
          {a.target.kind}{a.target.ref ? ` · ${a.target.ref}` : ""}
        </span>
      </div>
      <span style={{ fontSize: s(11.5), color: tokens.sectionSubtext, whiteSpace: "pre-wrap" }}>{a.scope}</span>
      {a.findings?.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
          {a.findings.map((f, i) => (
            <span key={i} style={{ fontSize: s(11), color: tokens.wordmark, display: "flex", gap: 6, alignItems: "baseline" }}>
              <Pill tone={SEVERITY_TONE[f.severity]}>{f.severity}</Pill>
              <span>{f.description}{f.reference ? <span style={{ color: tokens.pending }}> — {f.reference}</span> : null}</span>
            </span>
          ))}
        </div>
      )}
      <span style={noteStyle}>
        recorded {fmtDateTime(a.created_at)} by {a.created_by_name}
        {a.due_date ? ` · due ${a.due_date}` : ""}
        {a.completed_at ? ` · completed ${fmtDateTime(a.completed_at)}` : ""}
        {` · ${a.audit_id}`}
      </span>
    </div>
  );
}

function FindingEditor({ f, onChange, onRemove, idx }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "110px 1fr", gap: 6, padding: 8, border: "1px solid #101D33", borderRadius: 4 }}>
      <Dropdown options={SEVERITIES} value={f.severity} onChange={(v) => onChange({ ...f, severity: v })} minWidth={100} />
      <input aria-label={`Finding ${idx + 1} description`} style={inputStyle} value={f.description} placeholder="Finding"
        onChange={(e) => onChange({ ...f, description: e.target.value })} />
      <span />
      <div style={{ display: "flex", gap: 6 }}>
        <input aria-label={`Finding ${idx + 1} reference`} style={inputStyle} value={f.reference}
          placeholder="Reference (optional: sequence id, permit clause…)"
          onChange={(e) => onChange({ ...f, reference: e.target.value })} />
        <button type="button" onClick={onRemove} style={secondaryBtnStyle} aria-label={`Remove finding ${idx + 1}`}>✕</button>
      </div>
    </div>
  );
}

export default function AuditTrail({ audits, error, canRecord, onRecorded }) {
  const [form, setForm] = useState(EMPTY_FORM);
  const [submitting, setSubmitting] = useState(false);
  const [errors, setErrors] = useState([]);
  const [saved, setSaved] = useState(null);
  const set = (k) => (v) => setForm((f) => ({ ...f, [k]: v }));
  const needsRef = form.kind === "upload" || form.kind === "analysis";

  const submit = async (e) => {
    e.preventDefault();
    setSubmitting(true);
    setErrors([]);
    setSaved(null);
    try {
      const created = await createPartnerAudit(buildBody(form));
      setSaved(created.audit_id);
      setForm(EMPTY_FORM);
      onRecorded(created);
    } catch (err) {
      setErrors(formatApiError(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div style={{ ...cardBase, gridColumn: "1 / -1" }} id="audit-trail">
      <SectionLabel>AUDIT TRAIL</SectionLabel>
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1.25fr) minmax(0, 1fr)", gap: s(18) }}>
        <div style={{ display: "flex", flexDirection: "column", gap: s(8) }}>
          <ErrorLine what="audits" error={error} />
          {!error && audits === null && <span style={noteStyle}>Loading audits…</span>}
          {!error && audits?.length === 0 && (
            <span style={{ fontSize: s(12), color: tokens.sectionSubtext }}>
              No audits recorded in this scope yet. Record one with the form.
            </span>
          )}
          {audits?.map((a) => <AuditRow key={a.audit_id} a={a} />)}
          {audits?.length > 0 && <span style={noteStyle}>Newest first, up to 50. Audit records are written once and not edited.</span>}
        </div>

        {canRecord ? (
          <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: s(8) }} aria-label="Record an audit">
            <span style={{ fontSize: s(12.5), fontWeight: 600 }}>Record an audit</span>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
              <label style={fieldLabelStyle}>TARGET KIND
                <Dropdown options={TARGET_KINDS} value={form.kind} onChange={set("kind")} />
              </label>
              <label style={fieldLabelStyle}>TARGET ID{needsRef ? " (required)" : " (optional)"}
                <input style={inputStyle} value={form.ref} onChange={(e) => set("ref")(e.target.value)}
                  placeholder={needsRef ? `${form.kind}_id` : "—"} />
              </label>
            </div>
            <label style={fieldLabelStyle}>TARGET LABEL
              <input style={inputStyle} value={form.label} onChange={(e) => set("label")(e.target.value)} placeholder="e.g. Outfall zone B" />
            </label>
            <label style={fieldLabelStyle}>SCOPE
              <textarea style={{ ...inputStyle, minHeight: 56, resize: "vertical" }} value={form.scope}
                onChange={(e) => set("scope")(e.target.value)} placeholder="What the audit covers" />
            </label>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
              <label style={fieldLabelStyle}>STATUS
                <Dropdown options={STATUSES} value={form.status} onChange={set("status")} />
              </label>
              <label style={fieldLabelStyle}>DUE DATE
                <input type="date" style={inputStyle} value={form.due_date} onChange={(e) => set("due_date")(e.target.value)} />
              </label>
            </div>
            {form.status === "completed" && (
              <label style={fieldLabelStyle}>COMPLETED AT (your local time; blank = now)
                <input type="datetime-local" style={inputStyle} value={form.completed_at}
                  onChange={(e) => set("completed_at")(e.target.value)} />
              </label>
            )}
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <span style={fieldLabelStyle}>FINDINGS ({form.findings.length})</span>
              {form.findings.map((f, i) => (
                <FindingEditor key={i} idx={i} f={f}
                  onChange={(nf) => set("findings")(form.findings.map((x, j) => (j === i ? nf : x)))}
                  onRemove={() => set("findings")(form.findings.filter((_, j) => j !== i))} />
              ))}
              <button type="button" style={secondaryBtnStyle}
                onClick={() => set("findings")([...form.findings, { severity: "medium", description: "", reference: "" }])}>
                + Add finding
              </button>
            </div>
            {errors.length > 0 && (
              <div role="alert" style={{ display: "flex", flexDirection: "column", gap: 2, padding: 8, borderRadius: 4, border: `1px solid ${tokens.dangerBorder}`, background: tokens.dangerBg }}>
                <span style={{ fontSize: s(11), fontWeight: 600, color: tokens.danger }}>Not recorded — the server refused it:</span>
                {errors.map((m, i) => <span key={i} style={{ fontSize: s(11), color: tokens.danger }}>{m}</span>)}
              </div>
            )}
            {saved && <span role="status" style={{ fontSize: s(11.5), color: tokens.success }}>Recorded {saved}.</span>}
            <button type="submit" disabled={submitting} style={{ ...primaryBtnStyle, opacity: submitting ? 0.6 : 1 }}>
              {submitting ? "Recording…" : "Record audit"}
            </button>
            <span style={noteStyle}>
              Recorded under your account with the server time. Upload and analysis targets must exist and be visible to you.
            </span>
          </form>
        ) : (
          <span style={{ fontSize: s(12), color: tokens.sectionSubtext }}>Viewers can read audits but cannot record them.</span>
        )}
      </div>
    </div>
  );
}
