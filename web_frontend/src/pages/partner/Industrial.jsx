// Industrial partner page (t-1028-2, M1): incidents, audit trail, field-log
// tasks and a document hub, every figure read from this deployment's records:
//   GET /partner/summary    audit + task counts
//   GET /partner/incidents  flagged analyses + open urgent reviews
//   GET /partner/tasks      field-log tasks across the scoped analyses
//   GET/POST /partner/audits
//   GET /reports (+ custody, FAIR export) and /field-log/attachments
//
// Removed in t-1028-2 because no data source exists for them: the impact
// score (no defensible formula over real data), the risk radar, biological
// impact metrics, remediation plan, predictive biofouling threshold,
// remediation ROI and the hard-coded reference-DB footer. Nothing on this
// page is a placeholder: a panel with no data says so.
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import SidebarMenu from "../../components/sidebar/SidebarMenu";
import Dropdown from "../../components/shared/Dropdown";
import ConfidenceChip from "../../components/shared/ConfidenceChip";
import { CONTAMINATION_CHIP, NOVELTY_CHIP } from "../../lib/scoreChips";
import { tokens } from "../../components/shared/tokens";
import { useAuth } from "../../contexts/AuthContext";
import { getPartnerIncidents, getPartnerSummary, getPartnerTasks, listPartnerAudits, listReports } from "../../lib/api";
import { revealStyle } from "../../styles/reveal";
import AuditTrail from "./industrial/AuditTrail";
import DocumentHub from "./industrial/DocumentHub";
import {
  cardBase, fmtDate, fmtDateTime, linkStyle, monoStyle, noteStyle, panelLabelStyle, plural, rowStyle, s,
} from "./industrial/styles";
import { ErrorLine, Pill, SectionLabel } from "./industrial/ui";

const ALL_DATA_ROLES = ["admin", "company_owner"];

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

const TASK_TONE = { open: "accent", in_progress: "warning", done: "success" };

function Kpi({ label, value, tone, sub, testId, children }) {
  return (
    <div style={cardBase} data-testid={testId}>
      <span style={panelLabelStyle}>{label}</span>
      <span style={{ fontSize: s(28), fontWeight: 600, color: tone ? tokens[tone] : tokens.textPrimary }}>{value}</span>
      {sub && <span style={{ fontSize: s(11), color: tokens.pending }}>{sub}</span>}
      {children}
    </div>
  );
}

function IncidentRow({ inc }) {
  const types = Object.entries(inc.contamination_types || {}).map(([t, n]) => `${t} ×${n}`).join(", ");
  const tone = inc.contamination_flags || inc.urgent_open_reviews ? tokens.danger : tokens.warning;
  return (
    <div style={{ ...rowStyle, borderLeft: `3px solid ${tone}` }} data-testid="incident-row">
      <div style={{ display: "flex", justifyContent: "space-between", gap: s(10), flexWrap: "wrap", alignItems: "baseline" }}>
        <span style={{ fontSize: s(13), fontWeight: 600 }}>
          {inc.source_file || inc.analysis_id}
          {inc.location_label && <span style={{ fontWeight: 400, color: tokens.sectionSubtext }}> · {inc.location_label}</span>}
        </span>
        <Link to={`/analysis/${inc.analysis_id}`} style={linkStyle}>Open results →</Link>
      </div>
      <div style={{ display: "flex", gap: s(6), flexWrap: "wrap" }}>
        {inc.contamination_flags > 0 && <Pill tone="danger">{plural(inc.contamination_flags, "contamination flag")}</Pill>}
        {inc.novelty_flags > 0 && <Pill tone="purple">{plural(inc.novelty_flags, "novelty flag")}</Pill>}
        {inc.urgent_open_reviews > 0 && <Pill tone="danger">{plural(inc.urgent_open_reviews, "urgent open review")}</Pill>}
        <Pill tone="pending">{plural(inc.open_reviews, "open review")}</Pill>
      </div>
      <span style={{ fontSize: s(11), color: tokens.sectionSubtext }}>
        {inc.sequences} sequences · analysed {fmtDateTime(inc.created_at)}
        {inc.collected_at ? ` · collected ${fmtDate(inc.collected_at)}` : ""}
        {types ? ` · contamination type: ${types}` : ""}
      </span>
      {inc.flagged_sequences?.length > 0 && (
        <span style={monoStyle}>
          {inc.flagged_sequences.map((f) => `${f.sequence_id} (${f.flag})`).join(" · ")}
          {inc.flagged_sequences.length < inc.contamination_flags + inc.novelty_flags ? " · …" : ""}
        </span>
      )}
      <span style={monoStyle}>analysis {inc.analysis_id}{inc.upload_id ? ` · upload ${inc.upload_id}` : ""}</span>
    </div>
  );
}

function TaskRow({ t }) {
  return (
    <div style={{ ...rowStyle, borderLeft: `3px solid ${t.overdue ? tokens.danger : tokens[TASK_TONE[t.task_status]] || tokens.pending}` }} data-testid="task-row">
      <div style={{ display: "flex", gap: s(8), alignItems: "center", flexWrap: "wrap" }}>
        <Pill tone={TASK_TONE[t.task_status]}>{t.task_status.replace("_", " ")}</Pill>
        {t.overdue && <Pill tone="danger">overdue</Pill>}
        <span style={{ fontSize: s(12), color: t.task_status === "done" ? tokens.pending : tokens.wordmark, textDecoration: t.task_status === "done" ? "line-through" : "none" }}>
          {t.body}
        </span>
      </div>
      <span style={noteStyle}>
        {t.due_date ? `due ${t.due_date}` : "no due date"}
        {t.assignee ? ` · ${t.assignee}` : ""}
        {t.author_name ? ` · by ${t.author_name}` : ""}
        {" · "}
        <Link to={`/researcher-mode/comments?analysis_id=${t.analysis_id}`} style={{ ...linkStyle, fontSize: s(10.5) }}>field log</Link>
      </span>
    </div>
  );
}

export default function Industrial() {
  const { user } = useAuth();
  const privileged = ALL_DATA_ROLES.includes(user?.role);
  const [scope, setScope] = useState("mine");

  const [summary, setSummary] = useState(null);
  const [incidents, setIncidents] = useState(null);
  const [tasks, setTasks] = useState(null);
  const [audits, setAudits] = useState(null);
  const [reports, setReports] = useState(null);
  const [errors, setErrors] = useState({});

  // The scope the panels currently show; a summary refresh after recording
  // an audit is applied only if the scope has not changed since it was sent.
  const scopeRef = useRef(scope);
  useEffect(() => { scopeRef.current = scope; }, [scope]);

  useEffect(() => {
    // A batch for a scope the user has since switched away from must not
    // overwrite the current one (same guard as DocumentHub's attachments).
    let live = true;
    const params = { scope };
    // /partner/audits returns everyone's audits to admin/company_owner;
    // "My data" narrows it to the caller like the other panels.
    const auditParams = scope === "all" ? {} : { created_by: user?.user_id };
    setSummary(null);
    setIncidents(null);
    setTasks(null);
    setAudits(null);
    Promise.allSettled([
      getPartnerSummary(params),
      getPartnerIncidents(params),
      getPartnerTasks(params),
      listPartnerAudits(auditParams),
    ]).then(([sm, inc, tk, au]) => {
      if (!live) return;
      setSummary(sm.status === "fulfilled" ? sm.value : null);
      setIncidents(inc.status === "fulfilled" ? inc.value : null);
      setTasks(tk.status === "fulfilled" ? tk.value : null);
      setAudits(au.status === "fulfilled" ? au.value : null);
      setErrors((e) => ({
        ...e,
        summary: sm.reason || null,
        incidents: inc.reason || null,
        tasks: tk.reason || null,
        audits: au.reason || null,
      }));
    });
    return () => { live = false; };
  }, [scope, user?.user_id]);

  useEffect(() => {
    listReports(20)
      .then(setReports)
      .catch((e) => setErrors((x) => ({ ...x, reports: e })));
  }, []);

  const onRecorded = (audit) => {
    setAudits((list) => [audit, ...(list || [])]);
    const sent = scope;
    getPartnerSummary({ scope: sent })
      .then((sm) => { if (scopeRef.current === sent) setSummary(sm); })
      .catch((e) => { if (scopeRef.current === sent) setErrors((x) => ({ ...x, summary: e })); });
  };

  const auditSum = summary?.audits;
  const taskSum = summary?.tasks;
  const openTasks = taskSum ? (taskSum.by_status.open || 0) + (taskSum.by_status.in_progress || 0) : null;
  const dash = "—";

  const scrollTo = (id) => document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });

  return (
    <div style={pageStyle}>
      <div style={ambientGlow} />
      <SidebarMenu />
      <div style={{ position: "relative", maxWidth: s(1560), margin: "0 auto", padding: `${s(32)}px ${s(44)}px ${s(44)}px`, display: "flex", flexDirection: "column", gap: s(18) }}>
        {/* Header */}
        <div style={{ display: "flex", flexDirection: "column", gap: s(6), alignItems: "center", textAlign: "center" }}>
          <div style={{ fontSize: s(12), letterSpacing: "0.08em", color: tokens.labelText }}>PARTNER REPORT › INDUSTRIAL</div>
          <h1 style={{ margin: 0, fontSize: s(27), fontWeight: 600, letterSpacing: "-0.01em" }}>Enterprise Compliance Dashboard</h1>
          <p style={{ margin: 0, fontSize: s(14), color: tokens.sectionSubtext }}>
            Incidents, audits, field tasks and documents — counted from this deployment's records
          </p>
          <div style={{ display: "flex", gap: s(10), alignItems: "center", marginTop: s(4), flexWrap: "wrap", justifyContent: "center" }}>
            {privileged ? (
              <Dropdown
                options={[{ value: "mine", label: "My data" }, { value: "all", label: "All users" }]}
                value={scope}
                onChange={setScope}
                minWidth={130}
              />
            ) : (
              <Pill tone="pending">My data</Pill>
            )}
            <span style={noteStyle}>
              {incidents ? `computed ${fmtDateTime(incidents.generated_at)} · no date filter` : "loading…"}
            </span>
          </div>
        </div>

        {/* KPIs */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: s(14) }}>
          <Kpi
            testId="kpi-incidents"
            label="INCIDENTS (FLAGGED ANALYSES)"
            value={incidents ? incidents.total : dash}
            tone={incidents?.total ? "danger" : undefined}
            sub={incidents
              ? `${plural(incidents.contamination_flags, "contamination flag")} · ${plural(incidents.novelty_flags, "novelty flag")} · of ${plural(incidents.analyses_in_scope, "analysis", "analyses")}`
              : null}
          >
            {incidents?.total > 0 && (
              <button type="button" onClick={() => scrollTo("incidents")}
                style={{ alignSelf: "flex-start", padding: `${s(5)}px ${s(13)}px`, border: "1px solid rgba(255,123,123,0.35)", borderRadius: s(10), background: "rgba(255,123,123,0.08)", fontFamily: "inherit", fontSize: s(11.5), fontWeight: 600, color: "#FF9B9B", cursor: "pointer" }}>
                View source detections →
              </button>
            )}
          </Kpi>
          <Kpi
            testId="kpi-urgent"
            label="URGENT OPEN REVIEWS"
            value={incidents ? incidents.urgent_reviews_total : dash}
            tone={incidents?.urgent_reviews_total ? "danger" : undefined}
            sub="triage priority urgent; submitted, triaged or needs evidence"
          />
          <Kpi
            testId="kpi-audits"
            label="PENDING AUDITS"
            value={auditSum ? auditSum.pending : dash}
            tone={auditSum?.overdue ? "warningAlt" : undefined}
            sub={auditSum
              ? [
                  auditSum.next_due_date ? `next due ${auditSum.next_due_date}` : "no due date set",
                  auditSum.overdue ? `${auditSum.overdue} overdue` : null,
                  auditSum.last_completed_at ? `last completed ${fmtDate(auditSum.last_completed_at)}` : null,
                ].filter(Boolean).join(" · ")
              : null}
          />
          <Kpi
            testId="kpi-tasks"
            label="OPEN FIELD TASKS"
            value={openTasks ?? dash}
            tone={taskSum?.overdue ? "warningAlt" : undefined}
            sub={taskSum
              ? [`${taskSum.overdue} overdue`, taskSum.next_due_date ? `next due ${taskSum.next_due_date}` : null, `${taskSum.total} total`]
                  .filter(Boolean).join(" · ")
              : null}
          />
        </div>
        <ErrorLine what="the partner summary" error={errors.summary} />

        {/* Incidents */}
        <div style={{ ...cardBase, ...revealStyle(0) }} id="incidents">
          <SectionLabel>INCIDENTS — SOURCE DETECTIONS</SectionLabel>
          <ErrorLine what="incidents" error={errors.incidents} />
          {incidents && (
            <>
              <span style={{ ...noteStyle, color: tokens.sectionSubtext }}>{incidents.definitions.incident}</span>
              {incidents.expected_contamination_flags > 0 && (
                <span style={noteStyle} data-testid="expected-contamination">
                  Not counted as incidents: {plural(incidents.expected_contamination_flags, "expected contamination flag")}. {incidents.definitions.expected_contamination}
                </span>
              )}
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(420px, 1fr))", gap: s(10) }}>
                {incidents.incidents.map((inc) => <IncidentRow key={inc.analysis_id} inc={inc} />)}
              </div>
              {incidents.urgent_reviews.length > 0 && (
                <div style={{ display: "flex", flexDirection: "column", gap: s(6), marginTop: s(4) }}>
                  <span style={{ ...panelLabelStyle, fontSize: s(10) }}>URGENT OPEN REVIEWS (OLDEST FIRST)</span>
                  {incidents.urgent_reviews.map((r) => (
                    <div key={r.review_id} style={{ display: "flex", gap: s(8), alignItems: "baseline", flexWrap: "wrap" }} data-testid="urgent-review">
                      <Pill tone="danger">{(r.review_type || "review").replace(/_/g, " ")}</Pill>
                      <span style={{ fontSize: s(11.5), color: tokens.wordmark }}>{r.sequence_id}</span>
                      <span style={noteStyle}>
                        {r.state.replace(/_/g, " ")} · since {fmtDateTime(r.created_at)}
                        {r.contamination_score != null ? ` · contamination score ${r.contamination_score.toFixed(2)}` : ""}
                        {r.novelty_score != null ? ` · novelty score ${r.novelty_score.toFixed(2)}` : ""}
                      </span>
                      {r.contamination_score != null && <ConfidenceChip {...CONTAMINATION_CHIP} />}
                      {r.novelty_score != null && <ConfidenceChip {...NOVELTY_CHIP} />}
                      <Link to={`/analysis/${r.analysis_id}`} style={{ ...linkStyle, fontSize: s(10.5) }}>results →</Link>
                    </div>
                  ))}
                </div>
              )}
              {/* Server notes: the empty-state reason, or truncation. */}
              {incidents.notes.map((n) => (
                <span key={n} style={incidents.total ? noteStyle : { fontSize: s(12), color: tokens.sectionSubtext }}>{n}</span>
              ))}
            </>
          )}
          {!incidents && !errors.incidents && <span style={noteStyle}>Loading incidents…</span>}
        </div>

        {/* Audit trail (list + record form) */}
        <AuditTrail audits={audits} error={errors.audits} canRecord={user?.role !== "viewer"} onRecorded={onRecorded} />

        {/* Field tasks + documents */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: s(18) }}>
          <div style={cardBase} id="field-tasks">
            <SectionLabel>FIELD-LOG TASKS</SectionLabel>
            <ErrorLine what="field-log tasks" error={errors.tasks} />
            {!tasks && !errors.tasks && <span style={noteStyle}>Loading tasks…</span>}
            {tasks?.tasks.length === 0 && (
              <span style={{ fontSize: s(12), color: tokens.sectionSubtext }}>
                No field-log tasks on the analyses in scope. Tasks are added from an analysis's Field Log in Researcher Mode.
              </span>
            )}
            {tasks?.tasks.map((t) => <TaskRow key={t.entry_id} t={t} />)}
            {tasks?.truncated && <span style={noteStyle}>Showing {tasks.tasks.length} of {tasks.total}.</span>}
            {tasks && <span style={noteStyle}>{tasks.definitions.order} Overdue: {tasks.definitions.overdue}</span>}
          </div>
          <DocumentHub reports={reports} reportsError={errors.reports} />
        </div>
      </div>
    </div>
  );
}
